#!/usr/bin/env bash
# Provision the hosted API on a dedicated EC2 instance. Run it from AWS
# CloudShell, in a clone of this repository checked out at a release tag.
#
# It creates, or reuses when they already exist (so it is safe to run again):
#   - an IAM role and instance profile that allow Systems Manager sessions and
#     sending email through SES, with the SES policy generated from
#     src/core/email.py by IAM Policy Autopilot, so no AWS keys live on the server;
#   - a security group open only on ports 80 and 443 (no SSH: use Session Manager);
#   - an Elastic IP, so the DNS record survives the instance stopping and starting;
#   - an Amazon Linux 2023 instance with an encrypted disk, IMDSv2 only and
#     standard CPU credits, which on first boot installs Docker, checks out the
#     release, builds the image and starts the API, Redis and Caddy.
#
# Usage, with your own host name and sender:
#   SITE_ADDRESS=banks.example.com SIGNUP_EMAIL_FROM="Bank Directory API <no-reply@example.com>" \
#     deploy/aws/provision.sh
#
# SITE_ADDRESS and SIGNUP_EMAIL_FROM are required. The others have defaults:
# REGION=the CloudShell session's region, SES_REGION=$REGION, INSTANCE_TYPE=t4g.micro,
# NAME=bank-directory-api, RELEASE_TAG=the tag checked out in this clone.
set -euo pipefail

REGION="${REGION:-${AWS_REGION:-}}"
if [ -z "$REGION" ]; then
  echo "Set REGION to the AWS region to create the instance in, for example REGION=us-east-1." >&2
  exit 1
fi
SES_REGION="${SES_REGION:-$REGION}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t4g.micro}"
SITE_ADDRESS="${SITE_ADDRESS:?Set SITE_ADDRESS to the host name of the API, for example banks.example.com}"
SIGNUP_EMAIL_FROM="${SIGNUP_EMAIL_FROM:?Set SIGNUP_EMAIL_FROM, for example "Bank Directory API <no-reply@example.com>"}"
NAME="${NAME:-bank-directory-api}"
REPOSITORY="https://github.com/enwokoma/bank-directory-api.git"
COMPOSE_VERSION="v5.6.0"

here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
RELEASE_TAG="${RELEASE_TAG:-$(git -C "$repo_root" describe --tags --exact-match 2>/dev/null || true)}"
if [ -z "$RELEASE_TAG" ]; then
  echo "Check out a release tag first (git checkout vX.Y.Z), or set RELEASE_TAG." >&2
  exit 1
fi

export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
log() { printf '\n== %s\n' "$*"; }

account="$(aws sts get-caller-identity --query Account --output text)"
log "Account $account, region $REGION, SES region $SES_REGION, $INSTANCE_TYPE, release $RELEASE_TAG"

role="$NAME-ec2"
log "IAM role and instance profile: $role"
if ! aws iam get-role --role-name "$role" >/dev/null 2>&1; then
  aws iam create-role --role-name "$role" \
    --description "Bank Directory API server: Session Manager and SES sign-up emails" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    >/dev/null
fi
aws iam attach-role-policy --role-name "$role" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

log "SES policy, generated from src/core/email.py by IAM Policy Autopilot"
python3 -m venv "$work/autopilot"
"$work/autopilot/bin/pip" install --quiet --disable-pip-version-check iam-policy-autopilot
DISABLE_IAM_POLICY_AUTOPILOT_TELEMETRY=true "$work/autopilot/bin/iam-policy-autopilot" generate-policies \
  "$repo_root/src/core/email.py" --service-hints sesv2 ses --account "$account" --region "$SES_REGION" \
  >"$work/autopilot.json" 2>/dev/null
python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["Policies"][0]["Policy"], indent=2))' \
  "$work/autopilot.json" >"$work/ses-policy.json"
cat "$work/ses-policy.json"
aws iam put-role-policy --role-name "$role" --policy-name "$NAME-ses" --policy-document "file://$work/ses-policy.json"

if ! aws iam get-instance-profile --instance-profile-name "$role" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$role" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$role" --role-name "$role"
  aws iam wait instance-profile-exists --instance-profile-name "$role"
  # EC2 can reject a brand-new instance profile for a few seconds.
  sleep 15
fi

log "Security group $NAME: ports 80 and 443 only"
vpc="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
if [ "$vpc" = "None" ]; then
  echo "There is no default VPC in $REGION." >&2
  exit 1
fi
group="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$vpc" \
  --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$group" = "None" ]; then
  group="$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$vpc" \
    --description "Bank Directory API: HTTP and HTTPS only" --query GroupId --output text)"
  aws ec2 authorize-security-group-ingress --group-id "$group" --ip-permissions '[
    {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]},
    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]},
    {"IpProtocol": "udp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}
  ]' >/dev/null
fi

log "Elastic IP"
allocation="$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)"
if [ "$allocation" = "None" ]; then
  allocation="$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)"
fi
public_ip="$(aws ec2 describe-addresses --allocation-ids "$allocation" --query 'Addresses[0].PublicIp' --output text)"

log "Instance $NAME"
instance="$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$NAME" Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)"
if [ "$instance" = "None" ]; then
  arch="$(aws ec2 describe-instance-types --instance-types "$INSTANCE_TYPE" \
    --query 'InstanceTypes[0].ProcessorInfo.SupportedArchitectures[0]' --output text)"
  ami="$(aws ssm get-parameter --name "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-$arch" \
    --query Parameter.Value --output text)"

  # First boot. Values are filled in now; \$ marks what the server works out itself.
  cat >"$work/user-data.sh" <<USERDATA
#!/bin/bash
# First boot of the Bank Directory API server. The log is /var/log/bank-directory-bootstrap.log.
set -euxo pipefail
exec > >(tee -a /var/log/bank-directory-bootstrap.log) 2>&1

# A swap file gives the 1 GB instance room to build the image.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=1024
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf install -y docker git
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-\$(uname -m)" \\
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

git clone --branch "$RELEASE_TAG" --depth 1 "$REPOSITORY" /opt/bank-directory-api
cd /opt/bank-directory-api
cat > deploy/.env.production <<'SETTINGS'
PUBLIC_BASE_URL=https://$SITE_ADDRESS
SIGNUP_EMAIL_FROM=$SIGNUP_EMAIL_FROM
AWS_REGION=$SES_REGION
GUNICORN_WORKERS=2
SETTINGS
chmod 600 deploy/.env.production

docker build --tag bank-directory-api:latest .
SITE_ADDRESS=$SITE_ADDRESS docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.standalone.yml \\
  up --detach --no-build --wait
echo "Bank Directory API is running."
USERDATA

  instance="$(aws ec2 run-instances --image-id "$ami" --instance-type "$INSTANCE_TYPE" \
    --iam-instance-profile "Name=$role" --security-group-ids "$group" \
    --user-data "file://$work/user-data.sh" \
    --metadata-options HttpEndpoint=enabled,HttpTokens=required,HttpPutResponseHopLimit=2 \
    --credit-specification CpuCredits=standard \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=16,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)"
fi
aws ec2 wait instance-running --instance-ids "$instance"
aws ec2 associate-address --instance-id "$instance" --allocation-id "$allocation" >/dev/null

log "Done"
cat <<DONE
Instance:  $instance ($INSTANCE_TYPE)
Public IP: $public_ip

Next:
  1. Add a DNS A record: $SITE_ADDRESS -> $public_ip
  2. The server installs Docker, builds the image and starts in about 5 to 10 minutes.
     Follow it with Session Manager:
       aws ssm start-session --target $instance --region $REGION
       sudo tail -f /var/log/bank-directory-bootstrap.log
  3. Once DNS points here, Caddy gets the certificate and https://$SITE_ADDRESS/ answers.
DONE

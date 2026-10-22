# Running the API as a public service

How to serve the API publicly with [rate limits and API keys](../README.md#hosted-mode-rate-limits-and-api-keys): the API and a Redis run in Docker Compose behind a proxy that serves HTTPS, and sign-up emails go out through Amazon SES using the instance's IAM role, so no AWS keys are stored anywhere. To run it on your own machine instead, see [Run it with Docker](../README.md#run-it-with-docker).

The examples use `banks.example.com` for the API's host name and `no-reply@example.com` for the sender; use your own.

There are three ways to run it:

- **Managed by Coolify** on a dedicated instance: see [Managed by Coolify](#managed-by-coolify).
- **A dedicated instance on its own**, set up by one script from AWS CloudShell: see [Dedicated instance](#dedicated-instance-from-aws-cloudshell).
- **An existing server that already runs Caddy**, set up by hand: steps 1 to 8 below.

```text
client --HTTPS--> Caddy (host, :443) --> 127.0.0.1:5106 --> api container (gunicorn, 3 workers)
                                                             |-- redis container: rate limit counters
                                                             |-- keys volume: API keys (SQLite, hashes only)
                                                             '-- Amazon SES: sign-up emails, via the instance role
```

## Managed by Coolify

[Coolify](https://coolify.io) deploys and runs the API on the dedicated instance, with its own proxy (Traefik) serving HTTPS, and pulls the image each release publishes to `ghcr.io/enwokoma/bank-directory-api`, so the instance never builds.

The steps keep the instance's own stack serving the site until Coolify's is ready, so the switch itself takes under a minute.

1. Create the instance with `deploy/aws/provision.sh` as in [Dedicated instance](#dedicated-instance-from-aws-cloudshell), so it has the SES role, the IMDS hop limit and Docker.
2. Let Coolify connect over SSH:
   - In Coolify, under **Keys & Tokens > Private Keys**, generate an ED25519 key for the server. Coolify keeps the private key.
   - Add its public key to `/root/.ssh/authorized_keys` on the instance, from a Session Manager shell.
   - Allow port 22 in the instance's security group from Coolify's address only:

   ```bash
   aws ec2 authorize-security-group-ingress --group-id <GROUP_ID> \
     --ip-permissions 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=<COOLIFY_IP>/32,Description=Coolify}]'
   ```

3. Under **Servers > New server > IP address or domain**, add the instance's Elastic IP with user `root`, port 22 and that key, then validate it. Don't start its proxy yet: Caddy still holds ports 80 and 443.
4. Create a project. In its environment, add a **Docker Compose** resource (the one without a Git repository) on that server. Paste `deploy/coolify/docker-compose.yml` into it.
5. Set up the service:
   - **Domains > Add domain**: the api service, `https`, `banks.example.com`, port `5006`.
   - **Environment Variables**: set `PUBLIC_BASE_URL=https://banks.example.com`, `SIGNUP_EMAIL_FROM` and `AWS_REGION`. The others have defaults.
   - Deploy. The containers start, but get no traffic until the proxy runs.
6. API keys live in the stack's `keys` volume, and the new service starts with an empty one. If the instance's own stack has issued keys that people use, copy its `keys.sqlite3` into the new volume first.
7. Switch over. Stop the instance's own stack, keeping its volumes:

   ```bash
   cd /opt/bank-directory-api
   sudo SITE_ADDRESS=banks.example.com docker compose -f deploy/docker-compose.yml \
     -f deploy/docker-compose.standalone.yml down
   ```

   Then click **Start Proxy** on the server in Coolify. Traefik gets a certificate within seconds.
   - To roll back, stop the proxy and run the same command with `up --detach` instead of `down`.
8. Check the site as in [step 8](#8-check-it-end-to-end).

### Deploying releases automatically

With the service tracking `latest`, as `deploy/coolify/docker-compose.yml` does, the release workflow can redeploy it as soon as a release's image is published, so a release reaches the site a few minutes after its tag is pushed. The workflow calls Coolify's deploy webhook for the service, waits for the deployment to finish, and then checks that the site answers with the new version. Set it up once:

1. In Coolify, under **Keys & Tokens > API tokens**, create a token for the workflow with the **deploy** permission only, and copy it. Coolify's API must be enabled under **Settings > API**; leave its IP allowlist empty, since GitHub's runners have no fixed addresses.
2. Open the service, then its **Webhooks** tab, and copy the **Deploy Webhook** URL. It looks like `https://coolify.example.com/api/v1/deploy?uuid=<service>&force=false`.
3. In the service's compose editor, make sure the api service reads `image: ghcr.io/enwokoma/bank-directory-api:latest` with `pull_policy: always`, as in the repository's file, and redeploy once by hand.
4. In the GitHub repository, under **Settings > Secrets and variables > Actions**, add the secrets `COOLIFY_WEBHOOK_URL` (the URL from step 2) and `COOLIFY_API_TOKEN` (the token from step 1), and the variable `PUBLIC_SITE_URL` with the site's address, such as `https://banks.example.com`.

From then on, every release deploys itself; the workflow's **Deploy to the public instance** job shows what happened. Without the secrets the job does nothing, and the image is only published. To deploy a release again, or to test the setup, run the workflow on the release's tag:

```bash
gh workflow run release-image.yml --ref v0.6.0
```

To hold the site at one release while newer ones are published, pin the image in Coolify to that release's tag and digest instead of `latest`; the digest is on the `Digest:` line of `docker buildx imagetools inspect ghcr.io/enwokoma/bank-directory-api:0.6.0`. Deployments the workflow triggers then keep that release until the pin is removed.

Manage keys from the service's **Terminal** in Coolify with `python -m src.keys_admin`.

## Dedicated instance, from AWS CloudShell

`deploy/aws/provision.sh` sets up everything on a new instance: an IAM role allowing Session Manager and SES (its SES policy generated from the code by IAM Policy Autopilot), a security group open only on ports 80 and 443, an Elastic IP, and an Amazon Linux 2023 `t4g.micro` with an encrypted disk, IMDSv2 only with a hop limit of 2, and standard CPU credits. On first boot the instance installs Docker, checks out the release, builds the image, and starts the API, Redis and Caddy (from `deploy/docker-compose.standalone.yml`). It is safe to run again: it reuses whatever it already created.

1. Check SES as in [step 2](#2-amazon-ses).
2. Open AWS CloudShell in the target region and run:

   ```bash
   git clone --branch <LATEST_RELEASE_TAG> https://github.com/enwokoma/bank-directory-api.git
   cd bank-directory-api
   SITE_ADDRESS=banks.example.com SIGNUP_EMAIL_FROM="Bank Directory API <no-reply@example.com>" \
     deploy/aws/provision.sh
   ```

   It creates the instance in CloudShell's region; set `REGION` for another one, and `SES_REGION` if the sender's SES identity is in a different region.
3. Add the DNS A record it prints (see [step 1](#1-dns)).
4. Wait about 5 to 10 minutes for the first boot, then check the site as in [step 8](#8-check-it-end-to-end). Caddy gets the certificate once DNS points at the instance.

There is no SSH. To get a shell on the instance, use Session Manager from the EC2 console or `aws ssm start-session --target <INSTANCE_ID>`. The first-boot log is `/var/log/bank-directory-bootstrap.log`, and the code is in `/opt/bank-directory-api`. To deploy a new release there:

```bash
cd /opt/bank-directory-api
sudo git fetch --tags && sudo git checkout <TAG>
sudo docker build --tag bank-directory-api:latest .
sudo SITE_ADDRESS=banks.example.com docker compose -f deploy/docker-compose.yml \
  -f deploy/docker-compose.standalone.yml up --detach --no-build --wait
```

The commands in [Running it](#running-it) work there too, run with `sudo`, with `SITE_ADDRESS=banks.example.com` before `docker compose`, and with `-f deploy/docker-compose.standalone.yml` added after the first `-f` file.

## 1. DNS

At your DNS provider, add an A record:

| Type | Host | Value | TTL |
| --- | --- | --- | --- |
| A | `banks` | the server's public IP | Automatic |

Check it from your machine:

```bash
dig +short banks.example.com
```

If the server's address is not an Elastic IP, it changes when the instance stops and starts; an Elastic IP keeps the record valid.

## 2. Amazon SES

Sign-up emails come from `SIGNUP_EMAIL_FROM`, for example `Bank Directory API <no-reply@example.com>`.

- The sender must belong to an SES identity verified for sending, such as the `example.com` domain, in the region you set as `AWS_REGION`.
- The account must have SES production access. In the sandbox, SES only delivers to verified addresses, so most people would never get their link.

```bash
aws sesv2 get-account --region <REGION> --query ProductionAccessEnabled
aws sesv2 get-email-identity --email-identity example.com --region <REGION> --query VerifiedForSendingStatus
```

Both should print `true`.

## 3. IAM: let the server send email without stored keys

The API uses boto3's standard credential sources, which on EC2 means the instance's IAM role. If the instance has no role yet, create one that EC2 can assume and attach it to the instance.

The role needs permission to send email. This policy was generated from the API's code with [IAM Policy Autopilot](https://github.com/awslabs/iam-policy-autopilot); run it with your account ID and region so the resource ARNs are scoped to your account:

```bash
uvx iam-policy-autopilot@latest generate-policies "$PWD/src/core/email.py" \
  --service-hints sesv2 ses --account <ACCOUNT_ID> --region <REGION> --pretty
```

Without an account and region it produces:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail"],
      "Resource": [
        "arn:*:ses:*:*:configuration-set/*",
        "arn:*:ses:*:*:identity/*",
        "arn:*:ses:*:*:template/*"
      ]
    }
  ]
}
```

Review the generated policy, save it as `ses-policy.json`, and attach it to the instance role:

```bash
aws iam put-role-policy --role-name <INSTANCE_ROLE> --policy-name bank-directory-api-ses \
  --policy-document file://ses-policy.json
```

Containers sit one network hop further from the instance metadata service than the host, and with IMDSv2 the default hop limit of 1 keeps them from getting the role's credentials. Raise it to 2:

```bash
aws ec2 modify-instance-metadata-options --instance-id <INSTANCE_ID> \
  --http-endpoint enabled --http-tokens required --http-put-response-hop-limit 2
```

## 4. Docker on the server

Check the operating system with `cat /etc/os-release`.

On Amazon Linux 2023:

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # then log out and back in
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -fSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

On Ubuntu, follow Docker's [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/), which includes the Compose plugin.

## 5. Get the code and configure it

```bash
sudo mkdir -p /opt/bank-directory-api && sudo chown "$USER" /opt/bank-directory-api
git clone https://github.com/enwokoma/bank-directory-api.git /opt/bank-directory-api
cd /opt/bank-directory-api
git checkout <LATEST_RELEASE_TAG>
cp deploy/.env.production.example deploy/.env.production
```

Edit `deploy/.env.production`: set `AWS_REGION` to the SES identity's region and check `SIGNUP_EMAIL_FROM`. Rate limits have sensible defaults; the file lists the settings that change them. git ignores the file.

## 6. Start the containers

```bash
docker compose -f deploy/docker-compose.yml up --detach --build --wait
curl -s http://127.0.0.1:5106/
```

Confirm the container can use the instance role (this STS call needs no permission):

```bash
docker compose -f deploy/docker-compose.yml exec api \
  python -c "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"
```

It should print the role's ARN. An error about credentials means the role is missing or the hop limit in step 3 is still 1.

## 7. Serve it through Caddy

Add the block in `deploy/Caddyfile` to the server's Caddyfile (usually `/etc/caddy/Caddyfile`), then:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy gets the HTTPS certificate for `banks.example.com` on the first request. No security group change is needed: Caddy already serves ports 80 and 443, and the API's port is bound to the loopback address only.

If Caddy itself runs in a Docker container rather than on the host, `127.0.0.1` inside it is not the host: put both on a shared Docker network and use `reverse_proxy api:5006`, or reach the host through `host.docker.internal:5106` with `extra_hosts: ["host.docker.internal:host-gateway"]` on the Caddy container.

## 8. Check it end to end

```bash
curl -s https://banks.example.com/
curl -si https://banks.example.com/api/countries | grep -i '^x-ratelimit'
curl -s -X POST https://banks.example.com/api/keys/signup \
  -H 'Content-Type: application/json' -d '{"email": "you@example.com"}'
```

Open the emailed link, press the button, and use the key:

```bash
curl -s https://banks.example.com/api/keys/me -H "X-API-Key: <YOUR_KEY>"
```

## Running it

| Task | Command (from `/opt/bank-directory-api`) |
| --- | --- |
| Deploy a new release | `git fetch --tags && git checkout <TAG> && docker compose -f deploy/docker-compose.yml up --detach --build --wait` |
| Follow the logs | `docker compose -f deploy/docker-compose.yml logs --follow api` |
| List keys | `docker compose -f deploy/docker-compose.yml exec api python -m src.keys_admin list [EMAIL OR PREFIX]` |
| Issue a key by hand | `docker compose -f deploy/docker-compose.yml exec api python -m src.keys_admin issue <EMAIL>` |
| Revoke a key | `docker compose -f deploy/docker-compose.yml exec api python -m src.keys_admin revoke <ID>` |
| Change limits | Edit `deploy/.env.production`, then `docker compose -f deploy/docker-compose.yml up --detach --wait` |

The bank data is built into the image, so it changes only when a new release is deployed.

Access logs record paths without query strings, so sign-up tokens never reach them. Redis holds only rate limit counters; restarting it resets them.

### Backing up API keys

The key database holds email addresses and key hashes. To copy it safely while the API runs:

```bash
docker compose -f deploy/docker-compose.yml exec -T api python -c \
  "import sqlite3; sqlite3.connect('/var/lib/bank-directory/keys.sqlite3').backup(sqlite3.connect('/var/lib/bank-directory/backup.sqlite3'))"
docker compose -f deploy/docker-compose.yml cp api:/var/lib/bank-directory/backup.sqlite3 ./keys-backup.sqlite3
```

Keep backups somewhere private, such as an encrypted S3 bucket.

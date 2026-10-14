"""Tests for sending sign-up emails through Amazon SES, with no real AWS calls."""

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from app import create_app
from src.core.email import SesEmailSender
from src.core.settings import Settings


@pytest.fixture
def ses():
    client = boto3.client("sesv2", region_name="eu-central-1", aws_access_key_id="test", aws_secret_access_key="test")
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def test_sends_a_plain_text_email_from_the_sender(ses):
    client, stubber = ses
    stubber.add_response(
        "send_email",
        {"MessageId": "message-1"},
        {
            "FromEmailAddress": "Bank Directory API <no-reply@example.test>",
            "Destination": {"ToAddresses": ["ada@example.com"]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": "Your key", "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": "Hello", "Charset": "UTF-8"}},
                }
            },
        },
    )
    SesEmailSender("Bank Directory API <no-reply@example.test>", client=client).send("ada@example.com", "Your key", "Hello")


def test_leaves_ses_errors_to_the_caller(ses):
    client, stubber = ses
    stubber.add_client_error(
        "send_email", service_error_code="MessageRejected", service_message="Email address is not verified."
    )
    with pytest.raises(ClientError, match="MessageRejected"):
        SesEmailSender("no-reply@example.test", client=client).send("ada@example.com", "Your key", "Hello")


def test_creates_no_aws_client_until_an_email_is_sent(monkeypatch):
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: pytest.fail("created an AWS client too early"))
    SesEmailSender("no-reply@example.test")


@pytest.fixture
def no_aws_region_sources(monkeypatch, tmp_path):
    """Leave boto3 nothing of its own to find a region in, as on the hosted server."""
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def test_the_app_sends_from_the_region_in_aws_region(no_aws_region_sources):
    # boto3 ignores AWS_REGION by itself, which once left sign-up emails without a region.
    settings = Settings.from_env({"SIGNUP_EMAIL_FROM": "no-reply@example.test", "AWS_REGION": "eu-central-1"})
    sender = create_app(settings).extensions["bank_email_sender"]
    assert sender._ses().meta.region_name == "eu-central-1"


def test_without_aws_region_boto3_finds_the_region_itself(no_aws_region_sources, monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert SesEmailSender("no-reply@example.test")._ses().meta.region_name == "eu-west-1"

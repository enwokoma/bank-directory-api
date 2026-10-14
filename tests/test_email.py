"""Tests for sending sign-up emails through Amazon SES, with no real AWS calls."""

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from src.core.email import SesEmailSender


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

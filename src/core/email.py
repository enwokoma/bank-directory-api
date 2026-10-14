"""Sending sign-up emails through Amazon SES.

Credentials and region come from boto3's standard sources: on the hosted
server, the EC2 instance role and AWS_REGION. Nothing AWS-specific is stored
in this project. Errors are left to the caller, which decides what to tell the
person signing up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_sesv2 import SESV2Client

_SES_CONFIG = Config(retries={"total_max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=10)


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


class SesEmailSender:
    """Send plain-text email from one sender address with the SES v2 API."""

    def __init__(self, sender: str, client: SESV2Client | None = None) -> None:
        self.sender = sender
        self._client = client

    def send(self, to: str, subject: str, text: str) -> None:
        self._ses().send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
                }
            },
        )

    def _ses(self) -> SESV2Client:
        # Created on first use, so the app starts without AWS settings until an email is needed.
        if self._client is None:
            self._client = boto3.client("sesv2", config=_SES_CONFIG)
        return self._client

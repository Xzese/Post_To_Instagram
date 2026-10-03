#!/usr/bin/env python3
"""Single-attempt Instagram publishing. Never retry an uncertain publication."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
import logging
import mimetypes
import os
from pathlib import Path
import re
import smtplib
import ssl
from uuid import uuid4

import requests

LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 30)
__all__ = ["publish_image", "post_random_photo", "PublishResult", "PublishingError", "PublishOutcomeUnknown"]


class PublishingError(RuntimeError):
    """The operation failed. This exception does not authorise a retry."""


class PublishOutcomeUnknown(PublishingError):
    """The provider may have published. Reconcile before trying again."""

    def __init__(self, creation_id: str):
        self.creation_id = creation_id
        super().__init__("Publication outcome is unknown; reconcile the existing container before retrying.")


@dataclass(frozen=True)
class PublishResult:
    media_id: str
    creation_id: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PublishingError(f"{name} is required.")
    return value


def _graph_base() -> str:
    version = _required("GRAPH_API_VERSION")
    if not re.fullmatch(r"v[1-9][0-9]*\.[0-9]+", version):
        raise PublishingError("GRAPH_API_VERSION must have the form vNN.N.")
    return f"https://graph.facebook.com/{version}"


def _token() -> str:
    token = _required("ACCESS_TOKEN")
    try:
        expiry = datetime.fromisoformat(_required("ACCESS_TOKEN_EXPIRY").replace("Z", "+00:00"))
        # Existing .env files use local, naive timestamps. Preserve that meaning.
        if expiry.tzinfo is None:
            expiry = expiry.astimezone()
        if expiry <= datetime.now().astimezone():
            raise PublishingError("The Facebook access token has expired.")
    except ValueError:
        raise PublishingError("ACCESS_TOKEN_EXPIRY must be an ISO datetime.") from None
    return token


def _account() -> str:
    account = _required("IG_BUSINESS_USER_ID")
    if not account.isascii() or not account.isdigit():
        raise PublishingError("IG_BUSINESS_USER_ID must be a numeric account ID.")
    return account


def business_id_check() -> bool:
    """Require explicit account selection. Never silently select the first account."""
    _account()
    return True


def add_to_log(message: str) -> None:
    LOGGER.info(message)


def _best_effort_log(message: str) -> None:
    try:
        add_to_log(message)
    except Exception:
        # A local logger must not change the result of a remote side effect.
        pass


def upload_image(image_path: str) -> str:
    import boto3
    from botocore.config import Config

    path = Path(image_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise PublishingError("A non-empty image file is required.")
    bucket = _required("S3_BUCKET_NAME")
    client = boto3.client(
        "s3", endpoint_url=_required("S3_ENDPOINT"),
        aws_access_key_id=_required("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=_required("S3_SECRET_ACCESS_KEY"), region_name="auto",
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    key = f"instagram/{uuid4().hex}{path.suffix.lower()}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        client.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
        return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    except Exception:
        # Do not leak signed request URLs, credentials or SDK response bodies.
        raise PublishingError("Object upload or signing failed.") from None


def create_media_container(image_url: str, caption: str) -> str:
    url = f"{_graph_base()}/{_account()}/media"
    token = _token()
    try:
        response = requests.post(url, data={"image_url": image_url, "caption": caption, "access_token": token}, timeout=REQUEST_TIMEOUT, allow_redirects=False)
        if response.status_code != 200:
            raise PublishingError(f"Media container creation failed (HTTP {response.status_code}).")
        payload = response.json()
        identifier = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(identifier, str) or not identifier.strip():
            raise PublishingError("Media container response has no valid ID.")
        return identifier
    except requests.RequestException:
        raise PublishingError("Media container creation failed; no automatic retry was made.") from None
    except ValueError:
        raise PublishingError("Media container response is not valid JSON.") from None


def publish_media_container(creation_id: str) -> dict:
    if not isinstance(creation_id, str) or not creation_id.strip() or creation_id == "No Valid Token":
        raise PublishingError("A valid media container ID is required.")
    url = f"{_graph_base()}/{_account()}/media_publish"
    token = _token()
    try:
        response = requests.post(url, data={"creation_id": creation_id, "access_token": token}, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        raise PublishOutcomeUnknown(creation_id) from None
    if response.status_code >= 500 or 300 <= response.status_code < 400:
        raise PublishOutcomeUnknown(creation_id)
    if response.status_code != 200:
        raise PublishingError(f"Publication was not confirmed (HTTP {response.status_code}); no automatic retry was made.")
    try:
        payload = response.json()
    except ValueError:
        raise PublishOutcomeUnknown(creation_id) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not payload["id"].strip():
        raise PublishOutcomeUnknown(creation_id)
    _best_effort_log("Publication confirmed.")
    return payload


def publish_image(file_path: str, caption: str) -> PublishResult:
    """Publish once. The caller owns recovery and cross-invocation coordination."""
    if not isinstance(caption, str):
        raise PublishingError("The caption must be text.")
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise PublishingError("A non-empty image file is required.")
    _graph_base()
    _account()
    _token()
    for name in ("S3_BUCKET_NAME", "S3_ENDPOINT", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        _required(name)
    image_url = upload_image(str(path))
    container = create_media_container(image_url, caption)
    payload = publish_media_container(container)
    result = PublishResult(media_id=payload["id"], creation_id=container)
    _best_effort_log("Image publishing completed.")
    return result


def post_random_photo(file_path: str, caption: str) -> PublishResult:
    """Compatibility name. Returns a result or raises; it never silently fails."""
    return publish_image(file_path, caption)


def send_email_alert(subject: str, body: str) -> bool:
    """Optional notification. Its failure must not cause another publication."""
    try:
        sender = _required("SENDER_EMAIL")
        recipient = _required("RECIPIENT_EMAIL")
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP(_required("SMTP_SERVER"), int(_required("SMTP_PORT")), timeout=10) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(sender, _required("SENDER_PASSWORD"))
            server.send_message(message)
        return True
    except Exception:
        _best_effort_log("Email notification failed.")
        return False

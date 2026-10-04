"""Configuration is read only when called, never at import time."""

from datetime import datetime
import math
import os
import re
from urllib.parse import urlsplit

from .models import GraphConfig, PublishingError, StorageConfig


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PublishingError(f"{name} is required.")
    return value


def numeric_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise PublishingError("A numeric provider identifier is required.")
    return value


def graph_config() -> GraphConfig:
    version = required("GRAPH_API_VERSION")
    if not re.fullmatch(r"v[1-9][0-9]*\.[0-9]+", version):
        raise PublishingError("GRAPH_API_VERSION must have the form vNN.N.")
    account = numeric_id(required("IG_BUSINESS_USER_ID"))
    token = required("ACCESS_TOKEN")
    if any(c.isspace() for c in token):
        raise PublishingError("ACCESS_TOKEN must not contain whitespace.")
    try:
        expiry = datetime.fromisoformat(
            required("ACCESS_TOKEN_EXPIRY").replace("Z", "+00:00")
        )
        if expiry.tzinfo is None:
            expiry = expiry.astimezone()
        if expiry <= datetime.now().astimezone():
            raise PublishingError("The Facebook access token has expired.")
    except ValueError:
        raise PublishingError("ACCESS_TOKEN_EXPIRY must be an ISO datetime.") from None

    def seconds(name, default, low, high):
        try:
            value = float(os.getenv(name, default))
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError
            return value
        except ValueError:
            raise PublishingError(f"{name} is outside its supported range.") from None

    readiness = seconds("CONTAINER_READY_TIMEOUT", "60", 1, 300)
    poll = seconds("CONTAINER_POLL_INTERVAL", "2", 0.1, 60)
    return GraphConfig(version, account, token, readiness, poll)


def storage_config() -> StorageConfig:
    endpoint = required("S3_ENDPOINT")
    try:
        parts = urlsplit(endpoint)
        valid = (
            parts.scheme == "https"
            and parts.hostname
            and not parts.username
            and not parts.password
            and not parts.query
            and not parts.fragment
            and parts.path in ("", "/")
            and parts.port != 0
        )
    except ValueError:
        valid = False
    if not valid:
        raise PublishingError(
            "S3_ENDPOINT must be an HTTPS endpoint without credentials or query parameters."
        )
    prefix = os.getenv("S3_PREFIX", "instagram").strip("/")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", prefix):
        raise PublishingError("S3_PREFIX must contain only safe path segments.")
    return StorageConfig(
        required("S3_BUCKET_NAME"),
        endpoint,
        required("S3_ACCESS_KEY_ID"),
        required("S3_SECRET_ACCESS_KEY"),
        os.getenv("S3_REGION", "auto"),
        prefix,
    )

from io import BytesIO
from threading import RLock
from unittest.mock import Mock
import hashlib
import json

import boto3
from botocore.exceptions import ClientError
from PIL import Image
import pytest
import requests

from instagram_publisher.models import GraphConfig, StorageConfig
from instagram_publisher.graph import GraphClient
from instagram_publisher.service import Publisher
from instagram_publisher.storage import S3Storage


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    for key, value in {
        "GRAPH_API_VERSION": "v26.0",
        "ACCESS_TOKEN": "test-secret",
        "ACCESS_TOKEN_EXPIRY": "2099-01-01T00:00:00Z",
        "IG_BUSINESS_USER_ID": "123",
        "S3_BUCKET_NAME": "test",
        "S3_ENDPOINT": "https://storage.invalid",
        "S3_ACCESS_KEY_ID": "test-key",
        "S3_SECRET_ACCESS_KEY": "test-storage-secret",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        requests,
        "post",
        Mock(side_effect=AssertionError("Unexpected provider request")),
    )
    monkeypatch.setattr(
        requests, "get", Mock(side_effect=AssertionError("Unexpected provider request"))
    )
    monkeypatch.setattr(
        boto3, "client", Mock(side_effect=AssertionError("Unexpected storage request"))
    )


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "image.jpg"
    Image.new("RGB", (512, 512), "green").save(path, "JPEG")
    return path


def response(status=200, payload=None):
    reply = requests.Response()
    reply.status_code = status
    reply._content = json.dumps(payload).encode()
    reply._content_consumed = True
    return reply


def client_error(status, code):
    return ClientError(
        {
            "Error": {"Code": code, "Message": "secret provider diagnostic"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "operation",
    )


class FakeS3:
    """Atomic S3 conditional semantics with injectable lost replies."""

    def __init__(self, *, objects=None, lock=None):
        self.objects = objects if objects is not None else {}
        self.lock = lock if lock is not None else RLock()
        self.calls = []
        self.fail_phase = None
        self.lose_phase = None
        self.ignore_conditionals = False

    def put_object(self, **kwargs):
        key, body = kwargs["Key"], bytes(kwargs["Body"])
        phase = json.loads(body).get("phase") if "/operations/" in key else None
        self.calls.append(("put", kwargs))
        with self.lock:
            if phase == self.fail_phase and phase is not None:
                raise OSError("secret storage failure")
            previous = self.objects.get(key)
            if not self.ignore_conditionals:
                if kwargs.get("IfNoneMatch") == "*" and previous:
                    raise client_error(412, "PreconditionFailed")
                if "IfMatch" in kwargs and (
                    not previous or previous[1] != kwargs["IfMatch"]
                ):
                    raise client_error(412, "PreconditionFailed")
            etag = '"' + hashlib.md5(body).hexdigest() + '"'
            self.objects[key] = (body, etag)
            if phase == self.lose_phase and phase is not None:
                raise OSError("secret lost storage reply")
            return {"ETag": etag}

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        with self.lock:
            item = self.objects.get(kwargs["Key"])
        if item is None:
            raise client_error(404, "NoSuchKey")
        return {"Body": BytesIO(item[0]), "ETag": item[1]}

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))
        with self.lock:
            self.objects.pop(kwargs["Key"], None)
        return {}

    def generate_presigned_url(self, operation, **kwargs):
        return "https://storage.invalid/signed?secret=test-storage-secret"


@pytest.fixture
def setup():
    storage_config = StorageConfig("test", "https://storage.invalid", "key", "secret")
    graph_config = GraphConfig("v26.0", "123", "test-secret", 1, 0.1)
    s3 = FakeS3()
    transport = Mock()
    transport.post.side_effect = [
        response(payload={"id": "456"}),
        response(payload={"id": "789"}),
    ]
    transport.get.return_value = response(payload={"status_code": "FINISHED"})
    graph = GraphClient(graph_config, transport=transport, sleep=lambda seconds: None)
    store = S3Storage(storage_config, client=s3)
    return Publisher(graph, store), s3, transport

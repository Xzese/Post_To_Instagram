"""Real HTTP/SDK tests against a loopback S3/Graph simulator; no cloud calls."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import subprocess
import sys
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import pytest
import requests

from instagram_publisher.graph import GraphClient
from instagram_publisher.models import GraphConfig, PublishOutcomeUnknown, StorageConfig
from instagram_publisher.service import Publisher
from instagram_publisher.storage import S3Storage
from conftest import FakeS3


class Transport:
    def __init__(self, base):
        self.base = base
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, url, **kwargs):
        return self.session.get(
            self.base + "/graph/" + urlsplit(url).path.split("/", 2)[2], **kwargs
        )

    def post(self, url, **kwargs):
        return self.session.post(
            self.base + "/graph/" + urlsplit(url).path.split("/", 2)[2], **kwargs
        )


@pytest.fixture
def server():
    state = {
        "s3": FakeS3(),
        "creates": 0,
        "publishes": 0,
        "published": False,
        "lose_publish_reply": False,
        "graph_requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, status, content, *, etag=None, xml=False):
            self.send_response(status)
            self.send_header(
                "Content-Type", "application/xml" if xml else "application/json"
            )
            self.send_header("Content-Length", str(len(content)))
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            assert self.path.startswith("/graph/")
            assert self.headers["Authorization"] == "Bearer test-secret"
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            fields = parse_qs(body.decode())
            state["graph_requests"].append((self.path, fields))
            if self.path.endswith("/media"):
                with state["s3"].lock:
                    state["creates"] += 1
                self.reply(200, b'{"id":"456"}')
            elif self.path.endswith("/media_publish"):
                assert fields["creation_id"] == ["456"]
                with state["s3"].lock:
                    state["publishes"] += 1
                    state["published"] = True
                if state["lose_publish_reply"]:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    self.reply(200, b'{"id":"789"}')
            else:
                self.reply(404, b"{}")

        def do_GET(self):
            if self.path.startswith("/graph/"):
                assert self.headers["Authorization"] == "Bearer test-secret"
                status = "PUBLISHED" if state["published"] else "FINISHED"
                self.reply(200, json.dumps({"status_code": status}).encode())
                return
            key = urlsplit(self.path).path.removeprefix("/test/")
            try:
                result = state["s3"].get_object(Key=key)
            except ClientError:
                self.reply(
                    404,
                    b"<Error><Code>NoSuchKey</Code><Message>Missing</Message></Error>",
                    xml=True,
                )
                return
            self.reply(200, result["Body"].read(), etag=result["ETag"])

        def do_PUT(self):
            key = urlsplit(self.path).path.removeprefix("/test/")
            args = {
                "Key": key,
                "Body": self.rfile.read(int(self.headers.get("Content-Length", 0))),
            }
            for header in ["If-None-Match", "If-Match"]:
                if header in self.headers:
                    args[header.replace("-", "")] = self.headers[header]
            try:
                result = state["s3"].put_object(**args)
            except ClientError:
                self.reply(
                    412,
                    b"<Error><Code>PreconditionFailed</Code><Message>Condition failed</Message></Error>",
                    xml=True,
                )
                return
            self.reply(200, b"", etag=result["ETag"])

        def do_DELETE(self):
            key = urlsplit(self.path).path.removeprefix("/test/")
            state["s3"].delete_object(Key=key)
            self.reply(204, b"")

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{http.server_port}"
    try:
        yield base, state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def local_publisher(base):
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=base,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"total_max_attempts": 1},
            proxies={},
            s3={"addressing_style": "path"},
        ),
    )
    # The loopback S3 simulator uses HTTP; Meta's image URL remains an HTTPS
    # fixture. This test checks SDK requests/signing, not a real Meta URL fetch.
    sign = client.generate_presigned_url
    client.generate_presigned_url = lambda *args, **kwargs: sign(
        *args, **kwargs
    ).replace(base, "https://storage.invalid", 1)
    store = S3Storage(StorageConfig("test", base, "key", "secret"), client=client)
    graph = GraphClient(
        GraphConfig("v26.0", "123", "test-secret"), transport=Transport(base)
    )
    return Publisher(graph, store)


def test_real_sdk_http_publish_and_resume_receipt(image, server):
    base, state = server
    first = local_publisher(base).publish(str(image), "caption")
    second = local_publisher(base).publish(str(image), "caption")
    assert first.media_id == second.media_id == "789" and second.reused
    assert state["creates"] == state["publishes"] == 1
    assert all("access_token" not in fields for _, fields in state["graph_requests"])


def test_real_http_lost_publish_reply_is_reconciled_without_retry(image, server):
    base, state = server
    state["lose_publish_reply"] = True
    publisher = local_publisher(base)
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    assert state["publishes"] == 1
    after_restart = local_publisher(base).reconcile(caught.value.operation_id)
    assert after_restart.phase == "published"
    assert after_restart.creation_id == "456" and after_restart.media_id is None
    assert state["publishes"] == 1


WORKER = """
import json, sys
import boto3
from botocore.config import Config
import requests
from urllib.parse import urlsplit
from instagram_publisher import Publisher, PublishingError
from instagram_publisher.models import GraphConfig, StorageConfig
from instagram_publisher.graph import GraphClient
from instagram_publisher.storage import S3Storage
base, path = sys.argv[1:]
class Transport:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
    def get(self, url, **kwargs):
        return self.session.get(base + '/graph/' + urlsplit(url).path.split('/', 2)[2], **kwargs)
    def post(self, url, **kwargs):
        return self.session.post(base + '/graph/' + urlsplit(url).path.split('/', 2)[2], **kwargs)
client = boto3.session.Session().client('s3', endpoint_url=base, aws_access_key_id='test', aws_secret_access_key='test', region_name='auto', config=Config(signature_version='s3v4', retries={'total_max_attempts':1}, proxies={}, s3={'addressing_style':'path'}))
sign = client.generate_presigned_url
client.generate_presigned_url = lambda *args, **kwargs: sign(*args, **kwargs).replace(base, 'https://storage.invalid', 1)
publisher = Publisher(GraphClient(GraphConfig('v26.0','123','test-secret'), transport=Transport()), S3Storage(StorageConfig('test',base,'test','test'), client=client))
try:
    result = publisher.publish(path, 'caption', operation_key='shared-quote')
    print(json.dumps({'status':'published', 'media_id': result.media_id}))
except PublishingError as error:
    print(json.dumps({'status':'blocked', 'error':str(error)}))
"""


def test_independent_processes_share_atomic_claim_and_publish_once(
    image, server, tmp_path
):
    base, state = server
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    def run():
        completed = subprocess.run(
            [sys.executable, "-c", WORKER, base, str(image)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: run(), range(2)))
    assert any(row["status"] == "published" for row in outcomes)
    assert state["creates"] == state["publishes"] == 1

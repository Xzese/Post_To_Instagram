from dataclasses import replace
import json
from unittest.mock import Mock
import boto3
from botocore.stub import Stubber
import pytest

from instagram_publisher.models import JournalError
from instagram_publisher.storage import S3Storage, client_for
from instagram_publisher.config import storage_config


def test_unsupported_conditionals_fail_before_upload_or_graph(image, setup):
    publisher, s3, transport = setup
    s3.ignore_conditionals = True
    with pytest.raises(JournalError, match="conditional|If-None-Match"):
        publisher.publish(str(image), "caption")
    assert not any("/images/" in c["Key"] for m, c in s3.calls if m == "put")
    transport.post.assert_not_called()


def test_stale_worker_cannot_checkpoint_after_ownership_transfer(image, setup):
    publisher, _, transport = setup
    transport.get.side_effect = RuntimeError("simulated process interruption")
    with pytest.raises(RuntimeError):
        publisher.publish(str(image), "caption", operation_key="quote-1")
    key = next(k for k in publisher.storage.client.objects if "/operations/" in k)
    identifier = key.split("/")[-1][:-5]
    old, old_etag = publisher.storage.read(identifier)
    replacement = replace(old, owner="b" * 32, revision=old.revision + 1)
    publisher.storage.checkpoint(replacement, old_etag)
    with pytest.raises(JournalError):
        publisher.storage.checkpoint(
            replace(old, phase="publishing", revision=old.revision + 1), old_etag
        )
    assert transport.post.call_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", 2),
        ("revision", -1),
        ("revision", True),
        ("account_id", "１２３"),
        ("object_key", "other-account/image.jpg"),
        ("owner", "invalid"),
        ("phase", "unknown"),
        ("creation_id", "bad"),
        ("fingerprint", "bad"),
    ],
)
def test_invalid_persistent_record_blocks_replay(image, setup, field, value):
    publisher, s3, transport = setup
    result = publisher.publish(str(image), "caption")
    key = publisher.storage._key(result.operation_id)
    payload = json.loads(s3.objects[key][0])
    payload[field] = value
    s3.objects[key] = (json.dumps(payload).encode(), '"etag"')
    with pytest.raises(JournalError):
        publisher.publish(str(image), "caption")
    assert transport.post.call_count == 2


def test_checkpoints_do_not_store_credentials_caption_or_signed_url(image, setup):
    publisher, s3, _ = setup
    publisher.publish(str(image), "private caption")
    journals = [data for key, (data, _) in s3.objects.items() if "/operations/" in key]
    assert journals
    assert all(
        all(term not in data for term in [b"secret", b"private caption", b"signed?"])
        for data in journals
    )


def test_sdk_model_accepts_conditional_write_parameters(monkeypatch):
    # Exercise the pinned botocore service model, rather than mocking its validation.
    client = boto3.session.Session().client(
        "s3",
        endpoint_url="https://storage.invalid",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="auto",
    )
    with Stubber(client) as stubber:
        for condition in [{"IfNoneMatch": "*"}, {"IfMatch": '"old-etag"'}]:
            args = {"Bucket": "test", "Key": "record.json", "Body": b"{}", **condition}
            stubber.add_response("put_object", {"ETag": '"new-etag"'}, args)
            assert client.put_object(**args)["ETag"] == '"new-etag"'
        stubber.assert_no_pending_responses()


def test_sdk_retries_are_bounded_and_sigv4_is_explicit(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(boto3, "client", factory)
    client_for(storage_config())
    config = factory.call_args.kwargs["config"]
    assert config.retries == {"mode": "standard", "total_max_attempts": 3}
    assert config.signature_version == "s3v4"


def test_image_cleanup_failure_does_not_modify_success(image, setup):
    publisher, s3, transport = setup
    result = publisher.publish(str(image), "caption")
    s3.delete_object = Mock(side_effect=OSError("secret failure"))
    with pytest.raises(Exception, match="Image cleanup failed"):
        publisher.cleanup(result.operation_id)
    assert publisher.publish(str(image), "caption").reused
    assert transport.post.call_count == 2


def test_reconciliation_checkpoint_checks_conditionals_on_new_storage_instance(
    image, setup
):
    publisher, s3, transport = setup
    from instagram_publisher.models import PublishOutcomeUnknown
    from conftest import response
    import requests

    transport.post.side_effect = [response(payload={"id": "456"}), requests.Timeout()]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    publisher.storage = S3Storage(publisher.storage.config, client=s3)
    s3.ignore_conditionals = True
    transport.get.return_value = response(payload={"status_code": "PUBLISHED"})
    with pytest.raises(JournalError, match="If-None-Match"):
        publisher.reconcile(caught.value.operation_id)


def test_receipt_replay_requires_no_storage_write(image, setup):
    publisher, s3, _ = setup
    publisher.publish(str(image), "caption")
    publisher.storage = S3Storage(publisher.storage.config, client=s3)
    s3.put_object = Mock(side_effect=AssertionError("Unexpected receipt rewrite"))
    assert publisher.publish(str(image), "caption").reused

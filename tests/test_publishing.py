from dataclasses import replace
from unittest.mock import Mock
import pytest
import requests

import upload_photo as uploader
from instagram_publisher.models import (
    AlreadyPublished,
    JournalError,
    OperationBlocked,
    PublicationRejected,
    PublishingError,
    PublishOutcomeUnknown,
)
from instagram_publisher.service import Publisher
from conftest import response


def test_success_and_replay_reuse_receipt_without_new_side_effects(image, setup):
    publisher, s3, transport = setup
    result = publisher.publish(str(image), "caption")
    assert (result.media_id, result.creation_id) == ("789", "456")
    stored, _ = publisher.storage.read(result.operation_id)
    assert stored.phase == "published"
    assert stored.media_id == "789"
    assert stored.creation_id == "456"
    repeated = publisher.publish(str(image), "caption")
    assert repeated.reused and repeated.media_id == "789"
    assert transport.post.call_count == 2
    images = [
        call
        for method, call in s3.calls
        if method == "put" and "/images/" in call["Key"]
    ]
    assert len(images) == 1 and images[0]["ContentType"] == "image/jpeg"


@pytest.mark.parametrize(
    "error", [requests.Timeout("secret-url"), requests.ConnectionError("secret-url")]
)
def test_transport_failure_is_uncertain_and_not_retried(image, setup, error):
    publisher, s3, transport = setup
    transport.post.side_effect = [response(payload={"id": "456"}), error]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    assert caught.value.creation_id == "456"
    assert "secret" not in str(caught.value)
    operation, _ = publisher.storage.read(caught.value.operation_id)
    assert operation.phase == "publish_unknown"
    second_worker = Publisher(publisher.graph, publisher.storage)
    with pytest.raises(PublishOutcomeUnknown):
        second_worker.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 2


@pytest.mark.parametrize(
    "reply",
    [
        response(503),
        response(302),
        response(429),
        response(400),
        response(payload={}),
        response(payload=[]),
        response(payload={"id": ""}),
        response(payload={"id": "not-an-id"}),
    ],
)
def test_unconfirmed_responses_are_uncertain(setup, reply):
    publisher, _, transport = setup
    transport.post.side_effect = None
    transport.post.return_value = reply
    with pytest.raises(PublishOutcomeUnknown):
        publisher.graph.publish("456")
    assert transport.post.call_count == 1


def test_explicit_rejection_is_not_retried(image, setup):
    publisher, _, transport = setup
    transport.post.side_effect = [
        response(payload={"id": "456"}),
        response(400, {"error": {"code": 190, "message": "secret token"}}),
    ]
    with pytest.raises(PublicationRejected, match="Meta rejected"):
        publisher.publish(str(image), "caption")
    with pytest.raises(OperationBlocked):
        publisher.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 2


def test_post_success_checkpoint_failure_preserves_success_and_blocks_replay(
    image, setup
):
    publisher, s3, transport = setup
    s3.fail_phase = "published"
    result = publisher.publish(str(image), "caption")
    assert result.media_id == "789"
    operation, _ = publisher.storage.read(result.operation_id)
    assert operation.phase == "publishing"
    with pytest.raises(PublishOutcomeUnknown):
        publisher.publish(str(image), "caption")
    assert transport.post.call_count == 2


@pytest.mark.parametrize(
    "phase,posts",
    [
        ("claimed", 0),
        ("uploading", 0),
        ("uploaded", 0),
        ("creating", 0),
        ("container_created", 1),
        ("publishing", 1),
    ],
)
def test_failed_checkpoint_prevents_next_remote_side_effect(image, setup, phase, posts):
    publisher, s3, transport = setup
    s3.fail_phase = phase
    with pytest.raises(JournalError):
        publisher.publish(str(image), "caption")
    assert transport.post.call_count == posts


@pytest.mark.parametrize(
    "phase",
    ["claimed", "uploaded", "creating", "container_created", "publishing", "published"],
)
def test_lost_checkpoint_reply_is_confirmed_by_readback(image, setup, phase):
    publisher, s3, transport = setup
    s3.lose_phase = phase
    result = publisher.publish(str(image), "caption")
    assert result.media_id == "789"
    assert transport.post.call_count == 2
    assert publisher.storage.read(result.operation_id)[0].phase == "published"


def test_lost_container_response_blocks_new_container(image, setup):
    publisher, _, transport = setup
    transport.post.side_effect = requests.Timeout("secret")
    with pytest.raises(OperationBlocked) as caught:
        publisher.publish(str(image), "caption")
    assert (
        publisher.storage.read(caught.value.operation_id)[0].phase == "create_unknown"
    )
    with pytest.raises(OperationBlocked):
        publisher.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 1


def test_resume_ready_container_does_not_upload_or_create_again(image, setup):
    publisher, s3, transport = setup
    transport.get.side_effect = PublishingError("temporary read failure")
    with pytest.raises(PublishingError):
        publisher.publish(str(image), "caption", operation_key="quote-1")
    transport.get.side_effect = None
    result = publisher.publish(
        str(image), "caption", operation_key="quote-1", resume=True
    )
    assert result.media_id == "789"
    assert transport.post.call_count == 2
    assert (
        len(
            [
                call
                for method, call in s3.calls
                if method == "put" and "/images/" in call["Key"]
            ]
        )
        == 1
    )


def test_reconcile_published_unknown_container_never_guesses_media_id(image, setup):
    publisher, _, transport = setup
    transport.post.side_effect = [response(payload={"id": "456"}), requests.Timeout()]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    transport.get.return_value = response(payload={"status_code": "PUBLISHED"})
    operation = publisher.reconcile(caught.value.operation_id)
    assert operation.phase == "published" and operation.media_id is None
    with pytest.raises(AlreadyPublished):
        publisher.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 2


@pytest.mark.parametrize(
    "remote_status", ["IN_PROGRESS", "FINISHED", "ERROR", "EXPIRED"]
)
def test_reconciliation_does_not_reenable_unknown_publish(image, setup, remote_status):
    publisher, _, transport = setup
    transport.post.side_effect = [response(payload={"id": "456"}), requests.Timeout()]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    transport.get.return_value = response(payload={"status_code": remote_status})
    assert publisher.reconcile(caught.value.operation_id).phase == "publish_unknown"
    with pytest.raises(PublishOutcomeUnknown):
        publisher.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 2


def test_operation_key_cannot_be_reused_with_changed_content(image, setup):
    publisher, _, transport = setup
    publisher.publish(str(image), "caption", operation_key="quote-1")
    with pytest.raises(OperationBlocked, match="conflicting content"):
        publisher.publish(str(image), "changed caption", operation_key="quote-1")
    assert transport.post.call_count == 2


def test_other_account_cannot_reconcile_or_cleanup(image, setup):
    publisher, _, _ = setup
    result = publisher.publish(str(image), "caption")
    publisher.graph.config = replace(publisher.graph.config, account_id="999")
    with pytest.raises(OperationBlocked):
        publisher.reconcile(result.operation_id)
    with pytest.raises(OperationBlocked):
        publisher.cleanup(result.operation_id)


def test_cleanup_deletes_only_image_and_retains_duplicate_guard(image, setup):
    publisher, s3, transport = setup
    result = publisher.publish(str(image), "caption")
    row, _ = publisher.storage.read(result.operation_id)
    publisher.cleanup(result.operation_id)
    assert row.object_key not in s3.objects
    assert publisher.storage.read(result.operation_id)[0].phase == "published"
    assert publisher.publish(str(image), "caption").reused
    assert transport.post.call_count == 2


def test_uncertain_operation_cannot_be_cleaned_up(image, setup):
    publisher, _, transport = setup
    transport.post.side_effect = [response(payload={"id": "456"}), requests.Timeout()]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    with pytest.raises(PublishingError, match="Only a confirmed"):
        publisher.cleanup(caught.value.operation_id)


def test_logging_failure_does_not_repeat_publication(monkeypatch):
    import instagram_publisher.legacy as legacy

    post = Mock(return_value=response(payload={"id": "789"}))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(legacy, "add_to_log", Mock(side_effect=OSError("disk full")))
    assert uploader.publish_media_container("456") == {"id": "789"}
    assert post.call_count == 1
    assert "params" not in post.call_args.kwargs
    assert "access_token" not in post.call_args.kwargs["data"]
    assert post.call_args.kwargs["allow_redirects"] is False


def test_alert_failure_is_optional_and_redacted(monkeypatch, caplog):
    import instagram_publisher.legacy as legacy

    monkeypatch.setenv("SENDER_EMAIL", "sender@example.invalid")
    monkeypatch.setenv("RECIPIENT_EMAIL", "recipient@example.invalid")
    monkeypatch.setenv("SMTP_SERVER", "smtp.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setattr(
        legacy.smtplib, "SMTP", Mock(side_effect=OSError("secret SMTP credential"))
    )
    assert not uploader.send_email_alert("subject", "body")
    assert "secret" not in caplog.text


def test_resuming_worker_fences_out_old_worker_before_publish(image, setup):
    publisher, _, old_transport = setup
    new_transport = Mock()
    new_transport.get.return_value = response(payload={"status_code": "FINISHED"})
    new_transport.post.return_value = response(payload={"id": "789"})
    from instagram_publisher.graph import GraphClient

    replacement = Publisher(
        GraphClient(publisher.graph.config, transport=new_transport), publisher.storage
    )
    publisher.graph.wait_ready = lambda container: replacement.publish(
        str(image), "caption", operation_key="quote-1", resume=True
    )
    with pytest.raises(JournalError):
        publisher.publish(str(image), "caption", operation_key="quote-1")
    assert old_transport.post.call_count == 1
    assert new_transport.post.call_count == 1
    assert replacement.publish(str(image), "caption", operation_key="quote-1").reused


def test_unknown_publish_is_preserved_when_unknown_checkpoint_also_fails(image, setup):
    publisher, s3, transport = setup
    s3.fail_phase = "publish_unknown"
    transport.post.side_effect = [
        response(payload={"id": "456"}),
        requests.Timeout("secret"),
    ]
    with pytest.raises(PublishOutcomeUnknown) as caught:
        publisher.publish(str(image), "caption")
    assert publisher.storage.read(caught.value.operation_id)[0].phase == "publishing"
    with pytest.raises(PublishOutcomeUnknown):
        publisher.publish(str(image), "caption", resume=True)
    assert transport.post.call_count == 2

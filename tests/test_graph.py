import pytest
import requests

from instagram_publisher.models import PublishingError, CreationOutcomeUnknown
from conftest import response


def test_readiness_polls_before_publish_and_uses_bearer_headers(image, setup):
    publisher, _, transport = setup
    transport.get.side_effect = [
        response(payload={"status_code": "IN_PROGRESS"}),
        response(payload={"status_code": "FINISHED"}),
    ]
    publisher.publish(str(image), "caption")
    assert transport.get.call_count == 2
    for call in transport.get.call_args_list:
        assert call.kwargs["params"] == {"fields": "status_code"}
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-secret"
        assert "secret" not in call.args[0]
        assert not call.kwargs["allow_redirects"]


@pytest.mark.parametrize("status", ["PUBLISHED", "ERROR", "EXPIRED", "UNKNOWN", None])
def test_ineligible_containers_are_never_published(image, setup, status):
    publisher, _, transport = setup
    transport.get.return_value = response(payload={"status_code": status})
    with pytest.raises(PublishingError):
        publisher.publish(str(image), "caption")
    assert transport.post.call_count == 1


def test_read_retries_are_bounded_and_do_not_repeat_mutations(image, setup):
    publisher, _, transport = setup
    transport.get.side_effect = [
        requests.Timeout("secret"),
        response(503),
        response(payload={"status_code": "FINISHED"}),
    ]
    publisher.publish(str(image), "caption")
    assert transport.get.call_count == 3
    assert transport.post.call_count == 2


def test_permanent_read_error_does_not_retry(setup):
    publisher, _, transport = setup
    transport.get.return_value = response(
        403, {"error": {"code": 10, "message": "secret"}}
    )
    with pytest.raises(PublishingError):
        publisher.graph.status("456")
    assert transport.get.call_count == 1


def test_status_retry_exhaustion_is_redacted(setup):
    publisher, _, transport = setup
    transport.get.side_effect = requests.Timeout("secret token")
    with pytest.raises(PublishingError) as caught:
        publisher.graph.status("456")
    assert "secret" not in str(caught.value)
    assert transport.get.call_count == 3


def test_readiness_has_an_absolute_deadline(image, setup):
    publisher, _, transport = setup
    now = [0.0]
    publisher.graph.clock = lambda: now[0]
    publisher.graph.sleep = lambda duration: now.__setitem__(0, now[0] + duration)
    transport.get.return_value = response(payload={"status_code": "IN_PROGRESS"})
    with pytest.raises(PublishingError, match="deadline"):
        publisher.publish(str(image), "caption")
    assert now[0] <= 1.0
    assert transport.post.call_count == 1


@pytest.mark.parametrize(
    "payload", [{}, [], {"id": "../invalid"}, {"error": {"code": 1}}]
)
def test_bad_create_response_is_uncertain_and_not_retried(setup, payload):
    publisher, _, transport = setup
    transport.post.side_effect = None
    transport.post.return_value = response(payload=payload)
    with pytest.raises(CreationOutcomeUnknown):
        publisher.graph.create("https://storage.invalid/signed", "caption")
    assert transport.post.call_count == 1


def test_malformed_publish_json_is_uncertain(setup):
    from instagram_publisher.models import PublishOutcomeUnknown

    publisher, _, transport = setup
    reply = response()
    reply._content = b"not-json secret"
    transport.post.side_effect = None
    transport.post.return_value = reply
    with pytest.raises(PublishOutcomeUnknown):
        publisher.graph.publish("456")
    assert transport.post.call_count == 1

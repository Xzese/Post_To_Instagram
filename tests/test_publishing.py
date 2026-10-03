from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import upload_photo as uploader


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    for key, value in {"GRAPH_API_VERSION": "v25.0", "ACCESS_TOKEN": "test-secret", "ACCESS_TOKEN_EXPIRY": "2099-01-01T00:00:00Z", "IG_BUSINESS_USER_ID": "123", "S3_BUCKET_NAME": "test", "S3_ENDPOINT": "https://storage.invalid", "S3_ACCESS_KEY_ID": "test", "S3_SECRET_ACCESS_KEY": "test"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Unexpected network request")))


def response(status=200, payload=None):
    return SimpleNamespace(status_code=status, json=lambda: payload)


@pytest.mark.parametrize("error", [requests.Timeout("secret-url"), requests.ConnectionError("secret-url")])
def test_transport_failure_is_uncertain_and_not_retried(monkeypatch, error):
    post = Mock(side_effect=error)
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(uploader.PublishOutcomeUnknown) as caught:
        uploader.publish_media_container("456")
    assert caught.value.creation_id == "456"
    assert "secret" not in str(caught.value)
    assert post.call_count == 1


@pytest.mark.parametrize("reply", [response(503), response(302), response(payload={}), response(payload=[]), response(payload={"id": ""})])
def test_unconfirmed_responses_are_uncertain(monkeypatch, reply):
    post = Mock(return_value=reply)
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(uploader.PublishOutcomeUnknown):
        uploader.publish_media_container("456")
    assert post.call_count == 1


def test_logging_failure_does_not_repeat_publication(monkeypatch, tmp_path):
    path = tmp_path / "sample.jpg"
    path.write_bytes(b"fixture")
    upload = Mock(return_value="https://storage.invalid/signed")
    create = Mock(return_value="456")
    post = Mock(return_value=response(payload={"id": "789"}))
    monkeypatch.setattr(uploader, "upload_image", upload)
    monkeypatch.setattr(uploader, "create_media_container", create)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(uploader, "add_to_log", Mock(side_effect=OSError("disk full")))
    assert uploader.post_random_photo(str(path), "caption") == uploader.PublishResult("789", "456")
    assert upload.call_count == create.call_count == post.call_count == 1
    assert "params" not in post.call_args.kwargs
    assert post.call_args.kwargs["timeout"] == (5, 30)
    assert post.call_args.kwargs["allow_redirects"] is False


def test_preflight_failure_has_no_upload(monkeypatch, tmp_path):
    path = tmp_path / "sample.jpg"
    path.write_bytes(b"fixture")
    upload = Mock()
    monkeypatch.setattr(uploader, "upload_image", upload)
    monkeypatch.delenv("IG_BUSINESS_USER_ID")
    with pytest.raises(uploader.PublishingError):
        uploader.publish_image(str(path), "caption")
    upload.assert_not_called()


def test_uncertain_publish_is_not_retried_by_wrapper(monkeypatch, tmp_path):
    path = tmp_path / "sample.jpg"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(uploader, "upload_image", Mock(return_value="https://storage.invalid/signed"))
    monkeypatch.setattr(uploader, "create_media_container", Mock(return_value="456"))
    publish = Mock(side_effect=uploader.PublishOutcomeUnknown("456"))
    monkeypatch.setattr(uploader, "publish_media_container", publish)
    with pytest.raises(uploader.PublishOutcomeUnknown):
        uploader.post_random_photo(str(path), "caption")
    publish.assert_called_once()


@pytest.mark.parametrize("expiry", ["not a date", "2000-01-01T00:00:00Z"])
def test_bad_token_stops_before_request(monkeypatch, expiry):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRY", expiry)
    with pytest.raises(uploader.PublishingError):
        uploader.publish_media_container("456")
    requests.post.assert_not_called()


def test_permanent_failure_is_not_retried(monkeypatch):
    post = Mock(return_value=response(400))
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(uploader.PublishingError):
        uploader.publish_media_container("456")
    post.assert_called_once()


def test_signed_urls_are_not_logged(monkeypatch, tmp_path, capsys):
    import boto3
    path = tmp_path / "image.jpg"
    path.write_bytes(b"fixture")
    client = Mock()
    client.generate_presigned_url.return_value = "https://storage.invalid/image?secret=credential"
    monkeypatch.setattr(boto3, "client", Mock(return_value=client))
    assert "secret" in uploader.upload_image(str(path))
    uploader.upload_image(str(path))
    calls = client.upload_file.call_args_list
    assert calls[0].args[2] != calls[1].args[2]
    assert calls[0].args[2].endswith(".jpg")
    assert "secret" not in capsys.readouterr().out

import pytest
import requests
from PIL import Image
import boto3

from instagram_publisher.config import graph_config, storage_config
from instagram_publisher.media import MAX_BYTES, validate_media
from instagram_publisher.models import PublishingError
from instagram_publisher.service import publish_image


@pytest.mark.parametrize(
    "size,mode,fmt",
    [
        ((100, 100), "RGB", "JPEG"),
        ((1600, 1600), "RGB", "JPEG"),
        ((512, 800), "RGB", "JPEG"),
        ((1000, 320), "RGB", "JPEG"),
        ((512, 512), "CMYK", "JPEG"),
        ((512, 512), "RGB", "PNG"),
    ],
)
def test_invalid_media_has_no_provider_side_effects(tmp_path, size, mode, fmt):
    path = tmp_path / "looks-like-a-jpeg.jpg"
    Image.new(mode, size).save(path, fmt)
    with pytest.raises(PublishingError):
        publish_image(str(path), "caption")
    requests.post.assert_not_called()
    boto3.client.assert_not_called()


@pytest.mark.parametrize(
    "data", [b"", b"fixture", b"\xff\xd8\xff", b"x" * (MAX_BYTES + 1)]
)
def test_corrupt_empty_and_oversized_files_fail_before_upload(tmp_path, data):
    path = tmp_path / "image.jpg"
    path.write_bytes(data)
    with pytest.raises(PublishingError):
        publish_image(str(path), "caption")
    boto3.client.assert_not_called()


@pytest.mark.parametrize(
    "caption",
    [
        None,
        12,
        "x" * 2201,
        "bad\0caption",
        " ".join(f"#tag{i}" for i in range(31)),
        " ".join(f"@user{i}" for i in range(21)),
    ],
)
def test_invalid_caption_has_no_provider_side_effects(image, caption):
    with pytest.raises(PublishingError):
        publish_image(str(image), caption)
    boto3.client.assert_not_called()


def test_unicode_caption_and_extensionless_valid_jpeg_are_accepted(image):
    renamed = image.with_suffix("")
    image.rename(renamed)
    assert validate_media(str(renamed), "Café ☀️\n#inspiration").width == 512


def test_uploaded_snapshot_cannot_change_after_validation(image, setup):
    publisher, s3, _ = setup
    before = image.read_bytes()
    original = publisher.storage.claim

    def change_after_preflight(row):
        image.write_bytes(b"changed on disk")
        return original(row)

    publisher.storage.claim = change_after_preflight
    publisher.publish(str(image), "caption")
    uploaded = next(
        call["Body"]
        for method, call in s3.calls
        if method == "put" and "/images/" in call["Key"]
    )
    assert uploaded == before


@pytest.mark.parametrize(
    "setting,value",
    [
        ("ACCESS_TOKEN_EXPIRY", "not a date"),
        ("ACCESS_TOKEN_EXPIRY", "2000-01-01T00:00:00Z"),
        ("ACCESS_TOKEN", "bad\nsecret"),
        ("IG_BUSINESS_USER_ID", "١٢٣"),
        ("GRAPH_API_VERSION", "latest"),
        ("CONTAINER_READY_TIMEOUT", "nan"),
        ("CONTAINER_POLL_INTERVAL", "0"),
        ("S3_ENDPOINT", "http://storage.invalid"),
        ("S3_ENDPOINT", "https://secret@storage.invalid"),
        ("S3_ENDPOINT", "https://storage.invalid/?token=secret"),
        ("S3_PREFIX", "../other"),
    ],
)
def test_invalid_config_has_no_provider_side_effects(
    monkeypatch, image, setting, value
):
    monkeypatch.setenv(setting, value)
    with pytest.raises(PublishingError) as caught:
        publish_image(str(image), "caption")
    assert "secret" not in str(caught.value)
    boto3.client.assert_not_called()
    requests.post.assert_not_called()


def test_secrets_are_absent_from_config_repr():
    assert "test-secret" not in repr(graph_config())
    assert "test-storage-secret" not in repr(storage_config())


def test_invalid_unicode_caption_fails_before_provider(image):
    with pytest.raises(PublishingError, match="valid Unicode"):
        publish_image(str(image), "bad\ud800caption")
    boto3.client.assert_not_called()

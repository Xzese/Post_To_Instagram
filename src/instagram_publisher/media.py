"""Validate and snapshot the exact JPEG bytes that will be uploaded."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import re
import warnings

from PIL import Image
from .models import PublishingError

MAX_BYTES = 8_000_000


@dataclass(frozen=True)
class Media:
    content: bytes
    digest: str
    width: int
    height: int


def validate_media(file_path: str, caption: str) -> Media:
    if not isinstance(caption, str) or len(caption) > 2200 or "\0" in caption:
        raise PublishingError(
            "The caption must be text of at most 2,200 characters without NUL characters."
        )
    if (
        len(re.findall(r"(?<!\w)#\w+", caption)) > 30
        or len(re.findall(r"(?<!\w)@\w+", caption)) > 20
    ):
        raise PublishingError("The caption exceeds 30 hashtags or 20 mentions.")
    try:
        caption.encode("utf-8")
    except UnicodeError:
        raise PublishingError("The caption must contain valid Unicode text.") from None
    try:
        with Path(file_path).open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
        if not content or len(content) > MAX_BYTES:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if (
                    image.format != "JPEG"
                    or image.mode != "RGB"
                    or not 320 <= width <= 1440
                    or height <= 0
                    or not 0.8 <= width / height <= 1.91
                ):
                    raise ValueError
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (
        OSError,
        ValueError,
        TypeError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise PublishingError(
            "A valid RGB JPEG up to 8 MB, width 320–1440 and aspect ratio 4:5–1.91:1 is required."
        ) from None
    return Media(content, hashlib.sha256(content).hexdigest(), width, height)

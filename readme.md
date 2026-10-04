# Instagram image publishing

Publish an RGB JPEG through S3-compatible storage and the Instagram API with
Facebook Login. The library validates the image and configuration, checkpoints
remote operations, waits for the container to become ready and publishes once.

Repeated calls with the same account, image bytes and caption reuse a confirmed
receipt. Workers on different devices coordinate through conditional S3 writes.
An uncertain publication stays blocked until inspected; it is never retried
because of a timeout, failed log or missing final receipt.

## Install

Use Python 3.11 or later:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-lock.txt
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
```

The lock includes development tools. `requirements.txt` lists the smaller runtime
set. A wheel can be built with `python -m build --wheel --no-isolation`.

```text
src/instagram_publisher/    configuration, media, Graph, storage and orchestration
upload_photo.py            compatibility imports for existing callers
tests/                    failure injection, loopback HTTP and process races
docs/                     API compatibility and operation recovery
```

Importing the library does not load or write `.env`. Load it explicitly in your
application, or pass `--env-file .env` to the CLI. An account ID and token expiry
are required. The endpoint is `graph.facebook.com`; Instagram Login tokens and
`graph.instagram.com` are not supported by this implementation.

## Publish

```python
from dotenv import load_dotenv
from instagram_publisher import publish_image, PublishOutcomeUnknown

load_dotenv()
try:
    result = publish_image("image.jpg", "Caption", operation_key="quote-123")
    print(result.media_id, result.operation_id, result.reused)
except PublishOutcomeUnknown as error:
    print("Inspect operation:", error.operation_id, "container:", error.creation_id)
```

```bash
python -m instagram_publisher --env-file .env publish image.jpg \
  --caption 'Caption' --operation-key quote-123
python -m instagram_publisher --env-file .env reconcile OPERATION_ID
python -m instagram_publisher --env-file .env cleanup OPERATION_ID
```

An optional `operation_key` names a logical post. Reusing it with changed content
is rejected. Without a key, the account, image bytes and caption determine the
operation. A deliberately different key creates a different operation.

`resume=True` / `--resume` can continue an interrupted upload or a known container
before publishing. Conditional checkpoints fence out an older worker. A
`creating`, `create_unknown`, `publishing`, `publish_unknown` or `failed` operation
cannot be resumed automatically. See [recovery](docs/recovery.md).

## Storage and credentials

Use an HTTPS S3 endpoint with atomic `If-None-Match` and `If-Match` writes. AWS S3
and Cloudflare R2 document these operations. The library checks conditional-write
behaviour using a small temporary probe before claiming a new operation, and
fails closed if either conditional is ignored or unsupported. A live provider
integration still needs to be tested with your account.

All workers must use the same bucket and `S3_PREFIX`. Credentials need get/put
access to `operations/`, put/get/delete access to `probes/`, and put/get access to
`images/` (delete is needed for explicit cleanup). Keep the bucket private;
only the JPEG is signed for Meta to fetch, for one hour. Tokens, captions and
signed URLs are excluded from operation records and diagnostic messages.

Keep operation receipts indefinitely. Apply any expiry rule only to the
`images/` and `probes/` prefixes, never the entire prefix. Allow enough image
retention for Meta processing and manual investigation; three days is a useful
starting point. `cleanup` deletes an image only after confirmed publication and
keeps its operation receipt. It is explicit and never changes a publish result.

The source file must decode as an RGB JPEG, be no larger than 8 MB, have width
320–1440 and aspect ratio 4:5–1.91:1. This is a conservative feed-image profile;
unsupported images fail before any storage request. Captions are limited to
2,200 characters, 30 hashtags and 20 mentions. The uploaded bytes are snapshotted
so a changing file cannot alter an operation after validation.

## Compatibility

`from upload_photo import publish_image, post_random_photo` remains supported.
`post_random_photo` now uses the same persistent orchestration. Low-level
`upload_image`, `create_media_container` and `publish_media_container` remain for
checkpointing consumers such as the quote pipeline; they do not claim a durable
operation on their own. The caller owns readiness, recovery and coordination.
Never retry `publish_media_container` on an uncertain response.

The quote pipeline remains pinned to its reviewed submodule commit. Updating its
pin and switching its adapter to the new orchestration is a separate consumer
change. Do not install a standalone `upload_photo` module into that pipeline's
namespace-package environment without updating its imports first.

`send_email_alert` is optional and bounded; publishing never sends an email
implicitly. Configure application logging yourself. Provider raw bodies, signed
URLs and tokens are not logged by this library; avoid enabling third-party HTTP
or SDK wire-debug logs with production credentials.

## Development and validation

```bash
python -m pytest -q
ruff check src tests upload_photo.py
ruff format --check src tests upload_photo.py
pip-audit --disable-pip --no-deps -r requirements-lock.txt
```

The tests include real requests/boto3 calls to a loopback simulator and independent
processes sharing atomic claims. They do not contact Meta, S3/R2 or SMTP. CI checks
Python 3.11, 3.12 and 3.13, formatting, dependency integrity, wheel building and
known dependency advisories. Regenerate the lock using `pip-compile
--generate-hashes --allow-unsafe --strip-extras --output-file requirements-lock.txt
requirements.txt requirements-dev.txt` with the locked pip-tools version.

See [API compatibility](docs/meta-api.md) and [licensing review](docs/licensing.md).
No live publication or exactly-once delivery claim is made. Remote APIs do not
provide an end-to-end idempotency contract; unknown outcomes require inspection.

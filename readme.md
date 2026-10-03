# Instagram image publishing

Python integration for uploading an image to S3-compatible storage and publishing it to an Instagram business account.

## Development status

The `portfolio-modernisation` branch contains the first reliability implementation. Keep this PR in draft. Live Meta compatibility, media-container readiness polling, persistent operation ownership and recovery across process restarts are not complete.

## Setup

Use Python 3.11 or later. Clone this repository, create a virtual environment, and install `requirements.txt`. Copy `.env.example` to `.env` and set the values. Select a Graph API version supported by your Meta application; the code does not assume a current version.

`IG_BUSINESS_USER_ID` is now required. The library does not select the first returned account. Importing the module does not load or write configuration.

```python
from dotenv import load_dotenv
from upload_photo import publish_image, PublishOutcomeUnknown

load_dotenv()
try:
    result = publish_image("image.jpg", "Caption")
    print(result.media_id)
except PublishOutcomeUnknown as error:
    # Inspect this existing container and the account before any manual retry.
    print("Unconfirmed container:", error.creation_id)
```

`post_random_photo` remains as a compatibility name. It now returns `PublishResult` or raises an exception. It no longer hides failures or retries the complete publishing sequence.

## Safety boundaries

A timeout, server error, redirect or malformed success response can leave the publication outcome unknown. No automatic publication retry is made. Logging and notification failures do not turn a confirmed publication into another attempt. Signed object URLs and raw provider response bodies are not logged.

These safeguards cover one invocation. They do not prevent another scheduler run or device from publishing the same image. Do not claim exactly-once delivery. Persistent coordination and reconciliation remain required before unattended use.

Configure Python logging in the calling application. Optional email alerts use the `SMTP_*`, `SENDER_*` and `RECIPIENT_EMAIL` settings. No notification is sent automatically by `publish_image`.

## Tests

Install pytest, then run `python -m pytest -q tests`. The first pass has 14 passing mocked tests. No live publishing or account calls were made. Full CI and provider integration checks remain pending.

This change does not add or change a licence. The repository licence review remains open.

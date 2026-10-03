# Publishing reliability modernisation

Status: implementation started; keep the PR in draft.

## Implemented in the first pass
- Explicit PublishResult, PublishingError and PublishOutcomeUnknown types.
- Preflight token, account, configuration and non-empty file checks.
- One publishing attempt; no whole-operation or media-publish retry loops.
- Logging failures cannot cause confirmed success to be published again.
- Explicit account and Graph API version settings.
- Connection/read timeouts, no automatic redirects, form-encoded POST secrets.
- Collision-resistant storage keys, content type metadata and no signed-URL logging.
- Optional bounded SMTP notification handling.
- Fourteen mocked regression tests pass locally.

## Remaining before release
- Persistent operation ownership, cross-process/device coordination and reconciliation.
- Verified media-container readiness polling and operation-specific retry policy.
- Confirm the supported live Meta API version and permissions.
- Broader media validation, storage lifecycle cleanup and integration tests.
- Complete packaging, formatting, CI and licence review.
- Coordinate consumers; the AI pipeline PR must pin this implementation before it uses publish_image.

No live Meta, storage or SMTP calls were made during validation. These tests do not prove exactly-once delivery or production readiness.

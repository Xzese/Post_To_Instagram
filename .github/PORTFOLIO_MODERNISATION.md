# Publishing reliability modernisation

Placeholder for making the Instagram publishing integration safer and easier to reuse.

## Scope
- Separate object storage, Graph API access and publishing orchestration.
- Replace mixed None/string/exception outcomes with explicit typed results.
- Validate configuration and media before external side effects.
- Add persistent operation state for upload, media-container and confirmed publish identifiers.
- Distinguish known failure from uncertain remote outcome after timeouts.
- Prevent logging or notification failures from causing a confirmed publish to be retried.
- Classify retryable and permanent failures by operation.
- Avoid automatic duplicate publication when a previous outcome cannot be established safely.
- Stop logging signed object URLs or other sensitive values.
- Use collision-resistant object keys.
- Add focused tests for uncertain outcomes, authentication failure, duplicate invocation and post-success local failures.
- Review Graph API version compatibility and make the supported version explicit.
- Correct README clone instructions, API naming and licensing documentation.

## Portfolio outcome
Show robust integration design around externally visible side effects, retries, observability and uncertain outcomes.

No implementation is included in this placeholder PR.
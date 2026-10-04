# Operation recovery

The durable record is stored at
`S3_PREFIX/operations/OPERATION_ID.json`. It contains an opaque owner token,
content fingerprint, account ID, image object key, phase, revision and any known
container/media IDs. It contains neither caption nor credentials. Retain these
records across restarts, devices and releases; do not expire them with images.

## What can resume

| Persisted phase | Action |
| --- | --- |
| `claimed`, `uploading`, `uploaded` | An explicit resume may repeat a bounded upload to the same key using the same snapshotted image bytes. |
| `container_created` | An explicit resume reuses the saved container, checks readiness and attempts publication once. |
| `creating`, `create_unknown` | Container creation may have succeeded without its ID being checkpointed. No publish was attempted by this operation. Inspect Meta and the record before creating another operation. |
| `publishing`, `publish_unknown` | A publish may have succeeded. Read the existing container/account; never issue another publish automatically. |
| `published` with a media ID | Return the saved result, without uploading, creating or publishing again. |
| `published` without a media ID | Block republishing; recover the media ID manually if your consumer needs it. |
| `failed` | An explicit Meta error was returned. The operation stays blocked. Correct configuration and inspect the account before deciding on a new operation. |

Before a mutation, a conditional checkpoint records its intent. A worker whose
ETag is stale cannot advance to the next side effect. Claims have no automatic
lease expiry: a timeout is not evidence that a remote request has stopped.

`publish_image(..., resume=True)` explicitly adopts only the safe prepublication
phases. It preserves the image key and container ID and conditionally transfers
ownership. If two workers resume simultaneously, only the worker whose update
matches the current record can advance.

## Reconciling an uncertain publish

```python
from instagram_publisher import reconcile_operation
operation = reconcile_operation("OPERATION_ID")
print(operation.phase, operation.creation_id, operation.media_id)
```

Reconciliation makes no Graph POST: it reads container status and can update the
journal conditionally. A new storage instance may also probe conditional-write
capabilities before updating that journal.
It never uploads, creates or publishes. `PUBLISHED` is a positive confirmation:
the record becomes `published` even when the media ID was lost. The library does
not guess that ID from captions, timestamps or the most recent account post.

`FINISHED`, `IN_PROGRESS`, `ERROR` and `EXPIRED` do not re-enable publication after
an uncertain call. A delayed request may still complete, and container status is
not an end-to-end idempotency guarantee. Inspect the account and provider before
any manual decision to use a different operation key. Do not delete the old
record to bypass this block.

If the process dies after container creation but before its ID is saved, the
record remains `creating`. Automated reconciliation is impossible without a
known ID. Inspect provider/account records; the library will not invent an
association between a container and the operation.

If Meta confirms a media ID but the final journal write fails, the call still
returns that successful ID. The earlier `publishing` checkpoint protects the next
run. Preserve the returned result in your caller, and reconcile the existing
container. Logging/notification failures never initiate another publication.

## Cleanup

`cleanup_operation(OPERATION_ID)` deletes only the saved JPEG of a confirmed
published operation. A missing image can be deleted repeatedly. The operation
receipt remains intact, including when cleanup fails. Unknown operations cannot
be cleaned by this API; retain their image long enough for investigation.

A lifecycle policy can remove old images and abandoned capability probes. Its
filters must not match `operations/`. Do not share a prefix with another workflow
that deletes arbitrary objects. If records are externally removed or separate
workers use different buckets/prefixes, this library cannot coordinate them.

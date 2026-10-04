# Publishing reliability modernisation

Status: implementation complete for the local/loopback validation scope. Keep
this PR in draft until live provider and owner licensing review are complete.

## Implemented

- Separated configuration/media, Graph API, S3 storage and orchestration under
  `src/instagram_publisher`, with compatibility imports and a tests directory.
- Explicit results and errors distinguish rejection, blocked ownership and
  uncertain creation/publication outcomes.
- Configuration and decoded RGB JPEG/caption preflight before provider calls.
- Persistent S3 operation receipts, account/content fingerprints, remote IDs,
  atomic cross-process/device claims and ETag checkpoints.
- Conditional-write capability probes fail closed for unsupported providers.
- Bounded readiness polling and read retries; one POST per creation/publication.
- No automatic lease expiry or uncertain POST retry. Explicit safe-phase resume
  and status-only reconciliation never guess a lost published media ID.
- Confirmed success survives failed final journal/log/alert writes. Earlier
  durable intent blocks republishing on a later invocation.
- Collision-resistant image keys; snapshotted bytes; private signed image URLs;
  no credentials, captions, signed URLs or raw provider diagnostics in receipts.
- Explicit confirmed-image cleanup retains operation receipts; documented
  image/probe lifecycle policies and indefinite receipt retention.
- Failure injection, real requests/boto3 loopback calls, independent-process races,
  packaging checks, hashed dependencies, formatting and Python 3.11–3.13 CI.
- Reviewed current Meta SDK version, login/permission differences and S3/R2
  conditional contracts; documented inaccessible developer references and live
  release checks. Reviewed missing project/submodule licensing without inventing
  an owner licence or modifying the auth submodule.

Local validation: **111 tests passed** on Python 3.11.16, including real
loopback HTTP/SDK calls and independent-process coordination. The dependency
audit found no known vulnerabilities; all 47 locked versions matched the test
environment. Lint, formatting, compilation, packaging and `pip check` passed.

## Release gates and consumers

- Live Meta app/version/permissions and actual signed-URL media fetching.
- Live S3/R2 conditional coordination and least-privilege integration.
- Owner selection of project licence before distributing releases.
- Separate quote-pipeline adapter/pin migration; its existing pin is unchanged.

No live Meta, storage or SMTP call was made. Local/loopback tests do not prove
exactly-once publication or production readiness. See docs/meta-api.md and
docs/recovery.md for the supported contract and recovery limits.

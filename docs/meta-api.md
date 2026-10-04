# Meta API compatibility review

Reviewed 2026-10-04. This library implements single feed-photo publishing through
the Instagram API **with Facebook Login**, using `graph.facebook.com`. It does
not implement Instagram Login, OAuth acquisition, stories, reels or carousels.

Meta's [official Instagram API Postman collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
describes the Facebook Login path: an Instagram professional account linked to
a Facebook Page, and the publishing permission `instagram_content_publish`.
The collection also lists `instagram_basic`, `pages_show_list` and
`pages_read_engagement` among its Facebook Login permissions. Obtain the scopes,
app review/access level and Page/account tasks needed for your particular token
and use case; importing this library does not grant them or prove entitlement.

The Instagram Login path uses a different host and
`instagram_business_content_publish` / `instagram_business_basic` scopes. Those
tokens must not be used with this library's Facebook Login endpoint.

Version selection remains explicit. Meta's own
[Facebook iOS SDK changelog](https://github.com/facebook/facebook-ios-sdk/blob/main/CHANGELOG.md)
records the switch to Graph API `v26.0` in September 2026, which is the example
configuration here. This is evidence of a current Meta SDK version, not proof
that a particular application's Instagram permissions or token work with it.
Verify the version in your Meta app and keep a supported version pinned.

## Request contract

1. `POST /{ig-account-id}/media` with a public HTTPS `image_url` and caption.
2. `GET /{container-id}?fields=status_code` until `FINISHED`, within the configured
   deadline. `ERROR`, `EXPIRED`, `PUBLISHED` and malformed responses are not ready
   states for a new publish request.
3. `POST /{ig-account-id}/media_publish` with the saved `creation_id`.
4. Save the confirmed media ID. A lost response triggers reconciliation, not
   another POST. A `PUBLISHED` container is a positive confirmation of publication.

The authoritative references are Meta's
[content publishing guide](https://developers.facebook.com/docs/instagram-platform/content-publishing/),
[IG container reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-container/)
and [IG user media reference](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/reference/ig-user/media/).
Those developer pages returned access/rate-limit errors during this review.
The status contract and conservative JPEG profile are implemented and covered
by simulated contract tests, but a live check against your supported app/version
remains a release gate. Do not treat simulated responses as live Meta validation.

Tokens are sent in an Authorization bearer header, never query parameters.
Requests have connection/read timeouts and do not follow redirects. Only status
GETs retry transient transport errors, 429s and 5xx responses, up to three attempts
within the readiness deadline. Container creation and publication each make one
POST. Error bodies are used only for classification and are not returned/logged.

## Storage contract

AWS documents atomic [conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
with `If-None-Match: *` for claims and `If-Match: ETAG` for checkpoints.
Cloudflare's [R2 S3 compatibility table](https://developers.cloudflare.com/r2/api/s3/api/)
also lists these `PutObject` conditions. The pinned botocore service model is
exercised in tests. Each new storage instance probes both rejected conditions
before it can claim a new operation. Unsupported providers fail closed.

S3 GET/PUT/DELETE use bounded standard SDK retries; repeated JPEG PUTs use the
same key and bytes, and journal PUTs retain their conditions. A lost journal
reply is read back and accepted only when its exact owner/revision/content match.
No timeout-based claim stealing or automatic deletion of receipts is performed.

## Live release checks

Using a disposable test account and bucket, verify token permissions, media
fetching through the signed HTTPS URL, readiness, successful media ID recovery,
conditional writes and least-privilege storage credentials. Also verify a lost
response scenario through a controlled proxy before unattended use. No live
Meta, cloud storage or SMTP call was made for this PR; no production credentials
were needed for the local tests.

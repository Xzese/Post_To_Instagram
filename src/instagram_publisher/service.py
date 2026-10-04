"""Publishing orchestration with durable intent before every remote mutation."""

from dataclasses import replace
import hashlib
import json
from uuid import uuid4

from .config import graph_config, storage_config
from .graph import GraphClient
from .media import validate_media
from .models import (
    AlreadyPublished,
    CreationOutcomeUnknown,
    JournalError,
    Operation,
    OperationBlocked,
    PublicationRejected,
    PublishingError,
    PublishOutcomeUnknown,
    PublishResult,
)
from .storage import S3Storage


class Publisher:
    def __init__(self, graph: GraphClient, storage: S3Storage):
        self.graph, self.storage = graph, storage

    def publish(
        self,
        file_path: str,
        caption: str,
        *,
        operation_key: str | None = None,
        resume: bool = False,
    ) -> PublishResult:
        media = validate_media(file_path, caption)
        account = self.graph.config.account_id
        fingerprint = hashlib.sha256(
            json.dumps([account, media.digest, caption], ensure_ascii=False).encode()
        ).hexdigest()
        if operation_key is not None and (
            not isinstance(operation_key, str) or not 1 <= len(operation_key) <= 256
        ):
            raise PublishingError(
                "operation_key must be text between 1 and 256 characters."
            )
        identifier = hashlib.sha256(
            json.dumps(
                [account, operation_key if operation_key is not None else fingerprint]
            ).encode()
        ).hexdigest()
        proposed = Operation(
            identifier,
            fingerprint,
            account,
            uuid4().hex,
            f"{self.storage.config.prefix}/images/{uuid4().hex}.jpg",
        )
        row, etag, owned = self.storage.claim(proposed)
        if row.fingerprint != fingerprint or row.account_id != account:
            raise OperationBlocked(identifier, "conflicting content")
        if not owned:
            if row.phase == "published":
                if row.media_id is None:
                    raise AlreadyPublished(
                        identifier, "published without a recovered media ID"
                    )
                return PublishResult(
                    row.media_id, row.creation_id, identifier, reused=True
                )
            if row.phase in {"publishing", "publish_unknown"}:
                raise PublishOutcomeUnknown(row.creation_id, identifier)
            if not resume or row.phase not in {
                "claimed",
                "uploading",
                "uploaded",
                "container_created",
            }:
                raise OperationBlocked(identifier, row.phase)
            row = replace(row, owner=proposed.owner, revision=row.revision + 1)
            etag = self.storage.checkpoint(row, etag)

        try:
            return self._publish_owned(media, caption, row, etag)
        except PublishingError as error:
            error.operation_id = identifier
            raise error from None

    def _publish_owned(self, media, caption, row, etag):
        identifier = row.operation_id

        def save(**changes):
            nonlocal row, etag
            next_row = replace(row, revision=row.revision + 1, **changes)
            etag = self.storage.checkpoint(next_row, etag)
            row = next_row

        if row.phase in {"claimed", "uploading", "uploaded"}:
            save(phase="uploading")
            image_url = self.storage.upload(media.content, row.object_key)
            save(phase="uploaded")
            save(phase="creating")
            try:
                creation_id = self.graph.create(image_url, caption)
            except CreationOutcomeUnknown:
                save(phase="create_unknown")
                raise OperationBlocked(identifier, "create_unknown") from None
            except PublishingError:
                save(phase="failed")
                raise
            # If saving the ID fails, 'creating' remains durable and blocks any
            # second container. The unpublished container needs manual recovery.
            save(phase="container_created", creation_id=creation_id)
        self.graph.wait_ready(row.creation_id)
        save(phase="publishing")
        try:
            media_id = self.graph.publish(row.creation_id)
        except PublishOutcomeUnknown:
            try:
                save(phase="publish_unknown")
            except JournalError:
                pass  # Durable 'publishing' intent already blocks a replay.
            raise PublishOutcomeUnknown(row.creation_id, identifier) from None
        except PublicationRejected:
            save(phase="failed")
            raise
        result = PublishResult(media_id, row.creation_id, identifier)
        try:
            save(phase="published", media_id=media_id)
        except JournalError:
            # Remote success is still success, even when its final receipt cannot
            # be saved. The earlier intent blocks republishing on another run.
            return result
        return result

    def reconcile(self, operation_id: str) -> Operation:
        existing = self.storage.read(operation_id)
        if not existing:
            raise PublishingError("No persisted operation was found.")
        row, etag = existing
        if row.account_id != self.graph.config.account_id:
            raise OperationBlocked(operation_id, "different account")
        if row.phase == "published" or row.creation_id is None:
            return row
        state = self.graph.status(row.creation_id)
        if state == "PUBLISHED":
            # A PUBLISHED container does not supply the published media ID. Keep
            # it null rather than guessing from caption/time/feed ordering.
            confirmed = replace(row, phase="published", revision=row.revision + 1)
            self.storage.checkpoint(confirmed, etag)
            return confirmed
        # FINISHED after a timed-out publish is not proof the original request
        # cannot finish later. Reconciliation never retries a publish POST.
        return row

    def cleanup(self, operation_id: str) -> None:
        existing = self.storage.read(operation_id)
        if not existing:
            raise PublishingError("No persisted operation was found.")
        row, _ = existing
        if row.account_id != self.graph.config.account_id:
            raise OperationBlocked(operation_id, "different account")
        self.storage.delete_image(row)


def configured_publisher() -> Publisher:
    graph, storage = graph_config(), storage_config()
    return Publisher(GraphClient(graph), S3Storage(storage))


def publish_image(
    file_path: str,
    caption: str,
    *,
    operation_key: str | None = None,
    resume: bool = False,
) -> PublishResult:
    # Validate before creating even an SDK client or a capability-probe object.
    validate_media(file_path, caption)
    return configured_publisher().publish(
        file_path, caption, operation_key=operation_key, resume=resume
    )


def reconcile_operation(operation_id: str) -> Operation:
    return configured_publisher().reconcile(operation_id)


def cleanup_operation(operation_id: str) -> None:
    configured_publisher().cleanup(operation_id)

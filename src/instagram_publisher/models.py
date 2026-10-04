"""Public results and safe, operation-specific errors."""

from dataclasses import dataclass, field


class PublishingError(RuntimeError):
    """A safe error message; this exception alone never authorises a retry."""


class OperationBlocked(PublishingError):
    def __init__(self, operation_id: str, phase: str):
        self.operation_id, self.phase = operation_id, phase
        super().__init__(
            f"Operation {operation_id} is {phase}; inspect it before continuing."
        )


class PublishOutcomeUnknown(PublishingError):
    def __init__(self, creation_id: str, operation_id: str | None = None):
        self.creation_id, self.operation_id = creation_id, operation_id
        super().__init__(
            "Publication outcome is unknown; reconcile the existing container before retrying."
        )


class CreationOutcomeUnknown(PublishingError):
    """A container may exist, but no publication has been attempted."""


class JournalError(PublishingError):
    """Durable operation ownership or checkpointing could not be confirmed."""


class PublicationRejected(PublishingError):
    """Meta returned an explicit client-error object; the call is not retried."""


class AlreadyPublished(OperationBlocked):
    """Meta confirms publication, but its media ID still needs manual recovery."""


@dataclass(frozen=True)
class PublishResult:
    media_id: str
    creation_id: str
    operation_id: str | None = None
    reused: bool = False


@dataclass(frozen=True)
class GraphConfig:
    version: str
    account_id: str
    token: str = field(repr=False)
    readiness_seconds: float = 60
    poll_seconds: float = 2

    @property
    def base(self) -> str:
        return f"https://graph.facebook.com/{self.version}"


@dataclass(frozen=True)
class StorageConfig:
    bucket: str
    endpoint: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    region: str = "auto"
    prefix: str = "instagram"
    url_seconds: int = 3600


@dataclass(frozen=True)
class Operation:
    operation_id: str
    fingerprint: str
    account_id: str
    owner: str
    object_key: str
    phase: str = "claimed"
    creation_id: str | None = None
    media_id: str | None = None
    revision: int = 0
    schema: int = 1

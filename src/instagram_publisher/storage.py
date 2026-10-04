"""S3 objects and a persistent journal using conditional object writes."""

from dataclasses import asdict
import json
import re
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .models import JournalError, Operation, PublishingError, StorageConfig

PHASES = {
    "claimed",
    "uploading",
    "uploaded",
    "creating",
    "container_created",
    "publishing",
    "published",
    "create_unknown",
    "publish_unknown",
    "failed",
}


def client_for(config: StorageConfig):
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        region_name=config.region,
        config=Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )


class S3Storage:
    def __init__(self, config: StorageConfig, *, client=None):
        self.config = config
        self.client = client if client is not None else client_for(config)
        self._verified = False

    def _key(self, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch(
            r"[a-f0-9]{64}", operation_id
        ):
            raise JournalError("A valid operation ID is required.")
        return f"{self.config.prefix}/operations/{operation_id}.json"

    def _validate(self, row: Operation):
        try:
            self._key(row.operation_id)
            checks = [
                row.schema == 1 and type(row.schema) is int,
                isinstance(row.fingerprint, str)
                and re.fullmatch(r"[a-f0-9]{64}", row.fingerprint),
                isinstance(row.account_id, str)
                and re.fullmatch(r"[0-9]+", row.account_id),
                isinstance(row.owner, str) and re.fullmatch(r"[a-f0-9]{32}", row.owner),
                isinstance(row.object_key, str)
                and re.fullmatch(
                    re.escape(self.config.prefix) + r"/images/[a-f0-9]{32}\.jpg",
                    row.object_key,
                ),
                isinstance(row.phase, str) and row.phase in PHASES,
                type(row.revision) is int and row.revision >= 0,
            ]
            for value in [row.creation_id, row.media_id]:
                checks.append(
                    value is None
                    or isinstance(value, str)
                    and re.fullmatch(r"[0-9]+", value)
                )
            if row.phase in {
                "container_created",
                "publishing",
                "publish_unknown",
                "published",
            }:
                checks.append(row.creation_id is not None)
            if row.media_id is not None:
                checks.append(row.phase == "published")
            if not all(checks):
                raise ValueError
        except (ValueError, TypeError, JournalError):
            raise JournalError(
                "The persisted operation record is invalid; no side effect was attempted."
            ) from None

    def read(self, operation_id: str):
        key = self._key(operation_id)
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise JournalError("Operation record read failed.") from None
        except Exception:
            raise JournalError("Operation record read failed.") from None
        try:
            try:
                content = response["Body"].read(16_385)
            finally:
                response["Body"].close()
            if len(content) > 16_384:
                raise ValueError
            row = Operation(**json.loads(content))
            self._validate(row)
            etag = response["ETag"]
            if (
                row.operation_id != operation_id
                or not isinstance(etag, str)
                or not etag
            ):
                raise ValueError
            return row, etag
        except Exception:
            raise JournalError(
                "The persisted operation record is invalid; no side effect was attempted."
            ) from None

    def verify_conditionals(self):
        """Fail closed if a compatible provider silently ignores conditional writes."""
        if self._verified:
            return
        key = f"{self.config.prefix}/probes/{uuid4().hex}.json"
        try:
            first = self.client.put_object(
                Bucket=self.config.bucket,
                Key=key,
                Body=b"{}",
                IfNoneMatch="*",
                ContentType="application/json",
            )
            etag = first["ETag"]
            if not isinstance(etag, str) or not etag:
                raise ValueError
            for condition in [
                {"IfNoneMatch": "*"},
                {"IfMatch": '"intentionally-invalid-etag"'},
            ]:
                try:
                    self.client.put_object(
                        Bucket=self.config.bucket,
                        Key=key,
                        Body=b'{"probe":true}',
                        ContentType="application/json",
                        **condition,
                    )
                except ClientError as error:
                    if (
                        error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                        == 412
                    ):
                        continue
                    raise
                raise ValueError
            self._verified = True
        except Exception:
            raise JournalError(
                "Storage must support atomic If-None-Match and If-Match writes; capability verification failed."
            ) from None
        finally:
            try:
                self.client.delete_object(Bucket=self.config.bucket, Key=key)
            except Exception:
                pass

    def claim(self, row: Operation):
        self._validate(row)
        existing = self.read(row.operation_id)
        if existing is not None:
            return *existing, False
        self.verify_conditionals()
        try:
            result = self.client.put_object(
                Bucket=self.config.bucket,
                Key=self._key(row.operation_id),
                Body=json.dumps(asdict(row), sort_keys=True).encode(),
                ContentType="application/json",
                IfNoneMatch="*",
            )
            etag = result.get("ETag")
            if isinstance(etag, str) and etag:
                return row, etag, True
        except Exception:
            pass
        # A timeout/SDK retry may hide a successful claim. Only our unique owner
        # token and exact proposed record can confirm that this worker owns it.
        existing = self.read(row.operation_id)
        if existing is None:
            raise JournalError("Operation ownership could not be confirmed.")
        return *existing, existing[0] == row

    def checkpoint(self, row: Operation, etag: str):
        self._validate(row)
        self.verify_conditionals()
        try:
            result = self.client.put_object(
                Bucket=self.config.bucket,
                Key=self._key(row.operation_id),
                Body=json.dumps(asdict(row), sort_keys=True).encode(),
                ContentType="application/json",
                IfMatch=etag,
            )
            new_etag = result.get("ETag")
            if isinstance(new_etag, str) and new_etag:
                return new_etag
        except Exception:
            pass
        existing = self.read(row.operation_id)
        if existing and existing[0] == row:
            return existing[1]
        raise JournalError(
            "Operation checkpoint could not be confirmed; no further publishing request was made."
        )

    def upload(self, content: bytes, object_key: str):
        try:
            self.client.put_object(
                Bucket=self.config.bucket,
                Key=object_key,
                Body=content,
                ContentType="image/jpeg",
            )
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": object_key},
                ExpiresIn=self.config.url_seconds,
            )
            if not isinstance(url, str):
                raise ValueError
            return url
        except Exception:
            raise PublishingError("Object upload or signing failed.") from None

    def delete_image(self, row: Operation):
        self._validate(row)
        if row.phase != "published":
            raise PublishingError(
                "Only a confirmed published operation is eligible for image cleanup."
            )
        try:
            self.client.delete_object(Bucket=self.config.bucket, Key=row.object_key)
        except Exception:
            raise PublishingError(
                "Image cleanup failed; the confirmed publication is unchanged."
            ) from None

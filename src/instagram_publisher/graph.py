"""Graph transport: bounded read retries, single-attempt side effects."""

import time
from urllib.parse import urlsplit
import requests

from .config import numeric_id
from .models import (
    CreationOutcomeUnknown,
    GraphConfig,
    PublicationRejected,
    PublishOutcomeUnknown,
    PublishingError,
)

REQUEST_TIMEOUT = (5, 30)


class GraphClient:
    def __init__(
        self,
        config: GraphConfig,
        *,
        transport=requests,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.config, self.transport, self.sleep, self.clock = (
            config,
            transport,
            sleep,
            clock,
        )

    def _request(self, method, path, *, deadline=None, **kwargs):
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            remaining = deadline - self.clock() if deadline is not None else 35
            if remaining <= 0:
                raise PublishingError("Container status read deadline exceeded.")
            timeout = (
                (min(5, remaining / 2), min(30, remaining / 2))
                if deadline is not None
                else REQUEST_TIMEOUT
            )
            try:
                response = getattr(self.transport, method.lower())(
                    f"{self.config.base}/{path}",
                    headers={"Authorization": "Bearer " + self.config.token},
                    timeout=timeout,
                    allow_redirects=False,
                    **kwargs,
                )
            except requests.RequestException:
                if method == "GET" and attempt + 1 < attempts:
                    self._pause(attempt, deadline)
                    continue
                if method == "GET":
                    raise PublishingError("Container status read failed.") from None
                if path.endswith("/media_publish"):
                    raise PublishOutcomeUnknown(kwargs["data"]["creation_id"]) from None
                raise CreationOutcomeUnknown(
                    "Container creation outcome is unknown; no automatic retry was made."
                ) from None
            try:
                status = response.status_code
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
            finally:
                response.close()
            if (
                method == "GET"
                and (status == 429 or status >= 500)
                and attempt + 1 < attempts
            ):
                self._pause(attempt, deadline)
                continue
            return status, payload
        raise PublishingError("Provider read failed.")

    def _pause(self, attempt, deadline):
        delay = 0.25 * 2**attempt
        if deadline is not None:
            delay = min(delay, max(0, deadline - self.clock()))
        self.sleep(delay)

    def create(self, image_url: str, caption: str) -> str:
        parts = urlsplit(image_url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise PublishingError("The image URL must use HTTPS.")
        status, payload = self._request(
            "POST",
            f"{self.config.account_id}/media",
            data={"image_url": image_url, "caption": caption},
        )
        if status == 200 and isinstance(payload, dict):
            try:
                return numeric_id(payload.get("id"))
            except PublishingError:
                pass
        if self._explicit_rejection(status, payload):
            raise PublishingError("Meta rejected media container creation.")
        raise CreationOutcomeUnknown(
            "Container creation outcome is unknown; no automatic retry was made."
        )

    @staticmethod
    def _explicit_rejection(status, payload):
        error = payload.get("error") if isinstance(payload, dict) else None
        return (
            400 <= status < 500
            and status not in (408, 429)
            and isinstance(error, dict)
            and type(error.get("code")) is int
        )

    def publish(self, creation_id: str) -> str:
        numeric_id(creation_id)
        status, payload = self._request(
            "POST",
            f"{self.config.account_id}/media_publish",
            data={"creation_id": creation_id},
        )
        if status == 200 and isinstance(payload, dict):
            try:
                return numeric_id(payload.get("id"))
            except PublishingError:
                pass
        if self._explicit_rejection(status, payload):
            raise PublicationRejected(
                "Meta rejected publication; no automatic retry was made."
            )
        raise PublishOutcomeUnknown(creation_id)

    def status(self, creation_id: str, *, deadline=None) -> str:
        status, payload = self._request(
            "GET",
            numeric_id(creation_id),
            params={"fields": "status_code"},
            deadline=deadline,
        )
        state = payload.get("status_code") if isinstance(payload, dict) else None
        if status != 200 or state not in {
            "IN_PROGRESS",
            "FINISHED",
            "PUBLISHED",
            "ERROR",
            "EXPIRED",
        }:
            raise PublishingError("Meta returned no valid container status.")
        return state

    def wait_ready(self, creation_id: str) -> None:
        deadline = self.clock() + self.config.readiness_seconds
        while True:
            state = self.status(creation_id, deadline=deadline)
            if state == "FINISHED":
                return
            if state != "IN_PROGRESS":
                raise PublishingError(
                    "Container is not eligible for publication; reconcile it before another attempt."
                )
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise PublishingError("Container readiness deadline exceeded.")
            self.sleep(min(self.config.poll_seconds, remaining))

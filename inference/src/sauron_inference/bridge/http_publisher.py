from __future__ import annotations

import logging
import os

import httpx

from ..rules.events import Event
from .common import event_payload

log = logging.getLogger(__name__)


class HTTPEventPublisher:
    """Posts events directly to the API ingest endpoint (no broker required).

    Sends a bearer token when SAURON_INGEST_TOKEN is set (required when the
    API has auth enabled).
    """

    def __init__(
        self,
        api_url: str,
        timeout_s: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            headers = {}
            token = os.environ.get("SAURON_INGEST_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self._client = httpx.Client(base_url=api_url, timeout=timeout_s, headers=headers)

    def __call__(self, event: Event) -> None:
        try:
            resp = self._client.post("/api/v1/events", json=event_payload(event))
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("failed to POST event to API")

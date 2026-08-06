from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from .config import get_settings

log = logging.getLogger(__name__)


class SnapshotStorage:
    """MinIO/S3 storage for event snapshots. Disabled when no endpoint is set."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.s3_endpoint)

    def _get_client(self):
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self._settings.s3_endpoint,
                access_key=self._settings.s3_access_key,
                secret_key=self._settings.s3_secret_key,
                secure=self._settings.s3_secure,
            )
        return self._client

    def _put(self, key: str, data: bytes) -> None:
        import io

        client = self._get_client()
        bucket = self._settings.s3_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(bucket, key, io.BytesIO(data), len(data), content_type="image/jpeg")

    async def upload_snapshot(
        self, camera_id: uuid.UUID, ts: datetime, jpeg: bytes
    ) -> str | None:
        if not self.enabled:
            return None
        key = f"snapshots/{camera_id}/{ts:%Y/%m/%d/%H%M%S}-{uuid.uuid4().hex[:8]}.jpg"
        try:
            await asyncio.to_thread(self._put, key, jpeg)
            return key
        except Exception:
            log.exception("snapshot upload failed")
            return None

    def _presign(self, key: str) -> str | None:
        from datetime import timedelta

        try:
            return self._get_client().presigned_get_object(
                self._settings.s3_bucket, key, expires=timedelta(hours=1)
            )
        except Exception:
            log.exception("presign failed for %s", key)
            return None

    async def presigned_url(self, key: str | None) -> str | None:
        if not key or not self.enabled:
            return None
        return await asyncio.to_thread(self._presign, key)


_storage: SnapshotStorage | None = None


def get_storage() -> SnapshotStorage:
    global _storage
    if _storage is None:
        _storage = SnapshotStorage()
    return _storage

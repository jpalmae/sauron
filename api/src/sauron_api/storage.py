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
        self._public_client = None
        self._lifecycle_checked = False

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
        if not self._lifecycle_checked:
            self._lifecycle_checked = True
            days = self._settings.s3_retention_days
            if days > 0:
                try:
                    self._apply_lifecycle(days)
                except Exception:
                    log.exception("failed to apply bucket lifecycle")
        return self._client

    def _apply_lifecycle(self, days: int) -> None:
        from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

        client = self._client
        assert client is not None
        client.set_bucket_lifecycle(
            self._settings.s3_bucket,
            LifecycleConfig(
                [
                    Rule(
                        rule_id="expire-evidence",
                        status="Enabled",
                        expiration=Expiration(days=days),
                    )
                ]
            ),
        )
        log.info("bucket %s lifecycle: evidence expires after %d days",
                 self._settings.s3_bucket, days)

    def _get_public_client(self):
        """Client bound to the browser-reachable endpoint (presigned URLs).

        Built with an explicit region so presigning needs no network call —
        the endpoint only has to be reachable from the browser (e.g. the
        nginx-proxied bucket path on the web origin).
        """
        if self._public_client is None:
            from minio import Minio

            endpoint = self._settings.s3_public_endpoint or self._settings.s3_endpoint
            self._public_client = Minio(
                endpoint,
                access_key=self._settings.s3_access_key,
                secret_key=self._settings.s3_secret_key,
                secure=self._settings.s3_secure,
                region="us-east-1",
            )
        return self._public_client

    def _put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        import io

        client = self._get_client()
        bucket = self._settings.s3_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)

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

    async def upload_clip(
        self, camera_id: uuid.UUID, ts: datetime, mp4: bytes
    ) -> str | None:
        if not self.enabled:
            return None
        key = f"clips/{camera_id}/{ts:%Y/%m/%d/%H%M%S}-{uuid.uuid4().hex[:8]}.mp4"
        try:
            await asyncio.to_thread(self._put, key, mp4, "video/mp4")
            return key
        except Exception:
            log.exception("clip upload failed")
            return None

    def _presign(self, key: str) -> str | None:
        from datetime import timedelta

        try:
            return self._get_public_client().presigned_get_object(
                self._settings.s3_bucket, key, expires=timedelta(hours=1)
            )
        except Exception:
            log.exception("presign failed for %s", key)
            return None

    async def presigned_url(self, key: str | None) -> str | None:
        if not key or not self.enabled:
            return None
        return await asyncio.to_thread(self._presign, key)

    def _get(self, key: str) -> bytes:
        resp = self._get_client().get_object(self._settings.s3_bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    async def download_bytes(self, key: str) -> bytes | None:
        if not self.enabled:
            return None
        try:
            return await asyncio.to_thread(self._get, key)
        except Exception:
            log.exception("download failed for %s", key)
            return None


_storage: SnapshotStorage | None = None


def get_storage() -> SnapshotStorage:
    global _storage
    if _storage is None:
        _storage = SnapshotStorage()
    return _storage

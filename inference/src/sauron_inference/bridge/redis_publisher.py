from __future__ import annotations

import logging

from ..rules.events import Event
from .common import dumps

log = logging.getLogger(__name__)

DEFAULT_CHANNEL = "sauron:events"


class RedisEventPublisher:
    """Publishes events to a Redis Pub/Sub channel (sync client, worker-thread safe)."""

    def __init__(self, redis_url: str, channel: str = DEFAULT_CHANNEL) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url)
        self._channel = channel

    def __call__(self, event: Event) -> None:
        try:
            self._client.publish(self._channel, dumps(event))
        except Exception:
            log.exception("failed to publish event to redis")

from __future__ import annotations

import logging
import uuid

log = logging.getLogger(__name__)

LEADER_KEY = "sauron:inference:leader"


class RedisLeaderElector:
    """Active/standby leader election via Redis (SET NX PX + heartbeat).

    Run N inference replicas with SAURON_HA_ENABLED=true + shared Redis:
    only the leader runs pipelines; standby takes over within ~2x ttl.
    """

    def __init__(self, redis_url: str, ttl_s: float = 15.0, node_id: str | None = None) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url)
        self.ttl_ms = int(ttl_s * 1000)
        self.node_id = node_id or uuid.uuid4().hex[:12]
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    def try_acquire(self) -> bool:
        """Attempt to acquire/renew leadership. Updates is_leader."""
        acquired = self._client.set(LEADER_KEY, self.node_id, nx=True, px=self.ttl_ms)
        if acquired:
            if not self._is_leader:
                log.info("became leader (%s)", self.node_id)
            self._is_leader = True
            return True
        current = self._client.get(LEADER_KEY)
        if current is not None and self._value(current) == self.node_id:
            self._client.pexpire(LEADER_KEY, self.ttl_ms)  # renew
            self._is_leader = True
            return True
        if self._is_leader:
            log.warning("lost leadership (%s)", self.node_id)
        self._is_leader = False
        return False

    def release(self) -> None:
        current = self._client.get(LEADER_KEY)
        if current is not None and self._value(current) == self.node_id:
            self._client.delete(LEADER_KEY)
        self._is_leader = False

    @staticmethod
    def _value(raw: bytes | str) -> str:
        return raw.decode() if isinstance(raw, bytes) else raw

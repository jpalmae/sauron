import sys
import types

from sauron_inference.ha import LEADER_KEY, RedisLeaderElector


class FakeRedis:
    """Minimal SET NX PX / GET / PEXPIRE / DELETE semantics."""

    def __init__(self):
        self.store = {}

    @classmethod
    def from_url(cls, url):
        return cls()

    def set(self, key, value, nx=False, px=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        v = self.store.get(key)
        return v.encode() if isinstance(v, str) else v

    def pexpire(self, key, ms):
        return key in self.store

    def delete(self, key):
        self.store.pop(key, None)


def _elector(monkeypatch, node_id, store):
    fake_mod = types.ModuleType("redis")
    fake_mod.Redis = type("R", (), {"from_url": classmethod(lambda cls, url: FakeRedis())})
    monkeypatch.setitem(sys.modules, "redis", fake_mod)
    r = FakeRedis()
    r.store = store  # shared store between "nodes"
    e = RedisLeaderElector.__new__(RedisLeaderElector)
    e._client = r
    e.ttl_ms = 15000
    e.node_id = node_id
    e._is_leader = False
    return e


def test_single_leader_acquires_and_renews(monkeypatch):
    store = {}
    a = _elector(monkeypatch, "node-a", store)
    assert a.try_acquire() is True
    assert a.is_leader
    # renew (same node re-acquires)
    assert a.try_acquire() is True


def test_second_node_is_standby_then_takes_over(monkeypatch):
    store = {}
    a = _elector(monkeypatch, "node-a", store)
    b = _elector(monkeypatch, "node-b", store)

    assert a.try_acquire() is True
    assert b.try_acquire() is False
    assert not b.is_leader

    # a crashes (no renew, key expired/deleted) -> b takes over
    store.pop(LEADER_KEY)
    assert b.try_acquire() is True
    assert b.is_leader
    # a comes back but is now standby
    assert a.try_acquire() is False


def test_release_only_by_leader(monkeypatch):
    store = {}
    a = _elector(monkeypatch, "node-a", store)
    b = _elector(monkeypatch, "node-b", store)
    a.try_acquire()
    b.release()  # standby must NOT delete leader's key
    assert store.get(LEADER_KEY) == "node-a"
    a.release()
    assert LEADER_KEY not in store

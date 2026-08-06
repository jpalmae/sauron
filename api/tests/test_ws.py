from sauron_api.ws import ConnectionManager


class FakeWS:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, msg):
        if self.fail:
            raise RuntimeError("broken pipe")
        self.sent.append(msg)


async def test_broadcast_reaches_all_clients():
    mgr = ConnectionManager()
    a, b = FakeWS(), FakeWS()
    await mgr.connect(a)
    await mgr.connect(b)
    await mgr.broadcast({"event_type": "WRONG_WAY"})
    assert a.sent == [{"event_type": "WRONG_WAY"}]
    assert b.sent == [{"event_type": "WRONG_WAY"}]
    assert mgr.client_count == 2


async def test_dead_clients_are_dropped():
    mgr = ConnectionManager()
    good, bad = FakeWS(), FakeWS(fail=True)
    await mgr.connect(good)
    await mgr.connect(bad)
    await mgr.broadcast({"x": 1})
    assert mgr.client_count == 1
    assert good.sent == [{"x": 1}]


def _all_paths(routes):
    for r in routes:
        if hasattr(r, "path") and r.path:
            yield r.path
        for sub in (getattr(r, "routes", None), getattr(r, "original_router", None)):
            if sub is not None:
                yield from _all_paths(getattr(sub, "routes", []))


def test_ws_route_registered():
    from sauron_api.main import app
    from sauron_api.ws import router as ws_router

    assert any(getattr(r, "path", "") == "/ws/alerts" for r in ws_router.routes)
    paths = set(_all_paths(app.routes))
    assert "/ws/alerts" in paths
    assert "/cameras" in paths  # mounted under /api/v1 prefix

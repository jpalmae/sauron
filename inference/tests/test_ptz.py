
from sauron_inference.config import PTZConfig
from sauron_inference.ptz import PtzController, compute_move


class TestComputeMove:
    def test_centered_is_zero(self):
        vx, vy = compute_move((640, 360), (1280, 720))
        assert vx == 0.0 and vy == 0.0

    def test_right_edge_moves_right(self):
        vx, _ = compute_move((1200, 360), (1280, 720))
        assert vx > 0.8

    def test_top_moves_up(self):
        _, vy = compute_move((640, 60), (1280, 720))
        assert vy > 0.5  # negative dy -> pan up (camera y axis inverted)

    def test_clamped(self):
        vx, vy = compute_move((1280, 0), (1280, 720))
        assert vx <= 1.0 and vy <= 1.0


class FakeService:
    def __init__(self):
        self.moves = []
        self.stopped = False
        self.preset = None

    def ContinuousMove(self, payload):
        self.moves.append(payload)

    def Stop(self, payload):
        self.stopped = True

    def GotoPreset(self, payload):
        self.preset = payload["PresetToken"]


class TestController:
    def test_track_move_and_home(self):
        cfg = PTZConfig(host="cam", follow_seconds=0.05, preset_token="home1", cooldown_s=0.1)
        ctl = PtzController(cfg)
        svc = FakeService()
        ctl._service = svc  # bypass onvif connect

        assert ctl.track((1200, 360), (1280, 720)) is True
        assert len(svc.moves) == 1
        vx = svc.moves[0]["Velocity"]["PanTilt"]["x"]
        assert vx > 0

        # cooldown blocks a second immediate track
        assert ctl.track((100, 360), (1280, 720)) is False

        import time

        time.sleep(0.2)
        assert svc.stopped is True
        assert svc.preset == "home1"

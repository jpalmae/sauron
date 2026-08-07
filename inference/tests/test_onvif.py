import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "onvif_discover", Path(__file__).parent.parent / "tools" / "onvif_discover.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules["onvif_discover"] = mod  # dataclass resolution needs the module registered
spec.loader.exec_module(mod)

Profile = mod.Profile
select_rtsp_profile = mod.select_rtsp_profile


def test_prefers_hd_over_sub_hd():
    profiles = [
        Profile("sub", "rtsp://cam/sub", 704, 576),
        Profile("main", "rtsp://cam/main", 1920, 1080),
    ]
    assert select_rtsp_profile(profiles).name == "main"


def test_picks_highest_resolution():
    profiles = [
        Profile("hd", "rtsp://cam/hd", 1280, 720),
        Profile("fhd", "rtsp://cam/fhd", 1920, 1080),
    ]
    assert select_rtsp_profile(profiles).name == "fhd"


def test_falls_back_to_best_available_when_no_hd():
    profiles = [
        Profile("low", "rtsp://cam/low", 320, 240),
        Profile("mid", "rtsp://cam/mid", 704, 576),
    ]
    assert select_rtsp_profile(profiles, min_width=1280).name == "mid"


def test_empty_profiles():
    assert select_rtsp_profile([]) is None

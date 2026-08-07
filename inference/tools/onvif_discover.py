#!/usr/bin/env python3
"""ONVIF camera discovery: finds cameras on the LAN and proposes stream config.

Requires the optional extra:  pip install -e ".[onvif]"

Usage:
    python tools/onvif_discover.py --user admin --password secret [--timeout 8]

Prints a YAML `streams:` block ready to paste into pipeline.yaml.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass


@dataclass
class Profile:
    name: str
    rtsp_url: str
    width: int
    height: int


def select_rtsp_profile(profiles: list[Profile], min_width: int = 1280) -> Profile | None:
    """Pick the highest-resolution profile at or above HD; else the best available."""
    if not profiles:
        return None
    hd = [p for p in profiles if p.width >= min_width]
    candidates = hd or profiles
    return max(candidates, key=lambda p: p.width * p.height)


def discover(timeout: int) -> list[str]:
    """WS-Discovery probe; returns ONVIF XAddr service URLs."""
    from wsdiscovery import QName
    from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery

    wsd = WSDiscovery()
    wsd.start()
    try:
        services = wsd.searchServices(types=[QName("http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter")], timeout=timeout)
        xaddrs: list[str] = []
        for service in services:
            for xaddr in service.getXAddrs():
                if xaddr not in xaddrs:
                    xaddrs.append(xaddr)
        return xaddrs
    finally:
        wsd.stop()


def profiles_for(xaddr: str, user: str, password: str) -> tuple[str, list[Profile]]:
    """Query one camera: device info + RTSP URL per profile."""
    from onvif import ONVIFCamera

    cam = ONVIFCamera(xaddr.split("/")[2].split(":")[0], 80, user, password)
    info = cam.devicemgmt.GetDeviceInformation()
    name = f"{info.Manufacturer}-{info.Model}".replace(" ", "_")
    media = cam.create_media_service()
    profiles: list[Profile] = []
    for p in media.GetProfiles():
        try:
            uri = media.GetStreamUri(
                {"StreamSetup": {"Stream": "RTP-Unicast", "Transport": "RTSP"}, "ProfileToken": p.token}
            ).Uri
            ve = p.VideoEncoderConfiguration
            profiles.append(
                Profile(p.Name, uri, int(ve.Resolution.Width), int(ve.Resolution.Height))
            )
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            print(f"  # profile {getattr(p, 'Name', '?')} skipped: {e}", file=sys.stderr)
            continue
    return name, profiles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    xaddrs = discover(args.timeout)
    if not xaddrs:
        print("no ONVIF cameras found", file=sys.stderr)
        return 1

    print("streams:")
    for i, xaddr in enumerate(xaddrs, 1):
        try:
            name, profiles = profiles_for(xaddr, args.user, args.password)
        except Exception as e:  # noqa: BLE001 - camera firmware varies; skip and continue
            print(f"  # {xaddr}: query failed: {e}", file=sys.stderr)
            continue
        best = select_rtsp_profile(profiles)
        if best is None:
            print(f"  # {xaddr}: no RTSP profiles", file=sys.stderr)
            continue
        print(f"  - id: {name.lower()}-{i:02d}")
        print(f'    name: "{name} ({i})"')
        print("    type: rtsp")
        print(f'    source: "{best.rtsp_url}"')
        print(f"    target_fps: 15  # {best.width}x{best.height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

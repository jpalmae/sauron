from __future__ import annotations

import base64
import json
import socket
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: str
    latency_ms: int
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    pixel_format: str | None
    bitrate_kbps: int | None
    preview_jpeg: str | None
    error: str | None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "latency_ms": self.latency_ms,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "pixel_format": self.pixel_format,
            "bitrate_kbps": self.bitrate_kbps,
            "preview_jpeg": self.preview_jpeg,
            "error": self.error,
        }


def probe_camera(uri: str, timeout: float = 20.0, preview_width: int = 960) -> ProbeResult:
    parsed = urlparse(uri.strip())
    if parsed.scheme not in {"rtsp", "rtsps", "http", "https"}:
        raise ValueError("camera URL must use rtsp, rtsps, http or https")
    command = ["ffprobe", "-v", "error"]
    if parsed.scheme in {"rtsp", "rtsps"}:
        command.extend(["-rtsp_transport", "tcp"])
    command.extend(
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,pix_fmt,bit_rate",
            "-of",
            "json",
            uri,
        ]
    )
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return ProbeResult(
            "failed",
            round(timeout * 1000),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "connection timed out",
        )
    latency_ms = round((time.monotonic() - started) * 1000)
    if result.returncode != 0:
        return ProbeResult(
            "failed",
            latency_ms,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            _safe_error(result.stderr.decode(errors="replace"), uri),
        )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return ProbeResult(
            "failed",
            latency_ms,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "source has no video stream",
        )
    fps = _ratio(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    bitrate = _integer(stream.get("bit_rate"))
    preview = _capture_preview(uri, parsed.scheme, timeout, preview_width)
    return ProbeResult(
        status="ok",
        latency_ms=latency_ms,
        codec=stream.get("codec_name"),
        width=_integer(stream.get("width")),
        height=_integer(stream.get("height")),
        fps=round(fps, 2) if fps is not None else None,
        pixel_format=stream.get("pix_fmt"),
        bitrate_kbps=round(bitrate / 1000) if bitrate is not None else None,
        preview_jpeg=preview,
        error=None,
    )


def _capture_preview(uri: str, scheme: str, timeout: float, width: int) -> str | None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if scheme in {"rtsp", "rtsps"}:
        command.extend(["-rtsp_transport", "tcp"])
    command.extend(
        [
            "-i",
            uri,
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({width},iw)':-2",
            "-q:v",
            "3",
            "-f",
            "image2pipe",
            "pipe:1",
        ]
    )
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not result.stdout.startswith(b"\xff\xd8"):
        return None
    return base64.b64encode(result.stdout).decode()


def discover_onvif(timeout: float = 3.0) -> list[dict[str, str | list[str]]]:
    """Discover ONVIF devices with WS-Discovery; credentials are not required."""
    message_id = f"uuid:{uuid.uuid4()}"
    probe = f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header><w:MessageID>{message_id}</w:MessageID>
 <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
 <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>""".encode()
    found: dict[str, dict[str, str | list[str]]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.25)
        sock.sendto(probe, ("239.255.255.250", 3702))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(64 * 1024)
            except TimeoutError:
                continue
            for device in parse_onvif_response(data, address[0]):
                found[str(device["endpoint"])] = device
    finally:
        sock.close()
    return list(found.values())


def parse_onvif_response(data: bytes, source_ip: str) -> list[dict[str, str | list[str]]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    devices: list[dict[str, str | list[str]]] = []
    for match in root.iter():
        if not match.tag.endswith("ProbeMatch"):
            continue
        xaddrs: list[str] = []
        scopes: list[str] = []
        endpoint = ""
        for element in match.iter():
            text = (element.text or "").strip()
            if element.tag.endswith("XAddrs"):
                xaddrs.extend(text.split())
            elif element.tag.endswith("Scopes"):
                scopes.extend(unquote(scope) for scope in text.split())
            elif element.tag.endswith("Address") and text:
                endpoint = text
        if endpoint or xaddrs:
            devices.append(
                {
                    "endpoint": endpoint or xaddrs[0],
                    "ip": source_ip,
                    "xaddrs": xaddrs,
                    "scopes": scopes,
                    "name": _scope_value(scopes, "/name/") or source_ip,
                    "location": _scope_value(scopes, "/location/") or "",
                }
            )
    return devices


def _scope_value(scopes: list[str], marker: str) -> str | None:
    for scope in scopes:
        if marker in scope:
            return scope.rsplit(marker, 1)[-1].replace("_", " ")
    return None


def _ratio(value: object) -> float | None:
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _safe_error(message: str, uri: str) -> str:
    cleaned = " ".join(message.strip().split())[:500]
    if uri:
        cleaned = cleaned.replace(uri, "<camera-url>")
    parsed = urlparse(uri)
    if parsed.password:
        cleaned = cleaned.replace(parsed.password, "***")
    return cleaned or "unable to open camera stream"

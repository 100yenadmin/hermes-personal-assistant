"""Consent-gated geography with an allowlisted, pinned HTTPS connection."""
from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import time
from urllib.parse import urlencode, urlparse

from .gog_collector import DailyOpsError

_ALLOWED_HOSTS = {"nominatim.openstreetmap.org", "router.project-osrm.org"}
_UA = "personal-assistant-daily-ops/3"
_last_call = 0.0
_MIN_INTERVAL = 1.1


def _assert_public_https(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise DailyOpsError("GEO_REFUSED: endpoint must be approved HTTPS")
    host = parsed.hostname
    if not host or host.lower() not in _ALLOWED_HOSTS:
        raise DailyOpsError("GEO_REFUSED: endpoint host is not approved")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DailyOpsError("GEO_REFUSED: endpoint DNS lookup failed") from exc
    addresses = []
    for info in infos:
        try:
            address = str(ipaddress.ip_address(info[4][0]))
        except ValueError as exc:
            raise DailyOpsError("GEO_REFUSED: endpoint address is invalid") from exc
        ip = ipaddress.ip_address(address)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise DailyOpsError("GEO_REFUSED: endpoint resolves to a non-public address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise DailyOpsError("GEO_REFUSED: endpoint has no usable address")
    # Deterministic pinning makes the DNS result checked here the one curl uses.
    return host, addresses[0]


def _curl_json(url: str, timeout: int = 20, *, pinned: tuple[str, str] | None = None):
    global _last_call
    delay = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if delay > 0:
        time.sleep(delay)
    _last_call = time.monotonic()
    command = ["curl", "--silent", "--show-error", "--noproxy", "*", "--proto", "=https", "--max-time", str(timeout), "-A", _UA]
    if pinned:
        host, address = pinned
        port = urlparse(url).port or 443
        command += ["--resolve", f"{host}:{port}:{address}"]
    command.append(url)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _endpoint(geo_cfg: dict, key: str, default: str) -> str:
    base = geo_cfg.get(key, default)
    if not isinstance(base, str):
        raise DailyOpsError("GEO_REFUSED: endpoint must be a string")
    return base.rstrip("/")


def geocode(query: str, geo_cfg: dict):
    if (geo_cfg or {}).get("consent") is not True:
        return None
    base = _endpoint(geo_cfg or {}, "base", "https://nominatim.openstreetmap.org")
    url = base + "/search?" + urlencode({"q": query, "format": "json", "limit": 1})
    pinned = _assert_public_https(url)
    data = _curl_json(url, pinned=pinned)
    try:
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def drive_minutes(from_ll, to_ll, geo_cfg: dict):
    if not isinstance(from_ll, (tuple, list)) or not isinstance(to_ll, (tuple, list)):
        return None
    base = _endpoint(geo_cfg or {}, "osrm_base", "https://router.project-osrm.org")
    try:
        url = f"{base}/route/v1/driving/{float(from_ll[1])},{float(from_ll[0])};{float(to_ll[1])},{float(to_ll[0])}?overview=false"
    except (IndexError, TypeError, ValueError):
        return None
    pinned = _assert_public_https(url)
    data = _curl_json(url, pinned=pinned) or {}
    routes = data.get("routes") if isinstance(data, dict) else None
    try:
        return round(float(routes[0]["duration"]) / 60) if isinstance(routes, list) and routes else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None

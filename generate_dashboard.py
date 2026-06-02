#!/usr/bin/env python3
"""Generate a static Homer-like LAN dashboard.

No third-party dependencies.

Usage:
  python3 generate_dashboard.py                         # config subnets or 192.168.1.0/24
  python3 generate_dashboard.py 192.168.1.0/24
  python3 generate_dashboard.py 192.168.1.0/24,192.168.2.0/24
  python3 generate_dashboard.py --watch-interval 60
  python3 generate_dashboard.py --ports 22,80,443,3000,8123 --output index.html

Config file (auto-loaded from ./dashboard_config.json if it exists):
  {
    "subnets": ["192.168.1.0/24", "192.168.2.0/24"],
    "groups": [
      {"name": "Infrastructure", "icon": "🖧"},
      {"name": "Smart Home", "icon": "🏠"}
    ],
    "services": [
      {"port": 80, "name": "HTTP", "protocol": "http", "group": "Web", "favicon": true},
      {"port": 443, "name": "HTTPS", "protocol": "https", "group": "Web", "favicon": true},
      {"port": 8123, "name": "Home Assistant", "protocol": "http", "group": "Smart Home"}
    ],
    "manual_services": [
      {"name": "Router", "url": "http://192.168.1.1", "group": "Infrastructure", "icon": "🌐", "tags": ["router"]}
    ],
    "bookmarks": [
      {"group": "Cloud", "items": [{"name": "GitHub", "url": "https://github.com", "icon": ""}]}
    ],
    "hosts": {
      "192.168.1.1": {
        "name": "Router",
        "services": [{"port": 80, "name": "Router UI", "protocol": "http"}]
      },
      "aa:bb:cc:dd:ee:ff": "NAS"
    }
  }
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

DEFAULT_SUBNET = ipaddress.ip_network("192.168.1.0/24", strict=False)
DEFAULT_CONFIG_PATH = Path("dashboard_config.json")
DEFAULT_LOCAL_CONFIG_PATH = Path("dashboard_config.local.json")
DEFAULT_OVERRIDES_PATH = Path("dashboard_overrides.json")
DEFAULT_PORTS_CATALOG_PATH = Path("ports_catalog.json")

SIMPLE_DASH_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 72" role="img" aria-labelledby="title desc">
  <title id="title">Simple Dash</title>
  <desc id="desc">Simple Dash homelab dashboard logo</desc>
  <rect width="280" height="72" fill="#0d1116"/>
  <path d="M16 12h48v48H16z" fill="#212730" stroke="#757d89"/>
  <path d="M29 43 40 21l11 22" fill="none" stroke="#e86a52" stroke-width="5" stroke-linecap="square" stroke-linejoin="miter"/>
  <path d="M33 36h14" stroke="#d5d8db" stroke-width="5"/>
  <circle cx="40" cy="21" r="4" fill="#72e89d"/>
  <circle cx="29" cy="43" r="4" fill="#6a9fcc"/>
  <circle cx="51" cy="43" r="4" fill="#f7cf68"/>
  <text x="78" y="32" fill="#d5d8db" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="19" font-weight="700" letter-spacing="1.2">SIMPLE</text>
  <text x="78" y="55" fill="#e86a52" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="19" font-weight="700" letter-spacing="1.2">DASH</text>
</svg>
"""

SIMPLE_DASH_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" fill="#0d1116"/>
  <rect x="8" y="8" width="48" height="48" fill="#212730" stroke="#757d89" stroke-width="2"/>
  <path d="M20 42 32 18l12 24" fill="none" stroke="#e86a52" stroke-width="6" stroke-linecap="square" stroke-linejoin="miter"/>
  <path d="M24 34h16" stroke="#d5d8db" stroke-width="5"/>
  <circle cx="32" cy="18" r="4" fill="#72e89d"/>
  <circle cx="20" cy="42" r="4" fill="#6a9fcc"/>
  <circle cx="44" cy="42" r="4" fill="#f7cf68"/>
</svg>
"""

GENERIC_SERVICE_NAMES = {"HTTP", "HTTPS", "APP", "DEV", "WEB", "PORT"}

DEFAULT_SERVICE_DEFS = [
    {"port": 22, "name": "SSH", "icon": "⌁", "group": "Infrastructure"},
    {"port": 80, "name": "HTTP", "protocol": "http", "icon": "🌐", "group": "Web", "favicon": True},
    {"port": 443, "name": "HTTPS", "protocol": "https", "icon": "🔒", "group": "Web", "favicon": True},
    {"port": 3000, "name": "Dev", "protocol": "http", "icon": "⚙", "group": "Apps", "favicon": True},
    {"port": 5000, "name": "App", "protocol": "http", "icon": "▣", "group": "Apps", "favicon": True},
    {"port": 8000, "name": "HTTP", "protocol": "http", "icon": "🌐", "group": "Web", "favicon": True},
    {"port": 8080, "name": "HTTP", "protocol": "http", "icon": "🌐", "group": "Web", "favicon": True},
    {"port": 8123, "name": "Home Assistant", "protocol": "http", "icon": "🏠", "group": "Smart Home", "favicon": True},
    {"port": 8443, "name": "HTTPS", "protocol": "https", "icon": "🔒", "group": "Web", "favicon": True},
    {"port": 9000, "name": "App", "protocol": "http", "icon": "▣", "group": "Apps", "favicon": True},
    {"port": 9090, "name": "Metrics", "protocol": "http", "icon": "📈", "group": "Monitoring", "favicon": True},
]

# Fast discovery profile: common homelab/router/NAS/dev/media/database ports.
# These ports are scanned in addition to configured services by default.
COMMON_DISCOVERY_PORTS = sorted({
    20, 21, 22, 23, 25, 53, 67, 68, 69, 80, 110, 111, 123, 135, 137, 138, 139, 143, 161, 162, 389, 443, 445,
    465, 500, 514, 515, 548, 554, 587, 631, 636, 873, 902, 989, 990, 993, 995, 1194, 1433, 1521, 1723, 1883,
    1900, 2049, 2375, 2376, 2379, 2380, 2483, 2484, 3000, 3001, 3306, 3389, 3478, 4000, 4040, 4222, 4369, 4500,
    5000, 5001, 5353, 5432, 5555, 5601, 5672, 5683, 5900, 5938, 5984, 6379, 6443, 6666, 6881, 7000, 7001, 7070,
    8000, 8001, 8006, 8008, 8080, 8081, 8082, 8086, 8090, 8096, 8123, 8124, 8200, 8222, 8333, 8443, 8444, 8883,
    8888, 9000, 9001, 9002, 9042, 9090, 9091, 9100, 9200, 9300, 9443, 9800, 9981, 9999, 10000, 10250, 11211,
    15672, 18888, 25565, 27017, 32400, 32768, 49152, 49153, 49154, 50000, 50001,
})

HTTP_PORTS = {80, 3000, 3001, 4000, 4040, 5000, 5001, 5601, 5984, 7000, 7001, 7070, 8000, 8001, 8006, 8008, 8080, 8081, 8082, 8086, 8090, 8096, 8123, 8124, 8200, 8222, 8888, 9000, 9001, 9002, 9090, 9091, 9100, 9200, 9443, 9800, 9981, 10000, 15672, 32400}
HTTPS_PORTS = {443, 4443, 6443, 8443, 8444, 8883, 9443}

APP_PATTERNS = [
    ("home assistant", "Home Assistant", "🏠"),
    ("grafana", "Grafana", "📊"),
    ("prometheus", "Prometheus", "📈"),
    ("portainer", "Portainer", "🐳"),
    ("proxmox", "Proxmox", "🖥"),
    ("openwrt", "OpenWrt", "📡"),
    ("routeros", "MikroTik RouterOS", "📡"),
    ("mikrotik", "MikroTik", "📡"),
    ("truenas", "TrueNAS", "🗄"),
    ("freenas", "TrueNAS", "🗄"),
    ("jellyfin", "Jellyfin", "🎬"),
    ("plex", "Plex", "🎞"),
    ("synology", "Synology", "🗄"),
    ("qbit", "qBittorrent", "⬇"),
    ("transmission", "Transmission", "⬇"),
    ("pi-hole", "Pi-hole", "🕳"),
    ("pihole", "Pi-hole", "🕳"),
    ("adguard", "AdGuard Home", "🛡"),
    ("nginx", "Nginx", "🟢"),
    ("apache", "Apache", "🪶"),
    ("caddy", "Caddy", "🟣"),
]


@dataclass
class Service:
    port: int
    name: str
    protocol: str = ""
    url: str = ""
    icon: str = "▣"
    group: str = "Discovered"
    tags: tuple[str, ...] = ()
    favicon: bool = False


@dataclass
class ManualService:
    id: str
    name: str
    url: str
    group: str = "Manual"
    icon: str = "★"
    tags: tuple[str, ...] = ()
    favicon: bool = True


@dataclass
class Bookmark:
    name: str
    url: str
    group: str = "Bookmarks"
    icon: str = "↗"
    tags: tuple[str, ...] = ()
    favicon: bool = False


@dataclass
class ProbeResult:
    status: str = "online"
    latency_ms: float | None = None
    http_status: int | None = None
    fingerprint: str = ""
    detected_app: str = ""
    detected_icon: str = ""
    protocol: str = ""
    error: str = ""


@dataclass
class Host:
    ip: str
    hostname: str
    mac: str
    open_ports: tuple[int, ...]
    probes: dict[int, ProbeResult] = field(default_factory=dict)


@dataclass
class DuplicateGroup:
    id: str
    name: str
    hosts: tuple[str, ...]


@dataclass
class DashboardConfig:
    services: dict[int, Service]
    host_names: dict[str, str]
    host_services: dict[str, dict[int, Service]]
    subnet_values: tuple[str, ...]
    manual_services: list[ManualService]
    bookmarks: list[Bookmark]
    groups: dict[str, str]
    duplicate_groups: list[DuplicateGroup]


@dataclass
class DashboardData:
    subnets: list[ipaddress.IPv4Network]
    ports: list[int]
    config: DashboardConfig
    hosts: list[Host]
    manual_status: dict[str, ProbeResult]


def normalize_mac(value: str) -> str:
    return value.strip().lower().replace("-", ":")


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return value or hashlib.sha1(value.encode()).hexdigest()[:10]


def parse_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def parse_port(value: Any, source: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Bad port in {source}: {value!r}") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"Bad port in {source}: {port}")
    return port


def guess_service_name(port: int) -> str:
    if port == 80:
        return "HTTP"
    if port == 443:
        return "HTTPS"
    try:
        return socket.getservbyport(port, "tcp").upper()
    except OSError:
        return f"Port {port}"


def default_protocol(port: int) -> str:
    if port in HTTPS_PORTS:
        return "https"
    if port in HTTP_PORTS:
        return "http"
    return ""


def service_from_dict(raw: dict[str, Any], source: str) -> Service:
    port = parse_port(raw.get("port"), source)
    name = str(raw.get("name") or guess_service_name(port)).strip() or guess_service_name(port)
    protocol = str(raw.get("protocol") or default_protocol(port)).strip().lower()
    url = str(raw.get("url") or "").strip()
    if protocol and protocol not in {"http", "https"}:
        raise SystemExit(f"Bad protocol for port {port} in {source}: {protocol!r}. Use http/https or leave it empty")
    return Service(
        port=port,
        name=name,
        protocol=protocol,
        url=url,
        icon=str(raw.get("icon") or ("🔒" if protocol == "https" else "🌐" if protocol == "http" else "▣")),
        group=str(raw.get("group") or "Discovered").strip() or "Discovered",
        tags=parse_tags(raw.get("tags")),
        favicon=bool(raw.get("favicon", protocol in {"http", "https"} or port in {80, 443})),
    )


def parse_services(raw: Any, source: str) -> dict[int, Service]:
    services: dict[int, Service] = {}
    if raw is None:
        return services

    if isinstance(raw, list):
        for idx, item in enumerate(raw, start=1):
            if isinstance(item, int):
                port = parse_port(item, f"{source}: services[{idx}]")
                service = Service(port=port, name=guess_service_name(port), protocol=default_protocol(port), favicon=port in {80, 443})
            elif isinstance(item, dict):
                service = service_from_dict(item, f"{source}: services[{idx}]")
            else:
                raise SystemExit(f"Bad service entry in {source}: services[{idx}]")
            services[service.port] = service
        return services

    if isinstance(raw, dict):
        for key, value in raw.items():
            port = parse_port(key, source)
            if isinstance(value, dict):
                service = service_from_dict({**value, "port": port}, f"{source}: services.{key}")
            else:
                service = Service(port=port, name=str(value).strip() or guess_service_name(port), protocol=default_protocol(port), favicon=port in {80, 443})
            services[service.port] = service
        return services

    raise SystemExit(f"Bad services section in {source}. Use a list or an object")


def default_services() -> dict[int, Service]:
    return {service.port: service for service in (service_from_dict(item, "defaults") for item in DEFAULT_SERVICE_DEFS)}


def parse_groups(raw: Any) -> dict[str, str]:
    groups: dict[str, str] = {}
    if raw is None:
        return groups
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                groups[item] = "▦"
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    groups[name] = str(item.get("icon") or "▦")
    elif isinstance(raw, dict):
        for name, icon in raw.items():
            if str(name).strip():
                groups[str(name).strip()] = str(icon or "▦")
    return groups


SAFE_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def is_safe_external_url(url: str) -> bool:
    if url.startswith(("http://", "https://", "mailto:", "tel:")):
        return True
    return bool(SAFE_URL_SCHEME_RE.match(url))


def manual_from_dict(raw: dict[str, Any], default_group: str, source: str) -> ManualService:
    url = str(raw.get("url") or raw.get("href") or "").strip()
    if not url:
        raise SystemExit(f"Manual service without url in {source}")
    if not is_safe_external_url(url):
        raise SystemExit(f"Manual service in {source} has unsupported URL scheme: {url[:60]!r}. Use http://, https://, mailto:, tel:, or a custom scheme://...")
    name = str(raw.get("name") or raw.get("title") or url).strip()
    return ManualService(
        id=str(raw.get("id") or slug(f"{name}-{url}")),
        name=name,
        url=url,
        group=str(raw.get("group") or default_group or "Manual").strip() or "Manual",
        icon=str(raw.get("icon") or "★"),
        tags=parse_tags(raw.get("tags")),
        favicon=bool(raw.get("favicon", True)),
    )


def parse_manual_services(raw: Any, source: str) -> list[ManualService]:
    result: list[ManualService] = []
    if raw is None:
        return result
    if not isinstance(raw, list):
        raise SystemExit(f"Bad manual_services section in {source}: use an array")
    seen: set[tuple[str, str]] = set()
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            if "items" in item and isinstance(item.get("items"), list):
                group = str(item.get("group") or item.get("name") or "Manual")
                for jdx, child in enumerate(item["items"], start=1):
                    if isinstance(child, dict):
                        manual = manual_from_dict(child, group, f"{source}: manual_services[{idx}].items[{jdx}]")
                        key = (manual.name.lower(), manual.url.lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        result.append(manual)
            else:
                manual = manual_from_dict(item, "Manual", f"{source}: manual_services[{idx}]")
                key = (manual.name.lower(), manual.url.lower())
                if key in seen:
                    continue
                seen.add(key)
                result.append(manual)
    return result


def bookmark_from_dict(raw: dict[str, Any], default_group: str) -> Bookmark:
    url = str(raw.get("url") or raw.get("href") or "").strip()
    if url and not is_safe_external_url(url):
        raise SystemExit(f"Bookmark has unsupported URL scheme: {url[:60]!r}. Use http://, https://, mailto:, tel:, or a custom scheme://...")
    name = str(raw.get("name") or raw.get("title") or url).strip()
    return Bookmark(
        name=name,
        url=url,
        group=str(raw.get("group") or default_group or "Bookmarks").strip() or "Bookmarks",
        icon=str(raw.get("icon") or "↗"),
        tags=parse_tags(raw.get("tags")),
        favicon=bool(raw.get("favicon", False)),
    )


def parse_bookmarks(raw: Any) -> list[Bookmark]:
    result: list[Bookmark] = []
    if raw is None:
        return result
    if not isinstance(raw, list):
        raise SystemExit("Bad bookmarks section: use an array")
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "items" in item and isinstance(item.get("items"), list):
            group = str(item.get("group") or item.get("name") or "Bookmarks")
            for child in item["items"]:
                if isinstance(child, dict) and (child.get("url") or child.get("href")):
                    bookmark = bookmark_from_dict(child, group)
                    key = (bookmark.name.lower(), bookmark.url.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(bookmark)
        elif item.get("url") or item.get("href"):
            bookmark = bookmark_from_dict(item, "Bookmarks")
            key = (bookmark.name.lower(), bookmark.url.lower())
            if key in seen:
                continue
            seen.add(key)
            result.append(bookmark)
    return result


def merge_config_dicts(base: dict[str, Any], override: dict[str, Any], *, preserve_subnets: bool = False) -> dict[str, Any]:
    merged = dict(base)
    append_keys = {"services", "manual_services", "apps", "bookmarks", "groups", "duplicates", "duplicate_groups"}
    for key, value in override.items():
        if key in append_keys and isinstance(merged.get(key), list) and isinstance(value, list):
            merged[key] = [*merged[key], *value]
        elif key == "hosts" and isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        elif preserve_subnets and key in {"subnets", "subnet"} and key in merged:
            # Snapshots/overrides never overwrite the primary subnet list.
            continue
        else:
            merged[key] = value
    return merged


def load_json_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Bad JSON in {path}: {exc}") from None
    if not isinstance(data, dict):
        raise SystemExit(f"Bad config in {path}: top-level JSON value must be an object")
    return data


def parse_duplicate_groups(raw: Any) -> list[DuplicateGroup]:
    result: list[DuplicateGroup] = []
    if raw is None:
        return result
    if not isinstance(raw, list):
        raise SystemExit("Bad duplicates section: use an array")
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            hosts_raw = item.get("hosts", [])
            if isinstance(hosts_raw, str):
                hosts = tuple(host.strip() for host in hosts_raw.split(",") if host.strip())
            elif isinstance(hosts_raw, list):
                hosts = tuple(str(host).strip() for host in hosts_raw if str(host).strip())
            else:
                hosts = ()
            if len(hosts) < 2:
                continue
            name = str(item.get("name") or item.get("id") or f"Duplicate {idx}").strip()
            result.append(DuplicateGroup(id=str(item.get("id") or slug(name)), name=name, hosts=hosts))
    return result


def empty_config() -> DashboardConfig:
    return DashboardConfig(
        services=default_services(),
        host_names={},
        host_services={},
        subnet_values=(),
        manual_services=[],
        bookmarks=[],
        groups={
            "Infrastructure": "🖧",
            "Web": "🌐",
            "Apps": "▣",
            "Smart Home": "🏠",
            "Monitoring": "📈",
            "Discovered": "🔎",
            "Manual": "★",
            "Bookmarks": "↗",
        },
        duplicate_groups=[],
    )


def build_config_from_dict(data: dict[str, Any], source: str) -> DashboardConfig:
    config = empty_config()

    raw_subnets = data.get("subnets", data.get("subnet"))
    if raw_subnets is not None:
        if isinstance(raw_subnets, str):
            config.subnet_values = tuple(item.strip() for item in raw_subnets.split(",") if item.strip())
        elif isinstance(raw_subnets, list):
            config.subnet_values = tuple(str(item).strip() for item in raw_subnets if str(item).strip())
        else:
            raise SystemExit(f"Bad subnets section in {source}: use an array of subnet strings")

    config.groups.update(parse_groups(data.get("groups")))
    config.services.update(parse_services(data.get("services"), source))
    config.manual_services = parse_manual_services(data.get("manual_services", data.get("apps")), source)
    config.bookmarks = parse_bookmarks(data.get("bookmarks"))
    config.duplicate_groups = parse_duplicate_groups(data.get("duplicates", data.get("duplicate_groups")))

    raw_hosts = data.get("hosts", {}) or {}
    if not isinstance(raw_hosts, dict):
        raise SystemExit(f"Bad hosts section in {source}: use an object")
    for key, value in raw_hosts.items():
        host_key = normalize_mac(str(key))
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            if name:
                config.host_names[host_key] = name
            per_host_services = parse_services(value.get("services"), f"{source}: hosts.{key}")
            if per_host_services:
                config.host_services[host_key] = per_host_services
                config.services.update({port: config.services.get(port, service) for port, service in per_host_services.items()})
        else:
            name = str(value).strip()
            if name:
                config.host_names[host_key] = name

    for service in config.services.values():
        config.groups.setdefault(service.group, "▦")
    for item in config.manual_services:
        config.groups.setdefault(item.group, "▦")
    for item in config.bookmarks:
        config.groups.setdefault(item.group, "↗")

    return config


def resolve_config_data(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """Merge config sources in priority order: public ← local ← overrides.

    With --config, only the explicit file is used as the primary source; the
    overrides snapshot is still layered on top unless --config points at it.
    """
    overrides_path = DEFAULT_OVERRIDES_PATH

    if args.config is not None:
        primary = Path(args.config)
        if not primary.exists():
            raise SystemExit(f"Config file not found: {primary}")
        data = load_json_config(primary)
        sources = [str(primary)]
        if primary.resolve() != overrides_path.resolve() and overrides_path.exists():
            data = merge_config_dicts(data, load_json_config(overrides_path), preserve_subnets=True)
            sources.append(str(overrides_path))
        return data, " ← ".join(sources)

    data: dict[str, Any] = {}
    sources: list[str] = []
    if DEFAULT_CONFIG_PATH.exists():
        data = load_json_config(DEFAULT_CONFIG_PATH)
        sources.append(str(DEFAULT_CONFIG_PATH))
    if DEFAULT_LOCAL_CONFIG_PATH.exists():
        local = load_json_config(DEFAULT_LOCAL_CONFIG_PATH)
        data = merge_config_dicts(data, local, preserve_subnets=False)
        sources.append(str(DEFAULT_LOCAL_CONFIG_PATH))
    if overrides_path.exists():
        data = merge_config_dicts(data, load_json_config(overrides_path), preserve_subnets=True)
        sources.append(str(overrides_path))
    return data, " ← ".join(sources) if sources else "<defaults>"


def parse_ports(value: str) -> list[int]:
    ports: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = parse_port(start_text.strip(), "--ports")
            end = parse_port(end_text.strip(), "--ports")
            if end < start:
                raise argparse.ArgumentTypeError(f"bad port range: {item}")
            ports.extend(range(start, end + 1))
        else:
            ports.append(parse_port(item, "--ports"))
    return sorted(set(ports))


def parse_subnet(value: str | None) -> ipaddress.IPv4Network:
    if not value:
        return DEFAULT_SUBNET
    value = value.strip()
    if value.isdigit():
        third_octet = int(value)
        if not 0 <= third_octet <= 255:
            raise SystemExit("Subnet shorthand must be 0..255")
        return ipaddress.ip_network(f"192.168.{third_octet}.0/24", strict=False)
    if re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", value):
        return ipaddress.ip_network(f"{value}.0/24", strict=False)
    return ipaddress.ip_network(value, strict=False)


def parse_subnet_values(values: Iterable[str] | None) -> list[ipaddress.IPv4Network]:
    subnets: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()
    if not values:
        values = [str(DEFAULT_SUBNET)]
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if not item:
                continue
            subnet = parse_subnet(item)
            if subnet.version != 4:
                raise SystemExit("Only IPv4 subnets are supported")
            key = str(subnet)
            if key not in seen:
                seen.add(key)
                subnets.append(subnet)
    return subnets or [DEFAULT_SUBNET]


def resolve_subnets(cli_value: str | None, config: DashboardConfig) -> list[ipaddress.IPv4Network]:
    if cli_value:
        return parse_subnet_values([cli_value])
    return parse_subnet_values(config.subnet_values)


async def bounded_gather(items: list, work_fn, num_workers: int) -> list:
    """Map work_fn over items with at most num_workers active tasks. Order preserved.

    Uses a queue + worker pool so memory stays O(num_workers) live coroutines
    even for very large inputs (e.g. /16 subnets in ICMP discovery).
    """
    if not items:
        return []
    queue: asyncio.Queue[tuple[int, Any]] = asyncio.Queue()
    for idx, item in enumerate(items):
        queue.put_nowait((idx, item))
    results: list = [None] * len(items)

    async def worker() -> None:
        while True:
            try:
                idx, item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            results[idx] = await work_fn(item)

    workers = [asyncio.create_task(worker()) for _ in range(min(num_workers, len(items)))]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        for w in workers:
            w.cancel()
        raise
    return results


async def check_port_latency(ip: str, port: int, timeout: float) -> float | None:
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return (time.perf_counter() - start) * 1000
    except Exception:
        return None


async def check_port_latency_limited(ip: str, port: int, timeout: float, sem: asyncio.Semaphore) -> float | None:
    async with sem:
        return await check_port_latency(ip, port, timeout)


async def icmp_probe(ip: str, timeout: float) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-n", ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await asyncio.wait_for(proc.wait(), timeout=timeout) == 0
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False
    except FileNotFoundError:
        return False


def arp_table_ips(subnets: list[ipaddress.IPv4Network]) -> set[str]:
    import subprocess
    try:
        text = subprocess.check_output(["arp", "-a"], stderr=subprocess.DEVNULL).decode(errors="ignore")
    except Exception:
        return set()
    result: set[str] = set()
    for match in re.finditer(r"\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+([^\s]+)", text):
        ip_text, mac = match.groups()
        if mac.lower() == "(incomplete)":
            continue
        try:
            address = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if any(address in subnet for subnet in subnets):
            result.add(ip_text)
    return result


async def discover_host_ips(subnets: list[ipaddress.IPv4Network], args: argparse.Namespace) -> set[str]:
    modes = set(args.host_discovery.split(",")) if args.host_discovery else {"none"}
    discovered: set[str] = set()

    if "arp" in modes:
        discovered |= arp_table_ips(subnets)

    if "icmp" in modes:
        ips = [str(ip) for subnet in subnets for ip in subnet.hosts()]
        results = await bounded_gather(ips, lambda ip: icmp_probe(ip, args.discovery_timeout), args.discovery_concurrency)
        discovered |= {ip for ip, ok in zip(ips, results) if ok}

    return discovered


async def reverse_dns(ip: str, timeout: float) -> str:
    def lookup() -> str:
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return ""
    try:
        return await asyncio.wait_for(asyncio.to_thread(lookup), timeout=timeout)
    except asyncio.TimeoutError:
        return ""


async def get_mac(ip: str, timeout: float) -> str:
    commands = (["arp", "-n", ip], ["arp", ip])
    for cmd in commands:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                continue
            match = re.search(r"(?i)\b([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b", stdout.decode(errors="ignore"))
            if match:
                return normalize_mac(match.group(1))
        except FileNotFoundError:
            return ""
    return ""


def encode_netbios_name(name: str) -> bytes:
    raw = (name.upper()[:15].ljust(15) + "\x00").encode("ascii")
    encoded = bytearray()
    for byte in raw:
        encoded.append(ord("A") + ((byte >> 4) & 0x0F))
        encoded.append(ord("A") + (byte & 0x0F))
    return bytes([32]) + bytes(encoded) + b"\x00"


async def netbios_name(ip: str, timeout: float) -> str:
    def lookup() -> str:
        transaction_id = b"\x12\x34"
        packet = transaction_id + b"\x00\x00" + b"\x00\x01" + b"\x00\x00\x00\x00\x00\x00" + encode_netbios_name("*") + b"\x00\x21\x00\x01"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (ip, 137))
            data, _ = sock.recvfrom(2048)
        except Exception:
            return ""
        finally:
            sock.close()
        if len(data) < 57 or data[:2] != transaction_id:
            return ""

        def skip_name(offset: int) -> int:
            while offset < len(data) and data[offset] != 0:
                label_len = data[offset]
                if label_len & 0xC0 == 0xC0:
                    return offset + 2
                offset += 1 + label_len
            return offset + 1

        offset = skip_name(12) + 4
        offset = skip_name(offset) + 8
        if offset + 2 > len(data):
            return ""
        rdlength = int.from_bytes(data[offset : offset + 2], "big")
        offset += 2
        if offset + rdlength > len(data) or offset >= len(data):
            return ""
        count = data[offset]
        offset += 1
        for _ in range(count):
            if offset + 18 > len(data):
                break
            raw_name = data[offset : offset + 15].decode("ascii", errors="ignore").strip()
            suffix = data[offset + 15]
            flags = int.from_bytes(data[offset + 16 : offset + 18], "big")
            offset += 18
            if raw_name and suffix == 0x00 and not (flags & 0x8000) and raw_name != "__MSBROWSE__":
                return raw_name
        return ""
    try:
        return await asyncio.wait_for(asyncio.to_thread(lookup), timeout=timeout + 0.1)
    except asyncio.TimeoutError:
        return ""


def resolve_host_name(ip: str, discovered_name: str, mac: str, host_names: dict[str, str]) -> str:
    return host_names.get(ip) or (host_names.get(normalize_mac(mac)) if mac else "") or discovered_name or "Unknown device"


def service_for_host(ip: str, mac: str, port: int, config: DashboardConfig) -> Service:
    if port in config.host_services.get(ip, {}):
        return config.host_services[ip][port]
    if mac and port in config.host_services.get(normalize_mac(mac), {}):
        return config.host_services[normalize_mac(mac)][port]
    return config.services.get(port) or Service(port=port, name=guess_service_name(port), protocol=default_protocol(port), favicon=port in {80, 443})


def clean_fingerprint(value: str, max_len: int = 140) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -\t\r\n")
    return value[:max_len]


def detect_app(text: str) -> tuple[str, str]:
    haystack = text.lower()
    for needle, app, icon in APP_PATTERNS:
        if needle in haystack:
            return app, icon
    return "", ""


def parse_http_response(data: bytes) -> tuple[int | None, str, str, str]:
    text = data.decode("utf-8", errors="ignore")
    status: int | None = None
    if text.startswith("HTTP/"):
        parts = text.split(None, 2)
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])

    header_text, _, body = text.partition("\r\n\r\n")
    if not body:
        header_text, _, body = text.partition("\n\n")
    headers: dict[str, str] = {}
    for line in header_text.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    title = ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body or text)
    if match:
        title = clean_fingerprint(match.group(1), 90)

    auth = headers.get("www-authenticate", "")
    realm = ""
    realm_match = re.search(r'(?i)realm="?([^",]+)', auth)
    if realm_match:
        realm = clean_fingerprint(realm_match.group(1), 90)

    candidates = [title, realm, clean_fingerprint(headers.get("server", ""), 90), clean_fingerprint(headers.get("x-powered-by", ""), 90)]
    result: list[str] = []
    for item in candidates:
        if item and item.lower() not in {known.lower() for known in result}:
            result.append(item)
    fingerprint = " · ".join(result[:3])
    app, icon = detect_app(" ".join([fingerprint, text[:2000]]))
    return status, fingerprint, app, icon


def status_from_http(status: int | None) -> str:
    if status in {401, 403}:
        return "auth"
    if status and status >= 500:
        return "error"
    return "online"


async def probe_http(ip: str, port: int, protocol: str, timeout: float, path: str = "/") -> ProbeResult:
    ssl_context = None
    server_hostname = None
    if protocol == "https":
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        server_hostname = ip
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port, ssl=ssl_context, server_hostname=server_hostname), timeout=timeout
        )
        safe_path = path or "/"
        request = (
            f"GET {safe_path} HTTP/1.1\r\n"
            f"Host: {ip}\r\n"
            f"User-Agent: simple-dash/1.0\r\n"
            f"Accept: text/html,*/*;q=0.8\r\n"
            f"Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii", errors="ignore"))
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        data = await asyncio.wait_for(reader.read(32768), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        http_status, fingerprint, app, icon = parse_http_response(data)
        return ProbeResult(
            status=status_from_http(http_status),
            latency_ms=(time.perf_counter() - start) * 1000,
            http_status=http_status,
            fingerprint=fingerprint,
            detected_app=app,
            detected_icon=icon,
            protocol=protocol,
        )
    except Exception as exc:
        return ProbeResult(status="error", protocol=protocol, error=str(exc)[:80])


async def probe_banner(ip: str, port: int, timeout: float, latency_ms: float | None = None) -> ProbeResult:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        data = await asyncio.wait_for(reader.read(512), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        fingerprint = clean_fingerprint(data.decode("utf-8", errors="ignore"), 120)
        app, icon = detect_app(fingerprint)
        return ProbeResult(status="online", latency_ms=latency_ms, fingerprint=fingerprint, detected_app=app, detected_icon=icon)
    except Exception:
        return ProbeResult(status="online", latency_ms=latency_ms)


def protocol_for_probe(service: Service) -> str:
    if service.url.startswith("https://"):
        return "https"
    if service.url.startswith("http://"):
        return "http"
    return service.protocol or default_protocol(service.port)


async def probe_service(ip: str, port: int, service: Service, timeout: float, latency_ms: float | None) -> ProbeResult:
    protocol = protocol_for_probe(service)
    if protocol in {"http", "https"}:
        result = await probe_http(ip, port, protocol, timeout)
        if result.status != "error" or result.fingerprint or result.http_status:
            if result.latency_ms is None:
                result.latency_ms = latency_ms
            return result
    banner = await probe_banner(ip, port, timeout, latency_ms)
    if banner.fingerprint:
        return banner
    if not protocol:
        result = await probe_http(ip, port, "http", timeout)
        if result.status != "error" or result.fingerprint or result.http_status:
            return result
        result = await probe_http(ip, port, "https", timeout)
        if result.status != "error" or result.fingerprint or result.http_status:
            return result
    return ProbeResult(status="online", latency_ms=latency_ms, protocol=protocol)


async def probe_manual_service(item: ManualService, timeout: float) -> ProbeResult:
    parsed = urlparse(item.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ProbeResult(status="unknown")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    latency = await check_port_latency(parsed.hostname, port, timeout)
    if latency is None:
        return ProbeResult(status="offline", protocol=parsed.scheme)
    result = await probe_http(parsed.hostname, port, parsed.scheme, timeout, path)
    if result.latency_ms is None:
        result.latency_ms = latency
    return result


async def scan_host(ip: ipaddress.IPv4Address, ports: Iterable[int], args: argparse.Namespace, config: DashboardConfig, port_sem: asyncio.Semaphore, discovered_ips: set[str]) -> Host | None:
    ip_text = str(ip)
    latency_results = await asyncio.gather(*(check_port_latency_limited(ip_text, port, args.port_timeout, port_sem) for port in ports))
    open_ports = tuple(port for port, latency in zip(ports, latency_results) if latency is not None)
    if not open_ports and ip_text not in discovered_ips:
        return None

    dns_name, nb_name, mac = await asyncio.gather(
        reverse_dns(ip_text, args.dns_timeout),
        netbios_name(ip_text, args.netbios_timeout),
        get_mac(ip_text, args.arp_timeout),
    )
    hostname = resolve_host_name(ip_text, dns_name or nb_name, mac, config.host_names)

    probe_results = await asyncio.gather(
        *(probe_service(ip_text, port, service_for_host(ip_text, mac, port, config), args.service_timeout, latency) for port, latency in zip(ports, latency_results) if latency is not None)
    )
    probes = {port: probe for port, probe in zip(open_ports, probe_results)}
    return Host(ip=ip_text, hostname=hostname, mac=mac, open_ports=open_ports, probes=probes)


async def scan_hosts(subnets: list[ipaddress.IPv4Network], ports: list[int], args: argparse.Namespace, config: DashboardConfig) -> list[Host]:
    discovered_ips = await discover_host_ips(subnets, args)
    if discovered_ips:
        print(f"Discovered {len(discovered_ips)} host candidate(s) via {args.host_discovery}", flush=True)

    port_sem = asyncio.Semaphore(args.port_concurrency)
    ips: list[ipaddress.IPv4Address] = []
    seen: set[str] = set()
    for subnet in subnets:
        for ip in subnet.hosts():
            ip_text = str(ip)
            if ip_text not in seen:
                seen.add(ip_text)
                ips.append(ip)
    results = await bounded_gather(ips, lambda ip: scan_host(ip, ports, args, config, port_sem, discovered_ips), args.concurrency)
    hosts = [host for host in results if host]
    return sorted(hosts, key=lambda host: ipaddress.ip_address(host.ip))


async def scan_manual_services(items: list[ManualService], args: argparse.Namespace) -> dict[str, ProbeResult]:
    results = await asyncio.gather(*(probe_manual_service(item, args.service_timeout) for item in items))
    return {item.id: result for item, result in zip(items, results)}


def url_from_template(template: str, ip: str, port: int) -> str:
    try:
        return template.format(ip=ip, port=port)
    except Exception:
        return template.replace("{ip}", ip).replace("{port}", str(port))


def service_url(ip: str, service: Service, probe: ProbeResult | None = None) -> str:
    if service.url:
        return url_from_template(service.url, ip, service.port)
    protocol = service.protocol or (probe.protocol if probe and probe.protocol in {"http", "https"} else "")
    if service.port == 80 and protocol in {"", "http"}:
        return f"http://{ip}"
    if service.port == 443 and protocol in {"", "https"}:
        return f"https://{ip}"
    if protocol in {"http", "https"}:
        return f"{protocol}://{ip}:{service.port}"
    return ""


def origin_for_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def is_generic_name(name: str) -> bool:
    upper = name.upper()
    return upper in GENERIC_SERVICE_NAMES or upper.startswith("PORT ")


def display_name(service_name: str, probe: ProbeResult | None) -> str:
    if probe and probe.detected_app and is_generic_name(service_name):
        return probe.detected_app
    return service_name


def status_label(probe: ProbeResult | None) -> str:
    if not probe:
        return "unknown"
    if probe.status == "auth":
        return "auth"
    if probe.status == "offline":
        return "offline"
    if probe.status == "error":
        return "error"
    return "online"


def probe_meta(probe: ProbeResult | None) -> str:
    if not probe:
        return ""
    parts: list[str] = []
    if probe.http_status:
        parts.append(f"HTTP {probe.http_status}")
    if probe.latency_ms is not None:
        parts.append(f"{probe.latency_ms:.0f} ms")
    if probe.fingerprint:
        parts.append(probe.fingerprint)
    return " · ".join(parts)


def item_tags(*tag_groups: Iterable[str]) -> str:
    tags: list[str] = []
    for group in tag_groups:
        for tag in group:
            tag = str(tag).strip()
            if tag and tag not in tags:
                tags.append(tag)
    return " ".join(tags)


def icon_html(icon: str, url: str = "", favicon: bool = False, fallback: str = "▣") -> str:
    icon = icon or fallback
    if favicon and url and origin_for_url(url):
        src = html.escape(origin_for_url(url) + "/favicon.ico", quote=True)
        return f'<span class="icon"><img src="{src}" alt="" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline\';"><span style="display:none">{html.escape(icon)}</span></span>'
    if icon.startswith("http://") or icon.startswith("https://") or "/" in icon:
        return f'<span class="icon"><img src="{html.escape(icon, quote=True)}" alt="" loading="lazy"></span>'
    return f'<span class="icon">{html.escape(icon)}</span>'


def status_html(probe: ProbeResult | None) -> str:
    status = status_label(probe)
    return f'<span class="status status-{html.escape(status)}">{html.escape(status)}</span>'


def service_card_html(name: str, url: str, icon: str, group: str, tags: Iterable[str], probe: ProbeResult | None, subtitle: str, favicon: bool) -> str:
    meta = probe_meta(probe)
    all_tags = item_tags(tags, [group, status_label(probe)])
    data_search = " ".join([name, url, group, subtitle, meta, all_tags])
    content = (
        f'{icon_html(icon, url, favicon)}'
        f'<div class="card-body"><strong>{html.escape(name)}</strong><small>{html.escape(subtitle)}</small>'
        f'{f"<em>{html.escape(meta)}</em>" if meta else ""}</div>'
        f'{status_html(probe)}'
    )
    attrs = f'class="svc-card" data-card data-group="{html.escape(group, quote=True)}" data-tags="{html.escape(all_tags, quote=True)}" data-search="{html.escape(data_search, quote=True)}"'
    if url:
        return f'<a {attrs} href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{content}</a>'
    return f'<div {attrs}>{content}</div>'


def table_service_html(ip: str, mac: str, port: int, config: DashboardConfig, probe: ProbeResult | None) -> str:
    service = service_for_host(ip, mac, port, config)
    url = service_url(ip, service, probe)
    name = display_name(service.name, probe)
    meta = probe_meta(probe)
    label = f'<span>{html.escape(name)}{f"<em>{html.escape(meta)}</em>" if meta else ""}</span><b>{port}</b>'
    if url:
        return f'<a class="service service-link" href="{html.escape(url, quote=True)}" target="_blank" rel="noreferrer">{label}</a>'
    return f'<span class="service">{label}</span>'


def group_order(config: DashboardConfig, groups_present: Iterable[str]) -> list[str]:
    ordered = [group for group in config.groups if group in groups_present]
    for group in sorted(set(groups_present)):
        if group not in ordered:
            ordered.append(group)
    return ordered


def discovered_service_card(data: DashboardData, host: Host, port: int) -> str:
    service = service_for_host(host.ip, host.mac, port, data.config)
    probe = host.probes.get(port)
    url = service_url(host.ip, service, probe)
    name = display_name(service.name, probe)
    icon = probe.detected_icon or service.icon
    subtitle = f"{host.hostname} · {host.ip}:{port}" if host.hostname != "Unknown device" else f"{host.ip}:{port}"
    tags = (*service.tags, str(port), host.ip, host.hostname)
    return service_card_html(name, url, icon, service.group, tags, probe, subtitle, service.favicon)


def manual_service_card(item: ManualService, probe: ProbeResult | None) -> str:
    return service_card_html(item.name, item.url, item.icon, item.group, item.tags, probe, origin_for_url(item.url) or item.url, item.favicon)


def url_hostname(url: str) -> str:
    return (urlparse(url).hostname or "").strip().lower()


def collect_cards(data: DashboardData) -> dict[str, list[str]]:
    cards: dict[str, list[str]] = {}
    for item in data.config.manual_services:
        cards.setdefault(item.group, []).append(manual_service_card(item, data.manual_status.get(item.id)))

    for host in data.hosts:
        for port in host.open_ports:
            service = service_for_host(host.ip, host.mac, port, data.config)
            cards.setdefault(service.group, []).append(discovered_service_card(data, host, port))
    return cards


def host_subnet_name(ip: str, subnets: list[ipaddress.IPv4Network]) -> str:
    address = ipaddress.ip_address(ip)
    for subnet in subnets:
        if address in subnet:
            return str(subnet)
    return "Other"


def duplicate_group_for_host(config: DashboardConfig, host: Host) -> DuplicateGroup | None:
    keys = {host.ip.lower()}
    if host.hostname and host.hostname != "Unknown device":
        keys.add(host.hostname.lower())
    if host.mac:
        keys.add(normalize_mac(host.mac))
    for group in config.duplicate_groups:
        group_keys = {normalize_mac(item).lower() for item in group.hosts}
        if keys & group_keys:
            return group
    return None


def duplicate_badge(config: DashboardConfig, host: Host) -> str:
    group = duplicate_group_for_host(config, host)
    if not group:
        return ""
    peers = ", ".join(group.hosts)
    return f'<span class="duplicate" title="Same physical device: {html.escape(peers, quote=True)}">duplicate: {html.escape(group.name)}</span>'


def match_manual_services(data: DashboardData) -> tuple[dict[str, list[ManualService]], list[ManualService]]:
    host_by_name: dict[str, Host] = {}
    for host in data.hosts:
        host_by_name[host.ip.lower()] = host
        if host.hostname and host.hostname != "Unknown device":
            host_by_name[host.hostname.lower()] = host

    manual_by_host: dict[str, list[ManualService]] = {host.ip: [] for host in data.hosts}
    unmatched_manual: list[ManualService] = []
    for item in data.config.manual_services:
        matched = host_by_name.get(url_hostname(item.url))
        if matched:
            manual_by_host.setdefault(matched.ip, []).append(item)
        else:
            unmatched_manual.append(item)
    return manual_by_host, unmatched_manual


def machine_card(data: DashboardData, host: Host, manual_items: list[ManualService] | None = None) -> str:
    manual_items = manual_items or []
    service_cards = [manual_service_card(item, data.manual_status.get(item.id)) for item in manual_items]
    service_cards.extend(discovered_service_card(data, host, port) for port in host.open_ports)
    title = host.hostname if host.hostname != "Unknown device" else host.ip
    mac = host.mac or "—"
    subnet = host_subnet_name(host.ip, data.subnets)
    service_count = len(service_cards)
    port_text = ", ".join(str(port) for port in host.open_ports) or "—"
    statuses = [status_label(data.manual_status.get(item.id)) for item in manual_items] + [status_label(host.probes.get(port)) for port in host.open_ports]
    main_status = "online" if any(status in {"online", "auth"} for status in statuses) else (statuses[0] if statuses else "unknown")
    duplicate = duplicate_group_for_host(data.config, host)
    duplicate_text = duplicate.name if duplicate else ""
    search = " ".join([host.ip, host.hostname, mac, subnet, port_text, duplicate_text, *statuses])
    info = (
        f'<dl class="machine-info">'
        f'<div><dt>Hostname</dt><dd>{html.escape(host.hostname)}</dd></div>'
        f'<div><dt>IP</dt><dd>{html.escape(host.ip)}</dd></div>'
        f'<div><dt>Subnet</dt><dd>{html.escape(subnet)}</dd></div>'
        f'<div><dt>MAC</dt><dd>{html.escape(mac)}</dd></div>'
        f'<div><dt>Ports</dt><dd>{html.escape(port_text)}</dd></div>'
        f'<div><dt>Configure</dt><dd><code>hosts.{html.escape(host.ip)}</code></dd></div>'
        f'</dl>'
    )
    dup = duplicate_badge(data.config, host)
    summary_meta = f'{host.ip} · {subnet} · {service_count} service(s)' + (f' · duplicate: {duplicate_text}' if duplicate_text else '')
    return (
        f'<details class="machine-card" data-machine data-subnet="{html.escape(subnet, quote=True)}" data-tags="{html.escape(item_tags([subnet, main_status, duplicate_text]), quote=True)}" data-search="{html.escape(search, quote=True)}">'
        f'<summary><span class="machine-icon">🖥</span><span class="machine-title"><strong>{html.escape(title)}</strong><small>{html.escape(summary_meta)}</small></span>{dup}{status_html(ProbeResult(status=main_status))}</summary>'
        f'{info}<div class="machine-grid">{"".join(service_cards)}</div>'
        f'</details>'
    )


def manual_external_card(data: DashboardData, item: ManualService) -> str:
    probe = data.manual_status.get(item.id)
    search = " ".join([item.name, item.url, item.group, *item.tags, status_label(probe)])
    return (
        f'<details class="machine-card" data-machine data-subnet="Manual" data-tags="manual {html.escape(status_label(probe), quote=True)}" data-search="{html.escape(search, quote=True)}">'
        f'<summary><span class="machine-icon">★</span><span class="machine-title"><strong>{html.escape(item.name)}</strong><small>{html.escape(item.url)} · manual</small></span>{status_html(probe)}</summary>'
        f'<div class="machine-grid">{manual_service_card(item, probe)}</div>'
        f'</details>'
    )


def render_machine_sections(data: DashboardData) -> str:
    manual_by_host, unmatched_manual = match_manual_services(data)
    cards = [machine_card(data, host, manual_by_host.get(host.ip, [])) for host in data.hosts]
    cards.extend(manual_external_card(data, item) for item in unmatched_manual)
    if not cards:
        return '<div class="empty">Физические машины с открытыми сервисами не найдены</div>'
    return f'<section class="machine-section" data-section><div class="machine-list">{"".join(cards)}</div></section>'


def render_subnet_sections(data: DashboardData) -> str:
    manual_by_host, unmatched_manual = match_manual_services(data)
    sections: list[str] = []
    for subnet in data.subnets:
        hosts = [host for host in data.hosts if ipaddress.ip_address(host.ip) in subnet]
        if not hosts:
            sections.append(
                f'<section class="subnet-block" data-section data-search="{html.escape(str(subnet), quote=True)}">'
                f'<div class="subnet-head"><div><h2>▦ {html.escape(str(subnet))}</h2><p>Нет найденных машин</p></div><span class="chip">0 hosts</span></div>'
                f'</section>'
            )
            continue
        cards = [machine_card(data, host, manual_by_host.get(host.ip, [])) for host in hosts]
        service_count = sum(len(host.open_ports) + len(manual_by_host.get(host.ip, [])) for host in hosts)
        sections.append(
            f'<section class="subnet-block" data-section data-search="{html.escape(str(subnet), quote=True)}">'
            f'<div class="subnet-head"><div><h2>▦ {html.escape(str(subnet))}</h2><p>{len(hosts)} host(s) · {service_count} service(s)</p></div><span class="chip">{len(hosts)} hosts</span></div>'
            f'<div class="machine-list">{"".join(cards)}</div>'
            f'</section>'
        )

    if unmatched_manual:
        cards = [manual_external_card(data, item) for item in unmatched_manual]
        sections.append(
            f'<section class="subnet-block" data-section data-search="manual external">'
            f'<div class="subnet-head"><div><h2>★ Manual / external</h2><p>Сервисы из конфига без найденной физической машины</p></div></div>'
            f'<div class="machine-list">{"".join(cards)}</div>'
            f'</section>'
        )

    return "\n".join(sections) or '<div class="empty">Подсети с машинами не найдены</div>'


def collect_bookmarks(config: DashboardConfig) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in config.bookmarks:
        data_search = " ".join([item.name, item.url, item.group, *item.tags])
        html_item = (
            f'<a class="bookmark" data-card data-group="{html.escape(item.group, quote=True)}" data-tags="{html.escape(item_tags(item.tags, [item.group]), quote=True)}" '
            f'data-search="{html.escape(data_search, quote=True)}" href="{html.escape(item.url, quote=True)}" target="_blank" rel="noreferrer">'
            f'{icon_html(item.icon, item.url, item.favicon, "↗")}<span>{html.escape(item.name)}</span></a>'
        )
        groups.setdefault(item.group, []).append(html_item)
    return groups


def render(data: DashboardData) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subnets_text = ", ".join(str(subnet) for subnet in data.subnets)
    ports_text = ", ".join(map(str, data.ports))
    services_total = sum(len(h.open_ports) for h in data.hosts) + len(data.config.manual_services)
    linked_services = len(data.config.manual_services) + sum(1 for host in data.hosts for port in host.open_ports if service_url(host.ip, service_for_host(host.ip, host.mac, port, data.config), host.probes.get(port)))

    machine_html = render_machine_sections(data)
    subnet_html = render_subnet_sections(data)
    cards_by_group = collect_cards(data)
    bookmark_groups = collect_bookmarks(data.config)
    groups_present = set(cards_by_group) | set(bookmark_groups)

    sections = []
    for group in group_order(data.config, groups_present):
        items = cards_by_group.get(group, [])
        if not items:
            continue
        icon = data.config.groups.get(group, "▦")
        sections.append(f'<section class="group"><h2>{html.escape(icon)} {html.escape(group)}</h2><div class="card-grid">{"".join(items)}</div></section>')
    cards_html = "\n".join(sections) or '<div class="empty">Сервисы не найдены</div>'

    bookmark_sections = []
    for group in group_order(data.config, bookmark_groups):
        items = bookmark_groups.get(group, [])
        if not items:
            continue
        icon = data.config.groups.get(group, "↗")
        bookmark_sections.append(f'<section class="group bookmarks"><h2>{html.escape(icon)} {html.escape(group)}</h2><div class="bookmark-grid">{"".join(items)}</div></section>')
    bookmarks_html = "\n".join(bookmark_sections)

    all_tags = sorted({tag for item in data.config.manual_services for tag in item.tags} | {tag for item in data.config.bookmarks for tag in item.tags} | {service.group for service in data.config.services.values()} | {group.name for group in data.config.duplicate_groups} | {str(subnet) for subnet in data.subnets} | {"online", "offline", "auth", "error"})
    tags_html = "".join(f'<button class="tag" data-tag="{html.escape(tag, quote=True)}">{html.escape(tag)}</button>' for tag in all_tags if tag)
    meta_details = f"Subnets: {subnets_text}\nGenerated: {generated}\nPorts: {ports_text}"

    rows = []
    for host in data.hosts:
        mac = host.mac or "—"
        services_html = " ".join(table_service_html(host.ip, host.mac, port, data.config, host.probes.get(port)) for port in host.open_ports)
        search_text = " ".join([host.ip, host.hostname, mac, services_html])
        rows.append(
            f'<tr data-row data-search="{html.escape(search_text, quote=True)}">'
            f'<td data-label="IP"><div class="node-cell"><span class="node-dot"></span><div><strong>{html.escape(host.ip)}</strong><small>LAN node</small></div></div></td>'
            f'<td data-label="Name"><span class="device-name">{html.escape(host.hostname)}</span></td>'
            f'<td data-label="MAC"><code>{html.escape(mac)}</code></td>'
            f'<td data-label="Services"><div class="services">{services_html}</div></td>'
            '</tr>'
        )
    rows_html = "\n".join(rows) or '<tr><td colspan="4" class="empty">Узлы с открытыми сервисами не найдены</td></tr>'

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simple Dash</title>
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="assets/favicon.svg">
  <style>
    :root {{
      color-scheme:dark;
      --bg:#0d1116;
      --panel:#212730e6;
      --panel-soft:#252f3dd1;
      --line:#49505980;
      --line-strong:#757d8975;
      --text:#d5d8dbf5;
      --copy:#d5d8dbd6;
      --muted:#9fa4abad;
      --muted-strong:#d5d8dbcc;
      --accent:#e86a52;
      --accent-rust:#8f3222;
      --accent-blue:#6a9fcc;
      --ok:#72e89d;
      --warn:#f7cf68;
      --bad:#ff7b72;
      --mono:"SFMono-Regular","SF Mono",Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; color:var(--text); background:var(--bg); font:14px/1.55 var(--mono); }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.28; background:radial-gradient(circle at 18% 10%, rgba(232,106,82,.16), transparent 26rem), radial-gradient(circle at 82% 12%, rgba(106,159,204,.13), transparent 28rem), linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px); background-size:auto,auto,48px 48px,48px 48px; }}
    .site-tilt-layer {{ position:relative; z-index:1; }}
    main,.content-shell {{ width:min(1180px,100%); margin:auto; padding:34px 18px 48px; position:relative; }}
    .packages-dashboard {{ display:grid; gap:1rem; }}
    .content-card {{ border:1px solid var(--line-strong); background:var(--panel); overflow:hidden; }}
    .content-card-header {{ display:flex; align-items:baseline; justify-content:space-between; gap:1rem; padding:.78rem 1rem; border-bottom:1px solid var(--line); background:var(--panel-soft); }}
    .content-card-title {{ margin:0; color:var(--text); font-family:var(--mono); font-size:.82rem; font-weight:500; letter-spacing:.16em; line-height:1.2; text-transform:uppercase; }}
    .content-card-body {{ padding:1rem; }}
    .packages-count {{ color:var(--muted); font-family:var(--mono); font-size:.68rem; }}
    .hero,.content-hero {{ border:1px solid var(--line-strong); border-left:2px solid var(--accent-rust); background:var(--panel); padding:clamp(1rem,2.4vw,1.5rem); }}
    .hero::after {{ display:none; }}
    .topline {{ display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; flex-wrap:wrap; }}
    .brand {{ display:flex; align-items:center; min-width:0; }}
    .brand-logo {{ width:clamp(10rem, 24vw, 17.5rem); height:auto; display:block; border:1px solid var(--line); background:#0d1116; }}
    .header-actions {{ display:flex; align-items:center; justify-content:flex-end; gap:.5rem; flex-wrap:wrap; }}
    .header-stats {{ display:flex; align-items:center; justify-content:flex-end; gap:.42rem; flex-wrap:wrap; }}
    .header-stat {{ min-height:2.35rem; display:inline-flex; align-items:center; gap:.45rem; border:1px solid var(--line); border-left:2px solid var(--accent-rust); background:rgba(255,255,255,.015); padding:0 .68rem; font-family:var(--mono); }}
    .header-stat b {{ color:var(--text); font-size:.9rem; line-height:1; }}
    .header-stat em {{ color:var(--muted); font-size:.58rem; line-height:1; font-style:normal; text-transform:uppercase; letter-spacing:.08em; }}
    .meta-card {{ display:inline-flex; align-items:center; min-height:2.35rem; border:1px solid var(--line); background:rgba(255,255,255,.015); color:var(--muted-strong); padding:0 .68rem; font-family:var(--mono); font-size:.58rem; text-transform:uppercase; letter-spacing:.08em; cursor:help; }}
    .meta-card strong {{ color:var(--muted-strong); font-size:inherit; font-weight:500; }}
    .toolbar {{ display:flex; align-items:center; gap:.55rem; margin-top:.75rem; flex-wrap:wrap; }}
    .search {{ flex:1 1 280px; position:relative; }} .search span {{ position:absolute; left:.85rem; top:50%; transform:translateY(-50%); color:var(--muted); font-family:var(--mono); }}
    input {{ width:100%; height:2.95rem; padding:0 .85rem 0 2.35rem; border:1px solid var(--line-strong); outline:0; background:rgba(0,0,0,.18); color:var(--text); font: .82rem/1.2 var(--mono); }}
    input:focus {{ border-color:rgba(232,106,82,.55); box-shadow:inset 2px 0 0 var(--accent-rust); }}
    .chip,.view-btn,.tag {{ min-height:2.35rem; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--line); background:rgba(255,255,255,.015); color:var(--muted-strong); padding:0 .78rem; font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.07em; text-decoration:none; cursor:pointer; }}
    .view-btn.active,.tag.active {{ border-color:rgba(232,106,82,.55); color:var(--accent); background:rgba(232,106,82,.08); box-shadow:inset 2px 0 0 var(--accent-rust); }}
    .tags {{ display:none; }}
    .stats {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.55rem; margin:0; }}
    .stat-card {{ min-height:3.8rem; border:1px solid var(--line-strong); border-left:2px solid var(--accent-rust); background:rgba(255,255,255,.015); padding:.62rem .78rem; display:flex; align-items:center; justify-content:space-between; gap:.8rem; }}
    .card-label {{ color:var(--muted); font-family:var(--mono); font-size:.62rem; text-transform:uppercase; letter-spacing:.08em; }} .num {{ display:block; color:var(--text); font-family:var(--mono); font-size:1.42rem; line-height:1; font-weight:800; }}
    .group {{ margin-top:1.25rem; }} h2 {{ margin:0 0 .75rem; color:var(--muted-strong); font-family:var(--mono); font-size:.86rem; letter-spacing:.02em; }}
    .card-grid,.bookmark-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.9rem; align-items:start; }}
    .subnet-block {{ margin-top:1rem; border:1px solid var(--line-strong); border-left:2px solid var(--accent-rust); background:var(--panel); padding:1rem; }}
    .subnet-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; margin-bottom:.85rem; }}
    .subnet-head h2 {{ margin:0 0 .25rem; }} .subnet-head p {{ margin:0; color:var(--muted); font-family:var(--mono); font-size:.72rem; }}
    .machine-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.9rem; align-items:start; }}
    .machine-card,.packages-like-card {{ min-width:0; border:1px solid var(--line-strong); background:rgba(255,255,255,.015); transition:border-color 140ms ease, background 140ms ease; }}
    .machine-card:hover,.machine-card:focus-within,.svc-card:hover,.svc-card:focus-within,.bookmark:hover,.bookmark:focus-within {{ border-color:rgba(242,138,46,.42); background:rgba(255,255,255,.028); }}
    .machine-card summary {{ display:flex; align-items:center; gap:.75rem; padding:.9rem; cursor:pointer; list-style:none; }}
    .machine-card summary::-webkit-details-marker {{ display:none; }} .machine-card[open] summary {{ border-bottom:1px solid var(--line); background:var(--panel-soft); }}
    .machine-icon,.icon {{ width:2.5rem; height:2.5rem; display:grid; place-items:center; flex:none; border:1px solid var(--line); background:rgba(0,0,0,.18); font-size:1.2rem; overflow:hidden; }}
    .icon img {{ width:1.35rem; height:1.35rem; object-fit:contain; }}
    .machine-title {{ min-width:0; flex:1; }} .machine-title strong {{ display:block; color:var(--text); font-family:var(--mono); font-size:.86rem; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }} .machine-title small {{ display:block; color:var(--muted); font-family:var(--mono); font-size:.68rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .machine-info {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:.55rem; margin:.85rem .9rem 0; }} .machine-info div {{ border:1px solid var(--line); background:rgba(0,0,0,.16); padding:.55rem; }} .machine-info dt {{ color:var(--muted); font-family:var(--mono); font-size:.62rem; text-transform:uppercase; letter-spacing:.08em; }} .machine-info dd {{ margin:.15rem 0 0; color:var(--muted-strong); font-family:var(--mono); font-size:.72rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .machine-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:.65rem; padding:.9rem; }}
    .svc-card,.bookmark {{ min-width:0; display:flex; align-items:center; gap:.7rem; border:1px solid var(--line-strong); background:rgba(255,255,255,.015); color:var(--text); text-decoration:none; padding:.78rem; transition:border-color 140ms ease, background 140ms ease; }}
    .svc-card {{ min-height:5.2rem; }} .bookmark {{ min-height:3.7rem; }} .bookmark .icon {{ width:2rem; height:2rem; font-size:1rem; }}
    .card-body {{ min-width:0; flex:1; }} .card-body strong {{ display:block; color:var(--text); font-family:var(--mono); font-size:.8rem; font-weight:650; line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }} .card-body small,.card-body em {{ display:block; font-family:var(--mono); line-height:1.35; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-style:normal; }} .card-body small {{ color:var(--muted-strong); font-size:.68rem; font-weight:400; letter-spacing:-.025em; opacity:.88; }} .card-body em {{ color:var(--muted); font-size:.62rem; font-weight:400; letter-spacing:-.015em; }}
    .status,.duplicate {{ flex:none; align-self:flex-start; display:inline-flex; align-items:center; border:1px solid var(--line); padding:.14rem .5rem; font-family:var(--mono); font-size:.62rem; letter-spacing:.08em; line-height:1.25; text-transform:uppercase; background:transparent; }} .status-online {{ border-color:rgba(74,222,128,.55); color:var(--ok); }} .status-auth {{ border-color:rgba(251,191,36,.55); color:var(--warn); }} .status-offline,.status-error {{ border-color:rgba(255,123,114,.55); color:var(--bad); }} .status-unknown {{ color:var(--muted); }} .duplicate {{ border-color:rgba(251,191,36,.55); color:var(--warn); }}
    .panel {{ margin-top:1.25rem; border:1px solid var(--line-strong); border-left:2px solid var(--accent-rust); background:var(--panel); overflow:hidden; }}
    .panel-head {{ display:flex; align-items:center; justify-content:space-between; gap:.8rem; padding:1rem 1rem 0; flex-wrap:wrap; }} .muted {{ color:var(--muted); font-family:var(--mono); font-size:.72rem; }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; margin-top:.7rem; }} th,td {{ padding:.85rem 1rem; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }} th {{ color:var(--muted); font-family:var(--mono); font-size:.64rem; text-transform:uppercase; letter-spacing:.1em; }} tbody tr:hover {{ background:rgba(255,255,255,.028); }} tbody tr:last-child td {{ border-bottom:0; }}
    .node-cell {{ display:flex; align-items:center; gap:.65rem; }} .node-cell strong {{ font-family:var(--mono); font-size:.82rem; }} .node-cell small {{ display:block; color:var(--muted); font-family:var(--mono); font-size:.66rem; }} .node-dot {{ width:.55rem; height:.55rem; background:var(--accent); flex:0 0 auto; }} .device-name {{ font-family:var(--mono); font-weight:700; }}
    code {{ border:1px solid var(--line); background:rgba(0,0,0,.22); color:var(--muted-strong); padding:.22rem .42rem; font:.68rem/1.35 var(--mono); }}
    .services {{ display:flex; flex-wrap:wrap; gap:.45rem; }} .service {{ display:inline-flex; align-items:center; gap:.45rem; min-height:2rem; border:1px solid var(--line); background:rgba(255,255,255,.015); color:var(--text); padding:.34rem .55rem; text-decoration:none; font-family:var(--mono); }} .service span {{ display:flex; flex-direction:column; line-height:1.2; }} .service em {{ max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); font-size:.62rem; font-style:normal; }} .service b {{ color:var(--accent-blue); font-size:.68rem; }} .service-link:hover {{ border-color:rgba(232,106,82,.55); color:var(--accent); }}
    .empty {{ color:var(--muted); text-align:center; padding:2rem; font-family:var(--mono); }} .hidden {{ display:none !important; }}
    #subnets-view,#cards-view,#table-view {{ display:none; }} body.subnets-mode #subnets-view {{ display:block; }} body.groups-mode #cards-view {{ display:block; }} body.table-mode #table-view {{ display:block; }} body.subnets-mode #machine-view,body.groups-mode #machine-view,body.table-mode #machine-view {{ display:none; }}
    @media (max-width:860px) {{ .card-grid,.bookmark-grid,.machine-list {{ grid-template-columns:1fr; }} .stats {{ grid-template-columns:1fr; }} .header-actions,.header-stats {{ justify-content:flex-start; }} .meta-card {{ max-width:none; }} }}
    @media (max-width:760px) {{ main {{ padding:1rem .7rem 1.7rem; }} .hero {{ padding:1rem; }} table,thead,tbody,tr,th,td {{ display:block; }} thead {{ display:none; }} tbody tr {{ padding:.75rem 0; border-bottom:1px solid var(--line); }} td {{ display:flex; justify-content:space-between; gap:1rem; border:0; padding:.55rem 1rem; }} td::before {{ content:attr(data-label); color:var(--muted); font-family:var(--mono); font-size:.62rem; text-transform:uppercase; letter-spacing:.1em; }} td[data-label="Services"] {{ display:block; }} td[data-label="Services"]::before {{ display:block; margin-bottom:.6rem; }} .node-cell {{ justify-content:flex-end; text-align:right; }} }}
  </style>
</head>
<body>
<div class="site-tilt-layer">
<main class="content-shell packages-dashboard">
  <header class="content-hero hero">
    <div class="topline">
      <div class="brand">
        <img class="brand-logo" src="assets/simple-dash-logo.svg" alt="Simple Dash" width="280" height="72">
      </div>
      <div class="header-actions">
        <div class="header-stats" aria-label="Summary">
          <span class="header-stat"><b>{len(data.hosts)}</b><em>hosts</em></span>
          <span class="header-stat"><b>{services_total}</b><em>services</em></span>
          <span class="header-stat"><b>{linked_services}</b><em>links</em></span>
        </div>
        <div class="meta-card" title="{html.escape(meta_details, quote=True)}"><strong>scan details</strong></div>
      </div>
    </div>
    <div class="toolbar">
      <label class="search"><span>⌕</span><input data-filter placeholder="Поиск: сервис, IP, tag, hostname, порт…"></label>
      <button class="view-btn active" data-view="machines">Machines</button>
      <button class="view-btn" data-view="subnets">Subnets</button>
      <button class="view-btn" data-view="groups">Groups</button>
      <button class="view-btn" data-view="table">Table</button>
      <a class="chip" href="data.json" target="_blank">data.json</a>
    </div>
  </header>

  <section class="content-card packages-index-card dashboard-card"><header class="content-card-header"><h2 class="content-card-title">Dashboard</h2><div class="content-card-actions"><span class="packages-count">Machines / Subnets / Groups / Table</span></div></header><div class="content-card-body">
  <div id="machine-view">{machine_html}</div>
  <div id="subnets-view">{subnet_html}</div>
  <div id="cards-view">{cards_html}{bookmarks_html}</div>
  <section class="panel" id="table-view">
    <div class="panel-head"><h2>Network Nodes</h2><span class="muted" id="visible-count">{len(data.hosts)} devices</span></div>
    <table><thead><tr><th>IP</th><th>Name</th><th>MAC</th><th>Services</th></tr></thead><tbody>{rows_html}</tbody></table>
  </section>
  </div></section>
</main>
</div>
<script>
(() => {{
  const input = document.querySelector('[data-filter]');
  const cards = [...document.querySelectorAll('[data-card]')];
  const machines = [...document.querySelectorAll('[data-machine]')];
  const rows = [...document.querySelectorAll('[data-row]')];
  const counter = document.getElementById('visible-count');
  const tagButtons = [...document.querySelectorAll('[data-tag]')];
  const viewButtons = [...document.querySelectorAll('[data-view]')];
  let activeTag = '';
  function matchesFilter(el, query) {{
    const text = (el.dataset.search || '').toLowerCase();
    const tags = (el.dataset.tags || '').toLowerCase().split(/\\s+/);
    return text.includes(query) && (!activeTag || tags.includes(activeTag.toLowerCase()) || (el.dataset.group || '').toLowerCase() === activeTag.toLowerCase());
  }}
  function applyFilter() {{
    const query = (input?.value || '').trim().toLowerCase();
    let visibleRows = 0;
    cards.forEach((card) => {{
      card.classList.toggle('hidden', !matchesFilter(card, query));
    }});
    machines.forEach((machine) => {{
      const machineMatches = matchesFilter(machine, query);
      const visibleServices = [...machine.querySelectorAll('[data-card]')].some((card) => !card.classList.contains('hidden'));
      machine.classList.toggle('hidden', !(machineMatches || visibleServices));
    }});
    document.querySelectorAll('.machine-section,.subnet-block,.group').forEach((section) => {{
      const sectionText = (section.dataset.search || '').toLowerCase();
      const visibleCards = [...section.querySelectorAll('[data-card],[data-machine]')].some((card) => !card.classList.contains('hidden'));
      section.classList.toggle('hidden', !visibleCards && !sectionText.includes(query));
    }});
    rows.forEach((row) => {{
      const ok = (row.dataset.search || '').toLowerCase().includes(query);
      row.style.display = ok ? '' : 'none';
      if (ok) visibleRows += 1;
    }});
    if (counter) counter.textContent = `${{visibleRows}} devices`;
  }}
  input?.addEventListener('input', applyFilter);
  tagButtons.forEach((btn) => btn.addEventListener('click', () => {{
    tagButtons.forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    activeTag = btn.dataset.tag || '';
    applyFilter();
  }}));
  viewButtons.forEach((btn) => btn.addEventListener('click', () => {{
    viewButtons.forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    document.body.classList.toggle('table-mode', btn.dataset.view === 'table');
    document.body.classList.toggle('groups-mode', btn.dataset.view === 'groups');
    document.body.classList.toggle('subnets-mode', btn.dataset.view === 'subnets');
  }}));
}})();
</script>
</body>
</html>
"""


def probe_to_json(probe: ProbeResult | None, include_latency: bool = True) -> dict[str, Any]:
    if not probe:
        return {"status": "unknown"}
    return {
        "status": probe.status,
        "latency_ms": round(probe.latency_ms, 1) if include_latency and probe.latency_ms is not None else None,
        "http_status": probe.http_status,
        "fingerprint": probe.fingerprint,
        "detected_app": probe.detected_app,
        "protocol": probe.protocol,
        "error": probe.error,
    }


def service_to_json(service: Service) -> dict[str, Any]:
    return {
        "port": service.port,
        "name": service.name,
        "protocol": service.protocol,
        "url": service.url,
        "icon": service.icon,
        "group": service.group,
        "tags": list(service.tags),
        "favicon": service.favicon,
    }


def dashboard_json(data: DashboardData, include_generated: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subnets": [str(subnet) for subnet in data.subnets],
        "ports": data.ports,
        "hosts": [],
        "manual_services": [],
        "bookmarks": [item.__dict__ | {"tags": list(item.tags)} for item in data.config.bookmarks],
        "groups": data.config.groups,
        "duplicates": [{"id": group.id, "name": group.name, "hosts": list(group.hosts)} for group in data.config.duplicate_groups],
        "services": {str(port): service_to_json(service) for port, service in sorted(data.config.services.items())},
    }
    if include_generated:
        payload["generated"] = datetime.now().isoformat(timespec="seconds")
    for host in data.hosts:
        payload["hosts"].append({
            "ip": host.ip,
            "hostname": host.hostname,
            "mac": host.mac,
            "open_ports": list(host.open_ports),
            "services": [
                {
                    "port": port,
                    "definition": service_to_json(service_for_host(host.ip, host.mac, port, data.config)),
                    "probe": probe_to_json(host.probes.get(port), include_latency=include_generated),
                    "url": service_url(host.ip, service_for_host(host.ip, host.mac, port, data.config), host.probes.get(port)),
                }
                for port in host.open_ports
            ],
        })
    for item in data.config.manual_services:
        payload["manual_services"].append({
            "id": item.id,
            "name": item.name,
            "url": item.url,
            "group": item.group,
            "icon": item.icon,
            "tags": list(item.tags),
            "favicon": item.favicon,
            "probe": probe_to_json(data.manual_status.get(item.id), include_latency=include_generated),
        })
    return payload


def dashboard_signature(data: DashboardData) -> str:
    return json.dumps(dashboard_json(data, include_generated=False), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def discovered_overrides_json(data: DashboardData) -> dict[str, Any]:
    hosts: dict[str, Any] = {}
    for host in data.hosts:
        services = []
        for port in host.open_ports:
            base = service_for_host(host.ip, host.mac, port, data.config)
            probe = host.probes.get(port)
            protocol = base.protocol or (probe.protocol if probe and probe.protocol in {"http", "https"} else default_protocol(port))
            services.append({
                "port": port,
                "name": display_name(base.name, probe),
                "protocol": protocol,
                "icon": (probe.detected_icon if probe and probe.detected_icon else base.icon),
                "group": base.group,
                "tags": list(base.tags),
                "favicon": bool(base.favicon or protocol in {"http", "https"}),
            })
        host_entry: dict[str, Any] = {"services": services}
        if host.hostname and host.hostname != "Unknown device":
            host_entry["name"] = host.hostname
        hosts[host.ip] = host_entry

    return {
        "generated_from": "data.json",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hosts": hosts,
        "duplicates": [{"id": group.id, "name": group.name, "hosts": list(group.hosts)} for group in data.config.duplicate_groups],
    }


def write_snapshot(path: Path, data: DashboardData) -> bool:
    return write_if_changed(path, json.dumps(discovered_overrides_json(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_ports_catalog(path: Path) -> dict[int, Service]:
    if not path.exists():
        raise SystemExit(f"Ports catalog not found: {path}")
    data = load_json_config(path)
    raw = data.get("services", data.get("ports"))
    services = parse_services(raw, str(path))
    if not services:
        raise SystemExit(f"Ports catalog has no services: {path}")
    return services


def load_runtime_config(args: argparse.Namespace) -> tuple[DashboardConfig, list[int]]:
    data, source_label = resolve_config_data(args)
    if not data and args.config is None:
        config = empty_config()
    else:
        config = build_config_from_dict(data, source_label)
    extra_ports = args.ports or []

    catalog_services: dict[int, Service] = {}
    if args.discover_ports == "common":
        catalog_services = load_ports_catalog(Path(args.ports_catalog))
        for port, service in catalog_services.items():
            config.services.setdefault(port, service)

    ports = sorted(set(config.services) | set(extra_ports) | set(catalog_services))
    for port in extra_ports:
        config.services.setdefault(
            port,
            Service(
                port=port,
                name=guess_service_name(port),
                protocol=default_protocol(port),
                group="Discovered",
                icon="🌐" if default_protocol(port) == "http" else "🔒" if default_protocol(port) == "https" else "▣",
                favicon=default_protocol(port) in {"http", "https"},
            ),
        )
    return config, ports


async def scan_all(subnets: list[ipaddress.IPv4Network], ports: list[int], args: argparse.Namespace, config: DashboardConfig) -> tuple[list[Host], dict[str, ProbeResult]]:
    return await asyncio.gather(scan_hosts(subnets, ports, args, config), scan_manual_services(config.manual_services, args))


def scan_dashboard(args: argparse.Namespace) -> DashboardData:
    config, ports = load_runtime_config(args)
    subnets = resolve_subnets(args.subnet, config)
    subnets_text = ", ".join(str(subnet) for subnet in subnets)
    print(f"Scanning {subnets_text} ports {','.join(map(str, ports))} ...", flush=True)
    hosts, manual_status = asyncio.run(scan_all(subnets, ports, args, config))
    return DashboardData(subnets=subnets, ports=ports, config=config, hosts=hosts, manual_status=manual_status)


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)
    return True


def write_static_assets(output_dir: Path) -> bool:
    assets_dir = output_dir / "assets"
    logo_changed = write_if_changed(assets_dir / "simple-dash-logo.svg", SIMPLE_DASH_LOGO_SVG)
    favicon_changed = write_if_changed(assets_dir / "favicon.svg", SIMPLE_DASH_FAVICON_SVG)
    return logo_changed or favicon_changed


def write_outputs(args: argparse.Namespace, data: DashboardData) -> bool:
    output = Path(args.output)
    assets_changed = write_static_assets(output.parent)
    html_changed = write_if_changed(output, render(data))
    json_path = output.with_name("data.json")
    json_changed = write_if_changed(json_path, json.dumps(dashboard_json(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    snapshot_changed = False
    if args.snapshot_output:
        snapshot_changed = write_snapshot(Path(args.snapshot_output), data)
    return assets_changed or html_changed or json_changed or snapshot_changed


def run_once(args: argparse.Namespace) -> str:
    data = scan_dashboard(args)
    write_outputs(args, data)
    signature = dashboard_signature(data)
    print(f"Wrote {args.output}: {len(data.hosts)} host(s), {sum(len(h.open_ports) for h in data.hosts)} discovered service(s), {len(data.config.manual_services)} manual", flush=True)
    return signature


def run_watch(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    state_path = output_path.with_suffix(output_path.suffix + ".state.json")
    last_signature = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    nominal_interval = max(1, int(args.watch_interval))
    backoff_cap = max(nominal_interval * 8, 60)
    interval = nominal_interval
    while True:
        try:
            data = scan_dashboard(args)
            signature = dashboard_signature(data)
            discovered_total = sum(len(host.open_ports) for host in data.hosts)
            if signature != last_signature or not output_path.exists() or not output_path.with_name("data.json").exists():
                changed = write_outputs(args, data)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(signature, encoding="utf-8")
                last_signature = signature
                action = "Updated" if changed else "State saved"
                print(f"{action} {output_path}: {len(data.hosts)} host(s), {discovered_total} discovered, {len(data.config.manual_services)} manual", flush=True)
            else:
                print(f"No changes: {len(data.hosts)} host(s), {discovered_total} discovered. Output was not rewritten", flush=True)
            interval = nominal_interval
        except Exception as exc:
            interval = min(backoff_cap, max(nominal_interval, interval * 2))
            print(f"Scan failed: {exc}. Retrying in {interval}s", flush=True)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a static Homer-like LAN dashboard")
    parser.add_argument("subnet", nargs="?", help="CIDR subnet(s). Examples: 192.168.1.0/24, 192.168.1, 1, or comma-separated list. Defaults to config subnets or 192.168.1.0/24")
    parser.add_argument("--output", "-o", default="index.html", help="HTML file to write")
    parser.add_argument("--config", help="JSON config. Defaults to ./dashboard_config.local.json if it exists, otherwise ./dashboard_config.json")
    parser.add_argument("--ports", type=parse_ports, default=None, help="Extra comma-separated ports/ranges to probe in addition to configured services. Example: 1883,32400,9000-9010")
    parser.add_argument("--discover-ports", choices=("none", "common"), default="common", help="Port discovery profile. common loads known homelab ports from --ports-catalog; none scans only config/--ports")
    parser.add_argument("--ports-catalog", default=str(DEFAULT_PORTS_CATALOG_PATH), help="JSON catalog with known homelab ports for --discover-ports common")
    parser.add_argument("--host-discovery", default="arp", help="Include hosts without open scanned ports. Modes: none, arp, icmp, arp,icmp")
    parser.add_argument("--discovery-concurrency", type=int, default=128, help="Parallelism for host discovery probes")
    parser.add_argument("--discovery-timeout", type=float, default=0.6, help="Timeout for ICMP host discovery")
    parser.add_argument("--concurrency", type=int, default=64, help="Number of hosts scanned in parallel")
    parser.add_argument("--port-concurrency", type=int, default=512, help="Global limit for simultaneous TCP connect attempts")
    parser.add_argument("--port-timeout", type=float, default=0.35)
    parser.add_argument("--service-timeout", type=float, default=1.2, help="Timeout for app fingerprinting: HTTP title/server and TCP banners")
    parser.add_argument("--dns-timeout", type=float, default=0.5)
    parser.add_argument("--netbios-timeout", type=float, default=0.45)
    parser.add_argument("--arp-timeout", type=float, default=0.4)
    parser.add_argument("--watch-interval", type=int, default=0, help="Regenerate every N seconds. 0 = run once")
    parser.add_argument("--snapshot-output", default="", help="Write editable discovered overrides JSON, e.g. dashboard_overrides.json")
    parser.add_argument("--pid-file", default="", help="Write own PID to this file while running; remove on exit")
    args = parser.parse_args()
    pid_path = Path(args.pid_file) if args.pid_file else None
    if pid_path:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        if args.watch_interval > 0:
            run_watch(args)
        else:
            run_once(args)
    finally:
        if pid_path:
            try:
                if pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()

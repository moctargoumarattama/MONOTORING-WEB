"""Configuration sans dépendance supplémentaire et sans secret envoyé au navigateur."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    label: str
    port: int


SERVICES = (
    Service("merca-market", "Merca-Market", 5006),
    Service("klasora", "Klasora", 5005),
    Service("babamarket", "BabaMarket", 5002),
    Service("moc-mal", "Moc-Mal", 5003),
)
RESTART_ALLOWLIST = frozenset(service.name for service in SERVICES)


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    import math
    value = float(os.environ.get(name, str(default)))
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} doit être compris entre {minimum} et {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.environ.get(name, str(default)).lower()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} doit être true ou false")
    return raw in {"true", "1", "yes"}


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 5050
    interval: float = 2.0
    http_timeout: float = 1.5
    systemctl_timeout: float = 1.5
    backup_path: str = "/mnt/babamarket-backups"
    gateway_secret: str = "secret-gateway-local-klasora-2024"
    vps_token: str = ""
    admin_token: str = ""
    view_token: str = ""
    enable_restart: bool = True
    cookie_secure: bool = False
    vps_stale_seconds: float = 20.0
    vps_retention_seconds: float = 86400.0
    max_vps: int = 128
    max_streams: int = 32
    event_limit: int = 200

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.environ.get("NOC_HOST", "127.0.0.1"),
            port=int(_number("NOC_PORT", 5050, 1, 65535)),
            interval=_number("NOC_INTERVAL_SECONDS", 2, 0.5, 60),
            backup_path=os.environ.get("NOC_BACKUP_PATH", "/mnt/babamarket-backups"),
            gateway_secret=os.environ.get("NOC_GATEWAY_SECRET", cls.__dataclass_fields__["gateway_secret"].default),
            vps_token=os.environ.get("NOC_VPS_TOKEN", ""),
            admin_token=os.environ.get("NOC_ADMIN_TOKEN", ""),
            view_token=os.environ.get("NOC_VIEW_TOKEN", ""),
            enable_restart=_boolean("NOC_ENABLE_RESTART", True),
            cookie_secure=_boolean("NOC_COOKIE_SECURE", False),
            vps_stale_seconds=_number("NOC_VPS_STALE_SECONDS", 20, 5, 3600),
            vps_retention_seconds=_number("NOC_VPS_RETENTION_SECONDS", 86400, 60, 604800),
            max_vps=int(_number("NOC_MAX_VPS", 128, 1, 1024)),
            max_streams=int(_number("NOC_MAX_STREAMS", 32, 1, 128)),
        )

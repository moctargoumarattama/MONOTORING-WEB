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
    enable_restart: bool = True
    vps_stale_seconds: float = 20.0
    vps_retention_seconds: float = 86400.0
    max_vps: int = 128
    max_streams: int = 32
    event_limit: int = 200
    admin_phone_number: str = "212770010264"
    whatsapp_webhook_token: str = ""
    whatsapp_session_id: str = "1"
    whatsapp_send_url: str = "http://127.0.0.1:3001/message/send"
    whatsapp_send_to_field: str = "to"
    whatsapp_send_text_field: str = "text"
    whatsapp_send_timeout: float = 10.0
    whatsapp_media_dir: str = "/var/lib/klasora-whatsapp/media"
    whatsapp_max_audio_bytes: int = 8 * 1024 * 1024
    whatsapp_audio_seconds: int = 60
    voice_enabled: bool = True
    whisper_model: str = "tiny"
    whisper_model_path: str = "/opt/noc-dashboard/models/whisper"
    whisper_python: str = "/opt/noc-dashboard/voice-venv/bin/python"
    whisper_timeout: float = 120.0
    backup_script: str = "/usr/local/bin/backup-babamarket.sh"
    backup_timeout: float = 300.0
    voice_remote_url: str = ""
    voice_remote_token: str = ""
    sentinel_stale_seconds: float = 35.0
    sentinel_geoip_enabled: bool = True
    sentinel_state_path: str = "/var/lib/noc-dashboard/sentinel-counters.json"

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
            enable_restart=_boolean("NOC_ENABLE_RESTART", True),
            vps_stale_seconds=_number("NOC_VPS_STALE_SECONDS", 20, 5, 3600),
            vps_retention_seconds=_number("NOC_VPS_RETENTION_SECONDS", 86400, 60, 604800),
            max_vps=int(_number("NOC_MAX_VPS", 128, 1, 1024)),
            max_streams=int(_number("NOC_MAX_STREAMS", 32, 1, 128)),
            admin_phone_number=os.environ.get("ADMIN_PHONE_NUMBER", "212770010264"),
            whatsapp_webhook_token=os.environ.get("NOC_WHATSAPP_WEBHOOK_TOKEN", ""),
            whatsapp_session_id=os.environ.get("NOC_WHATSAPP_SESSION_ID", "1"),
            whatsapp_send_url=os.environ.get("NOC_WHATSAPP_SEND_URL", "http://127.0.0.1:3001/message/send"),
            whatsapp_send_to_field=os.environ.get("NOC_WHATSAPP_SEND_TO_FIELD", "to"),
            whatsapp_send_text_field=os.environ.get("NOC_WHATSAPP_SEND_TEXT_FIELD", "text"),
            whatsapp_send_timeout=_number("NOC_WHATSAPP_SEND_TIMEOUT", 10, 3, 30),
            whatsapp_media_dir=os.environ.get("NOC_WHATSAPP_MEDIA_DIR", "/var/lib/klasora-whatsapp/media"),
            whatsapp_max_audio_bytes=int(_number("NOC_WHATSAPP_MAX_AUDIO_BYTES", 8388608, 1024, 8388608)),
            whatsapp_audio_seconds=int(_number("NOC_WHATSAPP_AUDIO_SECONDS", 60, 1, 60)),
            voice_enabled=_boolean("NOC_VOICE_ENABLED", True),
            whisper_model=os.environ.get("NOC_WHISPER_MODEL", "tiny") or "tiny",
            whisper_model_path=os.environ.get("NOC_WHISPER_MODEL_PATH", "/opt/noc-dashboard/models/whisper") or "/opt/noc-dashboard/models/whisper",
            whisper_python=os.environ.get("NOC_WHISPER_PYTHON", "/opt/noc-dashboard/voice-venv/bin/python"),
            whisper_timeout=_number("NOC_WHISPER_TIMEOUT", 120, 5, 300),
            backup_script=os.environ.get("NOC_BACKUP_SCRIPT", os.environ.get("NOC_BABAMARKET_BACKUP_SCRIPT", "/usr/local/bin/backup-babamarket.sh")) or "/usr/local/bin/backup-babamarket.sh",
            backup_timeout=_number("NOC_BACKUP_TIMEOUT", 300, 5, 1800),
            voice_remote_url=os.environ.get("NOC_VOICE_REMOTE_URL", ""),
            voice_remote_token=os.environ.get("NOC_VOICE_REMOTE_TOKEN", ""),
            sentinel_stale_seconds=_number("NOC_SENTINEL_STALE_SECONDS", 35, 15, 300),
            sentinel_geoip_enabled=_boolean("NOC_SENTINEL_GEOIP", True),
            sentinel_state_path=os.environ.get("NOC_SENTINEL_STATE_PATH", "/var/lib/noc-dashboard/sentinel-counters.json"),
        )

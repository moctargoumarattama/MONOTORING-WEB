"""API NOC, consultation directe et flux SSE partagé, un seul worker."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import math
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sse_starlette.sse import EventSourceResponse

import collector
from config import RESTART_ALLOWLIST, Settings
from sentinel import SentinelManager
from whatsapp import WhatsAppController

LOGGER = logging.getLogger("noc-dashboard")
BASE_DIR = Path(__file__).resolve().parent


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    used: Annotated[int, Field(ge=0, le=2**60, strict=True)]
    total: Annotated[int, Field(gt=0, le=2**60, strict=True)]
    percent: Annotated[float, Field(ge=0, le=100, strict=True)]

    @model_validator(mode="after")
    def consistent(self) -> Metrics:
        if self.used > self.total:
            raise ValueError("used ne peut pas dépasser total")
        if abs(self.percent - self.used / self.total * 100) > 2:
            raise ValueError("Pourcentage incohérent avec used/total")
        return self


class RemoteService(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")]
    status: Annotated[str, Field(pattern=r"^(active|inactive|failed|unknown|activating|deactivating|reloading|maintenance)$")]


class VPSReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    hostname: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
    cpu_percent: Annotated[float, Field(ge=0, le=100, strict=True)]
    memory: Metrics
    disk: Metrics
    services: Annotated[list[RemoteService], Field(max_length=16)] = []

    @model_validator(mode="after")
    def unique_services(self) -> VPSReport:
        if len({item.name for item in self.services}) != len(self.services):
            raise ValueError("Services dupliqués")
        return self


async def limited_json(request: Request, limit: int) -> Any:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Content-Type application/json requis")
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > limit or int(length) < 0:
                raise HTTPException(413, "Corps de requête trop volumineux")
        except ValueError:
            raise HTTPException(400, "Content-Length invalide") from None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(413, "Corps de requête trop volumineux")
        body.extend(chunk)
    try:
        return json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "JSON invalide") from None


def validate_payload(model: type[BaseModel], data: Any) -> Any:
    try:
        return model.model_validate(data)
    except (ValidationError, ValueError):
        # Les données reçues ne sont pas recopiées dans les erreurs.
        raise HTTPException(422, "Données invalides : types, limites ou champs non conformes") from None


def token_matches(received: str | None, expected: str) -> bool:
    return bool(expected and received and hmac.compare_digest(received.encode(), expected.encode()))


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin:
        try:
            parts = urlsplit(origin)
        except ValueError:
            raise HTTPException(403, "Origine non autorisée") from None
        if parts.scheme not in {"http", "https"} or parts.netloc.lower() != request.url.netloc.lower():
            raise HTTPException(403, "Origine non autorisée")


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.collector = collector.Collector(settings)
        self.latest: dict[str, Any] | None = None
        self.serialized = "{}"
        self.revision = 0
        self.last_published = 0.0
        self.collect_task: asyncio.Task | None = None
        self.changed = asyncio.Condition()
        self.vps: dict[str, dict[str, Any]] = {}
        self.active_streams = 0
        self.restart_locks = {name: asyncio.Lock() for name in RESTART_ALLOWLIST}
        self.restart_times: dict[str, float] = {}
        self.sentinel = SentinelManager(settings, self)
        self.whatsapp = WhatsAppController(settings, self, self.restart_service)

    def vps_snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        result = []
        for hostname, item in list(self.vps.items()):
            age = max(0, now - item["seen"])
            if age > self.settings.vps_retention_seconds:
                del self.vps[hostname]
                self.collector._states.pop("vps:" + hostname, None)
                continue
            stale = age > self.settings.vps_stale_seconds
            healthy = not stale and item["report"]["cpu_percent"] < 95 and item["report"]["memory"]["percent"] < 90 and item["report"]["disk"]["percent"] < 90 and all(service["status"] == "active" for service in item["report"]["services"])
            self.collector.transition("vps:" + hostname, (stale, healthy), f"VPS {hostname} · {'rapport expiré' if stale else ('opérationnel' if healthy else 'incident détecté')}", healthy)
            item["stale"] = stale
            result.append({**item["report"], "last_seen": item["last_seen"], "age_seconds": round(age, 1), "stale": stale, "healthy": healthy})
        return sorted(result, key=lambda entry: entry["hostname"])

    async def publish(self, snapshot: dict[str, Any], *, collected: bool = True) -> None:
        snapshot["vps"] = self.vps_snapshot()
        if any(not item["healthy"] for item in snapshot["vps"]):
            snapshot["global_status"] = "incident"
        snapshot["events"] = list(self.collector.events)
        snapshot["sentinel"] = self.sentinel.snapshot()
        snapshot["voice"] = self.whatsapp.snapshot()
        serialized = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        self.latest = snapshot
        self.serialized = serialized
        if collected:
            self.last_published = time.monotonic()
        async with self.changed:
            self.revision += 1
            self.changed.notify_all()

    async def publish_module_update(self) -> None:
        if self.latest is not None:
            await self.publish(dict(self.latest), collected=False)

    async def restart_service(self, name: str) -> dict[str, Any]:
        """Chemin commun UI/WhatsApp après l'authentification propre au canal."""
        if name not in RESTART_ALLOWLIST:
            raise HTTPException(404, "Service non autorisé")
        sudo = shutil.which("sudo")
        systemctl = self.collector.systemctl
        if not self.settings.enable_restart or not systemctl or not sudo:
            raise HTTPException(503, "Redémarrages indisponibles sur cet hôte")
        lock = self.restart_locks[name]
        if lock.locked() or time.monotonic() - self.restart_times.get(name, -math.inf) < 30:
            raise HTTPException(429, "Redémarrage déjà demandé : patienter 30 secondes")
        async with lock:
            self.restart_times[name] = time.monotonic()
            self.collector.add_event("warning", f"Redémarrage demandé · {name}")
            try:
                code, _, _ = await collector.run_command([sudo, "-n", systemctl, "--no-block", "restart", name + ".service"], 5)
            except (OSError, asyncio.TimeoutError, RuntimeError):
                self.collector.add_event("error", f"Redémarrage non confirmé · {name}")
                raise HTTPException(504, "Commande expirée ou indisponible; vérifier le journal") from None
            if code != 0:
                self.collector.add_event("error", f"Redémarrage refusé · {name}")
                raise HTTPException(502, "systemd a refusé la commande; vérifier sudoers et le journal")
            self.collector.add_event("info", f"Redémarrage accepté par systemd · {name}")
            await self.publish_module_update()
            return {"ok": True, "service": name, "message": "Redémarrage accepté. Le collecteur vérifiera le retour du service."}

    async def collect_loop(self) -> None:
        while True:
            started = time.monotonic()
            try:
                snapshot = await self.collector.collect()
                if self.collector._states.get("collector") == "failed":
                    self.collector.transition("collector", "ready", "Collecteur rétabli", True)
                await self.publish(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("Collecte indisponible : %s", type(exc).__name__)
                self.collector.transition("collector", "failed", "Collecteur indisponible · nouvel essai automatique", False)
                if self.latest is not None:
                    snapshot = dict(self.latest)
                    snapshot["timestamp"] = collector.utc_now()
                    snapshot["global_status"] = "incident"
                    snapshot["collector"] = {"last_success": self.latest["collector"]["last_success"], "error": "Collecte indisponible"}
                    await self.publish(snapshot)
            await asyncio.sleep(max(0.05, self.settings.interval - (time.monotonic() - started)))


class CountedEventSourceResponse(EventSourceResponse):
    """Libère la place même si le client part avant le premier événement."""

    def __init__(self, *args, runtime: Runtime, **kwargs):
        self.runtime = runtime
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.runtime.active_streams = max(0, self.runtime.active_streams - 1)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = Runtime(settings)
        application.state.runtime = runtime
        await runtime.collector.start()
        await runtime.sentinel.start()
        await runtime.whatsapp.start()
        task = asyncio.create_task(runtime.collect_loop(), name="noc-collector")
        runtime.collect_task = task
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await runtime.collector.close()
            await runtime.whatsapp.close()
            await runtime.sentinel.close()

    application = FastAPI(title="NOC · Tour de contrôle", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @application.get("/")
    async def dashboard():
        return FileResponse(BASE_DIR / "static" / "index.html", media_type="text/html")

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @application.get("/api/health")
    async def health():
        runtime: Runtime = application.state.runtime
        latest = runtime.latest
        last_success = latest["collector"].get("last_success") if latest else None
        collecting = bool(last_success and not latest["collector"].get("error") and time.monotonic() - runtime.last_published <= max(10, 3 * settings.interval) and runtime.collect_task and not runtime.collect_task.done())
        return JSONResponse({"status": "ok" if collecting else "starting" if latest is None else "degraded", "collector_ready": collecting, "interval_seconds": settings.interval, "process_id": os.getpid()}, status_code=200 if collecting else 503)

    @application.get("/api/snapshot")
    async def snapshot():
        runtime: Runtime = application.state.runtime
        if runtime.latest is None:
            raise HTTPException(503, "Première collecte en cours", headers={"Retry-After": "2"})
        return Response(content=runtime.serialized, media_type="application/json")

    @application.get("/api/stream")
    async def stream(request: Request):
        runtime: Runtime = application.state.runtime
        if runtime.active_streams >= settings.max_streams:
            raise HTTPException(429, "Limite de flux simultanés atteinte", headers={"Retry-After": "5"})
        runtime.active_streams += 1

        async def events():
            revision = -1
            while True:
                if await request.is_disconnected():
                    break
                async with runtime.changed:
                    if runtime.revision == revision or runtime.latest is None:
                        try:
                            await asyncio.wait_for(runtime.changed.wait(), timeout=15)
                        except asyncio.TimeoutError:
                            continue
                    revision = runtime.revision
                    data = runtime.serialized
                yield {"event": "snapshot", "id": str(revision), "retry": 2000, "data": data}

        return CountedEventSourceResponse(events(), runtime=runtime, ping=15, send_timeout=10, headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-store"})

    @application.post("/api/vps/report")
    async def vps_report(request: Request):
        if not settings.vps_token:
            raise HTTPException(503, "Rapports VPS désactivés : jeton non configuré")
        if not token_matches(request.headers.get("x-vps-token"), settings.vps_token):
            raise HTTPException(401, "Jeton VPS incorrect")
        report: VPSReport = validate_payload(VPSReport, await limited_json(request, 32768))
        runtime: Runtime = application.state.runtime
        runtime.vps_snapshot()
        if report.hostname not in runtime.vps and len(runtime.vps) >= settings.max_vps:
            raise HTTPException(429, "Limite de serveurs VPS atteinte")
        runtime.vps[report.hostname] = {"report": report.model_dump(), "seen": time.monotonic(), "last_seen": collector.utc_now(), "stale": False}
        return {"ok": True, "hostname": report.hostname}

    @application.post("/api/service/{name}/restart")
    async def restart(name: str, request: Request):
        same_origin(request)
        if name not in RESTART_ALLOWLIST:
            raise HTTPException(404, "Service non autorisé")
        if not settings.admin_token:
            raise HTTPException(503, "Redémarrages désactivés : jeton non configuré")
        if not token_matches(request.headers.get("x-admin-token"), settings.admin_token):
            raise HTTPException(401, "Jeton administrateur incorrect")
        runtime: Runtime = application.state.runtime
        return await runtime.restart_service(name)

    @application.post("/api/whatsapp/webhook")
    async def whatsapp_webhook(request: Request):
        if not settings.admin_phone_number or not settings.whatsapp_webhook_token:
            raise HTTPException(503, "Commandes WhatsApp non configurées")
        if not token_matches(request.headers.get("x-gateway-secret"), settings.whatsapp_webhook_token):
            raise HTTPException(403, "Requête non autorisée")
        payload = await limited_json(request, 32768)
        if not isinstance(payload, dict):
            raise HTTPException(422, "Message WhatsApp invalide")
        try:
            return await application.state.runtime.whatsapp.accept(payload)
        except PermissionError:
            raise HTTPException(403, "Émetteur non autorisé") from None
        except ValueError:
            raise HTTPException(422, "Message WhatsApp invalide") from None
        except asyncio.QueueFull:
            raise HTTPException(429, "File de commandes pleine", headers={"Retry-After": "5"}) from None

    @application.post("/api/sentinel/incident")
    async def sentinel_incident(request: Request):
        if not settings.vps_token:
            raise HTTPException(503, "Sentinel désactivé : jeton VPS non configuré")
        if not token_matches(request.headers.get("x-vps-token"), settings.vps_token):
            raise HTTPException(401, "Jeton VPS incorrect")
        return await application.state.runtime.sentinel.accept(await limited_json(request, 16384))

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1, loop="asyncio", http="h11", ws="none", access_log=False, forwarded_allow_ips="127.0.0.1")

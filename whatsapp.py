"""Commandes WhatsApp bornées, liste blanche et transcription hors du processus NOC.

Le routeur vérifie le secret du webhook AVANT d'appeler ce module. Le numéro seul
ne prouve pas l'origine d'un webhook. Aucun texte reçu n'est passé à un shell.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlsplit

import httpx
from starlette.exceptions import HTTPException

from collector import utc_now
from config import RESTART_ALLOWLIST, Settings


def normalize_phone(value: Any) -> str:
    """Accepter un numéro personnel international; jamais un groupe ou un LID."""
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Numéro WhatsApp invalide")
    phone = value.strip()
    if "@" in phone:
        phone, domain = phone.rsplit("@", 1)
        if domain not in {"c.us", "s.whatsapp.net"}:
            raise ValueError("Seuls les messages personnels sont autorisés")
    if not re.fullmatch(r"\+?[0-9 ()-]+", phone):
        raise ValueError("Numéro WhatsApp invalide")
    phone = re.sub(r"[^0-9]", "", phone)
    if not 8 <= len(phone) <= 15:
        raise ValueError("Utiliser un numéro international de 8 à 15 chiffres")
    return phone


def validate_media_url(value: Any) -> str:
    """Aucun téléchargement vers un hôte tiers ni redirection (SSRF)."""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("URL audio invalide")
    try:
        url = urlsplit(value)
        allowed = (url.scheme == "http" and url.hostname == "127.0.0.1"
                   and url.port == 3001 and not url.username and not url.password
                   and not url.fragment)
    except ValueError:
        allowed = False
    if not allowed:
        raise ValueError("Audio autorisé uniquement depuis la passerelle locale")
    decoded = unquote(url.path)
    if (not decoded.startswith(("/media/", "/uploads/"))
            or any(part in {"..", "."} for part in decoded.split("/"))
            or "\\" in decoded or "%" in decoded or any(ord(char) < 32 for char in decoded)):
        raise ValueError("Chemin de média interdit")
    return value


def parse_message(payload: dict[str, Any], admin_phone_number: str) -> dict[str, Any] | None:
    """Normaliser le format documenté et les enveloppes usuelles des passerelles.

    Format stable: {id, from, text} ou {id, from, audio:{path|url,mimetype}}.
    Enveloppe acceptée: {event:'message',data:{id,from,body,type,media}}.
    Une passerelle Baileys doit fournir un média déjà déchiffré via path/url.
    """
    if not isinstance(payload, dict):
        raise ValueError("Objet JSON attendu")
    if "event" in payload and payload["event"] not in {"message", "message.received", "messages.upsert"}:
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("Message WhatsApp invalide")
    key = data.get("key", {})
    if not isinstance(key, dict):
        key = {}
    if any(name in item and not isinstance(item[name], bool)
           for item in (data, key) for name in ("fromMe",)):
        raise ValueError("fromMe doit être un booléen")
    if data.get("fromMe") is True or key.get("fromMe") is True:
        return None  # Éviter les boucles avec nos propres réponses.
    sender = data.get("from", key.get("remoteJid"))
    try:
        phone = normalize_phone(sender)
        admin = normalize_phone(admin_phone_number)
    except ValueError as exc:
        raise PermissionError("Émetteur non autorisé") from exc
    if phone != admin:
        raise PermissionError("Émetteur non autorisé")
    message_id = data.get("id", key.get("id"))
    if isinstance(message_id, dict):
        message_id = message_id.get("id", message_id.get("_serialized"))
    if not isinstance(message_id, str) or not re.fullmatch(r"[\w.:@+-]{1,128}", message_id):
        raise ValueError("Identifiant de message obligatoire (128 caractères maximum)")
    message = data.get("message", {})
    if not isinstance(message, dict):
        message = {}
    extended = message.get("extendedTextMessage", {})
    if not isinstance(extended, dict):
        extended = {}
    text = data.get("text", data.get("body", message.get("conversation", extended.get("text", ""))))
    if not isinstance(text, str) or len(text) > 1000:
        raise ValueError("Texte limité à 1000 caractères")
    audio = data.get("audio")
    if audio is None and data.get("messageType") == "audioMessage":
        audio = {"url": data.get("audioUrl"), "path": data.get("audioPath"),
                 "mimetype": data.get("mimetype", "audio/ogg")}
    if audio is None and (data.get("type") in {"ptt", "audio"} or "audioMessage" in message):
        audio = data.get("media", message.get("audioMessage"))
    if audio is not None:
        if not isinstance(audio, dict):
            raise ValueError("Média audio invalide")
        mimetype = audio.get("mimetype", data.get("mimetype", "audio/ogg"))
        if not isinstance(mimetype, str) or mimetype.split(";", 1)[0].strip().lower() not in {"audio/ogg", "audio/opus", "application/ogg"}:
            raise ValueError("Seules les notes vocales OGG/Opus sont autorisées")
        path, url = audio.get("path"), audio.get("url")
        if bool(path) == bool(url):
            raise ValueError("Fournir un seul chemin ou une seule URL audio déchiffrée")
        if path and (not isinstance(path, str) or len(path) > 2048):
            raise ValueError("Chemin audio invalide")
        if url:
            validate_media_url(url)
        audio = {"path": path, "url": url, "mimetype": mimetype}
    elif not text.strip():
        raise ValueError("Texte ou note vocale obligatoire")
    return {"id": message_id, "text": text.strip(), "audio": audio,
            "source": "voice" if audio else "text"}


def parse_intent(text: str) -> tuple[str, str | None]:
    """Grammaire volontairement exacte: les négations et phrases ambiguës refusent."""
    normalized = "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                         if not unicodedata.combining(char))
    normalized = " ".join(normalized.strip().rstrip(".!?").split())
    # Homophone observé avec tiny en français : lecture seule, jamais une action.
    if normalized in {"statut", "etat", "statut des services", "etat des services",
                      "statue", "statue des services", "statuts", "statuts des services"}:
        return "status", None
    match = re.fullmatch(r"redemarre ([a-z0-9-]+)", normalized)
    if match and match[1] in RESTART_ALLOWLIST:
        return "restart", match[1]
    if normalized == "sauvegarde babamarket":
        return "backup", "babamarket"
    return "unknown", None


async def run_process(arguments: list[str], timeout: float, capture: bool = False) -> tuple[int, bytes]:
    """Sortie limitée, sans shell; tuer aussi les descendants lors d'un timeout."""
    process = await asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name == "posix",
    )
    try:
        async with asyncio.timeout(timeout):
            output = bytearray()
            if capture:
                assert process.stdout is not None
                while chunk := await process.stdout.read(1024):
                    if len(output) + len(chunk) > 8192:
                        raise ValueError("Sortie du transcripteur trop volumineuse")
                    output.extend(chunk)
            code = await process.wait()
            return code, bytes(output)
    except BaseException:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), 2)
        raise


class WhatsAppController:
    def __init__(self, settings: Settings, runtime: Any,
                 restart: Callable[[str], Awaitable[dict[str, Any]]]):
        self.settings, self.runtime, self.restart = settings, runtime, restart
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=4)
        self.client: httpx.AsyncClient | None = None
        self.remote_client: httpx.AsyncClient | None = None
        self.worker: asyncio.Task[None] | None = None
        self.last_command: dict[str, Any] | None = None
        self.busy = False
        self._seen: OrderedDict[str, float] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.admin_phone_number and self.settings.whatsapp_webhook_token)

    async def start(self) -> None:
        if not self.enabled:
            return
        normalize_phone(self.settings.admin_phone_number)
        send = urlsplit(self.settings.whatsapp_send_url)
        if (send.scheme != "http" or send.hostname not in {"127.0.0.1", "::1"}
                or send.port != 3001 or send.username or send.password or send.fragment):
            raise ValueError("API WhatsApp d'envoi limitée à la passerelle locale:3001")
        self.client = httpx.AsyncClient(
            timeout=3, trust_env=False, verify=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        )
        if self.settings.voice_remote_url:
            remote = urlsplit(self.settings.voice_remote_url)
            try:
                tailscale = ipaddress.ip_address(remote.hostname or "") in ipaddress.ip_network("100.64.0.0/10")
            except ValueError:
                tailscale = False
            if (remote.scheme not in {"https", "http"} or (remote.scheme == "http" and not tailscale)
                    or remote.username or remote.password or remote.fragment
                    or not self.settings.voice_remote_token):
                raise ValueError("Transcription distante: HTTPS ou IP Tailscale, jeton obligatoire")
            self.remote_client = httpx.AsyncClient(
                timeout=self.settings.whisper_timeout, trust_env=False, follow_redirects=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            )
        self.worker = asyncio.create_task(self._worker(), name="noc-whatsapp")

    async def close(self) -> None:
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker
            self.worker = None
        for client in (self.client, self.remote_client):
            if client:
                await client.aclose()
        self.client = self.remote_client = None

    def snapshot(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "busy": self.busy, "queued": self.queue.qsize(),
                "last_command": dict(self.last_command) if self.last_command else None}

    async def accept(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Commandes WhatsApp non configurées")
        if ("sessionId" in payload
                and str(payload["sessionId"]) != self.settings.whatsapp_session_id):
            raise PermissionError("Session WhatsApp non autorisée")
        message = parse_message(payload, self.settings.admin_phone_number)
        if message is None:
            return {"accepted": False, "ignored": True}
        now = time.monotonic()
        while self._seen and now - next(iter(self._seen.values())) > 86400:
            self._seen.popitem(last=False)
        if message["id"] in self._seen:
            return {"accepted": True, "duplicate": True}
        # QueueFull laisse l'identifiant réessayable; aucun effet si non accepté.
        self.queue.put_nowait(message)
        self._seen[message["id"]] = now
        if len(self._seen) > 256:
            self._seen.popitem(last=False)
        return {"accepted": True, "duplicate": False}

    async def _publish(self) -> None:
        await self.runtime.publish_module_update()

    async def _worker(self) -> None:
        while True:
            message = await self.queue.get()
            self.busy = True
            self.last_command = {
                "id": message["id"], "timestamp": utc_now(), "source": message["source"],
                "transcription": message["text"][:1000], "action": "pending", "service": None,
                "status": "processing", "response": "", "reply_sent": False,
            }
            try:
                try:
                    await self._publish()
                    text = await self._transcribe(message["audio"]) if message["audio"] else message["text"]
                    action, service = parse_intent(text)
                    self.last_command.update(transcription=text[:1000], action=action, service=service)
                    await self._publish()
                    response, success = await self._execute(action, service)
                    self.last_command.update(response=response[:1000], status="completed" if success else "failed", timestamp=utc_now())
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Les chemins, les secrets et les erreurs HTTP brutes ne sont pas publiés.
                    response = "Commande impossible : " + (
                        str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    )[:180]
                    self.last_command.update(response=response, status="failed", timestamp=utc_now())
                # Publier le résultat avant d'attendre la réponse de la passerelle.
                await self._publish()
                self.last_command["reply_sent"] = await self._send_reply(self.last_command["response"])
                level = "info" if self.last_command["status"] == "completed" and self.last_command["reply_sent"] else "warning"
                delivery = "" if self.last_command["reply_sent"] else " · réponse non livrée"
                self.runtime.collector.add_event(level, f"WhatsApp · {self.last_command['action']} · {self.last_command['status']}{delivery}")
                self.busy = False
                await self._publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.busy = False
            finally:
                self.busy = False
                self.queue.task_done()

    async def _execute(self, action: str, service: str | None) -> tuple[str, bool]:
        if action == "status":
            latest = self.runtime.latest or {}
            lines = ["🛰 État de l'infrastructure"]
            for item in latest.get("services", []):
                lines.append(f"{'🟢' if item.get('healthy') else '🔴'} {item.get('label', item.get('name', '?'))} ({item.get('port', '?')})")
            gateway = latest.get("infrastructure", {}).get("whatsapp", {})
            lines.append(f"{'🟢' if gateway.get('healthy') else '🔴'} WhatsApp (3001)")
            hardware = latest.get("hardware", {})
            cpu, memory = hardware.get("cpu", {}), hardware.get("memory", {})
            cpu_value = cpu.get("percent")
            used, total = memory.get("used"), memory.get("total")
            lines.append(f"CPU Dell : {cpu_value:g} %" if isinstance(cpu_value, (int, float)) else "CPU Dell : indisponible")
            lines.append(f"RAM Dell : {used / 2**30:.1f}/{total / 2**30:.1f} Gio" if isinstance(used, (int, float)) and isinstance(total, (int, float)) else "RAM Dell : indisponible")
            lines.append("Relevé : " + str(latest.get("timestamp", "en attente")))
            return "\n".join(lines), True
        if action == "restart" and service in RESTART_ALLOWLIST:
            try:
                result = await self.restart(service)
            except HTTPException as exc:
                return f"❌ {service} : {str(exc.detail)[:180]}", False
            success = result.get("ok") is True
            return (f"✅ {service} : redémarrage demandé." if success else f"❌ {service} : redémarrage refusé ou en échec."), success
        if action == "backup":
            return await self._backup()
        return ("Commande non reconnue. Envoyez : statut ; redémarre klasora (ou merca-market, babamarket, moc-mal) ; sauvegarde babamarket.", False)

    async def _backup(self) -> tuple[str, bool]:
        configured = self.settings.backup_script
        if not configured:
            return "Sauvegarde non configurée : renseignez NOC_BACKUP_SCRIPT.", False
        script = Path(configured)
        if not script.is_absolute() or not script.is_file() or script.is_symlink():
            return "Script de sauvegarde absent ou interdit.", False
        resolved = script.resolve()
        if resolved != script:
            return "Liens symboliques interdits pour le script de sauvegarde.", False
        attributes = script.stat()
        if os.name != "posix" or attributes.st_uid != 0 or attributes.st_mode & 0o022 or not os.access(script, os.X_OK):
            return "Le script doit être exécutable, appartenir à root et ne pas être modifiable par le groupe ou les autres utilisateurs.", False
        for parent in script.parents:
            parent_attributes = parent.stat()
            if parent_attributes.st_uid != 0 or parent_attributes.st_mode & 0o022:
                return "Les répertoires du script doivent appartenir à root et ne pas être modifiables par le groupe ou les autres utilisateurs.", False
        arguments = [str(resolved)]
        # Une seule commande root exacte autorisée par l'installateur; les chemins
        # personnalisés s'exécutent uniquement avec les droits de noc-dashboard.
        if configured == "/usr/local/bin/backup-babamarket.sh":
            sudo = shutil.which("sudo")
            if not sudo:
                return "Sauvegarde indisponible : sudo absent sur cet hôte.", False
            arguments = [sudo, "-n", configured]
        code, _ = await run_process(arguments, self.settings.backup_timeout)
        return ("✅ Sauvegarde BabaMarket terminée." if code == 0 else "❌ Échec du script de sauvegarde BabaMarket."), code == 0

    async def _send_reply(self, response: str) -> bool:
        if self.client is None:
            return False
        payload = {
            "sessionId": self.settings.whatsapp_session_id,
            self.settings.whatsapp_send_to_field: normalize_phone(self.settings.admin_phone_number) + "@s.whatsapp.net",
            self.settings.whatsapp_send_text_field: response[:1000],
        }
        try:
            async with asyncio.timeout(3):
                async with self.client.stream("POST", self.settings.whatsapp_send_url, json=payload,
                                              headers={"x-gateway-secret": self.settings.gateway_secret}) as reply:
                    return reply.is_success
        except (httpx.HTTPError, TimeoutError):
            return False

    def _copy_local_audio(self, source: str, destination: Path) -> None:
        root = Path(self.settings.whatsapp_media_dir).resolve()
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Audio hors du répertoire de médias autorisé") from exc
        if candidate.resolve() != candidate or not candidate.resolve().is_relative_to(root):
            raise ValueError("Liens symboliques ou traversée de répertoire interdits")
        for parent in (candidate, *candidate.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("Lien symbolique audio interdit")
        if candidate.suffix.lower() not in {".ogg", ".opus"}:
            raise ValueError("Extension de note vocale OGG/Opus requise")
        try:
            descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise ValueError("Note vocale locale inaccessible") from exc
        with os.fdopen(descriptor, "rb") as incoming:
            attributes = os.fstat(incoming.fileno())
            if not stat.S_ISREG(attributes.st_mode) or not 0 < attributes.st_size <= self.settings.whatsapp_max_audio_bytes:
                raise ValueError("Note vocale vide ou trop volumineuse")
            with destination.open("wb") as outgoing:
                count = 0
                while chunk := incoming.read(16384):
                    count += len(chunk)
                    if count > self.settings.whatsapp_max_audio_bytes:
                        raise ValueError("Note vocale trop volumineuse")
                    outgoing.write(chunk)

    async def _download_audio(self, url: str, destination: Path) -> None:
        validate_media_url(url)
        if self.client is None:
            raise RuntimeError("Passerelle audio indisponible")
        async with asyncio.timeout(10):
            async with self.client.stream("GET", url, headers={"x-gateway-secret": self.settings.gateway_secret,
                                                                 "accept-encoding": "identity"}) as response:
                if not response.is_success:
                    raise ValueError("Note vocale locale inaccessible")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Compression HTTP audio interdite")
                count = 0
                with destination.open("wb") as outgoing:
                    async for chunk in response.aiter_raw(16384):
                        count += len(chunk)
                        if count > self.settings.whatsapp_max_audio_bytes:
                            raise ValueError("Note vocale trop volumineuse")
                        outgoing.write(chunk)
                if count == 0:
                    raise ValueError("Note vocale vide")

    async def _transcribe(self, audio: dict[str, Any]) -> str:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("ffmpeg doit être installé pour les commandes vocales")
        temporary_root = "/tmp" if os.name == "posix" else None
        with tempfile.TemporaryDirectory(prefix="noc-voice-", dir=temporary_root) as temporary:
            directory = Path(temporary)
            incoming, wav = directory / "message.ogg", directory / "message.wav"
            if audio.get("path"):
                await asyncio.to_thread(self._copy_local_audio, audio["path"], incoming)
            else:
                await self._download_audio(audio["url"], incoming)
            incoming.chmod(0o600)
            code, _ = await run_process([
                ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-threads", "1", "-i", str(incoming), "-vn", "-sn", "-dn", "-t", str(self.settings.whatsapp_audio_seconds),
                "-ac", "1", "-ar", "16000", "-f", "wav", str(wav),
            ], 20)
            if code or not wav.is_file():
                raise ValueError("Conversion audio impossible")
            wav.chmod(0o600)
            if self.remote_client is not None:
                with wav.open("rb") as file:
                    async with asyncio.timeout(self.settings.whisper_timeout):
                        async with self.remote_client.stream(
                            "POST", self.settings.voice_remote_url,
                            headers={"Authorization": "Bearer " + self.settings.voice_remote_token,
                                     "accept-encoding": "identity"},
                            files={"file": ("message.wav", file, "audio/wav")},
                        ) as response:
                            if not response.is_success:
                                raise ValueError("Transcription distante indisponible")
                            if response.headers.get("content-encoding", "identity").lower() != "identity":
                                raise ValueError("Compression HTTP transcription interdite")
                            output = bytearray()
                            async for chunk in response.aiter_raw(1024):
                                if len(output) + len(chunk) > 8192:
                                    raise ValueError("Transcription trop volumineuse")
                                output.extend(chunk)
            else:
                model = Path(self.settings.whisper_model_path)
                if not model.is_dir() or not (model / "model.bin").is_file():
                    raise ValueError("Modèle faster-whisper tiny local non installé")
                code, output = await run_process([
                    self.settings.whisper_python if Path(self.settings.whisper_python).is_file() else sys.executable,
                    str(Path(__file__).with_name("voice_transcribe.py")),
                    "--model", str(model), "--audio", str(wav),
                ], self.settings.whisper_timeout, capture=True)
                if code:
                    raise ValueError("Transcription locale impossible (voir installation faster-whisper)")
            decoded = json.loads(output)
            text = decoded.get("text") if isinstance(decoded, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                raise ValueError("Transcription vide ou trop longue")
            return text.strip()

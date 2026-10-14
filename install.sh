#!/usr/bin/env bash
# Installation limitée au NOC. Aucun service applicatif existant n'est modifié.
set -Eeuo pipefail
umask 027

readonly APP_DIR=/opt/noc-dashboard
APP_USER=noc-dashboard
APP_GROUP=noc-dashboard
readonly ENV_FILE=/etc/noc-dashboard.env
readonly UNIT_FILE=/etc/systemd/system/noc-dashboard.service
readonly SUDOERS_FILE=/etc/sudoers.d/noc-dashboard
readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BACKUP_DIR=""
STAGED_SUDOERS=""
STAGED_UNIT=""

fail() { printf 'Erreur : %s\n' "$*" >&2; exit 1; }
cleanup() {
    if [[ -n "$STAGED_SUDOERS" && -f "$STAGED_SUDOERS" ]]; then
        rm -f -- "$STAGED_SUDOERS"
    fi
    if [[ -n "$STAGED_UNIT" && -f "$STAGED_UNIT" ]]; then
        rm -f -- "$STAGED_UNIT"
    fi
}
trap cleanup EXIT
trap 'printf "Installation interrompue à la ligne %s. Consultez le message précédent.\n" "$LINENO" >&2' ERR

[[ "$(uname -s)" == Linux ]] || fail "ce script nécessite Ubuntu/Linux."
[[ "$EUID" -eq 0 ]] || fail "lancez sudo bash install.sh."
[[ -d /run/systemd/system ]] || fail "systemd doit être le gestionnaire de services de cette machine."
for command in python3.11 systemctl systemd-analyze sudo visudo useradd groupadd getent install realpath cmp find; do
    command -v "$command" >/dev/null || fail "commande requise absente : $command."
done
[[ -x /usr/bin/systemctl ]] || fail "/usr/bin/systemctl est requis par la règle sudoers."
python3.11 -c 'import sys, venv; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' \
    || fail "Python 3.11 avec le module venv est requis."

# Respecter le compte d'une installation existante avant toute modification.
EXISTING_UNIT=false
UNIT_LOAD_STATE="$(systemctl show noc-dashboard.service --property=LoadState --value)" \
    || fail "impossible de lire l'unité NOC existante."
if [[ -n "$UNIT_LOAD_STATE" && "$UNIT_LOAD_STATE" != not-found ]]; then
    EXISTING_UNIT=true
    APP_USER="$(systemctl show noc-dashboard.service --property=User --value)" \
        || fail "impossible de lire le compte du NOC."
    APP_GROUP="$(systemctl show noc-dashboard.service --property=Group --value)" \
        || fail "impossible de lire le groupe du NOC."
    [[ -n "$APP_USER" && "$APP_USER" != root ]] \
        || fail "l'unité NOC existante utilise root ; aucune migration implicite de compte n'est autorisée."
    [[ "$APP_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}\$?$ ]] \
        || fail "nom de compte NOC existant non pris en charge."
    getent passwd "$APP_USER" >/dev/null || fail "le compte NOC existant est absent."
    [[ "$(id -u "$APP_USER")" -ne 0 ]] || fail "le compte NOC existant ne peut pas avoir uid 0."
    if [[ -z "$APP_GROUP" ]]; then APP_GROUP="$(id -gn "$APP_USER")"; fi
    [[ "$APP_GROUP" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}\$?$ ]] \
        || fail "nom de groupe NOC existant non pris en charge."
    getent group "$APP_GROUP" >/dev/null || fail "le groupe NOC existant est absent."
fi
readonly APP_USER APP_GROUP

PROJECT_FILES=(requirements.txt requirements-voice.txt requirements-sentinel.txt config.py collector.py main.py sentinel.py sentinel_crypto.py whatsapp.py voice_transcribe.py vps_agent.py vps_sentinel.py install.sh install-voice.sh backup-babamarket.sh noc-dashboard.service vps-agent.service sentinel-vps.service integrations/baileys-noc.cjs integrations/baileys-send-alias.cjs tools/repair_whatsapp_contract.py tools/deploy_dashboard_update.py README.md MODULES.md .gitignore)
for relative in "${PROJECT_FILES[@]}" static/index.html; do
    [[ -f "$SOURCE_DIR/$relative" && ! -L "$SOURCE_DIR/$relative" ]] || fail "fichier source manquant ou lien symbolique : $relative."
done
[[ -d "$SOURCE_DIR/static" && ! -L "$SOURCE_DIR/static" ]] || fail "répertoire static invalide."
python3.11 - "$SOURCE_DIR" <<'PY'
import ast
import pathlib
import sys
directory = pathlib.Path(sys.argv[1])
for name in ("config.py", "collector.py", "main.py", "vps_agent.py", "whatsapp.py", "voice_transcribe.py", "sentinel.py", "sentinel_crypto.py", "vps_sentinel.py"):
    ast.parse((directory / name).read_text(encoding="utf-8"), filename=name)
PY

assert_destination() {
    local target="$1"
    [[ ! -L "$target" && "$(realpath -m -- "$target")" == "$target" ]] \
        || fail "destination contenant un lien symbolique, modification refusée : $target."
}

assert_destination "$APP_DIR"
assert_destination "$ENV_FILE"
assert_destination "$UNIT_FILE"
assert_destination "$SUDOERS_FILE"
[[ ! -e "$ENV_FILE" || -f "$ENV_FILE" ]] || fail "la configuration existante doit être un fichier ordinaire."
if [[ "$EXISTING_UNIT" == false ]]; then
    if ! getent group "$APP_GROUP" >/dev/null; then groupadd --system "$APP_GROUP"; fi
    if ! id "$APP_USER" >/dev/null 2>&1; then
        useradd --system --gid "$APP_GROUP" --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    fi
fi
[[ "$(id -u "$APP_USER")" -ne 0 ]] || fail "le compte NOC ne peut pas être root."
install -d -o root -g "$APP_GROUP" -m 0750 "$APP_DIR"

backup_if_changed() {
    local source="$1" destination="$2" backup_target
    if [[ -f "$destination" ]] && ! cmp -s -- "$source" "$destination"; then
        if [[ -z "$BACKUP_DIR" ]]; then
            assert_destination /var/backups/noc-dashboard
            install -d -o root -g root -m 0700 /var/backups/noc-dashboard
            BACKUP_DIR="$(mktemp -d /var/backups/noc-dashboard/update-XXXXXXXX)"
            chmod 0700 "$BACKUP_DIR"
        fi
        backup_target="$BACKUP_DIR$destination"
        install -d -o root -g root -m 0700 "$(dirname -- "$backup_target")"
        cp -p -- "$destination" "$backup_target"
    fi
}

copy_project_file() {
    local relative="$1" source="$SOURCE_DIR/$1" destination="$APP_DIR/$1" mode=0640
    assert_destination "$destination"
    install -d -o root -g "$APP_GROUP" -m 0750 "$(dirname -- "$destination")"
    if [[ "$relative" == *.sh || "$relative" == vps_agent.py || "$relative" == vps_sentinel.py ]]; then mode=0750; fi
    if [[ "$source" != "$destination" ]]; then
        backup_if_changed "$source" "$destination"
        if ! [[ -f "$destination" ]] || ! cmp -s -- "$source" "$destination"; then
            install -o root -g "$APP_GROUP" -m "$mode" "$source" "$destination"
        fi
    fi
    chown root:"$APP_GROUP" "$destination"
    chmod "$mode" "$destination"
}

# Le fichier existant reste intact : aucune rotation implicite des secrets.
if [[ ! -e "$ENV_FILE" ]]; then
    install -o root -g "$APP_GROUP" -m 0640 /dev/null "$ENV_FILE"
    {
        printf '%s\n' '# Configuration NOC, lisible seulement par root et le groupe du service.'
        printf '%s\n' 'NOC_HOST=127.0.0.1' 'NOC_PORT=5050' 'NOC_INTERVAL_SECONDS=2' 'NOC_VPS_STALE_SECONDS=20'
        printf '%s\n' 'NOC_BACKUP_PATH=/mnt/babamarket-backups' 'NOC_ENABLE_RESTART=true'
        printf 'NOC_GATEWAY_SECRET=%s\n' "${NOC_GATEWAY_SECRET:-secret-gateway-local-klasora-2024}"
        printf 'NOC_VPS_TOKEN=%s\n' "$(python3.11 -c 'import secrets; print(secrets.token_hex(32))')"
    } > "$ENV_FILE"
fi
chown root:"$APP_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

# Ajouter uniquement les nouvelles clés ; ne jamais remplacer un secret existant.
python3.11 - "$ENV_FILE" <<'PY'
import pathlib
import secrets
import sys
path = pathlib.Path(sys.argv[1])
original = path.read_text(encoding="utf-8")
keys = {line.split("=", 1)[0].strip() for line in original.splitlines() if "=" in line and not line.lstrip().startswith("#")}
defaults = {
    "ADMIN_PHONE_NUMBER": "212770010264",
    "NOC_WHATSAPP_WEBHOOK_TOKEN": secrets.token_hex(32),
    "NOC_BACKUP_SCRIPT": "/usr/local/bin/backup-babamarket.sh",
    "NOC_WHISPER_PYTHON": "/opt/noc-dashboard/voice-venv/bin/python",
    "NOC_WHISPER_MODEL_PATH": "/opt/noc-dashboard/models/whisper",
    "NOC_WHISPER_MODEL": "tiny",
    "NOC_VOICE_ENABLED": "true",
    "NOC_SENTINEL_STATE_PATH": "/var/lib/noc-dashboard/sentinel-counters.json",
}
missing = [f"{key}={value}" for key, value in defaults.items() if key not in keys]
if missing:
    with path.open("a", encoding="utf-8") as handle:
        if original and not original.endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(missing) + "\n")
PY

assert_destination "$APP_DIR/venv"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    python3.11 -m venv "$APP_DIR/venv" \
        || fail "création du venv impossible ; vérifiez le paquet python3.11-venv."
fi
"$APP_DIR/venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)' \
    || fail "le venv existant doit utiliser Python 3.11 ; il a été conservé."
"$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$SOURCE_DIR/requirements.txt"
chown -hR root:"$APP_GROUP" "$APP_DIR/venv"
chmod -R go-w "$APP_DIR/venv"
"$APP_DIR/venv/bin/python" -c 'import fastapi, uvicorn, psutil, httpx, sse_starlette, cryptography'

# Remplace le code uniquement une fois les dépendances utilisables.
for relative in "${PROJECT_FILES[@]}"; do copy_project_file "$relative"; done
while IFS= read -r -d '' source; do
    copy_project_file "${source#"$SOURCE_DIR/"}"
done < <(find "$SOURCE_DIR/static" -type f -print0)

# Le script d'un projet déjà installé reste intact.
assert_destination /usr/local/bin/backup-babamarket.sh
if [[ ! -e /usr/local/bin/backup-babamarket.sh ]]; then
    install -o root -g root -m 0755 "$APP_DIR/backup-babamarket.sh" /usr/local/bin/backup-babamarket.sh
fi

# Aucune étoile : ces quatre commandes exactes sont les seuls redémarrages autorisés.
STAGED_SUDOERS="$(mktemp /etc/sudoers.d/.noc-dashboard-XXXXXX)"
{
    printf 'Defaults:%s timestamp_timeout=0\n' "$APP_USER"
    printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block restart merca-market.service, /usr/bin/systemctl --no-block restart klasora.service, /usr/bin/systemctl --no-block restart babamarket.service, /usr/bin/systemctl --no-block restart moc-mal.service, /usr/local/bin/backup-babamarket.sh\n' "$APP_USER"
} > "$STAGED_SUDOERS"
chmod 0440 "$STAGED_SUDOERS"
visudo -cf "$STAGED_SUDOERS"
backup_if_changed "$STAGED_SUDOERS" "$SUDOERS_FILE"
chown root:root "$STAGED_SUDOERS"
mv -f -- "$STAGED_SUDOERS" "$SUDOERS_FILE"
STAGED_SUDOERS=""

STAGED_UNIT="$(mktemp /tmp/noc-dashboard-stage-XXXXXXXX.service)"
python3.11 - "$APP_DIR/noc-dashboard.service" "$STAGED_UNIT" "$APP_USER" "$APP_GROUP" <<'PY'
import pathlib
import re
import sys
source, target, user, group = sys.argv[1:]
text = pathlib.Path(source).read_text(encoding="utf-8")
for key, value in (("User", user), ("Group", group)):
    pattern = rf"^{key}=.*$"
    if len(re.findall(pattern, text, flags=re.MULTILINE)) != 1:
        raise SystemExit(f"Unité NOC invalide : {key} doit apparaître une seule fois")
    text = re.sub(pattern, lambda _match: f"{key}={value}", text, flags=re.MULTILINE)
pathlib.Path(target).write_text(text, encoding="utf-8")
PY
systemd-analyze verify "$STAGED_UNIT"
backup_if_changed "$STAGED_UNIT" "$UNIT_FILE"
install -o root -g root -m 0644 "$STAGED_UNIT" "$UNIT_FILE"
systemctl daemon-reload
if systemctl is-active --quiet noc-dashboard.service; then
    systemctl enable noc-dashboard.service
    systemctl restart noc-dashboard.service
else
    systemctl enable --now noc-dashboard.service
fi

# Vérifie une vraie réponse HTTP du processus démarré, avec la configuration retenue.
"$APP_DIR/venv/bin/python" - "$ENV_FILE" <<'PY'
import json
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
config = {}
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line.startswith(("NOC_HOST=", "NOC_PORT=")):
            key, value = line.split("=", 1)
            parsed = shlex.split(value)
            config[key] = parsed[0] if parsed else ""
host = config.get("NOC_HOST", "127.0.0.1")
host = "127.0.0.1" if host in {"0.0.0.0", ""} else "::1" if host == "::" else host
host = f"[{host}]" if ":" in host and not host.startswith("[") else host
url = f"http://{host}:{int(config.get('NOC_PORT', '5050'))}/api/health"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(20):
    active = subprocess.run(["systemctl", "is-active", "--quiet", "noc-dashboard.service"], check=False).returncode == 0
    if active:
        try:
            with opener.open(url, timeout=1) as response:
                health = json.loads(response.read(8192))
                pid = subprocess.run(
                    ["systemctl", "show", "--property=MainPID", "--value", "noc-dashboard.service"],
                    capture_output=True, text=True, timeout=1, check=False,
                )
                if response.status == 200 and isinstance(health, dict) and health.get("process_id") == int(pid.stdout.strip()):
                    print(f"Dashboard actif ; /api/health répond sur {url}.")
                    break
        except (OSError, urllib.error.URLError, ValueError, subprocess.TimeoutExpired):
            pass
    time.sleep(1)
else:
    print("Le NOC ne répond pas : consultez sudo journalctl -u noc-dashboard -n 50 --no-pager.", file=sys.stderr)
    raise SystemExit(1)
PY

printf '%s\n' 'Installation terminée. Le service noc-dashboard est actif.' \
    'Configuration et jetons : /etc/noc-dashboard.env (aucun jeton affiché).'
if [[ -n "$BACKUP_DIR" ]]; then printf 'Sauvegarde des fichiers remplacés : %s\n' "$BACKUP_DIR"; fi

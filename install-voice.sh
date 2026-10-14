#!/usr/bin/env bash
# Installer seulement les actifs vocaux, sans changer le service ni son compte.
set -Eeuo pipefail
umask 027
readonly NOC_APP_DIR=/opt/noc-dashboard
readonly NOC_MODELS_DIR="$NOC_APP_DIR/models"
readonly NOC_MODEL_DIR="$NOC_MODELS_DIR/whisper"
readonly NOC_VOICE_PYTHON="$NOC_APP_DIR/voice-venv/bin/python"
NOC_DOWNLOAD_STAGE=""
noc_fail() { printf 'Vocal : %s\n' "$*" >&2; exit 1; }
noc_cleanup() {
    if [[ -n "$NOC_DOWNLOAD_STAGE" && "$NOC_DOWNLOAD_STAGE" == "$NOC_MODELS_DIR/.whisper-download-"* \
          && "$(dirname -- "$NOC_DOWNLOAD_STAGE")" == "$NOC_MODELS_DIR" && ! -L "$NOC_DOWNLOAD_STAGE" ]]; then
        rm -rf -- "$NOC_DOWNLOAD_STAGE"
    fi
}
trap noc_cleanup EXIT
[[ "$(uname -s)" == Linux && "$EUID" -eq 0 ]] || noc_fail 'Lancez sudo bash install-voice.sh sur le Dell Ubuntu.'
for noc_command in python3.11 ffmpeg install getent systemctl runuser; do
    command -v "$noc_command" >/dev/null || noc_fail "Commande requise : $noc_command"
done
[[ -f "$NOC_APP_DIR/requirements-voice.txt" && -f "$NOC_APP_DIR/voice_transcribe.py" ]] \
    || noc_fail 'Installer le projet complet avec install.sh avant le modèle vocal.'
for noc_path in "$NOC_APP_DIR" "$NOC_APP_DIR/voice-venv" "$NOC_MODELS_DIR" "$NOC_MODEL_DIR"; do
    [[ ! -L "$noc_path" ]] || noc_fail "Lien symbolique refusé : $noc_path"
done

NOC_SERVICE_USER="$(systemctl show noc-dashboard.service --property=User --value 2>/dev/null || true)"
if [[ -z "$NOC_SERVICE_USER" ]]; then
    NOC_UNIT_STATE="$(systemctl show noc-dashboard.service --property=LoadState --value 2>/dev/null || true)"
    if [[ "$NOC_UNIT_STATE" == loaded ]]; then NOC_SERVICE_USER=root; else NOC_SERVICE_USER=noc-dashboard; fi
fi
getent passwd "$NOC_SERVICE_USER" >/dev/null || noc_fail "Compte du service absent : $NOC_SERVICE_USER"
NOC_SERVICE_GROUP="$(id -gn "$NOC_SERVICE_USER")"
NOC_MODEL_USER=root
NOC_MODEL_GROUP="$NOC_SERVICE_GROUP"
if getent passwd moctar >/dev/null; then
    getent group moctar >/dev/null || noc_fail 'Le compte moctar existe mais le groupe moctar est absent.'
    NOC_MODEL_USER=moctar
    NOC_MODEL_GROUP=moctar
fi

# Lire uniquement les paramètres vocaux, jamais exécuter ou sourcer le .env root.
NOC_CONFIG_TEXT="$(python3.11 - <<'PY'
import os
import shlex
import stat
from pathlib import Path
keys = {"NOC_WHISPER_MODEL", "NOC_WHISPER_MODEL_PATH", "NOC_VOICE_ENABLED"}
values = {"NOC_WHISPER_MODEL": os.environ.get("NOC_WHISPER_MODEL", "tiny"),
          "NOC_WHISPER_MODEL_PATH": "/opt/noc-dashboard/models/whisper",
          "NOC_VOICE_ENABLED": "true"}
path = Path("/etc/noc-dashboard.env")
if path.exists():
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 65536:
        raise SystemExit("Vocal : configuration root absente, trop volumineuse ou modifiable.")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() not in keys:
            continue
        parts = shlex.split(raw, posix=True)
        if len(parts) > 1:
            raise SystemExit("Vocal : mettre les chemins contenant des espaces entre guillemets.")
        values[key.strip()] = parts[0] if parts else ""
model = values["NOC_WHISPER_MODEL"].strip().lower() or "tiny"
if model not in {"tiny", "base"}:
    raise SystemExit("Vocal : NOC_WHISPER_MODEL doit être tiny ou base.")
model_path = values["NOC_WHISPER_MODEL_PATH"] or "/opt/noc-dashboard/models/whisper"
enabled = values["NOC_VOICE_ENABLED"].strip().lower() or "true"
if enabled not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
    raise SystemExit("Vocal : NOC_VOICE_ENABLED doit être true ou false.")
if any(char in model_path for char in "\r\n\0"):
    raise SystemExit("Vocal : chemin de modèle invalide.")
print(model)
print(model_path)
print(enabled)
PY
)"
mapfile -t NOC_CONFIG_VALUES <<< "$NOC_CONFIG_TEXT"
NOC_MODEL_NAME="${NOC_CONFIG_VALUES[0]}"
NOC_CONFIGURED_PATH="${NOC_CONFIG_VALUES[1]}"
NOC_ENABLED="${NOC_CONFIG_VALUES[2]}"
if [[ ! -x "$NOC_VOICE_PYTHON" ]]; then
    python3.11 -m venv "$NOC_APP_DIR/voice-venv"
fi
"$NOC_VOICE_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir -r "$NOC_APP_DIR/requirements-voice.txt"
install -d -o "$NOC_MODEL_USER" -g "$NOC_MODEL_GROUP" -m 0750 "$NOC_MODELS_DIR"

noc_grant_reading() {
    chown -hR root:"$NOC_SERVICE_GROUP" "$NOC_APP_DIR/voice-venv"
    chown -hR "$NOC_MODEL_USER:$NOC_MODEL_GROUP" "$NOC_MODELS_DIR"
    chmod -R go-w "$NOC_APP_DIR/voice-venv" "$NOC_MODELS_DIR"
    chmod -R g+rX "$NOC_APP_DIR/voice-venv" "$NOC_MODELS_DIR"
    # L'ACL nominative reste correcte même si Group= change le groupe effectif.
    if [[ "$NOC_SERVICE_USER" != root ]]; then
        if ! command -v setfacl >/dev/null; then
            command -v apt-get >/dev/null || noc_fail 'Installer le paquet acl pour donner la lecture au compte du service.'
            apt-get install --yes acl || noc_fail 'Installer le paquet acl puis relancer install-voice.sh.'
        fi
        setfacl -m "u:$NOC_SERVICE_USER:rx" "$NOC_APP_DIR"
        setfacl -m "u:$NOC_SERVICE_USER:r" "$NOC_APP_DIR/voice_transcribe.py"
        setfacl -R -P -m "u:$NOC_SERVICE_USER:r-X" "$NOC_APP_DIR/voice-venv" "$NOC_MODELS_DIR"
        find "$NOC_MODELS_DIR" -type d -exec setfacl -d -m "u:$NOC_SERVICE_USER:rx" {} +
    fi
}
noc_grant_reading
cd "$NOC_APP_DIR"
noc_probe() {
    runuser -u "$NOC_SERVICE_USER" -- env \
        "HF_HOME=$NOC_MODELS_DIR/.download-cache" "NOC_VOICE_ENABLED=$1" \
        "NOC_WHISPER_MODEL=$NOC_MODEL_NAME" "NOC_WHISPER_MODEL_PATH=$NOC_CONFIGURED_PATH" \
        "$NOC_VOICE_PYTHON" "$NOC_APP_DIR/voice_transcribe.py" \
        --check --model-name "$NOC_MODEL_NAME" --model "$NOC_CONFIGURED_PATH"
}
NOC_PROBE="$(noc_probe true)"
NOC_STATUS="$(printf '%s' "$NOC_PROBE" | python3.11 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
if [[ "$NOC_STATUS" != ready && "$NOC_STATUS" != missing_model ]]; then
    printf '%s\n' "$NOC_PROBE" >&2
    noc_fail 'Dépendance vocale inutilisable sous le compte du service.'
fi
# Rechercher le modèle demandé, pas seulement un secours d'une autre taille.
NOC_COPY_SOURCE="$(runuser -u "$NOC_SERVICE_USER" -- env \
    "HF_HOME=$NOC_MODELS_DIR/.download-cache" "NOC_WHISPER_MODEL_PATH=$NOC_CONFIGURED_PATH" \
    "$NOC_VOICE_PYTHON" - "$NOC_MODEL_NAME" "$NOC_MODEL_DIR" <<'PY'
import sys
from pathlib import Path
from voice_transcribe import _candidates, _local_model
name, standard = sys.argv[1], Path(sys.argv[2])
direct = _local_model(standard, name)
if direct is not None and direct[1] == name:
    print(direct[0])
else:
    for path, hint in _candidates(name):
        found = _local_model(path, hint)
        if found is not None and found[1] == name:
            print(found[0])
            break
PY
)"
if [[ "$NOC_COPY_SOURCE" != "$NOC_MODEL_DIR" ]]; then
    NOC_DOWNLOAD_STAGE="$(mktemp -d "$NOC_MODELS_DIR/.whisper-download-XXXXXXXX")"
    if [[ -n "$NOC_COPY_SOURCE" ]]; then
        # Copier comme le service évite qu'un lien de cache puisse divulguer un
        # fichier uniquement lisible par root. L'original et sa config restent.
        chown "$NOC_SERVICE_USER:$NOC_SERVICE_GROUP" "$NOC_DOWNLOAD_STAGE"
        runuser -u "$NOC_SERVICE_USER" -- "$NOC_VOICE_PYTHON" - \
            "$NOC_COPY_SOURCE" "$NOC_DOWNLOAD_STAGE" "$NOC_MODEL_NAME" <<'PY'
import json
import shutil
import sys
from pathlib import Path
from voice_transcribe import _local_model
source, target, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
found = _local_model(source, name)
if found is None or found[1] != name:
    raise SystemExit("Vocal : le modèle local a changé ou est illisible; relancer l'installation.")
for asset in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json"):
    if (source / asset).is_file():
        shutil.copy2(source / asset, target / asset)
(target / ".noc-whisper-model.json").write_text(json.dumps({"model": name}), encoding="utf-8")
if _local_model(target, name) is None:
    raise SystemExit("Vocal : copie locale incomplète; le modèle précédent reste conservé.")
PY
        printf 'Modèle %s réutilisé depuis %s, sans téléchargement.\n' "$NOC_MODEL_NAME" "$NOC_COPY_SOURCE"
    elif ! HF_HOME="$NOC_MODELS_DIR/.download-cache" "$NOC_VOICE_PYTHON" - "$NOC_MODEL_NAME" "$NOC_DOWNLOAD_STAGE" <<'PY'
import json
import sys
from pathlib import Path
from faster_whisper.utils import download_model
from voice_transcribe import _local_model
name, target = sys.argv[1], Path(sys.argv[2])
try:
    download_model(name, output_dir=str(target), use_auth_token=False)
    (target / ".noc-whisper-model.json").write_text(json.dumps({"model": name}), encoding="utf-8")
    if _local_model(target, name) is None:
        raise ValueError("Actifs vocaux incomplets")
except Exception:
    raise SystemExit("Vocal : téléchargement impossible; vérifier le réseau vers Hugging Face puis relancer.") from None
PY
    then noc_fail 'Aucun modèle existant n’a été remplacé.'; fi
    # La copie précédente, même incomplète, est conservée par renommage.
    if [[ -e "$NOC_MODEL_DIR" ]]; then
        NOC_PREVIOUS="$(mktemp -d "$NOC_MODELS_DIR/.whisper-before-XXXXXXXX")"
        mv -- "$NOC_MODEL_DIR" "$NOC_PREVIOUS/model"
        printf 'Modèle précédent conservé dans %s\n' "$NOC_PREVIOUS/model"
    fi
    mv -- "$NOC_DOWNLOAD_STAGE" "$NOC_MODEL_DIR"
    NOC_DOWNLOAD_STAGE=""
    noc_grant_reading
fi

# Vérification finale des droits effectifs, sans charger les poids et sans réseau.
NOC_VERIFIED="$(noc_probe true)"
printf '%s' "$NOC_VERIFIED" | python3.11 -c \
    'import json,sys; d=json.load(sys.stdin); print(d["reason"]); raise SystemExit(0 if d["status"] == "ready" else 1)' \
    || noc_fail 'Le service ne peut pas lire le modèle : vérifier droits, ACL et Python vocal.'
noc_probe "$NOC_ENABLED"
printf 'Vocal installé et vérifié sous %s. Configuration et compte systemd conservés.\n' "$NOC_SERVICE_USER"

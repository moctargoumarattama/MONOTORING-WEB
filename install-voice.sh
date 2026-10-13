#!/usr/bin/env bash
# Environnement vocal séparé : le serveur FastAPI ne charge jamais Whisper.
set -Eeuo pipefail
umask 027
readonly NOC_APP_DIR=/opt/noc-dashboard
[[ "$(uname -s)" == Linux && "$EUID" -eq 0 ]] || { printf '%s\n' 'Lancez sudo bash install-voice.sh sur le Dell Ubuntu.' >&2; exit 1; }
for noc_command in python3.11 ffmpeg install getent; do
    command -v "$noc_command" >/dev/null || { printf 'Commande requise : %s\n' "$noc_command" >&2; exit 1; }
done
getent group noc-dashboard >/dev/null || { printf '%s\n' 'Installez d’abord noc-dashboard avec install.sh.' >&2; exit 1; }
[[ -f "$NOC_APP_DIR/requirements-voice.txt" ]] || { printf '%s\n' 'requirements-voice.txt absent.' >&2; exit 1; }
for noc_path in "$NOC_APP_DIR" "$NOC_APP_DIR/voice-venv" "$NOC_APP_DIR/models" "$NOC_APP_DIR/models/whisper-tiny"; do
    [[ ! -L "$noc_path" ]] || { printf 'Lien symbolique refusé : %s\n' "$noc_path" >&2; exit 1; }
done
if [[ ! -x "$NOC_APP_DIR/voice-venv/bin/python" ]]; then
    python3.11 -m venv "$NOC_APP_DIR/voice-venv"
fi
"$NOC_APP_DIR/voice-venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$NOC_APP_DIR/requirements-voice.txt"
install -d -o root -g noc-dashboard -m 0750 "$NOC_APP_DIR/models"
if [[ ! -f "$NOC_APP_DIR/models/whisper-tiny/model.bin" ]]; then
    HF_HOME="$NOC_APP_DIR/models/.download-cache" "$NOC_APP_DIR/voice-venv/bin/python" - "$NOC_APP_DIR/models/whisper-tiny" <<'PY'
import sys
from faster_whisper.utils import download_model
download_model("tiny", output_dir=sys.argv[1])
PY
fi
chown -hR root:noc-dashboard "$NOC_APP_DIR/voice-venv" "$NOC_APP_DIR/models"
chmod -R go-w "$NOC_APP_DIR/voice-venv" "$NOC_APP_DIR/models"
chmod -R g+rX "$NOC_APP_DIR/voice-venv" "$NOC_APP_DIR/models"
printf '%s\n' 'Whisper tiny multilingue prêt : CPU int8, deux threads, processus temporaire par commande.'

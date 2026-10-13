# Tour de contrôle NOC

Dashboard FastAPI pour le Dell M4800 sous Ubuntu et ses VPS : métriques matérielles, état systemd, sondes HTTP, passerelle WhatsApp, rapports distants et flux SSE toutes les deux secondes. Le frontend est en HTML/JavaScript, sans compilation. Le serveur utilise un seul worker ; les derniers rapports VPS restent en mémoire et disparaissent au redémarrage.

Le projet est livré pour une installation locale sous `/opt/noc-dashboard`. Le script installe uniquement le NOC : il ne remplace aucune unité des applications existantes et ne les redémarre pas. Les redémarrages manuels sont limités à `merca-market`, `klasora`, `babamarket` et `moc-mal`.

## Installation sur le Dell Ubuntu

Préconditions : Linux avec systemd démarré, Python **3.11**, son module `venv` et `pip` utilisable dans ce venv, ainsi que `sudo`, `visudo` et `curl`. Python 3.11 doit être disponible sous la commande `python3.11` ; selon la version d'Ubuntu, son paquet peut nécessiter une préparation préalable par l'administrateur.

Depuis PowerShell, dans le dossier livré, transférez le projet vers votre compte SSH :

```powershell
Set-Location 'C:\Users\hp\Desktop\MONOTORING WEB'
$serveur = Read-Host 'Compte et hôte SSH du Dell'
tar -czf noc-dashboard.tar.gz --exclude=.venv --exclude=venv --exclude=.qa --exclude=__pycache__ noc-dashboard
scp .\noc-dashboard.tar.gz "${serveur}:~/noc-dashboard.tar.gz"
ssh $serveur
```

Sur le Dell :

```bash
tar -xzf "$HOME/noc-dashboard.tar.gz" -C "$HOME"
cd "$HOME/noc-dashboard"
python3.11 --version
python3.11 -m venv --help >/dev/null
command -v sudo visudo systemctl curl
sudo bash install.sh
sudo systemctl status noc-dashboard.service --no-pager
curl --fail --silent --show-error http://127.0.0.1:5050/api/health
```

L'installateur crée le compte système `noc-dashboard`, un venv isolé et `/etc/noc-dashboard.env`. Il génère deux jetons indépendants pour les actions administrateur et les rapports VPS, avec `secrets.token_hex(32)`, sans les afficher. Le code appartient à `root` ; le service peut le lire mais pas le modifier. Le fichier de configuration est en `root:noc-dashboard`, mode `0640`.

Une seconde exécution conserve le venv et la configuration existants. Les fichiers remplacés sont sauvegardés dans un dossier privé sous `/var/backups/noc-dashboard`. Le script fonctionne aussi lorsqu'il est lancé directement depuis `/opt/noc-dashboard`, sans recopier les fichiers sur eux-mêmes. Aucun paquet Python global n'est installé. L'installateur vérifie la syntaxe du code, la règle sudoers, l'unité systemd et la réponse réelle de `/api/health`.

Pour ouvrir le tableau depuis le PC, dans un autre terminal PowerShell :

```powershell
$serveur = Read-Host 'Compte et hôte SSH du Dell'
ssh -N -L 5050:127.0.0.1:5050 $serveur
```

Ouvrez **http://127.0.0.1:5050** : le tableau et ses mesures s'affichent directement, sans connexion ni jeton de consultation. Le jeton administrateur se saisit seulement lorsque vous souhaitez autoriser une action de redémarrage.

## Configuration

Modifiez la configuration avec `sudoedit /etc/noc-dashboard.env`, puis appliquez-la avec `sudo systemctl restart noc-dashboard.service`.

| Variable | Valeur initiale / rôle |
| --- | --- |
| `NOC_HOST` | `127.0.0.1`, pour accès local ou tunnel |
| `NOC_PORT` | `5050` |
| `NOC_INTERVAL_SECONDS` | `2`, période de collecte et diffusion |
| `NOC_BACKUP_PATH` | `/mnt/babamarket-backups` ; absence ou volume non monté signalés sans inventer de métriques |
| `NOC_VPS_STALE_SECONDS` | `20`, délai après lequel un rapport VPS est signalé ancien |
| `NOC_GATEWAY_SECRET` | Secret de la passerelle WhatsApp communiqué dans le cahier des charges |
| `NOC_ADMIN_TOKEN` | Jeton distinct pour le header `x-admin-token` des redémarrages |
| `NOC_VPS_TOKEN` | Jeton distinct pour le header `x-vps-token` des agents distants |
| `NOC_ENABLE_RESTART` | `true` ; les actions nécessitent aussi Linux et un jeton administrateur |

Le secret WhatsApp est lu depuis l'environnement et envoyé uniquement à `http://127.0.0.1:3001/session/1/status`. S'il a été changé sur la passerelle, reportez la nouvelle valeur dans cette configuration. Les jetons ne sont inclus ni dans les snapshots, ni dans les événements SSE.

La consultation de `/`, `/api/health`, `/api/snapshot` et `/api/stream` est directe, sans jeton ni cookie. Les anciennes variables `NOC_VIEW_TOKEN` et `NOC_COOKIE_SECURE`, si elles figurent encore dans une configuration existante, sont ignorées ; vous pouvez les laisser en place. Sans `NOC_ADMIN_TOKEN`, les redémarrages sont désactivés. Sans `NOC_VPS_TOKEN`, les rapports VPS sont désactivés.

Ports locaux sondés : Merca-Market `5006`, Klasora `5005`, BabaMarket `5002`, Moc-Mal `5003`. `cloudflared` est surveillé par systemd ; la passerelle utilise `klasora-whatsapp` et le port `3001`. Un service arrêté, une sonde qui expire ou une température absente sont affichés sans bloquer les autres mesures. Si systemd est indisponible, son état est explicitement `unknown`.

L'unité conserve l'accès au bus systemd et autorise l'élévation nécessaire à `sudo`, avec des capacités limitées. Le fichier `/etc/sudoers.d/noc-dashboard`, vérifié par `visudo`, autorise les quatre commandes `systemctl --no-block restart` exactes et le script `/usr/local/bin/backup-babamarket.sh` sans argument, sans wildcard. Le backend utilise `sudo -n` et une liste fermée de noms ; aucun nom fourni par le client n'est exécuté par un shell.

## Mise à jour d'une installation existante

Sur un Dell qui utilise encore l'ancienne version, ces deux commandes rendent immédiatement la consultation accessible sans jeton. Elles vident uniquement l'ancien jeton de consultation et conservent les secrets administrateur, VPS et WhatsApp :

```bash
sudo sed -i 's/^NOC_VIEW_TOKEN=.*/NOC_VIEW_TOKEN=/' /etc/noc-dashboard.env
sudo systemctl restart noc-dashboard.service
```

Rechargez ensuite le navigateur avec **Ctrl+F5** pour cette ancienne installation. Dans la version actuelle, `NOC_VIEW_TOKEN` est ignoré, même si sa valeur reste non vide.

Pour installer la version actuelle avec WhatsApp vocal et Sentinel, suivez la [mise à jour complète dans MODULES.md](MODULES.md#1-mettre-à-jour-le-dell). Transférez le projet complet puis exécutez `sudo bash install.sh` : les nouveaux modules Python, la dépendance cryptographique, l'unité et la règle sudoers doivent être installés ensemble. L'installateur sauvegarde les fichiers remplacés et conserve la configuration existante. Le venv vocal et le modèle tiny se préparent séparément avec `sudo bash install-voice.sh`.

## Tests API après installation

Les exemples supposent le bind initial `127.0.0.1:5050`. Les mesures et le flux SSE se consultent sans authentification ; les rapports VPS utilisent le jeton réel chargé depuis la configuration par systemd.

```bash
# Santé publique.
curl --fail --silent --show-error http://127.0.0.1:5050/api/health

# Snapshot complet.
curl --fail --silent --show-error \
  http://127.0.0.1:5050/api/snapshot | python3.11 -m json.tool

# Plusieurs événements en sept secondes ; curl termine normalement avec le code 28.
curl --silent --show-error --no-buffer --max-time 7 \
  http://127.0.0.1:5050/api/stream || test "$?" -eq 28

# Rapport VPS réel depuis le Dell ; utilise /proc et le système de fichiers.
sudo systemd-run --quiet --wait --pipe --collect --unit=noc-local-agent-check \
  --property=User=noc-dashboard --property=Group=noc-dashboard \
  --property=EnvironmentFile=/etc/noc-dashboard.env \
  --setenv=NOC_REPORT_URL=http://127.0.0.1:5050/api/vps/report \
  --setenv=NOC_VPS_SERVICES=cloudflared \
  /opt/noc-dashboard/venv/bin/python /opt/noc-dashboard/vps_agent.py --once

# Le nouveau rapport apparaît dans le snapshot et le flux SSE.
curl --fail --silent --show-error \
  http://127.0.0.1:5050/api/snapshot | python3.11 -m json.tool

```

Vérification du refus d'un rapport non authentifié :

```bash
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  --header 'Content-Type: application/json' --data '{}' \
  http://127.0.0.1:5050/api/vps/report
```

Avec la configuration de l'installation, le code attendu est `401`. Les erreurs de structure d'un rapport authentifié produisent `422`.

Test facultatif d'action : **la commande suivante redémarre réellement Merca-Market**. Exécutez-la au moment souhaité pour cette application :

```bash
NOC_ADMIN_TOKEN="$(sudo sed -n 's/^NOC_ADMIN_TOKEN=//p' /etc/noc-dashboard.env)"
printf 'header = "x-admin-token: %s"\n' "$NOC_ADMIN_TOKEN" |
  curl --fail --silent --show-error --config - --request POST \
    http://127.0.0.1:5050/api/service/merca-market/restart
unset NOC_ADMIN_TOKEN
```

`cloudflared` et `klasora-whatsapp` ne font pas partie des services redémarrables. L'installateur ne lance aucun de ces tests de redémarrage applicatif.

## Agent sur un VPS distant

`vps_agent.py` utilise exclusivement la bibliothèque standard Python. Il lit `/proc/stat` et `/proc/meminfo`, mesure le disque racine et vérifie les unités systemd configurées. Au plus 16 noms de services de 128 caractères sont acceptés. Les sondes systemd durent au plus une seconde et sont exécutées avec au plus quatre threads ; le POST a un timeout de trois secondes et au plus deux tentatives. Un cycle retardé saute les échéances passées ; aucun cycle ne se chevauche dans un processus. `SIGTERM` et `SIGINT` arrêtent la boucle proprement.

La cible HTTPS doit pointer exactement sur `/api/vps/report`, sans identifiants dans l'URL. La validation TLS reste active et les redirections sont refusées pour éviter de transmettre le jeton à un autre serveur. HTTP est accepté sur loopback ; pour un réseau privé où vous choisissez HTTP distant, définissez explicitement `NOC_ALLOW_INSECURE_HTTP=true`, sachant que le jeton traverse alors ce réseau sans chiffrement. Un tunnel HTTPS vers le Dell permet de conserver son bind local.

Depuis le dossier source sur le Dell, copiez l'agent et son unité sur le VPS :

```bash
cd "$HOME/noc-dashboard"
read -r -p 'Compte et hôte SSH du VPS : ' VPS_SSH_HOST
scp vps_agent.py vps-agent.service "$VPS_SSH_HOST:"
ssh "$VPS_SSH_HOST"
```

Sur le VPS, créez le compte de lecture et installez les deux fichiers :

```bash
python3 --version
getent group noc-agent >/dev/null || sudo groupadd --system noc-agent
id noc-agent >/dev/null 2>&1 || sudo useradd --system --gid noc-agent \
  --home-dir /opt/noc-agent --no-create-home --shell /usr/sbin/nologin noc-agent
sudo install -d -o root -g noc-agent -m 0750 /opt/noc-agent
sudo install -o root -g noc-agent -m 0640 "$HOME/vps_agent.py" /opt/noc-agent/vps_agent.py
sudo install -o root -g root -m 0644 "$HOME/vps-agent.service" /etc/systemd/system/noc-vps-agent.service
```

Pour la première configuration, saisissez l'URL HTTPS réelle et le jeton `NOC_VPS_TOKEN` lu dans la configuration du Dell. La saisie du jeton est masquée :

```bash
if sudo test -e /etc/noc-vps-agent.env; then
  sudoedit /etc/noc-vps-agent.env
else
  read -r -p 'URL HTTPS complète du endpoint /api/vps/report : ' NOC_REPORT_URL
  read -r -s -p 'Jeton VPS du Dell : ' NOC_VPS_TOKEN
  printf '\n'
  read -r -p 'Services séparés par des virgules, ou vide : ' NOC_VPS_SERVICES
  sudo install -o root -g noc-agent -m 0640 /dev/null /etc/noc-vps-agent.env
  {
    printf 'NOC_REPORT_URL=%s\n' "$NOC_REPORT_URL"
    printf 'NOC_VPS_TOKEN=%s\n' "$NOC_VPS_TOKEN"
    printf 'NOC_VPS_SERVICES=%s\n' "$NOC_VPS_SERVICES"
  } | sudo tee /etc/noc-vps-agent.env >/dev/null
  unset NOC_REPORT_URL NOC_VPS_TOKEN NOC_VPS_SERVICES
fi
sudo chown root:noc-agent /etc/noc-vps-agent.env
sudo chmod 0640 /etc/noc-vps-agent.env

# Test ponctuel sous le compte de l'agent, sans jeton dans la ligne de commande.
sudo systemd-run --quiet --wait --pipe --collect --unit=noc-agent-check \
  --property=User=noc-agent --property=Group=noc-agent \
  --property=EnvironmentFile=/etc/noc-vps-agent.env \
  /usr/bin/python3 /opt/noc-agent/vps_agent.py --once

# Agent permanent : rapport toutes les cinq secondes.
sudo systemd-analyze verify /etc/systemd/system/noc-vps-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now noc-vps-agent.service
sudo systemctl status noc-vps-agent.service --no-pager
sudo journalctl -u noc-vps-agent.service -n 30 --no-pager
```

Sur un serveur systemd, vous pouvez choisir cron à la place du service permanent. Le rapport part alors une fois par minute ; adaptez `NOC_VPS_STALE_SECONDS` sur le Dell à au moins `90`. Cette alternative utilise une unité transitoire fixe pour empêcher un chevauchement et charge les secrets par systemd :

```bash
sudo systemctl disable --now noc-vps-agent.service
printf '%s\n' \
  '* * * * * root /usr/bin/systemd-run --quiet --wait --collect --unit=noc-vps-cron --property=User=noc-agent --property=Group=noc-agent --property=EnvironmentFile=/etc/noc-vps-agent.env /usr/bin/python3 /opt/noc-agent/vps_agent.py --once' |
  sudo tee /etc/cron.d/noc-vps-agent >/dev/null
sudo chmod 0644 /etc/cron.d/noc-vps-agent
```

Le JSON transmis contient `hostname`, `cpu_percent`, `memory` et `disk` avec `used`, `total`, `percent`, ainsi que `services`, une liste de `{name, status}`. Les volumes sont exprimés en octets, le CPU et les autres pourcentages de 0 à 100. Les rapports absents sont signalés anciens par le Dell ; une coupure réseau ne stoppe pas l'agent permanent.

## Exécution locale Windows

Le backend et le frontend fonctionnent aussi dans ce dossier pour vérification. Les métriques psutil restent réelles ; systemd et les redémarrages sont indisponibles et apparaissent `unknown`. L'agent VPS nécessite Linux.

```powershell
Set-Location 'C:\Users\hp\Desktop\MONOTORING WEB\noc-dashboard'
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:NOC_GATEWAY_SECRET = Read-Host 'Secret de la passerelle WhatsApp locale'
$env:NOC_HOST = '127.0.0.1'
$env:NOC_PORT = '5050'
.\venv\Scripts\python.exe main.py
```

Ouvrez http://127.0.0.1:5050 : le tableau s'affiche directement. En l'absence de services et de passerelle sur ce PC, les sondes montrent leur indisponibilité ; aucune donnée de production n'est simulée. Le bind est local et les redémarrages restent désactivés.

La suite de tests utilise `unittest` de la bibliothèque standard, sans paquet de test supplémentaire. Depuis le dossier source sur Linux, préparez un environnement de test séparé de l'installation puis exécutez-la :

```bash
cd "$HOME/noc-dashboard"
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Sur Windows, dans le venv de développement créé ci-dessus :

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Mesure de mémoire et dépannage

L'objectif est un fonctionnement léger, avec collecte mutualisée, historique limité, client HTTP partagé et un seul worker. **La limite de 50 Mo n'est pas garantie avant une mesure sur le Dell Ubuntu**, sous la charge et le nombre de clients réels. Les valeurs Windows ne permettent pas de certifier la consommation Linux.

```bash
sudo systemctl show noc-dashboard.service -p MemoryCurrent -p TasksCurrent -p MainPID
curl --fail --silent --show-error \
  http://127.0.0.1:5050/api/snapshot |
  python3.11 -c 'import json,sys; d=json.load(sys.stdin); print("RSS du backend : %.2f MiB" % (d["hardware"]["process_rss_bytes"]/1024**2))'
```

`MemoryCurrent` concerne le groupe du service ; le RSS du snapshot concerne le processus Python. Mesurez après plusieurs minutes, puis avec les onglets et VPS habituels.

```bash
sudo journalctl -u noc-dashboard.service -n 80 --no-pager
sudo ss -ltnp 'sport = :5050'
sudo visudo -cf /etc/sudoers.d/noc-dashboard
sudo -l -U noc-dashboard
sudo systemctl is-active merca-market.service klasora.service babamarket.service moc-mal.service cloudflared.service klasora-whatsapp.service
```

Une erreur `401` sur un rapport VPS ou une action de redémarrage exige le jeton correspondant à cette route. Un restart refusé demande la vérification de `NOC_ENABLE_RESTART`, du jeton administrateur et de la règle sudoers. Une température absente indique généralement qu'aucun capteur exploitable n'est exposé à psutil. Le chemin de sauvegarde absent ou non monté est explicitement indisponible, avec des métriques nulles ; aucune capacité de sauvegarde n'est déduite du disque racine.

Le frontend est autonome : CSS, icônes SVG et graphiques sont intégrés au HTML, sans dépendance CDN ni compilation. Les accès réseau aux applications du Dell restent limités à loopback. L'installation initiale reste accessible uniquement localement ou via tunnel ; les jetons administrateur et VPS protègent toujours les écritures.

## Modules WhatsApp vocal et Sentinel

Cette version ajoute les commandes WhatsApp texte/vocales et le radar Sentinel VPS en direct. Suivez [MODULES.md](MODULES.md) pour la mise à jour du Dell, le modèle vocal local, la sauvegarde BabaMarket et l'installation du service `sentinel-vps.service` sur le VPS. La mise à jour de ces modules nécessite le projet complet et ses nouvelles dépendances : l'ancienne procédure limitée à trois fichiers ne suffit pas.

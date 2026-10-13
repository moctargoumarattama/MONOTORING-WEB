# WhatsApp vocal et Radar Sentinel

Guide pour mettre à jour le Dell existant et installer la sentinelle sur `187.77.171.225`. Les métriques et les événements partagent le flux SSE existant. Les commandes vocales et les incidents se publient immédiatement, indépendamment des sondes toutes les deux secondes.

## 1. Mettre à jour le Dell

Transférez l'archive actualisée comme indiqué dans [README.md](README.md), puis sur le Dell :

```bash
tar -xzf "$HOME/noc-dashboard.tar.gz" -C "$HOME"
cd "$HOME/noc-dashboard"
sudo apt-get install ffmpeg rsync
sudo bash install.sh
sudo bash install-voice.sh
sudoedit /etc/noc-dashboard.env
```

`install.sh` sauvegarde les fichiers remplacés et conserve la configuration existante. Il met à jour uniquement le NOC, ses dépendances et sa règle sudoers. Le script `/usr/local/bin/backup-babamarket.sh` est installé seulement s'il n'existe pas : une sauvegarde déjà personnalisée est conservée.

`install-voice.sh` prépare un venv séparé dans `/opt/noc-dashboard/voice-venv` et le modèle **tiny multilingue** local dans `/opt/noc-dashboard/models/whisper-tiny`. Le téléchargement intervient à l'installation. Une commande vocale ne télécharge jamais de modèle.

Vérifiez ces valeurs dans `/etc/noc-dashboard.env`, en conservant les secrets actuels :

```dotenv
NOC_HOST=0.0.0.0
NOC_PORT=5050
ADMIN_PHONE_NUMBER=212770010264
NOC_WHATSAPP_SESSION_ID=1
NOC_WHATSAPP_SEND_URL=http://127.0.0.1:3001/message/send
NOC_WHATSAPP_SEND_TO_FIELD=to
NOC_WHATSAPP_SEND_TEXT_FIELD=text
NOC_WHISPER_PYTHON=/opt/noc-dashboard/voice-venv/bin/python
NOC_WHISPER_MODEL_PATH=/opt/noc-dashboard/models/whisper-tiny
NOC_BACKUP_SCRIPT=/usr/local/bin/backup-babamarket.sh
NOC_BACKUP_PATH=/mnt/babamarket-backups
```

`NOC_GATEWAY_SECRET` et `NOC_VPS_TOKEN` doivent garder leurs valeurs réelles. L'installateur ajoute un secret privé aléatoire `NOC_WHATSAPP_WEBHOOK_TOKEN` s'il n'existe pas, sans l'afficher ni le renouveler à chaque mise à jour. Dans la configuration du webhook de la passerelle, recopiez cette valeur dans le header `X-Gateway-Secret`. Ce secret protège les messages entrants; les réponses envoyées à la passerelle gardent le `NOC_GATEWAY_SECRET` existant. Sans jeton webhook configuré, le canal de commandes est désactivé même si le numéro administrateur est renseigné.

Le bind `0.0.0.0` permet les accès LAN et Tailscale : `http://192.168.11.103:5050` et `http://100.68.163.14:5050`. Un ancien `NOC_HOST=127.0.0.1` empêcherait les rapports Sentinel venant du VPS. Un bind uniquement sur `100.68.163.14` est possible si vous souhaitez l'accès Tailscale seul; les commandes de vérification utilisant loopback doivent alors employer cette IP.

```bash
sudo systemctl restart noc-dashboard.service
sudo systemctl status noc-dashboard.service --no-pager
curl --retry 4 --retry-connrefused --retry-delay 1 --fail \
  http://127.0.0.1:5050/api/health
sudo visudo -cf /etc/sudoers.d/noc-dashboard
```

Le dashboard reste accessible sans connexion ni jeton de consultation. Le contrôle WhatsApp utilise le numéro autorisé et le secret du webhook; les jetons des agents et des actions du navigateur restent propres à ces canaux.

## 2. Configurer le webhook de la passerelle WhatsApp

Dans la passerelle existante, configurez :

- URL : `http://127.0.0.1:5050/api/whatsapp/webhook`.
- Méthode : `POST`, `Content-Type: application/json`.
- Header : `X-Gateway-Secret`, avec la valeur de `NOC_WHATSAPP_WEBHOOK_TOKEN` lue dans `/etc/noc-dashboard.env`.

Note vocale au format réel de la passerelle :

```json
{
  "event": "messages.upsert",
  "sessionId": "1",
  "data": {
    "from": "212770010264@s.whatsapp.net",
    "fromMe": false,
    "id": "3EB0EXEMPLEVOCAL",
    "messageType": "audioMessage",
    "mimetype": "audio/ogg; codecs=opus",
    "audioUrl": "http://127.0.0.1:3001/media/download/audio_temp.ogg",
    "base64": null,
    "timestamp": 1791849600
  }
}
```

Message texte :

```json
{
  "event": "messages.upsert",
  "sessionId": "1",
  "data": {
    "from": "212770010264@s.whatsapp.net",
    "fromMe": false,
    "id": "3EB0EXEMPLETEXTE",
    "messageType": "conversation",
    "text": "statut"
  }
}
```

La réponse est envoyée au numéro autorisé par `POST http://127.0.0.1:3001/message/send`, avec `X-Gateway-Secret: NOC_GATEWAY_SECRET` et ce corps :

```json
{"sessionId":"1","to":"212770010264@s.whatsapp.net","text":"État de l'infrastructure…"}
```

Les messages sortants `fromMe:true` sont ignorés. Les autres numéros, groupes et sessions sont refusés. Un header de webhook invalide répond `403`; un canal non configuré répond `503`. Les identifiants de message servent à éviter les doublons; une file limitée et un worker unique empêchent les traitements audio simultanés.

Le format générique `{id,from,text}` ou `{id,from,audio:{path|url,mimetype}}` est également accepté. Une URL audio doit désigner `http://127.0.0.1:3001/media/...` ou `/uploads/...`, sans redirection. Le média doit être déjà déchiffré par la passerelle. Les blobs `base64` et les URLs WhatsApp externes ne sont pas téléchargés par le NOC.

Pour des fichiers locaux, renseignez `NOC_WHATSAPP_MEDIA_DIR` avec le dossier exact de médias de la passerelle, lisible par `noc-dashboard`. Les fichiers OGG/Opus doivent rester dans ce dossier et les liens symboliques sont refusés. Les notes sont limitées à 8 Mio et 60 secondes; la copie temporaire et le WAV mono 16 kHz sont supprimés après traitement. La transcription tiny multilingue utilise le filtre VAD de détection de parole pour écarter les silences.

## 3. Commandes prises en charge

| Commande texte ou vocale | Action |
| --- | --- |
| `statut`, `état`, `état des services` | Dernier relevé des ports 5002, 5003, 5005, 5006, 3001, CPU et RAM Dell |
| `redémarre merca-market` | Demande systemd limitée à Merca-Market |
| `redémarre klasora` | Demande systemd limitée à Klasora |
| `redémarre babamarket` | Demande systemd limitée à BabaMarket |
| `redémarre moc-mal` | Demande systemd limitée à Moc-Mal |
| `sauvegarde babamarket` | Exécute le script configuré |

La grammaire des actions est exacte : les négations, services inconnus et phrases combinant plusieurs actions ne déclenchent aucune commande. Pour la lecture seule, l'homophone `statue des services` est accepté comme `statut des services`; aucune correction approximative ne déclenche un redémarrage ou une sauvegarde. Les redémarrages partagent les protections existantes du NOC, notamment `NOC_ENABLE_RESTART` et le délai de 30 secondes par service. Aucun texte reçu n'est exécuté par un shell.

La carte Voice-to-Action affiche la transcription, l'action, son résultat et l'horodatage. Le résultat SSE est publié avant d'attendre l'envoi de la réponse WhatsApp. Un échec de livraison est signalé dans le journal. Les nouveaux événements s'affichent sans rechargement manuel.

### Préparer la sauvegarde BabaMarket

Le script fourni détecte la source dans `WorkingDirectory` de `babamarket.service`. Si cette valeur est absente ou ne désigne pas le dossier des données, définissez `NOC_BACKUP_SOURCE=/chemin/absolu/precis/babamarket` dans `/etc/noc-dashboard.env`.

```bash
sudo systemctl show babamarket.service --property=WorkingDirectory --value
findmnt --mountpoint /mnt/babamarket-backups
sudo test -x /usr/local/bin/backup-babamarket.sh
```

Le volume cible doit être réellement monté sur un système de fichiers distinct du disque racine, séparé de la source, et accepter des dossiers privés appartenant à root. S'il est absent, la sauvegarde refuse d'écrire sur le disque racine. Les fichiers sont copiés avec `rsync`; les bases identifiées comme SQLite sont copiées par l'API de sauvegarde en ligne et vérifiées. Les venvs, caches Python et `.git` sont exclus. Une copie incomplète reste identifiée comme telle et n'est pas publiée comme sauvegarde réussie.

L'unité systemd autorise l'écriture dans `/mnt/babamarket-backups`. Pour un autre `NOC_BACKUP_PATH`, ajoutez aussi ce chemin à `ReadWritePaths` dans un override créé avec `sudo systemctl edit noc-dashboard.service`, puis exécutez `sudo systemctl daemon-reload` et redémarrez le NOC. La variable seule ne modifie pas les permissions du service.

Le script comporte un délai interne de 280 secondes. `sudo` est accordé uniquement au chemin exact `/usr/local/bin/backup-babamarket.sh`, sans argument. Un `NOC_BACKUP_SCRIPT` personnalisé est exécuté avec les droits de `noc-dashboard`, sans nouvelle permission root; il doit être exécutable, appartenir à root et être non modifiable, tout comme ses dossiers parents. Un chemin absent produit une réponse claire et ne bloque pas le collecteur.

Les autres moteurs de base de données nécessitent leur propre script adapté. Une copie de fichiers en fonctionnement n'est pas un instantané transactionnel global; vérifiez aussi une restauration sur une copie isolée des données.

## 4. Installer Sentinel sur le VPS

Le VPS doit rejoindre le même réseau Tailscale que le Dell et atteindre `100.68.163.14:5050`. Il faut Python 3.11 avec `venv` et un pare-feu existant : UFW **déjà actif**, ou iptables. L'installation ci-dessous n'active, ne réinitialise et ne remplace pas le pare-feu.

Depuis le VPS, vous pouvez vérifier cette liaison avant de démarrer Sentinel avec la [CLI Tailscale](https://tailscale.com/docs/reference/tailscale-cli) :

```bash
tailscale status
tailscale ping --c 3 100.68.163.14
curl --connect-timeout 3 --fail http://100.68.163.14:5050/api/health
```

Depuis le dossier source du Dell :

```bash
cd "$HOME/noc-dashboard"
read -r -p 'Compte SSH sur 187.77.171.225 : ' SENTINEL_SSH_HOST
scp vps_sentinel.py sentinel_crypto.py sentinel-vps.service requirements-sentinel.txt \
  "$SENTINEL_SSH_HOST:"
ssh "$SENTINEL_SSH_HOST"
```

Sur le VPS :

```bash
sudo install -d -o root -g root -m 0750 /opt/noc-sentinel
sudo install -o root -g root -m 0640 "$HOME/vps_sentinel.py" \
  "$HOME/sentinel_crypto.py" "$HOME/requirements-sentinel.txt" /opt/noc-sentinel/
sudo python3.11 -m venv /opt/noc-sentinel/venv
sudo /opt/noc-sentinel/venv/bin/python -m pip install \
  -r /opt/noc-sentinel/requirements-sentinel.txt
sudo install -o root -g root -m 0644 "$HOME/sentinel-vps.service" \
  /etc/systemd/system/sentinel-vps.service
```

Utilisez le **même** `NOC_VPS_TOKEN` que dans `/etc/noc-dashboard.env` sur le Dell. Pour créer la configuration du VPS, la saisie ci-dessous garde le secret hors de l'historique et des arguments des processus :

```bash
if sudo test -e /etc/noc-sentinel.env; then
  sudoedit /etc/noc-sentinel.env
else
  read -r -s -p 'NOC_VPS_TOKEN du Dell : ' SENTINEL_TOKEN
  printf '\n'
  sudo install -o root -g root -m 0600 /dev/null /etc/noc-sentinel.env
  {
    printf 'NOC_VPS_TOKEN=%s\n' "$SENTINEL_TOKEN"
    printf '%s\n' 'SENTINEL_REPORT_URL=http://100.68.163.14:5050/api/sentinel/incident'
    printf '%s\n' 'SENTINEL_PORT=22222' 'SENTINEL_FIREWALL=ufw'
    printf '%s\n' 'SENTINEL_PROTECTED_CIDRS='
  } | sudo tee /etc/noc-sentinel.env >/dev/null
  unset SENTINEL_TOKEN
fi
sudo chmod 0600 /etc/noc-sentinel.env
sudoedit /etc/noc-sentinel.env
```

Choisissez `SENTINEL_FIREWALL=iptables` si c'est votre pare-feu existant. Ajoutez vos IP publiques d'administration à `SENTINEL_PROTECTED_CIDRS`, séparées par des virgules, avant de démarrer. Le LAN `192.168.11.0/24`, Tailscale `100.64.0.0/10`, loopback, les IP indiquées du Dell/VPS et les sources non publiques sont protégés contre les bannissements.

Pour le mode UFW, vérifiez son état puis ouvrez uniquement le port du piège :

```bash
sudo ufw status
sudo ufw allow 22222/tcp
```

En mode iptables, autorisez ce même port dans votre politique existante. Conservez les règles SSH et Tailscale. Si le fournisseur a un pare-feu réseau, ouvrez également son port TCP 22222.

```bash
sudo systemd-analyze verify /etc/systemd/system/sentinel-vps.service
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel-vps.service
sudo systemctl status sentinel-vps.service --no-pager
sudo ss -ltnp 'sport = :22222'
sudo journalctl -u sentinel-vps.service -n 30 --no-pager
```

L'agent fonctionne sous root avec les capacités nécessaires au pare-feu. Il ne touche pas au port SSH réel. Le piège TELNET capture `login` et `password` en clair; une bannière `SSH-...` est signalée comme négociation SSH, sans prétendre extraire un mot de passe chiffré. Une tentative déclenche la règle de blocage après capture ou expiration du dialogue, avec un délai borné de cinq secondes.

Les incidents sont chiffrés et authentifiés par AES-256-GCM, puis envoyés avec `X-VPS-Token`. Sur HTTP, le transport choisi est le réseau chiffré Tailscale; pour une destination hors Tailscale, HTTPS est requis. Le backend vérifie l'enveloppe, l'horodatage et les doublons. Un heartbeat toutes les dix secondes met à jour le statut; le Dell affiche « Déconnecté » après 35 secondes sans rapport.

Le buffer du radar conserve 50 incidents en RAM. La résolution GeoIP HTTPS est asynchrone, limitée et mise en cache; elle peut être désactivée par `NOC_SENTINEL_GEOIP=false`. Les identifiants capturés ne sont pas écrits dans les journaux. Les fichiers d'état conservent les compteurs quotidiens et des informations bornées de déduplication, pas les mots de passe. Le jour de référence est celui d'`Africa/Casablanca`.

## 5. Vérification et mémoire

Les tests automatisés utilisent des transports HTTP simulés : ils n'envoient aucun message WhatsApp réel et ne modifient aucun pare-feu. Sur le Dell, vérifiez l'état courant :

```bash
curl --fail --silent http://127.0.0.1:5050/api/snapshot |
  python3.11 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"voice":d.get("voice"),"sentinel":d.get("sentinel")},ensure_ascii=False,indent=2))'
sudo systemctl show noc-dashboard.service -p MemoryCurrent -p TasksCurrent
sudo journalctl -u noc-dashboard.service -n 50 --no-pager
```

Sur le VPS, un test loopback du piège ne provoque aucun bannissement et ne compte pas comme attaque bloquée : `printf 'test-local\nmot-de-passe-fictif\n' | nc -w 7 127.0.0.1 22222`. Le heartbeat suffit à confirmer le statut actif même lorsqu'aucune attaque n'a été reçue.

Le modèle vocal charge uniquement dans un worker CPU `int8` jetable, limité à deux threads; sa mémoire est libérée après la note. Le pic pendant une transcription locale dépasse 50 Mo, conformément au choix accepté pour le vocal local. La mémoire supplémentaire **au repos** du dashboard doit être mesurée sur le Dell avant/après sous la même charge : `MemoryCurrent` inclut les enfants du service, tandis que `hardware.process_rss_bytes` dans le snapshot décrit le Python principal. Une configuration `NOC_VOICE_REMOTE_URL` et `NOC_VOICE_REMOTE_TOKEN` reste disponible si une transcription distante devient préférable.

Un essai réel de transcription française sous **Windows** a mesuré une acceptation du webhook en 31 ms, environ 232 Mio pour le worker temporaire et 64 Mio pour le backend, contre environ 60 Mio auparavant. Les sondes sont restées espacées de deux secondes. Ces chiffres ne certifient pas Ubuntu : les mesures sur le Dell et le déploiement VPS restent à effectuer. Les captures du radar utilisent des incidents fictifs et ne prouvent aucun bannissement réel. Les détails de validation figurent dans [docs/VERIFICATION.md](docs/VERIFICATION.md).

Les nouvelles dépendances sont `cryptography` dans [requirements.txt](requirements.txt) et [requirements-sentinel.txt](requirements-sentinel.txt), ainsi que `faster-whisper==1.2.1` dans [requirements-voice.txt](requirements-voice.txt), uniquement pour le venv vocal. La conversion utilise le binaire système `ffmpeg`, sans `ffmpeg-python`.

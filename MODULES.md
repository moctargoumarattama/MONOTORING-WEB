# WhatsApp vocal et Radar Sentinel

Guide pour mettre à jour le Dell existant et installer la sentinelle sur `187.77.171.225`. Les métriques et les événements partagent le flux SSE existant. Les commandes vocales et les incidents se publient immédiatement, indépendamment des sondes toutes les deux secondes.

## 1. Mettre à jour le Dell

Pour appliquer seulement ce correctif vocal à une version NOC/Sentinel déjà installée, transférez l'archive actualisée, extrayez-la puis remplacez les fichiers suivants. Sauvegardez les versions courantes avant la copie ; aucune modification du compte de service ni des dépendances du dashboard n'est nécessaire :

```bash
tar -xzf "$HOME/noc-dashboard.tar.gz" -C "$HOME"
cd "$HOME/noc-dashboard"
sudo install -d -o root -g root -m 0700 /var/backups/noc-dashboard
NOC_VOICE_BACKUP="$(sudo mktemp -d /var/backups/noc-dashboard/voice-fix-XXXXXXXX)"
sudo cp -p /opt/noc-dashboard/config.py /opt/noc-dashboard/main.py \
  /opt/noc-dashboard/whatsapp.py /opt/noc-dashboard/voice_transcribe.py \
  /opt/noc-dashboard/install-voice.sh "$NOC_VOICE_BACKUP/"
sudo install -d -o root -g root -m 0700 "$NOC_VOICE_BACKUP/static"
sudo cp -p /opt/noc-dashboard/static/index.html "$NOC_VOICE_BACKUP/static/"
NOC_SERVICE_USER="$(sudo systemctl show noc-dashboard.service --property=User --value)"
NOC_SERVICE_GROUP="$(sudo systemctl show noc-dashboard.service --property=Group --value)"
if test -z "$NOC_SERVICE_GROUP"; then NOC_SERVICE_GROUP="$(id -gn "$NOC_SERVICE_USER")"; fi
sudo install -o root -g "$NOC_SERVICE_GROUP" -m 0640 config.py main.py whatsapp.py voice_transcribe.py /opt/noc-dashboard/
sudo install -o root -g "$NOC_SERVICE_GROUP" -m 0750 install-voice.sh /opt/noc-dashboard/install-voice.sh
sudo install -o root -g "$NOC_SERVICE_GROUP" -m 0640 static/index.html /opt/noc-dashboard/static/index.html
sudoedit /etc/noc-dashboard.env
sudo bash /opt/noc-dashboard/install-voice.sh
sudo systemctl restart noc-dashboard.service
```

Appliquez les paramètres ci-dessous et branchez ensuite le bridge Baileys de la section 2. Si les modules NOC/Sentinel n'étaient pas encore installés, utilisez plutôt l'installation complète :

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

`install-voice.sh` prépare un venv séparé dans `/opt/noc-dashboard/voice-venv` et le modèle **tiny multilingue** local dans `/opt/noc-dashboard/models/whisper`. Le téléchargement intervient à l'installation. Une commande vocale ne télécharge jamais de modèle. Un ancien chemin `whisper-tiny` explicitement configuré reste compatible : l'installateur principal préserve les valeurs existantes et ajoute uniquement les clés absentes.

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
NOC_WHISPER_MODEL_PATH=/opt/noc-dashboard/models/whisper
NOC_WHISPER_MODEL=tiny
NOC_VOICE_ENABLED=true
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

Le dashboard et ses actions web restent accessibles directement, sans saisie de jeton. Le contrôle WhatsApp utilise le numéro autorisé et le secret du webhook ; les agents VPS conservent leur jeton.

### Compte moctar et permissions du modèle

Les services existants continuent à fonctionner sous leur compte actuel, y compris `moctar`. L'installateur principal conserve le **User et le Group non-root déjà configurés** pour le NOC, puis adapte les droits des fichiers et sudoers à ces valeurs. Une installation neuve utilise `noc-dashboard`. Il ne crée ni ne remplace le compte d'une installation existante ; une ancienne unité exécutée sous root est refusée pour éviter toute migration implicite. Si `moctar` existe, le modèle reste propriétaire `moctar:moctar` et l'installation vocale accorde la lecture au véritable compte du NOC par groupe/ACL ou permissions adaptées. Les dossiers parents doivent également être traversables par ce compte.

```bash
sudo systemctl show noc-dashboard.service --property=User --property=Group
sudo systemctl show klasora-whatsapp.service --property=User --property=Group
NOC_SERVICE_USER="$(sudo systemctl show noc-dashboard.service --property=User --value)"
sudo -u "$NOC_SERVICE_USER" test -x /opt/noc-dashboard/voice-venv/bin/python
sudo -u "$NOC_SERVICE_USER" test -r /opt/noc-dashboard/models/whisper/model.bin
sudo -u "$NOC_SERVICE_USER" test -r /opt/noc-dashboard/models/whisper/config.json
sudo -u "$NOC_SERVICE_USER" test -r /opt/noc-dashboard/models/whisper/tokenizer.json
namei -l /opt/noc-dashboard/models/whisper/model.bin
curl --fail --silent http://127.0.0.1:5050/api/voice/status | python3.11 -m json.tool
```

Ces chemins suivent les nouveaux défauts ; utilisez votre chemin configuré s'il diffère. `/api/voice/status` expose `status`, `reason`, `model`, `model_path`, `download_available` et `webhook_configured`. Un modèle absent ou illisible produit un diagnostic sans bloquer la collecte. Si le venv dédié ne contient pas `faster_whisper`, le backend vérifie aussi le Python qui exécute le dashboard. Rechargez l'interface avec **Ctrl+F5** après mise à jour. Aucun déploiement sur le Dell n'a été exécuté depuis cet environnement Windows.

## 2. Configurer le webhook de la passerelle WhatsApp

### Livraison sortante et actions web directes

Lorsque la passerelle propose uniquement `POST /session/:ecoleId/send`, le nouvel alias `/message/send` réutilise ses sessions existantes. Le NOC envoie exactement `{to,text}` avec `X-Gateway-Secret: NOC_GATEWAY_SECRET`. L'alias utilise la session configurée si elle est connectée, sinon la première session connectée ; il accepte aussi `message` comme texte. Il confirme le succès uniquement après `sock.sendMessage`, conserve la route d'origine et ne crée aucune connexion Baileys supplémentaire.

Depuis le checkout Git du Dell :

```bash
git pull --ff-only && sudo python3.11 tools/deploy_dashboard_update.py --apply
```

Le script installe les fichiers du NOC et injecte l'alias dans `/opt/klasora/app/whatsapp-server/server.js`, **avant** l'enregistrement de `/session/:ecoleId/send`. Il conserve les autres routes, les secrets et les comptes systemd. Il sauvegarde les fichiers remplacés, synchronise le secret d'envoi de `/etc/noc-dashboard.env` avec la passerelle, vérifie les sources et l'import sous le compte de la passerelle, puis redémarre uniquement `noc-dashboard.service` et `klasora-whatsapp.service`. La disponibilité de l'alias est vérifiée avec un corps invalide authentifié pour ne pas envoyer de message. Une route ou un Map `sessions` non reconnu est refusé avant modification. Les fichiers écrits par le script sont restaurés si les services ne reviennent pas. Même lorsque `git pull` a déjà remplacé les sources directement sous `/opt`, le script redémarre les services.

Le délai de réponse Python est de dix secondes (`NOC_WHATSAPP_SEND_TIMEOUT=10`), supérieur à la limite de huit secondes de l'alias. Un envoi expiré n'est pas réessayé automatiquement pour éviter un doublon. Envoyez ensuite `statut` depuis le numéro administrateur pour vérifier la livraison réelle.

Les actions de redémarrage web s'exécutent **en un clic**, sans jeton, prompt ou confirmation. Les boutons restent verrouillés pendant la requête et le délai de 30 secondes. `NOC_ENABLE_RESTART=false` désactive toujours les redémarrages ; seules les quatre applications autorisées sont accessibles. Les appels issus d'une autre page sont refusés par Origin et Fetch Metadata. La simulation vocale fonctionne aussi directement et reste sans effet sur les services. Les secrets machine de WhatsApp et des agents VPS restent requis sur leurs canaux. Une ancienne valeur `NOC_ADMIN_TOKEN` peut rester dans l'environnement ; elle ne bloque plus ces actions web.

### Réparer le relais existant sans éditeur

Le diagnostic fourni montre `POST {sender,message}` refusé avec « Émetteur non autorisé ». Dans cette version, l'ancien backend lisait `from` ou `key.remoteJid`, donc le champ `sender` était absent de la comparaison. Le POST audio lisait `X-WhatsApp-From`, alors que le relais utilisait `X-Sender`. Les deux variantes sont désormais prises en charge ; les valeurs contradictoires restent refusées.

Le bloc Node communiqué avait également un numéro admin **codé en dur pour tous les expéditeurs**, aucun ID Baileys et une référence `audioMsg` non définie. Le [script de réparation](tools/repair_whatsapp_contract.py) reconnaît uniquement ce bloc précis et le remplace par le bridge borné. Une source différente ou plusieurs blocs sont refusés avant toute modification. Il conserve les autres gestionnaires, les comptes systemd, les secrets existants et le code Python hors des fonctions corrigées.

Transférez l'archive actuelle sur le Dell, puis exécutez en une passe :

```bash
tar -xzf "$HOME/noc-dashboard.tar.gz" -C "$HOME"
cd "$HOME/noc-dashboard"
sudo python3.11 tools/repair_whatsapp_contract.py --apply --probe
```

Sans `--apply`, le script effectue uniquement la préparation. Avec `--apply`, il sauvegarde les fichiers dans `/var/backups/noc-dashboard/whatsapp-relay-*`, valide Python/Node et l'export Baileys, synchronise le secret entrant de `/etc/noc-dashboard.env` vers un fichier privé de la passerelle, puis redémarre **seulement** `noc-dashboard.service` et `klasora-whatsapp.service`. Le secret d'envoi `NOC_GATEWAY_SECRET` reste inchangé. Il vérifie le NOC et la ligne `NOC relay ready` de la nouvelle invocation systemd ; un échec restaure les fichiers et tente de rétablir l'état précédent des deux services. `--probe` poste une seule commande `statut` au backend avec un ID unique et affiche séparément réception, traitement et livraison HTTP. Ce test direct ne simule pas une réception WhatsApp : envoyez ensuite un message texte et une note vocale depuis le téléphone administrateur.

Les champs `myPN: 212684056613:38@s.whatsapp.net` et `myLID` du journal désignent **le bot**, pas l'administrateur. Un suffixe d'appareil `:38` est retiré uniquement d'un JID personnel valide. Pour un LID entrant, le bridge utilise `remoteJidAlt` ou la correspondance locale [`getPNForLID` de Baileys](https://github.com/WhiskeySockets/Baileys/blob/master/src/Signal/lid-mapping.ts) avant de vérifier exactement `212770010264`. Un LID sans correspondance est refusé et n'est jamais converti arbitrairement en numéro.

L'identifiant Baileys reste obligatoire : `id`, `messageId`, ou `X-Message-Id`. Un appel curl `{sender,message}` sans ID répond maintenant `422`, et non `403` ; ne générez pas un nouvel ID à chaque reprise d'une même commande. Exemple valide, avec jeton lu sans l'afficher :

```bash
NOC_WEBHOOK_TOKEN="$(sudo sed -n 's/^NOC_WHATSAPP_WEBHOOK_TOKEN=//p' /etc/noc-dashboard.env)"
NOC_MESSAGE_ID="$(python3.11 -c 'import uuid; print(uuid.uuid4().hex)')"
{
  printf 'header = "X-Gateway-Secret: %s"\n' "$NOC_WEBHOOK_TOKEN"
  printf 'header = "X-Message-Id: %s"\n' "$NOC_MESSAGE_ID"
} | curl --config - --fail-with-body --silent --show-error \
    --header 'Content-Type: application/json' \
    --data '{"sender":"212770010264","message":"statut"}' \
    http://127.0.0.1:5050/api/whatsapp/webhook
unset NOC_WEBHOOK_TOKEN NOC_MESSAGE_ID
```

Le POST répond `{accepted,duplicate}` ; la réponse finale est envoyée plus tard par le NOC à `/message/send`. Le bloc `server.js` fourni ne lit pas le corps de la réponse HTTP : rien ne prouve un conflit `reply`/`text` dans ce bloc. `last_command.status=completed` avec `reply_sent=false` indique un problème sur le chemin de retour (route ou secret d'envoi), tandis qu'une transcription en échec apparaît dans `last_command.response`. Le `403` observé arrive **avant** l'audio et ne constitue pas un échec Whisper.

### Bridge Baileys pour les notes vocales réelles

L'URL `mmg.whatsapp.net` d'un `audioMessage` contient un blob chiffré. Le module [integrations/baileys-noc.cjs](integrations/baileys-noc.cjs) réutilise `downloadMediaMessage` de la **version Baileys déjà installée**, avec le mode `stream`, puis envoie l'audio déchiffré au NOC. Ce mode et `sock.updateMediaMessage` sont décrits dans la [documentation Baileys](https://github.com/WhiskeySockets/docs/blob/main/messaging/media-messages.mdx). Aucun nouveau paquet Node n'est nécessaire.

Installez le bridge dans un emplacement lisible par la passerelle, même sous `moctar` :

```bash
cd "$HOME/noc-dashboard"
sudo install -d -o root -g root -m 0755 /usr/local/lib/noc-integrations
sudo install -o root -g root -m 0644 integrations/baileys-noc.cjs /usr/local/lib/noc-integrations/baileys-noc.cjs
sudo systemctl show klasora-whatsapp.service --property=WorkingDirectory --property=ExecStart
```

Chargez seulement le secret privé entrant et le numéro administrateur dans la passerelle. Conservez son secret de réponses et ses paramètres actuels :

```bash
NOC_WEBHOOK_TOKEN="$(sudo sed -n 's/^NOC_WHATSAPP_WEBHOOK_TOKEN=//p' /etc/noc-dashboard.env)"
NOC_ADMIN_PHONE="$(sudo sed -n 's/^ADMIN_PHONE_NUMBER=//p' /etc/noc-dashboard.env)"
if sudo test ! -e /etc/klasora-whatsapp-noc.env; then
  sudo install -o root -g root -m 0600 /dev/null /etc/klasora-whatsapp-noc.env
fi
{
  printf 'NOC_WHATSAPP_WEBHOOK_TOKEN=%s\n' "$NOC_WEBHOOK_TOKEN"
  printf 'ADMIN_PHONE_NUMBER=%s\n' "$NOC_ADMIN_PHONE"
} | sudo tee /etc/klasora-whatsapp-noc.env >/dev/null
unset NOC_WEBHOOK_TOKEN NOC_ADMIN_PHONE
sudo systemctl edit klasora-whatsapp.service
```

Ajoutez uniquement ce bloc dans l'override, sans changer `User` ni réinitialiser les paramètres existants :

```ini
[Service]
EnvironmentFile=/etc/klasora-whatsapp-noc.env
```

Après création du socket **sock** de la session 1 dans le code de la passerelle, réutilisez son export Baileys `downloadMediaMessage` et ajoutez :

```javascript
const { attachNocWebhook } = require('/usr/local/lib/noc-integrations/baileys-noc.cjs');
let detachNocWebhook = () => {};
try {
  detachNocWebhook = attachNocWebhook(sock, {
    downloadMediaMessage,
    adminPhone: process.env.ADMIN_PHONE_NUMBER,
    sessionId: '1',
    webhookToken: process.env.NOC_WHATSAPP_WEBHOOK_TOKEN,
    baseUrl: 'http://127.0.0.1:5050'
  });
} catch {
  console.warn('NOC vocal non branché : vérifier la configuration privée du bridge.');
}
sock.ev.on('connection.update', update => {
  if (update.connection === 'close') detachNocWebhook();
});
```

Dans une passerelle ESM, importez le module `.cjs` avec l'interopérabilité existante et réutilisez le même export Baileys déjà chargé. Gardez tous les gestionnaires actuels : le bridge ajoute un listener `messages.upsert` indépendant ; `detachNocWebhook()` retire seulement ce listener. Ne réinstallez pas Baileys et ne remplacez pas la connexion des autres sessions.

```bash
sudo systemctl daemon-reload
sudo systemctl restart klasora-whatsapp.service
sudo systemctl status klasora-whatsapp.service --no-pager
sudo journalctl -u klasora-whatsapp.service -n 30 --no-pager
```

Seuls les événements nouveaux `notify`, le numéro administrateur et les messages entrants directs de la session configurée sont acceptés. `fromMe`, groupes, historiques et autres numéros sont ignorés. Les JID avec suffixe d'appareil et les LID avec numéro alternatif Baileys sont pris en charge. La file accepte huit messages en attente, avec un seul traitement actif ; le cache de doublons garde au plus 256 IDs. L'audio est limité **pendant le streaming** à 8 Mio, sans gros buffer global. Deux essais HTTP au maximum gardent le même ID ; aucune redirection n'est suivie et les secrets ne sont pas journalisés. Un téléchargement Baileys qui reste bloqué suspend cette file jusqu'à sa résolution, sans accumuler des tâches orphelines.

### Webhook JSON compatible

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
{"to":"212770010264","text":"État de l'infrastructure…"}
```

Les messages sortants `fromMe:true` sont ignorés. Les autres numéros, groupes et sessions sont refusés. Un header de webhook invalide répond `403`; un canal non configuré répond `503`. Les identifiants de message servent à éviter les doublons; une file limitée et un worker unique empêchent les traitements audio simultanés.

Le format générique `{id,from,text}` ou `{id,from,audio:{path|url,mimetype}}` est également accepté. Une URL audio doit désigner `http://127.0.0.1:3001/media/...` ou `/uploads/...`, sans redirection. Le média doit être déjà déchiffré par la passerelle. Les blobs `base64` et les URLs WhatsApp externes ne sont pas téléchargés par le NOC.

Pour des fichiers locaux, renseignez `NOC_WHATSAPP_MEDIA_DIR` avec le dossier exact de médias de la passerelle, lisible par le véritable User du service NOC. Les fichiers OGG, Opus, MP3 et WAV doivent rester dans ce dossier et les liens symboliques sont refusés. Les notes sont limitées à 8 Mio et 60 secondes; la copie temporaire et le WAV mono 16 kHz sont supprimés après traitement. La transcription tiny multilingue utilise le filtre VAD de détection de parole pour écarter les silences.

### Routes et vérifications sans action réelle

| Route | Fonction |
| --- | --- |
| `GET /api/overview` | Alias de `/api/snapshot` |
| `GET /events` | Alias SSE de `/api/stream` |
| `GET /api/voice/status` | Diagnostic et disponibilité du modèle / canal vocal |
| `POST /api/voice/webhook` | JSON normalisé, alias de `/api/whatsapp/webhook` |
| `POST /api/voice/process` | Audio brut déchiffré, ou JSON normalisé compatible |
| `POST /api/voice/simulate` | Analyse directe depuis le navigateur, toujours en simulation |

Le POST audio accepte `audio/ogg`, `audio/opus`, `audio/mpeg`, `audio/wav` et `application/octet-stream`. Ses headers obligatoires sont `X-Gateway-Secret` (valeur de **NOC_WHATSAPP_WEBHOOK_TOKEN**, différente de `NOC_GATEWAY_SECRET`), `X-WhatsApp-From`, `X-Message-Id` et `X-Session-Id`. Le bridge envoie l'audio sur `/api/voice/process` et le texte sur `/api/voice/webhook`. Un upload accepté produit `202`, puis le résultat arrive dans le SSE ; le webhook JSON normalisé garde sa réponse `200`.

La simulation ci-dessous ne redémarre **jamais** de service et n'envoie aucune réponse WhatsApp, même pour `restart babamarket`. Elle ne demande aucun jeton :

```bash
curl --fail --silent http://127.0.0.1:5050/api/overview | python3.11 -m json.tool
curl --silent --no-buffer --max-time 7 http://127.0.0.1:5050/events || test "$?" -eq 28
curl --fail --silent http://127.0.0.1:5050/api/voice/status | python3.11 -m json.tool
curl --fail --silent --show-error --header 'Content-Type: application/json' \
    --data '{"text":"restart babamarket"}' http://127.0.0.1:5050/api/voice/simulate
```

Pour un test réel de transcription, enregistrez seulement **« statut »** dans un fichier OGG. Ce test traite la note puis répond sur WhatsApp. Fournissez un fichier existant avec `--data-binary`, sans JSON, base64 ni multipart :

```bash
read -r -p 'Chemin du fichier OGG enregistré : ' NOC_AUDIO_FILE
NOC_WEBHOOK_TOKEN="$(sudo sed -n 's/^NOC_WHATSAPP_WEBHOOK_TOKEN=//p' /etc/noc-dashboard.env)"
NOC_ADMIN_PHONE="$(sudo sed -n 's/^ADMIN_PHONE_NUMBER=//p' /etc/noc-dashboard.env)"
NOC_SESSION_ID="$(sudo sed -n 's/^NOC_WHATSAPP_SESSION_ID=//p' /etc/noc-dashboard.env)"
NOC_SESSION_ID="${NOC_SESSION_ID:-1}"
NOC_MESSAGE_ID="$(python3.11 -c 'import uuid; print(uuid.uuid4().hex)')"
{
  printf 'header = "X-Gateway-Secret: %s"\n' "$NOC_WEBHOOK_TOKEN"
  printf 'header = "X-WhatsApp-From: %s@s.whatsapp.net"\n' "$NOC_ADMIN_PHONE"
  printf 'header = "X-Message-Id: %s"\n' "$NOC_MESSAGE_ID"
  printf 'header = "X-Session-Id: %s"\n' "$NOC_SESSION_ID"
} | curl --config - --fail --silent --show-error --header 'Content-Type: audio/ogg' \
  --data-binary "@$NOC_AUDIO_FILE" http://127.0.0.1:5050/api/voice/process
unset NOC_WEBHOOK_TOKEN NOC_ADMIN_PHONE NOC_SESSION_ID NOC_MESSAGE_ID NOC_AUDIO_FILE
```

Suivez ensuite `/events` et la carte Voice-to-Action pour la transcription et le résultat. Dans le dossier source, `node --test tests/test_baileys_noc.cjs` vérifie le bridge avec Baileys simulé et un serveur HTTP loopback, sans envoyer de message WhatsApp réel.

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

Le script comporte un délai interne de 280 secondes. `sudo` est accordé uniquement au chemin exact `/usr/local/bin/backup-babamarket.sh`, sans argument. Un `NOC_BACKUP_SCRIPT` personnalisé est exécuté avec les droits du User du service NOC, sans nouvelle permission root; il doit être exécutable, appartenir à root et être non modifiable, tout comme ses dossiers parents. Un chemin absent produit une réponse claire et ne bloque pas le collecteur.

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

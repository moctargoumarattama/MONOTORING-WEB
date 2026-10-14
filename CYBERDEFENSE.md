# Console Honeypot locale

Les fichiers complets sont [main.py](main.py), [cyberdefense.py](cyberdefense.py), [config.py](config.py) et [static/index.html](static/index.html). Le nouveau module utilise uniquement la bibliothèque standard Python. Les contrôles WhatsApp, les sondes et Sentinel restent dans leurs modules existants.

## Utilisation

Cliquez sur **>_** ou **IP BLOQUÉES** dans le radar. La modale affiche le simulateur, les bannissements du dashboard, les recommandations locales et les 60 dernières minutes d'activité. Ses données sont publiées dans `snapshot.cyber` sur le même flux SSE ; aucune actualisation de page n'est nécessaire.

Le simulateur sélectionne une adresse réservée `198.51.100.x`, indiquée **TEST**. Il ne bannit jamais l'adresse de votre navigateur ni celle du VPS. Les tests sont conservés avec les autres entrées, mais exclus des compteurs de blocage réels. L'analyse des exercices est présentée séparément du score des scans publics.

Les adresses publiques touchant une route piège sont bannies **dans l'application NOC sur le Dell** : leurs requêtes suivantes sont refusées par le middleware HTTP. Les adresses locales/privées, loopback, Tailscale et le VPS `187.77.171.225` sont protégées. Le bouton **Débannir** retire uniquement ce blocage applicatif. Les incidents Sentinel VPS apparaissent en lecture seule ; supprimer une entrée locale ne retire aucune règle du pare-feu distant.

L'audit est un algorithme heuristique local : recherche de secrets, scans WordPress/phpMyAdmin, diversité et répétition des chemins. Le score indique une suspicion sur les tentatives observées ; ce n'est pas une mesure de précision de détection. **Générer les règles** produit des propositions de corrélation lisibles, sans installer de règle système ni publier de vrai secret ou honeytoken.

## Routes

| Méthode | Route | Comportement |
| --- | --- | --- |
| GET / POST | `/wp-login.php`, `/wp-admin`, `/wp-admin.php`, `/.env`, `/phpmyadmin`, `/actuator/env`, `/api/config` | Enregistrer l'IP de la connexion et appliquer le filtre local si elle n'est pas protégée. Les variantes avec `/` final sont acceptées. |
| GET | `/api/cyber/banned-ips` | État complet de la console : IP, dates, motifs, trafic, audit, persistance. |
| POST | `/api/cyber/simulate` | JSON `{"path":"/.env"}` ; adresse de test attribuée par le serveur. |
| DELETE | `/api/cyber/unban/{ip}` | Retirer le bannissement local ; IP IPv4/IPv6 validée. |
| POST | `/api/cyber/audit` | Recalculer les recommandations et les propositions de règles. |
| GET | `/api/cyber/export` | Télécharger l'état et le journal borné au format JSON. |

Les actions du navigateur utilisent les contrôles d'origine déjà présents, sans saisie de jeton. Le POST de simulation n'accepte ni URL arbitraire ni IP à cibler. Les journaux ne stockent pas les corps reçus sur les pièges ni les secrets WhatsApp/VPS.

## Persistance et service systemd

Le chemin par défaut est `/var/lib/noc-dashboard/blocked_ips.json`, configurable par `NOC_CYBER_STATE_PATH`. Le fichier est créé au premier événement et remplacé atomiquement, avec synchronisation disque, sous le compte du NOC. Il conserve jusqu'à 512 entrées et les 256 dernières tentatives. Un fichier invalide ou une erreur de permissions produit un diagnostic dans la console ; la disponibilité du dashboard est conservée.

Cet emplacement utilise le `StateDirectory=noc-dashboard` existant. `/opt/noc-dashboard` est en lecture seule dans l'unité actuelle ; y placer le JSON empêcherait la sauvegarde. Les répertoires d'état déclarés par systemd sont exclus du mode lecture seule de `ProtectSystem=strict`. [Documentation systemd](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).

`NOC_CYBER_PROTECTED_IPS` ajoute des IP à protéger, séparées par des virgules. Les protections locales et celle du VPS actuel restent actives. Le lancement fourni désactive la réécriture des IP par les headers de proxy afin qu'un `X-Forwarded-For` forgé ne fasse pas bannir une autre personne. [Configuration Uvicorn](https://www.uvicorn.org/settings/).

Avec un reverse proxy local, le NOC voit l'IP locale du proxy : les scans sont enregistrés comme provenant d'une adresse protégée. Le bannissement d'IP externes nécessite alors une intégration explicite avec le proxy ; ce module ne fait pas confiance aux headers arbitraires. Conservez une seule instance/worker, comme le service existant.

## Mise à jour ciblée sur le Dell

Depuis les sources actualisées dans un dossier **distinct** de `/opt/noc-dashboard`, après transfert de l'archive complète :

```bash
bash -euo pipefail <<'NOC_CYBER_DEPLOY'
test "$(pwd -P)" != /opt/noc-dashboard
NOC_CYBER_USER="$(sudo systemctl show noc-dashboard.service --property=User --value)"
NOC_CYBER_GROUP="$(sudo systemctl show noc-dashboard.service --property=Group --value)"
test -n "$NOC_CYBER_USER" && test "$NOC_CYBER_USER" != root
if test -z "$NOC_CYBER_GROUP"; then NOC_CYBER_GROUP="$(id -gn "$NOC_CYBER_USER")"; fi
sudo install -d -o root -g root -m 0700 /var/backups/noc-dashboard
NOC_CYBER_BACKUP="$(sudo mktemp -d /var/backups/noc-dashboard/cyber-XXXXXXXX)"
sudo cp -p /opt/noc-dashboard/main.py /opt/noc-dashboard/config.py "$NOC_CYBER_BACKUP/"
sudo cp -p /opt/noc-dashboard/static/index.html "$NOC_CYBER_BACKUP/index.html"
if sudo test -f /opt/noc-dashboard/cyberdefense.py; then sudo cp -p /opt/noc-dashboard/cyberdefense.py "$NOC_CYBER_BACKUP/"; fi
sudo install -d -o "$NOC_CYBER_USER" -g "$NOC_CYBER_GROUP" -m 0750 /var/lib/noc-dashboard
sudo install -o root -g "$NOC_CYBER_GROUP" -m 0640 main.py config.py cyberdefense.py /opt/noc-dashboard/
sudo install -o root -g "$NOC_CYBER_GROUP" -m 0640 static/index.html /opt/noc-dashboard/static/index.html
sudo systemctl restart noc-dashboard.service
curl --retry 4 --retry-connrefused --retry-delay 1 --fail http://127.0.0.1:5050/api/cyber/banned-ips
NOC_CYBER_DEPLOY
```

La configuration `/etc/noc-dashboard.env`, le compte du service et le pare-feu ne sont pas remplacés par ces commandes. L'installateur complet et le script de mise à jour existant incluent également le nouveau module.

## Vérification sans bannir le poste administrateur

```bash
curl --fail -X POST http://127.0.0.1:5050/api/cyber/simulate \
  -H 'Content-Type: application/json' -d '{"path":"/.env"}'
curl --fail http://127.0.0.1:5050/api/cyber/banned-ips
curl --fail -X DELETE http://127.0.0.1:5050/api/cyber/unban/198.51.100.1
```

L'adresse attribuée figure dans le retour `ip` ; remplacez `198.51.100.1` par cette valeur si des exercices existent déjà. Ne testez pas les bannissements réels en utilisant l'accès public de votre poste administrateur : utilisez le simulateur ou les tests automatisés.

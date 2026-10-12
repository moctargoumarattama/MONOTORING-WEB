# Vérifications de livraison — 13 octobre 2026

Projet développé dans un dossier vide, sous Windows avec Python 3.11.9. Aucun projet existant ni service applicatif de production n'a été modifié.

- 37 tests automatisés `unittest` réussis : droits d'accès, cookies signés, expiration des sessions SSE, validation et limites des rapports VPS, états périmés, limite des connexions, redémarrages limités aux quatre unités, gestion des erreurs, nettoyage des processus et reprise du collecteur.
- Instance Uvicorn réelle : `/api/health` et `/api/snapshot` répondent ; `/api/stream` transmet des snapshots JSON successifs toutes les deux secondes. Le premier snapshot est transmis immédiatement, donc le délai avant le suivant dépend de la phase de collecte.
- Chrome réel : affichage à 1440 × 1100 et 390 × 844, sans débordement horizontal ni erreur JavaScript. Voir `preview.png` et `preview-mobile.png` : mesures réelles du PC Windows, services Linux absents et signalés indisponibles.
- Parcours navigateur vérifié sur une instance isolée : mauvais jeton refusé, connexion réussie, cookie `HttpOnly` et `SameSite=Strict`, actions désactivées sur Windows, réception SSE d'un rapport VPS de test, pause du journal, déconnexion et effacement des données affichées.
- Syntaxe Bash de l'installateur, compilation Python, JavaScript et cohérence des dépendances vérifiées. Les fichiers utilisent UTF-8 et des fins de ligne LF.
- Agent VPS : cinq contrôles avec `/proc` et Linux simulés, portant sur le delta CPU, le format RAM/disque, les services, la validation de la configuration et le refus des redirections.

## Vérifications restantes sur le Dell

L'installation réelle systemd, sudoers, les capteurs matériels et la passerelle WhatsApp doivent être contrôlés sur le Dell Ubuntu avec les commandes du README. Aucun accès SSH au Dell n'était fourni ; aucune installation distante n'a été effectuée.

Le RSS observé du backend sous Windows est d'environ **60 MiB**. La contrainte **inférieure à 50 Mo** n'est donc pas certifiée : elle doit être mesurée sur Ubuntu avec les VPS et navigateurs habituels. Le code expose son RSS et systemd permet de mesurer l'ensemble du groupe du service. Aucun plafond artificiel susceptible de tuer le collecteur n'est imposé.

## Reproduire les tests dans le dossier source

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tests\check_runtime.py
```

La dernière commande suppose une instance locale démarrée. Si la consultation est protégée, définissez `NOC_VIEW_TOKEN` dans l'environnement du terminal de test.

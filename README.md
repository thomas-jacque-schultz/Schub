# Schub

La boîte à outils de la communauté Discord Miam : serveurs de jeu démarrés à la demande depuis le
site ou Discord, et outillage des équipes League of Legends (statistiques, pool de champions,
préparation de draft, revue d'après-partie).

En ligne sur [schultz-thomas.fr](https://schultz-thomas.fr).

## Dépôts

| Sous-module | Rôle |
|---|---|
| `schub-front-servers` | SPA React bilingue |
| `schub-back-bff` | BFF : session, droits, proxy vers le cœur |
| `schub-core` | Domaine : identité, serveurs de jeu, ports, équipes LoL |
| `schub-connector-discord` | Bot Discord |
| `schub-connector-portainer` | Démarrage, arrêt et sonde des stacks |
| `schub-connector-freebox` | Redirections de ports de la box |
| `schub-connector-riot` | API Riot Games : collecte, cache, statistiques |

L'architecture et son historique : `docs/migration-microservices.md` et `docs/evolutions-2026-09.md`.

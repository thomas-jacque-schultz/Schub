# Schub

Le dépôt parent de deux produits, qui partagent un cœur, un BFF et un front :

- **Schub** (schultz-thomas.fr) : les serveurs de jeu de la communauté Discord Miam, démarrés à la demande depuis le site ou Discord, et l'administration.
- **PremadeLab** (premadelab.eu) : l'analyse de parties League of Legends pour un joueur et son équipe, le Macro Planner et les mini-jeux.

## Les dépôts

| Sous-module | Rôle |
|---|---|
| `schub-front-servers` | les applications web de Schub, de PremadeLab et des mini-jeux |
| `schub-back-bff` | le BFF : session, droits, relais vers le cœur |
| `schub-core` | le domaine des deux produits |
| `schub-connector-discord` | le bot Discord de Schub |
| `schub-connector-discord-premadelab` | les messages privés de l'application Discord PremadeLab |
| `schub-connector-riot` | l'API Riot Games : collecte, quota et cache |
| `schub-connector-freebox` | les redirections de ports du routeur |
| `schub-connector-portainer` | les stacks des serveurs de jeu |
| `schub-together-games` | le relais WebSocket des mini-jeux et du Macro Planner |

L'infrastructure vit dans `schub-infra-docker`. `docs/` garde le plan des évolutions et la découpe en microservices, datés. Le suivi est dans le [projet GitHub](https://github.com/users/thomas-jacque-schultz/projects/1).

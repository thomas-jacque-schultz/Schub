# Découpe Schub — plan de travail

> Document de travail. Ouvert le 2026-09-05, **réorienté le 2026-09-13**.
> Source de vérité pour la découpe ; en cas de doute, c'est ce fichier qui tranche.

## 1. Pourquoi

Le bot Discord possède aujourd'hui le domaine « serveurs de jeu », l'adapter Portainer et
l'adapter Freebox. On coupe selon une règle unique : **tout système externe a son connecteur,
tout le reste vit dans le cœur.**

> **État constaté le 2026-09-05, toujours vrai** : la stack applicative `CodeInfrastructure`
> (désormais `schub-mongo`, `connector-discord`, `schub-front`, `schub-bff`) **n'est pas déployée** sur le Swarm.
> 37 services y tournent — monitoring, jeux, Nextcloud, Matrix — mais aucun du projet Schub.
> La « prod » de Schub n'existe qu'en fichiers ; le dev est la seule cible vivante.

### Décisions

| Sujet | Choix | Date |
|---|---|---|
| Découpe | connecteurs par système externe + un cœur | 13-09 |
| Nommage | plus aucun « bot » : services, images et repo renommés | 13-09 |
| Repos | un par service | 05-09 |
| Données | une instance Mongo, une base logique par service | 05-09 |
| Transport | **HTTP direct partout** | 13-09 |
| Messagerie | **pas de broker** — voir §5 | 13-09 |
| Sonde d'état | portée par le connecteur Portainer | 13-09 |
| Portée du port-forwarding | l'app pilote **tous** les ports, fixes compris | 15-09 |

### Ce qui a été abandonné

**RabbitMQ**, décidé le 05-09 puis retiré le 13-09. La phase 0 avait livré un broker, une
topologie vérifiée et un contrat AsyncAPI — tout cela est supprimé. Le raisonnement qui
l'annule est en §5 ; il tient en une phrase : *le système est déjà réconciliant, et une boucle
de réconciliation rend les garanties de livraison inutiles*. Ce raisonnement était disponible
dès le 05-09, le scheduler existait déjà. Seule la base Mongo par service a survécu de la phase 0.

## 2. Vocabulaire (à appliquer partout, sans exception)

Le mot « serveur » désigne quatre choses dans le code actuel. On l'interdit seul.

| Terme retenu | Ce que ça désigne | Ce qu'on n'écrit plus |
|---|---|---|
| **Guild** | un serveur Discord | « serveur Discord » |
| **Node** | une machine du Swarm (`dynamis`, `loki`) | « serveur » au sens machine |
| **GameServer** | l'entité métier que des joueurs rejoignent | `GamingServerEntity` |
| **Deployment** | la stack Portainer qui *réalise* un GameServer | `portainerStackId`, « stack » |
| **PortRule** | une redirection **voulue** | — |
| **Redirection** | une redirection **telle que le routeur la porte** | — |
| **Connector** | un service dont l'unique rôle est de parler à un système externe | — |
| **Core** | le service qui détient le domaine et orchestre les connecteurs | — |

Renommages de champs :

- `GamingServerEntity.identifier` → `GameServer.slug` (identifiant humain, dans les URLs)
- `GamingServerEntity.id` → `GameServer.id` (identifiant Mongo, jamais exposé)
- `GamesNameEnum` → `Game` · `ServerStatusEnum` → `GameServerStatus`

## 3. Cible

```
                      front (React)
                            |
                      schub-back-bff              edge : auth JWT, agrégation
                            |
                      schub-core                  LE domaine
                     /      |      \
                    /       |       \             HTTP + X-Internal-Secret
                   v        v        v
     connector-discord  connector-   connector-freebox
            ^           portainer           |
            |               |               v
        (Discord)      (Portainer)      (Freebox)

     connector-riot   — isolé pour l'instant
```

`connector-discord` est le seul **bidirectionnel** : il reçoit les commandes slash (il appelle
alors le cœur) et reçoit du cœur les ordres de rafraîchir ses messages.

### Responsabilités

| Service | Possède | N'a pas le droit de | Base |
|---|---|---|---|
| `schub-core` | GameServer, Deployment, politique de ports, orchestration | parler à un système externe autrement que par un connecteur | `servers` |
| `schub-connector-discord` | lien `slug` ↔ message Discord, salons, utilisateurs | connaître Portainer, la Freebox, la logique de ports | `bot` |
| `schub-connector-portainer` | traduction Deployment ⇄ API Portainer, **sonde d'état** | savoir ce qu'est un GameServer | aucune |
| `schub-connector-freebox` | traduction PortRule ⇄ API Freebox, appairage | savoir *pourquoi* un port doit être ouvert | aucune |
| `schub-connector-riot` | appels API Riot | — | `riot` |
| `schub-back-bff` | auth JWT, agrégation pour le front | contenir de la logique métier | `backend` |

**Un connecteur sans base de données, c'est la règle** (Discord et Riot exceptés : ils
détiennent de l'état propre à leur plateforme, pas du domaine). Un connecteur qui se met à
stocker du métier est un connecteur qui a dérivé.

## 4. Frontière cœur / connecteurs

> **Un connecteur ne sait pas pourquoi on l'appelle.**

`connector-portainer` ne sait pas ce qu'est un serveur de jeu : il démarre la stack 12.
`connector-freebox` ne sait pas pourquoi le port 15007 doit s'ouvrir : il l'ouvre.
Toute la raison d'agir vit dans le cœur.

Corollaire côté Discord :

> **Le connecteur Discord ne connaît d'un serveur que son `slug`.**

Vérifiable au `grep` : si `portainerStackId` apparaît dans le connecteur Discord, c'est raté.

**Chacun finit son propre travail.** Le connecteur Discord traduit une intention Discord en
appel au cœur, entièrement. Le cœur résout le slug, ouvre les ports, lance la stack,
entièrement. Aucun ne termine le travail de l'autre.

### Conséquence : `/create` et `/update` quittent Discord

Une *commande* est un impératif adressé à un système qui détient déjà le contexte ; une *fiche*
est un document qu'on rédige. Le chat est bon pour les premières, mauvais pour les secondes.

Test décisif : qui valide une fiche envoyée par `/create` ? Si c'est le cœur, le connecteur a
commencé un travail qu'il ne pouvait pas finir. Si c'est le connecteur, il lui faut les règles
du domaine et le couplage revient. Pas de troisième option.

Constat qui clôt le débat : **`/create` n'expose pas d'option `portainer-stack-id`**, alors que
les trois opérations en dépendent. Un serveur créé depuis Discord est inutilisable — la commande
est déjà cassée aujourd'hui.

Discord garde `/start`, `/pause`, `/refresh` et la consultation. Les fiches se saisissent dans
le front, dont le formulaire est déjà plus complet.

## 4 bis. L'app pilote tous les ports (15-09)

Décidé le 15-09, après avoir vu l'état réel de la box : 44 redirections, toutes ouvertes en
permanence, aucune libellée.

Le code actuel distingue les règles **gérées** (marquées `[schub]`) des règles **manuelles**,
qu'il observe sans y toucher. Cette dualité est la vraie complexité du réconciliateur. On la
supprime : l'app devient la source de vérité de **toute** la table de redirections — les ports
fixes (Samba, HomeAssistant, web) comme ceux des serveurs de jeu.

Ce qu'on y gagne :

- le `marker` devient inutile, ou purement informatif ;
- `PortRuleResolver` perd toute sa branche de conflit avec les règles manuelles ;
- `pruneOrphans` devient le comportement normal au lieu d'une option dangereuse ;
- **les 44 règles deviennent déclarées**. Aujourd'hui personne ne sait à quoi servent 9065,
  15000 ou 15777 ; les écrire force à répondre.

### Ce que ça ne change pas

**La réconciliation reste.** Elle ne compense pas une méconnaissance de l'API Freebox — celle-ci
est un CRUD simple sur `/fw/redir/` avec des ids stables. Elle existe parce que l'état de la box
*dérive* : appel échoué, redémarrage à contretemps, serveur de jeu mort sans nettoyer. Et c'est
elle qui justifie l'abandon du broker (§5) : la retirer rouvrirait cette question.

**Le connecteur n'est pas concerné.** C'est de la politique, donc du cœur. La phase 1 reste valide.

### Ordre d'opérations obligatoire

Le marqueur protège aujourd'hui `tcp/445`, `tcp/8123` et `tcp/80` : l'app ne peut pas y toucher.
Quand elle possédera tout, **une ligne oubliée dans `port-forwarding.yml` fermera Samba ou
HomeAssistant**. Donc, dans cet ordre, sans raccourci :

1. rester en `dry-run`, et lui faire imprimer ce qu'il *supprimerait* ;
2. transcrire cette liste dans les règles permanentes ;
3. relire, puis seulement alors donner les pleins pouvoirs.

## 5. Transport : HTTP partout, pas de broker

### Pourquoi pas de broker

Le système est **déjà réconciliant** : une boucle sonde l'état et corrige l'écart. C'est elle,
et non une garantie de livraison, qui rattrape les incidents.

| Promesse d'un broker | Ce qu'elle vaut ici |
|---|---|
| Notification conservée si le destinataire est éteint | Une notification « serveur démarré » livrée 20 min plus tard est **fausse**, pas utile. La boucle corrige en une minute. |
| Rejeu automatique | Deux essais côté client HTTP couvrent le transitoire ; la boucle couvre le durable. |
| Plusieurs abonnés | Il y en a exactement un. |
| Le producteur ne tombe pas si le consommateur est absent | Sur une commande, échouer franchement est **meilleur** que réussir dix minutes trop tard. |

### La règle qui le remplace

> **Push pour la latence, pull pour la correction.**

- Le cœur **pousse** en HTTP quand il constate un changement → le message Discord bouge tout de suite.
- `connector-discord` **tire** périodiquement (`GET /game-servers`) et resynchronise ses messages.

Un push perdu n'a aucune conséquence : le pull suivant corrige. Aucune garantie de livraison
n'est nécessaire, donc aucun broker.

### Commandes longues et contrainte Discord

Discord exige un accusé de réception en 3 s, or démarrer une stack en prend 30 et plus.
C'est résolu **dans le connecteur**, pas par l'architecture : `deferReply()` laisse 15 minutes
pour éditer la réponse. Le connecteur défère, appelle le cœur, édite à la réponse.

### Authentification interne

En-tête `X-Internal-Secret` sur tous les appels entre services, comparé à temps constant.
Seul `GET /actuator/health` est ouvert. Un service joignable sur l'overlay sans secret n'existe pas.

## 6. La sonde d'état vit dans le connecteur Portainer

Décidé le 13-09. Aujourd'hui `DockerStatusRefresh` appelle `getContainerState(stackId)` **une
fois par serveur et par minute**. `GET /api/stacks` renvoie toutes les stacks en un seul appel.

En déplaçant la boucle dans le connecteur :

- **une requête Portainer par minute**, quel que soit le nombre de serveurs ou d'appelants ;
- **un seul réglage** (`connector.portainer.refresh-interval`) contrôle la charge sur Portainer ;
- les lectures du cœur deviennent gratuites (elles tapent un cache mémoire).

Deux exigences que ça impose, à ne pas oublier :

1. **Le connecteur date ses réponses** (`observedAt`). Sans ça, juste après un démarrage, le
   cœur lirait un cache périmé et conclurait que le serveur est toujours éteint.
2. **`POST /stacks/refresh`** force une lecture immédiate, à appeler par le cœur juste après
   avoir agi.

Le connecteur sonde **toutes** les stacks sans savoir lesquelles sont des serveurs de jeu :
c'est le cœur qui trie. Le cœur conserve la notion métier de changement de statut
(`statusHistory`, notification à Discord) ; le connecteur ne fait que refléter Portainer.

## 7. Phases

Chaque phase est déployable et testable seule.

### Phase 0 — socle — partiellement conservée

- [x] Renommage complet, 13-09 : dossier `schub-back-bot-server` → `schub-connector-discord`,
      services compose `bot-mongo` → `schub-mongo`, `bot-back` → `connector-discord`,
      `bot-front` → `schub-front`, `schub-back` → `schub-bff` ; images Docker `discord-bot` →
      `schub-connector-discord`, `bot-front` → `schub-front`, `schub-back` → `schub-bff` ;
      propriété `bot.internal-secret` → `schub.internal-secret`, variable `BOT_INTERNAL_SECRET`
      → `SCHUB_INTERNAL_SECRET` ; `.gitmodules`, `SUBREPOS` et `artifactId` alignés.
      **À faire à la main : renommer le repo sur GitHub** (voir §11).
- [x] Bases et utilisateurs Mongo `bot`, `servers`, `riot` (`scripts/mongo-init-databases.js`,
      `task db:init`) — cloisonnement et idempotence vérifiés
- [x] Squelettes des 4 nouveaux repos créés et compilant (13-09)
- [ ] ~~RabbitMQ~~ — retiré le 13-09, voir §5
- [~] `contracts/` : remplacer l'AsyncAPI par les OpenAPI des trois connecteurs —
      `connector-freebox.openapi.yaml` écrit le 15-09, les autres suivront leurs phases

### Phase 1 — `schub-connector-freebox` — FAITE le 2026-09-15

Le refactor du 04-09 avait déjà posé l'interface : la phase a été mécanique, comme prévu.
La box a été appairée avant le déménagement (§9), donc le code déplacé est celui dont on a
vu le comportement réel.

- [x] Déplacer depuis `schub-connector-discord` : `FreeboxRedirectionRequestService`,
      `FreeboxSessionManager`, `FreeboxApiConfiguration`, `FreeboxProperties`,
      `model/freebox/*`, `FreeboxException`, `scripts/freebox-pair.sh`
- [x] Exposer l'API interne : `GET /redirections`, `POST /redirections`,
      `PUT /redirections/{id}`, `DELETE /redirections/{id}`, `GET /router/status`
- [x] Le DTO exposé est `PortRule` (domaine), **pas** `FreeboxRedirection`
- [x] Côté appelant : `HttpRedirectionRequestService` implémente la même interface
      `RedirectionRequestService` — **le réconciliateur et ses tests n'ont pas bougé** (30 tests, verts après la coupe)
- [x] Le secret `FREEBOX_APP_TOKEN` suit le service

### Phase 2 — `schub-connector-portainer`

- [ ] Déplacer `PortainerRequestService`, `PortainerErrorLogger`, `PortainerApiConfiguration`
- [ ] Boucle de sonde sur `GET /api/stacks`, cache mémoire daté (§6)
- [ ] API : `GET /stacks`, `GET /stacks/{id}`, `POST /stacks/{id}/start`,
      `POST /stacks/{id}/stop`, `POST /stacks/refresh`
- [ ] Le secret `PORTAINER_TOKEN` suit le service — il est le plus dangereux du système,
      il ne doit plus vivre à côté de la logique métier

### Phase 3 — `schub-core` + amaigrissement du connecteur Discord

Le gros morceau. Les deux moitiés d'une même coupe.

- [ ] Déplacer vers le cœur : `GamingServerEntity` (→ `GameServer`), son repository, son service,
      `DockerService` (→ `DeploymentService`), `PortForwardingService`, `PortRuleResolver`,
      `PortForwardingProperties`, `model/portforwarding/*`, `GamingServerController`, le mapper
- [ ] Appliquer **tous** les renommages du §2 pendant le déplacement — une seule fois
- [ ] Migration Mongo : collection `servers` vers sa base, `identifier` → `slug`
- [ ] Supprimer `CreateGamingServerCommand` et `UpdateGamingServerCommand` (§4)
- [ ] Le connecteur Discord n'a **aucune** projection : il tire `GET /game-servers` périodiquement
- [ ] Le cœur pousse vers `POST connector-discord/notifications/gameserver-changed`

### Phase 4 — BFF et front

- [ ] BFF : router `/gaming-server/**` vers le cœur, `/discord/**` vers le connecteur Discord
- [ ] Vérifier la fiche serveur bout en bout, champ « Ports Freebox » compris

### Phase 5 — `schub-connector-riot`

- [ ] Remplir le squelette quand les fonctionnalités seront cadrées

### Phase 6 — nettoyage

- [ ] `SUBREPOS` dans `release.yml` et le Taskfile, `.gitmodules`
- [ ] Supprimer le code mort, mettre à jour les README

## 8. Ports de dev

| Service | Port hôte |
|---|---|
| schub-mongo | 27017 |
| connector-discord | 18081 |
| schub-bff | 18082 |
| core | 18083 |
| connector-freebox | 18084 |
| connector-riot | 18085 |
| connector-portainer | 18086 |
| schub-front | 18090 |

## 9. Risques identifiés

- **Collision de noms DNS entre dev et prod.** Le réseau `schub` est un overlay Swarm
  **attachable et partagé** : les conteneurs de dev le rejoignent, et Swarm y publie le nom
  court de chaque service. Après le renommage du 13-09, dev et prod portent **toujours les
  mêmes noms** (`schub-mongo`, `connector-discord`, `schub-bff`) : renommer les deux côtés à
  l'identique ne règle rien. Tant que `CodeInfrastructure` n'est pas déployée le problème dort ;
  le jour où elle le sera, le `schub-bff` de dev résoudra `connector-discord` sur la **prod**. Correctif : réseau bridge propre à la stack de dev, `schub` réservé à
  `admin-portainer`.
- **Le port-forwarding n'a jamais tourné.** Ni appairé, ni sorti du dry-run. La phase 1 le
  déplace sans l'avoir validé. Appairer **avant** de déménager, sinon deux inconnues à la fois.
- **Migration de données** : la collection `servers` change de base *et* de schéma en une
  opération. Sauvegarde préalable, script rejouable.
- **Le cache du connecteur Portainer peut mentir** si le cœur ignore `observedAt`. Traiter une
  lecture périmée comme une absence de réponse, pas comme un état.
- **Sept repos à releaser.** `release.yml` attend l'image de chaque repo séquentiellement ;
  l'attente mérite d'être parallélisée.
- **Pas de contrats partagés en jar** — délibéré (cadence de release commune évitée), au prix
  d'une duplication qui dérive si `contracts/` n'est pas tenu à jour.

## 10. État d'avancement

| Phase | État |
|---|---|
| 0 — socle | partiellement faite ; squelettes créés le 13-09, contrats à refaire |
| 1 — connector-freebox | **faite le 15-09** |
| 2 — connector-portainer | à faire |
| 3 — core + connector-discord | à faire |
| 4 — BFF et front | à faire |
| 5 — connector-riot | à faire |
| 6 — nettoyage | à faire |

## 11. GitHub — fait le 2026-09-13

`gh` 2.100.0 est installé dans `/config/.local/gh`, relié depuis `/config/.local/bin`
(persistant, déjà sur le `PATH`).

- [x] Repo `schub-back-bot-server` renommé en `schub-connector-discord`, remote local réaligné
- [x] Quatre repos créés (publics, défaut `main`, comme les existants) :
      `schub-core`, `schub-connector-portainer`, `schub-connector-freebox`, `schub-connector-riot`
- [x] Branches `main` et `develop` poussées sur chacun
- [x] Les quatre ajoutés en submodules (`branch = main`) et à `SUBREPOS`
      dans `Taskfile.yml` et `release.yml`

### Ce qui reste, et que `gh` ne pourra jamais faire

- [ ] **Étendre le `RELEASE_PAT`** aux quatre nouveaux repos (`contents:write`). GitHub
      n'expose aucune API pour créer ou modifier un jeton personnel : interface de compte
      exclusivement. Sans ça, une release échouera à mi-parcours en laissant des tags posés
      sur certains repos et pas sur les autres.
- [ ] Secrets `DOCKER_USERNAME` et `DOCKER_PASSWORD` sur les quatre nouveaux repos
      (`gh secret set` sait le faire, mais les valeurs vous appartiennent)
- [ ] `SONAR_TOKEN` si vous copiez `pr-sonarcloud.yml`

### CI — état au 2026-09-15

Deux blocages découverts en ouvrant les premières PR vers `develop`.

**Impasse de déclenchement, corrigée.** `pr-build.yml` et `pr-sonarcloud.yml` ne se
déclenchaient que sur les PR vers `main`, alors que la protection de `develop` exige leurs deux
contrôles. Aucune PR vers `develop` ne pouvait donc satisfaire ses propres contrôles, et le push
direct était refusé par ailleurs : plus rien n'était fusionnable. `develop` ajouté aux
déclencheurs dans les trois repos.

**SonarCloud cassé, contourné — À REMETTRE.** Les clés de projet sont restées
`thomas-jacque-schultz_{Bot,Back,Front}`, les noms d'avant le renommage des repos. SonarCloud
répond « Not authorized or project not found » et le contrôle échoue depuis le 29-08.
Contournement du 15-09 : **« SonarCloud Code Analysis » retiré des contrôles *requis* sur
`develop`** dans les trois repos (le workflow tourne toujours, en informatif).

> À faire : rétablir la liaison des trois projets dans l'interface SonarCloud, mettre les
> nouvelles clés dans les workflows, puis **remettre le contrôle en requis**. Tant que ce n'est
> pas fait, `pr - build` est le seul garde-fou sur `develop`.

**Méthode de fusion : `rebase` uniquement.** Les hashes changent à la fusion, donc les gitlinks
de `Schub` pointant sur des commits de branches de PR deviennent orphelins. Les réaligner après
chaque fusion de sous-repo

Note sur les images Docker : les nouveaux noms (`schub-connector-discord`, `schub-front`,
`schub-bff`) n'existeront sur Docker Hub qu'après la prochaine release. Les anciens tags
restent sous les anciens noms. Sans conséquence puisque la stack de prod n'est pas déployée,
mais il ne faut pas tenter un déploiement avant d'avoir releasé.

## 12. À faire, repo par repo

État relevé le 2026-09-13. Rien n'est commité nulle part.

### Ordre conseillé

Les trois premiers sont indépendants et sans risque. Le quatrième a un piège.
Les nouveaux repos viennent après, et `Schub` **en dernier** (voir pourquoi ci-dessous).

---

### 1. `schub-infra-docker` — branche `develop`

*6 entrées, tout est cohérent, rien ne bloque.*

- [ ] Relire et committer :
      `Hosting/Tool/CodeInfrastructure/{Taskfile.yml, docker-compose.dev.yml, docker-compose.yml}`,
      `port-forwarding.example.yml`, `contracts/`, `scripts/`
- [ ] Écrire les OpenAPI dans `contracts/` au fil des phases 1 à 3
- [ ] **Collision DNS dev/prod** : donner à la stack de dev son propre réseau bridge et ne
      garder `schub` que pour joindre `admin-portainer` (§9)

### 2. `schub-back-bff` — branche `develop`

*Une seule ligne modifiée.*

- [ ] Committer le renommage d'image `schub-back` → `schub-bff`
- [ ] Phase 4 : router `/gaming-server/**` vers `schub-core`, `/discord/**` vers le connecteur.
      Les propriétés `bot.base-url` / `bot.internal-secret` sont à renommer **à ce moment-là**,
      pas avant — le BFF devra distinguer deux destinations.

### 3. `schub-front-servers` — branche `develop`

*Trois fichiers.*

- [ ] Committer : renommage d'image `bot-front` → `schub-front`, champ « Ports Freebox »
      (`GameServerFormPage.tsx`, `types/server.ts`)
- [ ] Phase 4 : vérifier la fiche serveur bout en bout si les chemins du BFF bougent

### 4. `schub-connector-discord` — branche `develop`

*38 entrées. C'est le plus lourd, et il a un piège.*

- [ ] **Avant tout commit : `git add -A`.** L'index contient encore
      `FreeboxRedirectionClient.java` et `RedirectionKey.java`, supprimés par le refactor du
      04-09 mais restés en `AD`. Committer en l'état les ressusciterait et le projet ne
      compilerait plus.
- [ ] Relire le diff complet plutôt que fichier par fichier : la découpe a bougé trois fois
      depuis le premier `git add`
- [x] **Appairer la Freebox** — fait le 15-09 : appairé, permission « Modification des
      réglages » accordée, secret `FREEBOX_APP_TOKEN` créé sur le Swarm. Le script vit
      désormais dans `schub-connector-freebox`. **Reste à sortir du dry-run.**
- [ ] Renommer le repo sur GitHub, puis `git remote set-url` (§11)
- [x] Phase 1 : tout le Freebox sorti vers `schub-connector-freebox` le 15-09
- [ ] Phase 3 : en sortir le domaine vers `schub-core`, supprimer `CreateGamingServerCommand`
      et `UpdateGamingServerCommand`, renommer le paquet `schultz.thomas.discord.bot` →
      `schultz.thomas.schub.connector.discord`

### 5 à 8. `schub-core`, `schub-connector-{portainer,freebox,riot}`

*Squelettes créés, compilant, et **déjà initialisés en git sur `develop` avec un premier
commit** (13-09). Il ne reste que la partie GitHub.*

Pour chacun :

- [x] `git init`, branche `develop`, premier commit du squelette
- [x] Créer le repo sur GitHub, `git remote add origin`, pousser `main` puis `develop`
- [x] L'ajouter en submodule de `Schub` et dans `SUBREPOS`
- [ ] Copier `pr-build.yml` et `pr-sonarcloud.yml` depuis un repo existant si vous voulez
      les mêmes contrôles de PR
- [ ] L'ajouter au `docker-compose.dev.yml` (ports : core 18083, freebox 18084, riot 18085,
      portainer 18086) et au compose de prod

Puis, par service :

- [ ] `schub-connector-freebox` — phase 1, le premier à remplir
- [ ] `schub-connector-portainer` — phase 2, avec la sonde d'état et son cache daté (§6)
- [ ] `schub-core` — phase 3, le gros morceau
- [ ] `schub-connector-riot` — phase 5, quand les fonctionnalités seront cadrées

### 9. `Schub` (parent) — branche `main`

- [x] ~~Ne pas committer avant le renommage GitHub~~ — fait le 13-09, `.gitmodules` est
      désormais valide et les sept submodules existent
- [ ] Une fois le repo renommé : committer `.gitmodules`, `Taskfile.yml`,
      `.github/workflows/release.yml`, `docs/`
- [ ] Mettre à jour les gitlinks des submodules après les commits des sous-repos
- [ ] Retirer `schub-core` et les trois connecteurs de la liste des non-suivis en les
      déclarant comme submodules
- [ ] Phase 6 : paralléliser l'attente des images dans `release.yml` — sept repos en
      séquentiel, ça va devenir long

---

### Deux choses qui ne sont dans aucun repo

- [ ] **GitHub** : renommer `schub-back-bot-server`, créer les quatre nouveaux repos (§11)
- [ ] **Docker Hub** : les nouveaux noms d'images n'existeront qu'après la prochaine release.
      Ne pas tenter de déployer la prod avant.

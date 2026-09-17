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

## 6 bis. Migrations de schéma et ordre de démarrage (17-09)

### Ce qui a déclenché le sujet

La prod **a déjà tourné**, contrairement à ce qui était noté ici. Ses données sont toujours
sur le disque, à `/mnt/volume/MongoBot` (fichiers WiredTiger d'août 2025, dossier touché le
20 avril 2026), **à l'ancien schéma** : base `discordbot`, champs `identifier` et
`portainerStackId`. Un `MongoBotDev` en est une copie conforme datée du même jour.

Deux bugs trouvés en le vérifiant :

1. **Le compose de prod pointait sur `/mnt/volume/BotFront/Database`, qui n'existe pas.** Avec
   `type: none, o: bind`, Docker refuse de monter un chemin absent : `schub-mongo` n'aurait pas
   démarré. Ce chemin n'a jamais changé depuis la création du repo — la prod qui a tourné
   n'utilisait donc pas ce fichier. Corrigé vers `/mnt/volume/MongoBot`.
2. **Le cloisonnement Mongo n'était qu'à moitié fait.** Le cœur utilisait bien son utilisateur
   `servers`, mais `connector-discord` se connectait toujours en **root**, et l'utilisateur
   `bot` créé par `mongo-init-databases.js` ne servait à personne — il était de surcroît créé
   sur une base `bot` que rien n'utilise, alors que les données sont dans `discordbot`.
   Corrigé : l'utilisateur `bot` est créé sur `discordbot`, le connecteur s'y connecte, et
   **plus aucun service applicatif ne détient les identifiants root**.

### La règle : Mongock possède le schéma, une seule exception

Les évolutions du schéma de `servers` sont des classes `@ChangeUnit` dans
`schub-core`, paquet `schultz.thomas.schub.core.migration` (Mongock 5.5.1). Appliquées au
démarrage, dans l'ordre, une seule fois, tracées en base. **Rien à lancer à la main.**

Première migration écrite : `V001_GameServerSlugUniqueIndex`. Elle a un vrai contenu —
`GameServer.slug` porte `@Indexed(unique = true)`, mais cette annotation est **inerte** parce
que Spring Boot 3 laisse `auto-index-creation` à `false`. L'index d'unicité n'a donc jamais
existé, alors que le slug est l'identité du domaine et la lecture chaude (`findBySlug`).

**L'exception, et pourquoi elle en est une.** Le déplacement historique
`discordbot.servers` → `servers.servers` enjambe deux bases. Le cœur se connecte avec
l'utilisateur `servers`, qui n'a de droits que sur `servers` : il ne *peut pas* lire
`discordbot`, et ne doit pas obtenir ce droit. Ce droit ne servirait **qu'une fois**, au
basculement de la prod, et resterait acquis pour toujours — dans un an, plus personne ne sait
pourquoi le cœur peut lire la base du connecteur Discord, et du code finit par s'appuyer
dessus. La frontière entre services est précisément ce que la découpe achète.

Ce déplacement reste donc une opération d'exploitation lancée en root :
`task db:migrate:legacy`. **C'est le dernier script manuel du système.**

### Ordre de démarrage : deux réponses, pas une

**Docker Swarm ignore `depends_on`.** L'ordre de lancement ne s'exprime pas dans un compose
déployé en stack — c'est un fait de Swarm, pas un oubli. La prod ne peut donc compter que sur
la résilience : `restart_policy: condition: any`, et des services qui tolèrent d'arriver trop
tôt. C'est déjà le cas par construction (§5 : boucle de réconciliation, pull pour la
correction), et c'est un argument de plus pour l'absence de broker.

**En dev**, qui est du compose classique, `depends_on` fonctionne et est désormais utilisé :

| service | attend | pourquoi |
|---|---|---|
| `dev-schub-core` | `dev-schub-mongo` sain | pas de migration sur une base injoignable |
| `dev-connector-discord` | `dev-schub-mongo` **et** `dev-schub-core` sains | ne pas lire un schéma en cours de transformation |

Le cœur expose une sonde sur `/actuator/health/readiness`. Elle ne passe au vert qu'une fois
le contexte Spring démarré, donc **après** les migrations Mongock : `service_healthy` y signifie
« le schéma est à jour », pas seulement « le port répond ». C'est ce qui donne sa valeur à la
dépendance ; sans la sonde, `depends_on` n'attendrait que le démarrage du conteneur.

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
- [x] Bases et utilisateurs Mongo `bot`, `servers`, `riot` (`Hosting/Tool/CodeInfrastructure/mongo-init-databases.js`,
      `task db:init`) — cloisonnement et idempotence vérifiés
- [x] Squelettes des 4 nouveaux repos créés et compilant (13-09)
- [ ] ~~RabbitMQ~~ — retiré le 13-09, voir §5
- [x] ~~`contracts/`~~ — **abandonné le 17-09.** Les OpenAPI écrits à la main ne servaient
      ni de codegen ni de validation : une seconde source de vérité à côté des contrôleurs,
      condamnée à dériver. Le contrat vit dans le code des contrôleurs ; une évolution
      incompatible se traite par la règle du §5 (exposer en parallèle, migrer, retirer).

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

### Phase 2 — `schub-connector-portainer` — FAITE le 2026-09-16

- [x] Déplacer `PortainerRequestService`, `PortainerErrorLogger`, `PortainerApiConfiguration`
- [x] Boucle de sonde sur `GET /api/stacks`, cache mémoire daté (§6)
- [x] API : `GET /stacks`, `GET /stacks/{id}`, `POST /stacks/{id}/start`,
      `POST /stacks/{id}/stop`, `POST /stacks/refresh`
- [x] Le secret `PORTAINER_TOKEN` suit le service — il est le plus dangereux du système,
      il ne doit plus vivre à côté de la logique métier

### Phase 3 — `schub-core` + amaigrissement du connecteur Discord — FAITE le 2026-09-16

Le gros morceau. Les deux moitiés d'une même coupe.

> Le connecteur Discord passe de 3813 à 1738 lignes. Les 30 tests suivent le domaine dans le
> cœur et y passent. **Le BFF et le front restent à rebrancher — c'est la phase 4, et d'ici là
> l'interface web est cassée** : elle appelle `/gaming-server` sur le connecteur Discord, qui
> ne sert plus cette route.

- [x] Déplacer vers le cœur : `GamingServerEntity` (→ `GameServer`), son repository, son service,
      `DockerService` (→ `DeploymentService`), `PortForwardingService`, `PortRuleResolver`,
      `PortForwardingProperties`, `model/portforwarding/*`, `GamingServerController`, le mapper
- [x] Appliquer **tous** les renommages du §2 pendant le déplacement — une seule fois
- [x] Migration Mongo : collection `servers` vers sa base, `identifier` → `slug`
- [x] Supprimer `CreateGamingServerCommand` et `UpdateGamingServerCommand` (§4)
- [x] Le connecteur Discord n'a **aucune** projection : il tire `GET /game-servers` périodiquement
- [x] Le cœur pousse vers `POST connector-discord/notifications/gameserver-changed`

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
- **La prod n'est pas un terrain vierge** : ses données existent à `/mnt/volume/MongoBot`, à
  l'ancien schéma. Le premier démarrage du cœur en prod doit être précédé de
  `task db:migrate:legacy`, sinon le cœur lit une base vide et la réconciliation ferme des
  ports de serveurs qui tournent.
- **Swarm ignore `depends_on`** : aucun ordre de démarrage n'est garanti en prod. Tout service
  qui suppose qu'un autre est déjà là est un bug qui n'apparaîtra qu'au déploiement.
- **Pas de contrats partagés en jar ni de contrats écrits** — délibéré (cadence de release
  commune évitée). Le contrat est ce que servent les contrôleurs : une rupture ne se voit donc
  qu'à l'appel. C'est le prix assumé de la découpe, et la raison de la règle « exposer en
  parallèle avant de retirer » du §5.

## 10. État d'avancement

| Phase | État |
|---|---|
| 0 — socle | faite ; squelettes 13-09, `contracts/` abandonné et cloisonnement Mongo terminé le 17-09 |
| 1 — connector-freebox | **faite le 15-09** |
| 2 — connector-portainer | **faite le 16-09** |
| 3 — core + connector-discord | **faite le 16-09** |
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

### Secrets et jetons — fait le 2026-09-17

- [x] **`RELEASE_PAT` étendu** aux sept sous-repos (`contents:write` + `actions:read`).
      GitHub n'expose aucune API pour créer ou modifier un jeton personnel : interface de
      compte exclusivement, et sa valeur n'est pas relisible. Sans cette extension, une
      release échouait à mi-parcours — les trois premiers repos de `SUBREPOS` poussés et
      tagués, puis 403 sur `schub-connector-freebox`, laissant trois tags à retirer à la main.
- [x] `DOCKER_USERNAME` et `DOCKER_PASSWORD` sur les **sept** repos (un seul jeton Docker Hub
      « Read & Write », posé partout pour n'en avoir qu'un à faire tourner). `DOCKER_USERNAME`
      n'est pas un secret : c'est `thomasschultzschub`, lisible dans les tags du compose.
- [x] `SONAR_TOKEN` régénéré et posé sur les trois repos qui ont `pr-sonarcloud.yml`.
- [ ] `SONAR_TOKEN` sur les quatre nouveaux repos, le jour où ils auront ce workflow.

**Pas de secret partagé possible ici.** GitHub ne partage des secrets qu'au niveau
*organisation* ; ces repos vivent sous un compte personnel. D'où la duplication assumée
ci-dessus. Deux sorties si elle devient pénible : transférer les repos dans une organisation
(gratuit pour des repos publics, mais il faut reprendre les remotes, les URLs de submodules et
le `thomas-jacque-schultz/` codé en dur dans `release.yml`), ou passer les images sur **GHCR**,
qui s'authentifie avec le `GITHUB_TOKEN` intégré et supprime les deux secrets Docker au lieu de
les partager.

### CI — état au 2026-09-15

Deux blocages découverts en ouvrant les premières PR vers `develop`.

**Impasse de déclenchement, corrigée.** `pr-build.yml` et `pr-sonarcloud.yml` ne se
déclenchaient que sur les PR vers `main`, alors que la protection de `develop` exige leurs deux
contrôles. Aucune PR vers `develop` ne pouvait donc satisfaire ses propres contrôles, et le push
direct était refusé par ailleurs : plus rien n'était fusionnable. `develop` ajouté aux
déclencheurs dans les trois repos.

**SonarCloud cassé, contourné le 15-09.** « SonarCloud Code Analysis » a été retiré des
contrôles *requis* sur `develop` dans les trois repos (le workflow tournait toujours, en
informatif). `pr - build` est resté le seul garde-fou.

### SonarCloud réparé le 2026-09-17 — le diagnostic du 15-09 était faux

Le 15-09 la panne avait été imputée aux **clés de projet périmées** après le renommage des
repos. C'est inexact, et ça a coûté une journée de contournement. Vérification faite par l'API
publique de SonarCloud : les trois projets existent, sont publics, et SonarCloud a lui-même
suivi le renommage (`thomas-jacque-schultz_Bot` s'appelle aujourd'hui `schub-connector-discord`).
**Les clés `_Bot` / `_Back` / `_Front` sont des noms historiques, mais parfaitement valides** —
il n'y a rien à rebrancher dans l'interface SonarCloud.

Il y avait **deux pannes superposées**, et la seconde aurait survécu à la réparation de la
première :

1. **Le `SONAR_TOKEN` était expiré** (créé le 04-05, dernière analyse réussie le 11-05).
   Régénéré sans date d'expiration et reposé sur les trois repos.
2. **Les deux workflows Java passaient `-Dsonar.login=`, que `sonar-maven-plugin` 4.x ne lit
   plus.** Le jeton était donc ignoré et l'analyse partait en anonyme. Corrigé : `SONAR_TOKEN`
   en variable d'environnement du step.

**Pourquoi le mauvais diagnostic a tenu.** Les trois repos donnent deux messages différents, et
seul celui du front est exploitable :

- Java → « Not authorized or project not found... A project with the same key may already exist
  in another organization. » Le message **évoque la clé de projet alors que le problème est le
  jeton** — c'est lui qui a égaré le 15-09.
- Front → `Failed to query JRE metadata: GET api.sonarcloud.io/analysis/jres ... HTTP 403`.
  Cet endpoint **ne dépend que du jeton**, il ne connaît aucune clé de projet. Décisif.

Règle à retenir : devant un échec Sonar, croire le message du scanner générique, pas celui du
plugin Maven. Et vérifier un jeton avant toute autre hypothèse —
`curl -u '<jeton>:' https://sonarcloud.io/api/authentication/validate` répond `{"valid":true}`
ou non, en une seconde et sans CI.

Il y avait en réalité **une troisième cause, propre au BFF** : son `pom.xml` ne déclarait pas
`sonar-maven-plugin`. Maven ne résout un préfixe de goal que dans les groupes de plugins par
défaut, auxquels `org.sonarsource.scanner.maven` n'appartient pas — `sonar:sonar` échouait donc
sur « No plugin found for prefix 'sonar' », avant toute question d'authentification. Le
connecteur Discord déclarait déjà ce plugin, d'où deux repos qui semblaient avoir la même panne
sans l'avoir. Signe distinctif : ses runs duraient 13 s là où ceux du Discord duraient 1 min.

**Les trois analyses passent depuis le 17-09.**

### Vert ne veut pas dire vert — le piège avant de remettre le contrôle en requis

`mvn sonar:sonar` **n'attend pas le verdict du quality gate** : il envoie l'analyse et sort en 0.
Le job GitHub est donc vert même quand SonarCloud refuse le code. Le contrôle « SonarCloud Code
Analysis », lui, est posté par l'application GitHub de SonarCloud et reflète le *gate*. Le
remettre en requis alors que les jobs sont verts bloque donc des PR sans prévenir.

État des gates au 17-09, après réparation :

- `schub-connector-discord` — **OK**. Deux findings corrigés : une méthode vide sans appelant
  depuis la phase 3, et `S3077` sur la vue. Sur ce dernier, `List.copyOf` ne suffit pas :
  **la règle est syntaxique**, elle refuse `volatile` sur tout champ dont le type déclaré n'est
  pas prouvablement immuable, et `List` est une interface. Le champ est passé en
  `AtomicReference`, qui exprime l'échange atomique de référence ; le `List.copyOf` reste, car
  c'est lui la garantie d'immuabilité — le cœur rend un `ArrayList` que `all()` laissait fuir.
- `schub-back-bff` — **ERROR sur `new_coverage`** : 0 % contre 80 % exigés, le repo n'a aucun
  test. **Décision de politique qualité en attente**, pas une panne. Soit reprendre ce que fait
  déjà le connecteur Discord (`<sonar.coverage.exclusions>**/*</sonar.coverage.exclusions>` dans
  son pom, ce qui retire la couverture du gate — et explique que sa PR ne bute pas dessus), soit
  écrire des tests et ajouter JaCoCo.

- [ ] **Reste à faire** : remettre « SonarCloud Code Analysis » en contrôle *requis* sur
      `develop` dans les trois repos — **une fois les gates verts, pas les jobs**. Les rulesets
      « Pr on develop » n'exigent aujourd'hui que `pr - build`.

**Méthode de fusion : `rebase` uniquement.** Les hashes changent à la fusion, donc les gitlinks
de `Schub` pointant sur des commits de branches de PR deviennent orphelins. Les réaligner après
chaque fusion de sous-repo

Note sur les images Docker : les nouveaux noms (`schub-connector-discord`, `schub-front`,
`schub-bff`) n'existeront sur Docker Hub qu'après la prochaine release. Les anciens tags
restent sous les anciens noms. Sans conséquence puisque la stack de prod ne tourne pas
actuellement, mais il ne faut pas tenter un déploiement avant d'avoir releasé.

> **Ne pas lire « ne tourne pas » comme « n'a jamais tourné ».** Elle a tourné jusqu'en avril
> 2026 et **ses données existent toujours** (§6 bis). L'erreur coûte cher : elle fait croire
> que la prod démarrera sur une base vierge, alors qu'elle démarrera sur l'ancien schéma.

## 12. À faire, repo par repo

État relevé le 2026-09-13. Rien n'est commité nulle part.

### Ordre conseillé

Les trois premiers sont indépendants et sans risque. Le quatrième a un piège.
Les nouveaux repos viennent après, et `Schub` **en dernier** (voir pourquoi ci-dessous).

---

### 1. `schub-infra-docker` — branche `develop`

*6 entrées, tout est cohérent, rien ne bloque.*

- [ ] Relire et committer : `Hosting/Tool/CodeInfrastructure/{Taskfile.yml,
      docker-compose.dev.yml, docker-compose.yml, port-forwarding.example.yml,
      mongo-init-databases.js, mongo-migrate-servers-to-core.js}`
- [x] Rangement du 17-09 : `contracts/` supprimé, les deux scripts Mongo descendus à côté du
      compose qu'ils servent — la racine du repo d'infra ne porte plus que des stacks
- [x] 17-09 : chemin du volume Mongo de prod corrigé (`BotFront/Database` inexistant →
      `MongoBot`), `connector-discord` passé de root à l'utilisateur `bot`, `depends_on` du
      dev branché sur des sondes de santé, tâche `db:migrate:legacy` ajoutée (§6 bis)
- [ ] **Avant le premier démarrage du cœur en prod** : lancer `task db:migrate:legacy` contre
      la base de prod, et créer le secret Swarm `MONGO_BOT_PASSWORD`
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
- [x] `schub-connector-portainer` — phase 2 faite le 16-09
- [x] `schub-core` — phase 3 faite le 16-09
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

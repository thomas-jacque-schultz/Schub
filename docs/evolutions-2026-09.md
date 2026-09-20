# Évolutions Schub — plan de travail

> Ouvert le 2026-09-17. **Neuf arbitrages tranchés le 2026-09-18, récapitulés au §8.**
> Fait suite à `migration-microservices.md`, dont le §13
> (authentification Discord) est **absorbé par ce document** : ce qui suit le précise et le
> corrige sur un point d'architecture.
> Source de vérité pour les quatre chantiers. En cas de doute, c'est ce fichier qui tranche.

## 0. Ce qui est demandé, et ce qui est déjà là

Quatre chantiers :

| # | Chantier | Ampleur | Dépend de |
|---|---|---|---|
| A | SSO Discord + droits/rôles + admins de serveur | moyenne, mais **bloquante** | rien |
| B | Design system + Storybook | moyenne | rien |
| C | Portfolio public à la racine | petite | B (et A pour le menu connecté) |
| D | App d'équipe LoL | **grande** | A (identité), B (écrans) |

Ce qui existe déjà et qu'on ne réécrit pas :

- `UserEntity` (`discordId`, `discordUsername`, `UserPrivilegeEnum`) dans `schub-connector-discord`,
  avec son seeding OWNER par `DISCORD_ADMIN_ID` — **le garde-fou anti-verrouillage existe déjà**.
- `Command.roleNeeded()` / `hasRight()` : c'est « le truc propre à base de droits » évoqué. C'est
  une liste de privilèges par commande. Le chantier A le généralise, il ne l'invente pas.
- `GameServer.admins` est **déjà** une `List<String>`. Il n'y a pas de changement de type à faire :
  seulement à décider ce que la chaîne contient (§A.4) et à câbler l'autorisation dessus.
- JWT HMAC, expiration 1 h, `JwtService` du BFF : la mécanique de jeton est saine, seul son
  contenu change.
- `schub-connector-riot` : squelette qui compile, trois couches vides, `internal-secret` câblé.

---

## 1. La décision qui commande tout : où vit l'identité

C'est le seul vrai arbitrage du plan. Tout le reste en découle.

### Le problème

Le §13 posait : « le connecteur Discord garde la propriété de l'identité ». C'était juste tant
que l'identité se réduisait à *un couple (discordId, privilège)*. Les quatre chantiers la font
grossir : un rôle éditable, un jeu de permissions, un lien vers un compte Riot, une appartenance
à une équipe, une présence dans les `admins` d'un serveur.

Or la règle du §4 de la migration est explicite :

> Un connecteur ne sait pas pourquoi on l'appelle. Un connecteur qui se met à stocker du métier
> est un connecteur qui a dérivé.

Un rôle nommé « modérateur » qui contient la permission « démarrer un serveur », ce n'est pas de
l'état de plateforme Discord. C'est du domaine.

Conséquence concrète si on ne bouge pas : le cœur, pour savoir si l'acteur d'un `POST
/game-servers/{slug}/start` a le droit d'agir, devrait appeler le connecteur Discord à **chaque**
action, alors que la liste `admins` qui donne ce droit vit dans le cœur. L'autorisation serait
coupée en deux, à cheval sur deux services.

### La décision

**`User`, `Role` et `Permission` vivent dans `schub-core`, base `servers`.**
Le connecteur Discord garde ce qui est vraiment de Discord : salons, messages, guildes, et la
**traduction** d'un profil Discord (`GET /users/@me`) en identité connue du cœur.

| Détient | Service |
|---|---|
| `User` (id interne, discordId, discordUsername, avatar, roleId, riotPuuid) | `schub-core` |
| `Role` (nom, jeu de permissions) | `schub-core` |
| Évaluation « cet acteur a-t-il le droit de faire X sur Y » | `schub-core` |
| Salons, messages, guildes, commandes slash | `schub-connector-discord` |
| Échange du code OAuth2, lecture de `/users/@me` | `schub-back-bff` |

### Pourquoi maintenant, et pas après

**La prod est vierge** — vérifié le 17-09 : ni base applicative, ni utilisateur. La collection
`discordbot.users` n'existe qu'en dev, avec une poignée d'enregistrements. Déplacer l'identité
aujourd'hui coûte un `ChangeUnit` qui crée trois collections vides et un seeding OWNER.

Le faire après la mise en service, c'est le déplacement inter-bases `discordbot.users` →
`servers.users`, qui retombe exactement sur l'exception documentée au §6 bis : un script
d'exploitation lancé en root, parce que l'utilisateur `servers` n'a pas le droit de lire
`discordbot` et ne doit pas l'obtenir. **La fenêtre pour que ce chantier soit gratuit se ferme au
premier utilisateur créé en prod.**

### La cible : plus aucun compte local (décidé le 18-09)

Le §13 conservait le compte par mot de passe « en secours ». **C'est abandonné.** L'objectif est
qu'il n'existe **aucun** compte local : le super-administrateur est un compte Discord désigné par
son id, et rien d'autre. Disparaissent donc, à terme :

- `AUTH_ADMIN_USERNAME` / `AUTH_ADMIN_PASSWORD` et l'`InMemoryUserDetailsManager` du BFF ;
- `POST /auth/login`, `BCryptPasswordEncoder`, `DaoAuthenticationProvider`, `AuthenticationManager` ;
- l'écran de connexion par formulaire, remplacé par un bouton ;
- `authUsername`, `passwordHash` et `findByAuthUsername` de `UserEntity`.

Le gain est réel et pas cosmétique : un secret partagé de moins dans l'environnement, aucun mot
de passe stocké donc aucun à fuiter, et l'authentification déléguée à un fournisseur qui fait du
MFA mieux que nous. C'est aussi la fin du « compte étrange avec d'autres propriétés » : un
utilisateur du système **est** un compte Discord, sans exception à expliquer.

**Le risque qu'il faut nommer** : il n'y a plus de porte de service. Si le `CLIENT_SECRET` est
mal déployé ou l'URL de rappel mal déclarée, **personne** ne se connecte, toi compris. Trois
garde-fous, non négociables :

1. Le seeding `OWNER` par `DISCORD_ADMIN_ID` est rejoué **à chaque démarrage** du cœur, pas
   seulement à la première création. C'est ce qui rend le verrouillage par erreur de rôle
   impossible : redémarrer le service te rend ton `OWNER`.
2. L'IHM refuse de retirer le dernier `OWNER`, et de modifier son propre rôle.
3. **Le retrait du compte mot de passe est le DERNIER lot du chantier A** (A.6), dans une PR à
   part, après que la connexion Discord a fonctionné en prod. On ne démonte pas la porte de
   service avant d'avoir vu la porte principale s'ouvrir.

Ce que ça expose vraiment : une panne de Discord ferme l'IHM d'administration. Elle ferme déjà le
bot et les commandes slash — l'exposition n'est donc pas nouvelle, elle s'étend au front. Les
serveurs de jeu, eux, continuent de tourner : c'est le pilotage qui devient indisponible, pas
l'hébergement.

### Ce que ça invalide du §13

- ❌ « Connecteur : exposer `GET /discord/users/{discordId}` … et `PUT …/privilege` » → ces routes
  vivent dans le **cœur** (`/users/…`), pas dans le connecteur.
- ❌ « (3) `GET /discord/users/{id}/privilege` » dans le schéma de flux → devient
  `GET /users/by-discord/{id}` sur le cœur.
- ❌ « Le compte par mot de passe est conservé en secours » → **annulé le 18-09**, voir ci-dessus.
- ✅ Tout le reste tient : pas de Keycloak, tout le monde peut se connecter sans inscription
  préalable, **l'autorisation par rôle dans le BFF d'abord**.

---

## 2. Chantier A — Identité, droits, rôles

### A.0 · ⚠️ Le préalable absolu

Aujourd'hui le BFF applique `anyRequest().authenticated()` et **pas un seul `hasRole`** ; le
`isAdmin` du front ne fait que masquer des boutons. C'est sans danger avec un compte unique.

Ouvrir la connexion Discord à tout le monde **avant** d'avoir écrit l'autorisation, c'est donner
à n'importe quel compte Discord l'accès à `POST /game-servers`, à la suppression de règles de
ports et à l'arrêt des serveurs. C'est une élévation de privilèges.

> **Rien de ce qui touche à OAuth ne commence avant que A.2 soit vert.**

### A.1 · Le modèle : permissions, rôles, portée

Trois notions, à ne pas confondre :

```
Permission   un verbe atomique, figé dans le code     SERVER_START
Role         un nom + un jeu de permissions, ÉDITABLE en base
User         un compte + un rôle + des liens externes
```

**Les permissions sont une `enum` Java, pas des lignes en base.** Une permission correspond à du
code qui la vérifie : en ajouter une depuis une IHM produirait une permission que rien ne lit.
Les **rôles**, eux, sont en base et éditables — c'est exactement la fenêtre demandée.

Jeu initial, déduit des routes existantes :

| Permission | Ce qu'elle ouvre |
|---|---|
| `SERVER_VIEW` | la vue « membre » d'un serveur — voir les trois niveaux ci-dessous |
| `SERVER_INFRA_VIEW` | ports, déploiement, admins : ce qui décrit l'infrastructure |
| `SERVER_START` / `SERVER_STOP` | actions de cycle de vie |
| `SERVER_CREATE` / `SERVER_EDIT` / `SERVER_DELETE` | la fiche |
| `PORT_VIEW` / `PORT_RULE_EDIT` | règles permanentes et réconciliation |
| `DISCORD_CHANNEL_MANAGE` | abonnement des salons |
| `USER_VIEW` / `USER_ROLE_ASSIGN` | écran utilisateurs |
| `ROLE_MANAGE` | écran rôles — **la fenêtre réservée** |
| `SCRIM_*` | ajoutées au chantier D, pas avant |

Rôles livrés par le seeding : **`VISITEUR`** (`SERVER_VIEW` seul — décidé le 18-09),
`MODERATOR` (`SERVER_VIEW`, `SERVER_START`, `SERVER_STOP`), `ADMINISTRATOR` (tout sauf
`ROLE_MANAGE`), `OWNER` (tout). Ils reprennent `UserPrivilegeEnum` pour que la reprise soit un
simple mapping — `USER` devient `VISITEUR`, le reste ne bouge pas.

#### Trois niveaux de visibilité d'un serveur, et pourquoi il en faut trois

C'est la conséquence directe de « tout le monde peut se connecter ». **Un `VISITEUR`, ce n'est pas
un proche : c'est n'importe qui sur Internet possédant un compte Discord.** Lui donner « la vue
détaillée » telle qu'elle existe aujourd'hui, c'est lui donner `deploymentId`, la liste des ports
ouverts sur ta box et le nom des administrateurs. Ce n'est pas une fuite grave, c'est une
cartographie gratuite de ton infrastructure offerte à un inconnu.

| Niveau | Qui | Contenu |
|---|---|---|
| public | tout le monde, sans compte | `PublicServerStatusDto` : nom, jeu, statut. Inchangé. |
| membre (`SERVER_VIEW`) | tout compte connecté | + URL de connexion, version, installation, description, nombre de places, historique de statut |
| infra (`SERVER_INFRA_VIEW`) | `ADMINISTRATOR`, `OWNER` | + `deploymentId`, ports, admins |

Concrètement : `GameServerDto` se scinde, et le contrôleur du cœur choisit la projection selon
les permissions de l'acteur. À faire en écrivant A.1, pas après — c'est une décision de contrat
d'API, et la changer plus tard casse le front.

**Deux sources d'autorité, et c'est voulu :**

```
autorité = permissions du rôle  ∪  (acteur ∈ serveur.admins → START/STOP sur CE serveur)
```

C'est la demande « le champ admin me permet de sélectionner qui pourra les gérer » : un rôle
donne un droit *partout*, la liste `admins` le donne *sur un serveur*. Un `PermissionEvaluator`
dans `schub-core.business` répond à `can(actorId, permission, ressource?)` — un seul endroit,
appelé par les contrôleurs du cœur.

**Démarrer et arrêter, rien de plus — décidé le 18-09.** Être admin d'un serveur ne donne ni
l'édition de la fiche, ni les ports. Modifier les ports d'un serveur, c'est écrire dans la table
de redirections de la box : un pouvoir global déguisé en pouvoir local. `SERVER_EDIT` et
`PORT_RULE_EDIT` restent des permissions de rôle.

**Cette même mécanique resservira telle quelle au chantier D** : appartenir à une équipe donnera
des droits sur *cette* équipe, exactement comme appartenir aux `admins` en donne sur *ce*
serveur. Écrire `PermissionEvaluator` avec une ressource générique plutôt qu'un `slug` de serveur
coûte dix minutes maintenant et évite de le réécrire au lot D.4.

**`ROLE_MANAGE` est réservé au rôle `OWNER` — décidé le 18-09.** Ce n'est pas une permission
attribuable : elle n'apparaît pas dans la matrice de l'écran des rôles, et `OWNER` lui-même n'est
pas attribuable depuis l'IHM. C'est ce qui rend « accessible seulement à moi-même » vrai par
construction plutôt que par convention.

**Corollaire à écrire dans le code, sinon la décision ne vaut rien** : `USER_ROLE_ASSIGN` ne
permet d'attribuer qu'un rôle dont les permissions sont un **sous-ensemble** de celles de
l'acteur. Sans cette règle, un `ADMINISTRATOR` crée un rôle « tout coché », se l'attribue, et la
hiérarchie n'existe plus. C'est le chemin d'élévation classique d'un modèle rôles/permissions ;
il se ferme en trois lignes, à condition d'y penser en écrivant A.1.

### A.2 · L'autorisation, route par route

Deux niveaux, et la frontière est nette :

- **BFF** : contrôle *grossier*. `@PreAuthorize("hasAuthority('PORT_RULE_EDIT')")` à partir des
  permissions portées par le JWT. Suffit pour tout ce qui n'est pas lié à un serveur précis.
- **Cœur** : contrôle *fin*, parce que lui seul connaît `admins`. Le BFF et le connecteur Discord
  transmettent l'acteur dans un en-tête `X-Actor-Id` ; le `X-Internal-Secret` est ce qui rend
  cette assertion digne de confiance.

Le connecteur Discord **cesse alors de vérifier les droits lui-même** : `CommandExecutorService`
transmet l'id Discord de l'auteur, et c'est le cœur qui refuse. `Command.roleNeeded()` disparaît
au profit d'une permission par commande. Une seule règle, un seul endroit — aujourd'hui Discord
et le front n'appliquent pas la même.

**La fraîcheur du jeton — tranché le 18-09 : durée courte et réémission glissante.**

Les permissions voyagent dans le JWT, dont la durée passe de 1 h à **15 minutes**. Retirer un
droit prend donc effet en 15 min au pire. Pour que ça ne se paie pas en déconnexions
permanentes, le BFF **réémet** le jeton à chaque requête authentifiée à laquelle il reste moins
de la moitié de sa durée de vie : une session glissante.

Pourquoi pas un couple *access token* / *refresh token* : il faudrait stocker, faire tourner et
révoquer les refresh tokens, donc redonner un état au BFF, qui est sans état depuis la phase 4.
La réémission glissante offre la même propriété — l'utilisateur actif ne se reconnecte jamais,
les droits se rafraîchissent vite — sans rien stocker. Elle n'est possible que **parce que** le
jeton vit dans un cookie (A.3) : c'est le serveur qui le repose, le front n'orchestre rien.

Assumé : un utilisateur inactif est déconnecté au bout de 15 min. Si c'est pénible à l'usage, la
réponse est d'allonger la durée, pas d'ajouter un refresh token.

### A.3 · OAuth2 Discord dans le BFF

> **Livré côté back le 2026-09-19** (`schub-core`#4, `schub-back-bff`#9, fusionnées). Le front —
> bouton et bascule au cookie — est en cours. Ce qui suit reste la référence de conception ;
> trois points ont été tranchés à l'écriture et méritent d'être connus :
>
> - **Le `state` et le vérificateur PKCE vivent dans deux cookies de dix minutes**, effacés dès
>   l'entrée du callback **avant validation** : usage unique, car un `state` qui survit à un échec
>   peut être rejoué. `SameSite=Lax` y est *obligatoire* et non prudent — le retour de Discord est
>   une navigation venue d'un autre site, et `Strict` ne joindrait pas le cookie.
> - **Le scope `identify` est figé en dur dans le code**, pas en configuration : une variable
>   d'environnement mal réglée ne doit pas pouvoir réclamer `email` ou `guilds`.
> - **Le BFF accepte cookie ET `Authorization: Bearer`** le temps que le front bascule. Le retrait
>   du `Bearer` est une étape à part, à faire une fois le front migré — et à ne pas oublier, car
>   tant qu'il est là, un oubli côté front ne se voit pas.
>
> Deux pièges évités à l'écriture, qui auraient exposé des secrets : `DiscordOAuthProperties` est
> un `record`, dont le `toString()` imprime tous les composants — un `log.debug("{}", properties)`
> aurait suffi à poser le client secret dans les journaux ; et l'appel à Discord passe par un
> `RestTemplate` dédié et non par Feign, dont la configuration du BFF aurait envoyé le
> `X-Internal-Secret` de Schub à Discord.

Flux : `GET /auth/discord` → redirection Discord (scopes `identify` uniquement) → `GET
/auth/discord/callback?code=…` → échange du code → `GET /users/@me` → `POST /users/by-discord`
sur le cœur (créé au rôle `USER` si inconnu) → émission du JWT maison.

À anticiper :

- **`state` obligatoire** (CSRF), et PKCE tant qu'à faire. Un callback OAuth sans `state` est une
  faille, pas un raccourci.
- **Le jeton vit dans un cookie `httpOnly` — tranché le 18-09.** Le callback pose
  `Set-Cookie: schub_session=<jwt>; HttpOnly; Secure; SameSite=Lax; Path=/` puis redirige vers
  `/`. Trois raisons de préférer ça au `localStorage` actuel :
  1. **Le callback OAuth est une redirection de navigateur.** En `localStorage`, il faut faire
     transiter le jeton par l'URL — donc dans l'historique, les journaux du proxy et le
     `Referer`. Le cookie supprime le problème au lieu de le contourner.
  2. **Immunité au XSS** : aucun script de la page ne peut lire le jeton. Sur un site qui affiche
     des pseudos Discord et un formulaire de contact, ce n'est pas théorique.
  3. **C'est ce qui rend la réémission glissante (A.2) possible** sans une ligne de code côté front.
  Le front et le BFF sont sur la même origine — `nginx` proxifie `/api/` vers `schub-bff:8080` —
  donc rien ne s'y oppose. `SameSite=Lax` couvre le CSRF : toutes les écritures sont
  `POST`/`PUT`/`DELETE`, et `Lax` ne joint pas le cookie à une écriture inter-sites.
  **Coût, à payer d'un bloc** : `httpClient.ts` cesse de porter un en-tête `Authorization`,
  `authStore.tsx` ne connaît plus de `accessToken` (l'état connecté vient uniquement de
  `GET /auth/me`), et les six `*Api.ts` perdent leur paramètre `accessToken`. C'est mécanique,
  mais ça touche tout `src/api/` — d'où le fait de le faire **avant** le chantier C, pas après.
- **Deux URLs de rappel à déclarer** dans le portail développeur Discord : `http://localhost:…`
  pour le dev **et** `https://schultz-thomas.fr/api/auth/discord/callback` pour la prod.
- **Secrets** : `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, en secrets Swarm
  externes comme les autres, plus les entrées dans `.env.dev.example`.
- **Le compte mot de passe disparaît, mais en dernier** (lot A.6, motivation au §1). Tant que la
  connexion Discord n'a pas fonctionné en prod, `POST /auth/login` reste en place. En revanche
  `authUsername`, `passwordHash` et `findByAuthUsername` de `UserEntity` partent dès maintenant :
  rien ne les écrit ni ne les lit, le mapper les ignore explicitement.
- **Se verrouiller dehors** : le seeding OWNER par `DISCORD_ADMIN_ID` doit être rejoué à chaque
  démarrage (il l'est déjà), et l'IHM doit refuser de retirer le dernier `OWNER` ou de modifier
  son propre rôle.

### A.4 · `GameServer.admins` : des identifiants, pas des pseudos

Le champ est déjà une `List<String>`. Ce qu'il contient devient : **l'id interne du `User`** —
pas le `discordId`. Un id Discord est un identifiant *externe* ; si un jour un compte se lie
autrement, la liste devient fausse. Le cœur résout ensuite `User → discordUsername` pour
l'affichage.

Côté API, `GameServerDto.admins` passe d'une liste de chaînes à une liste de
`{ userId, discordUsername, avatarUrl }` : le front doit afficher qui c'est, comme demandé, sans
faire N appels.

**À anticiper :** les valeurs actuellement en base (dev) sont des pseudos libres saisis à la
main. Le `ChangeUnit` qui migre doit décider quoi en faire — *recommandation : tenter la
correspondance par `discordUsername`, et vider ce qui ne correspond à personne, en le
journalisant*. Silencieusement garder une chaîne qui ne désigne plus rien serait pire.

### A.5 · Les écrans (après B)

Trois, tous sous le menu *Configuration* :

1. **Utilisateurs** — liste, rôle attribuable, compte Riot lié (chantier D), dernière connexion.
2. **Rôles** — matrice rôles × permissions à cocher. Visible seulement avec `ROLE_MANAGE`.
3. **Fiche serveur** — le champ `admins` devient un sélecteur multiple d'utilisateurs, avec
   avatar et pseudo.

L'écran de connexion, lui, se réduit à un bouton « Se connecter avec Discord ».

### A.5 bis · Comment le front sait s'il est administrateur (tranché le 19-09)

Question restée ouverte jusqu'à l'écriture, et dont la réponse évidente était une fuite.

`GET /auth/me` renvoyait un `actorId` qui est l'identifiant **Discord**, alors que
`GameServer.admins` contient des identifiants **internes**. Les deux ne se comparent pas — et la
confusion ne lève aucune erreur : elle répond « non » à chaque fois. Résultat, les boutons
démarrer/arrêter étaient proposés à tout compte connecté, et un `VISITEUR` recevait un 403 en
cliquant. La décision n°11 était appliquée côté serveur mais **invisible côté client**.

La réponse évidente — exposer `admins` dans la projection membre pour que le front compare — est
exclue : c'est précisément la liste que la décision n°10 retire à cette projection, parce qu'un
`VISITEUR` est n'importe qui sur Internet. Et c'est bien ce compte-là qui est concerné, puisqu'un
modérateur inscrit dans les `admins` n'a pas `SERVER_INFRA_VIEW`.

**La réponse retenue : `viewerIsAdmin`**, un booléen calculé pour le lecteur, porté par les deux
projections. **Un fait sur lui, qui ne nomme personne d'autre.** Aucun appel supplémentaire,
aucune fuite, et c'est la seule forme possible sur une projection qui ne peut pas porter la liste.
En complément, le JWT porte désormais l'identifiant **interne** de l'appelant à côté de son
identifiant Discord : c'est le sien, donc pas une fuite, et le sélecteur d'administrateurs du lot
A.5 en a besoin pour se reconnaître.

**À retenir au-delà de ce cas** : chaque fois qu'un écran doit savoir « ai-je le droit sur cet
objet ? », la bonne réponse est un fait sur le lecteur, pas la liste des ayants droit. La liste
est une information sur les autres.

### A.6 · Retrait du compte local — dernier lot, PR séparée

À ne lancer qu'après une connexion Discord réussie **en prod**. Contenu et justification au §1 ;
c'est une suppression pure, et c'est précisément pour ça qu'elle mérite sa propre PR : elle ne
doit pas être noyée dans un diff qui ajoute des fonctionnalités, et elle doit pouvoir être
annulée d'un `revert` si quelque chose se révèle.

---

## 3. Chantier B — Design system et Storybook

### L'objectif réel

La demande n'est pas « avoir un Storybook », c'est **« me forcer à n'utiliser que certains
composants »**. Un Storybook seul ne force rien : il documente. Ce qui force, c'est :

1. un dossier `src/design-system/` qui est la **seule** porte vers MUI ;
2. une règle ESLint `no-restricted-imports` qui **interdit `@mui/material` partout ailleurs** ;
3. une ligne dans le `CLAUDE.md` du repo front qui l'énonce.

Sans le point 2, la consigne sera contournée dans trois semaines, par moi comme par n'importe qui.
C'est le livrable le plus important du chantier, et il tient en vingt lignes de configuration.

### Ce qu'il faut ranger d'abord

L'état actuel est incohérent, et ça se voit : `theme.ts` définit une palette **claire**, pendant
que `LandingPage` et `App` peignent en dur des dégradés **sombres**
(`radial-gradient(... #0d47a1 ...) #071019`). Deux systèmes de couleur qui coexistent sans se
parler. Tant que ce n'est pas tranché, chaque nouvel écran rouvrira la question.

**Tranché le 18-09 : le sombre est le thème par défaut, le clair reste disponible.** C'est
l'inverse de `theme.ts` aujourd'hui. B.1 consiste donc à faire du sombre la palette canonique —
les dégradés actuellement en dur dans les pages en sont la matière première, mais transposés en
tokens — et à porter la palette claire existante en thème alternatif. Le choix se mémorise en
`localStorage` et démarre sur `prefers-color-scheme` au premier passage.

Point de vigilance : MUI 7 sait faire ça nativement, avec `createTheme({ colorSchemes: { dark:
true, light: true } })` et un `defaultMode`. Ne pas réinventer un `ThemeProvider` qui bascule
deux thèmes à la main : l'API existe, elle génère des variables CSS (donc pas de scintillement au
chargement), et `@storybook/addon-themes` sait s'y brancher.

Ordre : **tokens → primitives → composants métier → pages**. Dans l'autre sens, on redessine
trois fois.

### Lots

| Lot | Contenu | Note |
|---|---|---|
| B.0 | **i18n FR/EN** : `react-i18next`, clés typées, `/` = FR et `/en/` = EN, sélecteur en pied de page | voir ci-dessous |
| B.1 | Tokens : palette **sombre canonique** + thème clair alternatif, échelle d'espacement, rayons, ombres, typographie. Un seul fichier, source de vérité. | voir ci-dessus |
| B.2 | Storybook 8 + builder Vite, `@storybook/addon-a11y`, `@storybook/addon-themes` pour basculer clair/sombre | |
| B.3 | Primitives : `Button`, `Card`, `Stack/Section`, `Field`, `Select`, `Badge/StatusChip`, `Table`, `Dialog`, `Toast`, `EmptyState`, `PageHeader` | chacune avec sa story |
| B.4 | ESLint `no-restricted-imports` + `CLAUDE.md` du repo | **le verrou** |
| B.5 | Migration de l'existant (`AllServersComponent`, `PortForwardingCard`, `DiscordChannelsCard`, `AdminActionBar`, `FormActionButton`) vers les primitives | peut traîner après C |
| B.6 | Publication : build statique servi sous `/storybook` par le nginx du front, **lien public en pied de page** | voir ci-dessous |

### B.0 · L'i18n, et pourquoi elle est dans ce chantier et pas dans le suivant

Décidé le 18-09 : le site est **bilingue FR/EN**. Tu as toi-même noté que « ça peut être un gros
ticket » — ça l'est, mais **seulement si on le fait après**.

La différence est brutale : écrit dès le départ, l'i18n est une habitude — on écrit
`t('servers.empty')` au lieu de `"Aucun serveur"`, et ça ne coûte rien. Rattrapé plus tard, il
faut rouvrir chaque fichier de chaque écran, retrouver chaque chaîne, la nommer, et vérifier
qu'aucune n'a été oubliée — sur une quinzaine d'écrans, c'est plusieurs jours de travail sans
valeur visible. C'est exactement l'argument qui met le design system avant les écrans, appliqué
une seconde fois.

Choix techniques, pour ne pas les rouvrir à chaque fenêtre :

- **`react-i18next`**, avec des clés typées (TypeScript sait alors si une clé n'existe pas).
- **Un fichier par langue et par domaine** (`fr/servers.json`, `en/servers.json`…) plutôt qu'un
  gros fichier : deux fenêtres parallèles qui travaillent sur des écrans différents ne se
  marchent pas dessus.
- **URL par langue** : `/` en français, `/en/…` en anglais. Un sélecteur qui ne change pas l'URL
  est plus simple à coder, mais il rend la version anglaise invisible pour les moteurs de
  recherche — or c'est la page d'accueil d'un portfolio. Avec les balises `hreflang`, les deux
  versions sont indexées.
- **Les dates et les nombres passent par `Intl`**, jamais par une chaîne formatée à la main.
- **Le contenu du portfolio est doublé, et c'est le vrai coût** : deux versions à écrire et à
  maintenir. Une piste : rédiger le français, puis générer l'anglais et te le faire relire.

Ce que l'i18n ne couvre pas et qu'il faut décider au cas par cas : les messages d'erreur qui
viennent du **back**. Aujourd'hui ils arrivent en français, en dur. *Recommandation : le back
renvoie un **code** et le front le traduit.* Sinon il faut une i18n côté Java, pour trois écrans
d'administration que seuls des francophones verront.

### À anticiper

- **Vite 4 + Storybook 8** : vérifier la compatibilité dès B.2, avant d'écrire la moindre story.
  Si ça coince, monter Vite à 5 — c'est un changement mineur sur ce projet, mais ça se fait en
  premier, pas au milieu.
- **Le Storybook est public, en pied de page — décidé le 18-09**, à côté des liens Discord,
  LinkedIn et GitHub. C'est cohérent avec le chantier C : sur un portfolio, un design system
  consultable est une pièce du dossier, pas une fuite. Une seule règle à tenir en écrivant les
  stories : **aucune donnée réelle dedans** — pas de vrai pseudo Discord, pas de vraie IP, pas de
  vrai port. Les stories se nourrissent de fausses données, toujours.
- **Le poids du bundle** : le build Storybook ne doit pas partir dans l'image du front par
  accident. Étape de build séparée, copiée dans un répertoire distinct.
- **La revue demandée** (« je les review ») suppose de voir le rendu : le Storybook statique doit
  être consultable *avant* le merge. Le plus simple est de le construire en CI et d'en publier
  l'artefact sur la PR.

---

## 4. Chantier C — Portfolio public à la racine

### Ce qui change dans le routage

Aujourd'hui `/` est la `LandingPage` (statut public des serveurs). Elle devient une **section**
du site, pas la racine. Nouvelle structure :

```
/                 portfolio            public
/servers          statut des serveurs  public (la LandingPage actuelle, déplacée)
/lol              chantier D           public en vitrine, connecté pour l'outil
/lol/teams/:id    page d'équipe, à onglets            membre de l'équipe
/contact          formulaire           public
/login            → OAuth Discord
/config/*         serveurs, ports, utilisateurs, rôles, salons   connecté + permission
/storybook        build statique       public, lié en pied de page
```

Le **pied de page** est public et porte les liens sortants — Discord, LinkedIn, GitHub — et le
Storybook (décidé le 18-09). Il fait partie du layout, au même titre que le header.

Le header (menus + bouton *Connexion* en haut à droite, *Configuration* qui apparaît une fois
connecté) devient un **layout partagé**, pas un morceau de page. C'est un composant du design
system (B.3, `PageHeader` / `AppShell`) : il se fait **après B**, et il est consommé par A.5, C
et D. C'est le point de jonction des quatre chantiers.

### Le contenu

Oui — envoie le PDF ou le texte de ton profil LinkedIn, je génère de bout en bout : accroche,
parcours, compétences, projets (Schub est en soi la meilleure pièce du dossier), et la page
contact. À prévoir de ton côté : une photo, et le choix français seul ou FR/EN.

### À anticiper

- **Le formulaire de contact t'écrit en message privé sur Discord — décidé le 18-09.** Chemin :
  `POST /contact` (public) sur le BFF → `POST /discord/direct-messages` sur le connecteur → le
  bot ouvre un canal privé avec `DISCORD_ADMIN_ID` et envoie le message. Rien de neuf côté
  infrastructure, et la notification arrive là où tu es déjà.
  **Ce qui est neuf côté connecteur** : il sait écrire dans des *salons*
  (`DiscordMessageService`, `ChannelEntity`), pas en privé. La capacité est à ajouter —
  `jda.retrieveUserById(id).flatMap(User::openPrivateChannel).flatMap(c -> c.sendMessage(…))` —
  et elle a **deux modes d'échec silencieux** : le bot doit partager une guilde avec le
  destinataire (c'est le cas), et le destinataire doit accepter les MP des membres de cette
  guilde. D'où un repli obligatoire : si le MP échoue, poster dans un salon abonné plutôt que de
  perdre le message. Un formulaire de contact qui perd des messages est pire que pas de
  formulaire.
- **Une route publique qui déclenche une écriture a besoin d'un anti-spam.** Sans lui, le premier
  robot qui trouve le formulaire transforme ta messagerie Discord en boîte à spam — et on ne se
  désabonne pas d'un bot. Trois couches, toutes bon marché : Turnstile (Cloudflare, gratuit,
  déjà dans ton infra), un champ leurre invisible, et une limitation de débit par IP dans le BFF.
  Secret à prévoir : `TURNSTILE_SECRET`.
- **SEO et partage** : `index.html` a besoin de `<title>`, `<meta description>`, balises
  OpenGraph, `robots.txt`, `sitemap.xml`, favicon. Un SPA Vite ne les produit pas tout seul, et
  c'est la racine d'un domaine à ton nom.
- **Le rendu côté client** : le portfolio sera indexé par Google sans SSR, mais partiellement.
  Si ça compte, la parade légère est de pré-rendre `/` au build (`vite-plugin-prerender` ou une
  page statique séparée). *Recommandation : ne rien faire pour l'instant, mais écrire le contenu
  du portfolio dans des données (`portfolio.ts`) et pas dans du JSX, pour que le pré-rendu reste
  possible sans réécriture.*
- **`AUTH_CORS_ALLOWED_ORIGINS`** est déjà à `https://schultz-thomas.fr` : rien à changer, mais
  toute nouvelle route publique doit être ajoutée explicitement au `permitAll()` du BFF, qui est
  en `anyRequest().authenticated()`.
- **`/servers` déplacée** : le tunnel Cloudflare vise `schub-front:80` et nginx fait déjà
  `try_files … /index.html`. Aucune redirection serveur n'est nécessaire, mais garder un
  redirect client `/ → /servers` pour les liens existants ne coûte rien.

---

## 5. Chantier D — App d'équipe LoL

C'est le plus gros. On le traite dans cet ordre.

### D.0 · Le risque qui n'existe plus (levé le 18-09)

Ce document a d'abord posé un risque bloquant : *les scrims sont des parties personnalisées, et
`match-v5` couvre mal les customs — s'il faut passer par la Tournament API, c'est une clé de
production approuvée et un changement de produit.*

**Ce risque est levé, et il n'était pas fondé.** Précision de l'utilisateur : l'équipe ne joue
**pas** en partie personnalisée. Elle joue en **ranked flex**, en **ranked 5v5** et en **draft
normale** — trois files de matchmaking standard, que `match-v5` couvre intégralement et sans
réserve. Il n'y a ni Tournament API, ni code de tournoi, ni approbation à obtenir pour ça.

Ce que ça change, et ce n'est pas mince :

- **Plus aucun lot du chantier D n'est conditionnel.** L'ordre initial séparait ce qui dépendait
  du spike et ce qui n'en dépendait pas ; cette distinction disparaît.
- **La demande de clé de production redevient un simple sujet de délai** (D.1), pas un risque
  d'existence.
- **Le mot « scrim » est trompeur** et sera évité dans le code : l'objet métier n'est pas une
  partie d'entraînement, c'est **une partie où au moins 4 des 5 membres de l'équipe ont joué**,
  quelle que soit la file. Le paquet s'appelle `team`, pas `scrim`.

Reste une vérification de vingt minutes, qui ne gate plus rien : prendre une partie récente de
ton historique, résoudre ton `puuid` via `account-v1`, la retrouver dans
`/lol/match/v5/matches/by-puuid/{puuid}/ids`, et relever les `queueId` réellement rencontrés
(flex, solo/duo, draft normale) pour les inscrire dans le catalogue de files.

### D.1 · Les clés Riot

- Une **clé personnelle expire toutes les 24 h**. Impossible de faire tourner une collecte
  continue avec. Il faut demander une **clé de production**, ce qui suppose un produit décrit et
  une URL publique qui le présente. *(Une clé de dev valide a été fournie le 18-09 et vérifiée —
  elle sert au développement, pas au déploiement.)*
- → **Le chantier C sert directement le chantier D** : la page `/lol` du portfolio est la page
  produit que Riot demandera. Raison de plus pour faire C avant la demande, et la demande **tôt**
  (le délai d'instruction est subi, pas piloté).
- Limites de débit à respecter dès le premier appel (20 req/s, 100 req/2 min sur clé de dev). Le
  **connecteur** porte le quota : c'est une contrainte du système externe, donc sa place est là,
  avec le cache. Pas dans le domaine.

### D.2 · Où ça vit — dans le cœur (décidé le 18-09)

Le domaine LoL est un **paquet du cœur**, pas un service. `schub-connector-riot` reste un
traducteur pur : il parle à l'API Riot, il ne sait pas ce qu'est une équipe.

```
connector-riot   traduction API Riot, quota, cache, ingestion   (aucune notion d'équipe)
schub-core       Team, Roster, Match ingéré, Draft, Review      (le domaine)
                 + User ↔ puuid : le lien de compte
```

Le raisonnement : à cinq joueurs et un site personnel, un service de plus coûte un dépôt, une
base, une entrée dans `release.yml`, un client Feign, deux entrées de compose et un tag d'image à
bumper — pour aucun gain de disponibilité ni de montée en charge. Ce qui compte n'est pas de
l'extraire un jour, c'est que l'extraction reste **bon marché** le jour où elle se justifie.

**Ce qui la garde bon marché — la seule discipline à tenir :**

```
schultz.thomas.schub.core.team.{api,business,data}
```

Un paquet racine à part, avec ses trois couches, et deux interdits qui font toute la différence :

1. **Aucun dépôt ni entité de `team` n'est lu depuis le domaine hébergement, et réciproquement.**
   Pas de `GameServerRepository` dans `team`, pas de `TeamRepository` en dehors.
2. **Le seul lien avec l'identité est un id.** `RosterMember.userId` référence un `User` — pas de
   `@DBRef`, pas de jointure, pas de champ recopié. Le jour où `team` part, ce lien devient un
   appel HTTP et rien d'autre ne bouge.

Collections préfixées `team_*` dans la base `servers`. Aucun utilisateur Mongo à créer : le cœur
a déjà le sien — c'est aussi pourquoi ce choix allège l'infra (§7).

**Test de dérive, à faire avant chaque merge du chantier D** : `grep -r "\\bteam\\b" --include=*.java`
hors du paquet `team` ne doit rien renvoyer, sauf le câblage dans `config/`. Le jour où ce grep
renvoie du code métier, la sortie du domaine vient de coûter cher.

**Le lien compte Discord ↔ compte Riot vit sur le `User`** (`riotPuuid`, `riotGameName`,
`riotTagLine`), donc hors du paquet `team` : l'identité reste une, et un futur service d'équipe
ne reprendrait pas la propriété des comptes.

**L'ingestion est déléguée au connecteur, comme tu l'as prévu.** La collecte périodique des
parties vit dans `connector-riot` : c'est lui qui détient le quota Riot et le cache, exactement
comme `connector-portainer` détient la sonde d'état depuis le §6 de la migration. Le cœur lui
demande « les parties de ces cinq puuids », il ne planifie pas les appels. Si l'ingestion devient
lourde, elle est déjà du bon côté de la frontière et sortira sans rien casser.

### D.2 bis · Les équipes (précisé le 18-09)

Ce n'était pas « cinq joueurs dans un coin de l'app » : c'est une **notion d'équipe à part
entière**, et elle structure tout le chantier.

Ce qui a été demandé :

- un écran de **création d'équipe** : un nom, et on y ajoute des joueurs ;
- les joueurs ajoutés **voient l'équipe apparaître sur leur compte** ;
- ouvrir une équipe donne une page à **quatre panneaux**.

#### Les quatre panneaux d'une équipe

| Panneau | Contenu | Source |
|---|---|---|
| **1 · Joueurs** | 5 colonnes, une par joueur : ses statistiques individuelles | `match-v5` + `league-v4` (rang, LP) |
| **2 · Équipe** | les parties où **au moins 4 des 5** membres ont joué, **toutes files confondues**, et les résultats qui en découlent | intersection des historiques |
| **3 · Pool de champions** | 5 colonnes, une par poste : les champions jouables selon les maîtrises de chaque membre | `champion-mastery-v4` + Data Dragon |
| **4 · Préparateur de draft** | des **brouillons** de composition, à proposer à l'équipe | domaine seul |

Trois précisions qui ont leur importance :

- **« Au moins 4 des 5 », pas 3.** Le seuil était mal noté dans la première version de ce
  document. Il définit ce qu'est une « partie d'équipe » et il conditionne tout le panneau 2.
- **Toutes les files comptent** — ranked flex, ranked 5v5, draft normale. Le panneau 2 ne filtre
  pas par file, il filtre par *présence des joueurs*. Le `queueId` est conservé et affiché, parce
  qu'une victoire en normale draft ne vaut pas une victoire en flex, mais il n'exclut rien.
- **Le panneau 4 produit des brouillons**, pas des drafts jouées. C'est un outil de proposition :
  on prépare, on enregistre, on montre à l'équipe. Pas de bans, pas d'ordre de pick, pas de
  minuteur — voir la note « ce qui a été demandé n'est pas un simulateur » plus bas.

#### Ce que ça change dans le modèle

```
Team          nom, créateur, membres
TeamMember    (userId | riotPuuid), rôle de jeu (TOP/JGL/MID/ADC/SUP), statut
Composition   équipe, nom, 5 × (rôle, champion, joueur), patch, notes
```

Trois points à trancher en écrivant D.4, parce qu'ils sont coûteux à changer après :

1. **Peut-on ajouter un joueur qui n'a pas de compte Schub ?** Sinon, aucune équipe n'existe tant
   que les cinq ne se sont pas connectés avec Discord — et tu ne peux pas préparer quoi que ce
   soit tout seul. *Recommandation : oui.* Un `TeamMember` est soit **lié** à un `User`, soit
   **libre**, identifié par son seul Riot ID. Un membre libre devient lié le jour où la personne
   se connecte et revendique son Riot ID — c'est le moment où l'équipe apparaît « sur son
   compte », comme demandé.
2. **Qui peut modifier une équipe ?** *Recommandation : son créateur (capitaine), plus `OWNER`.*
   Un membre voit tout et n'écrit rien, sauf ses propres notes de revue. C'est exactement la
   mécanique de portée du §A.1 — appartenir à une ressource donne des droits sur cette ressource
   — d'où l'insistance à écrire `PermissionEvaluator` avec une ressource générique.
3. **Une équipe peut-elle dépasser cinq joueurs ?** Un roster réel a des remplaçants et des
   coachs. *Recommandation : pas de limite à 5, mais une composition en désigne exactement 5.*
   Coder « une équipe = 5 » en dur est le genre d'hypothèse qui se paie six mois plus tard.

Nouvelles permissions, toutes à portée d'équipe : `TEAM_CREATE` (globale), `TEAM_EDIT`,
`TEAM_VIEW`, `COMPOSITION_EDIT`. Le rôle `VISITEUR` reçoit `TEAM_CREATE` — sinon personne ne peut
rien faire de l'outil, ce qui viderait le chantier de son sens.

#### Ce que ça demande à l'API Riot

| Besoin | Endpoint | Panneau |
|---|---|---|
| Riot ID → puuid | `account-v1` | liaison de compte |
| liste des parties d'un joueur | `match-v5` *(ids par puuid)* | 1 et 2 |
| détail d'une partie | `match-v5` *(match)* | 1 et 2 |
| rang et LP | `league-v4` | 1 |
| maîtrises de champions | `champion-mastery-v4` | 3 |
| catalogue des champions, icônes, patch | Data Dragon | 3 et 4 |

### D.2 ter · Le cache du connecteur — ce n'est pas un détail d'optimisation

> « Ce qui a été pull un jour ne doit pas l'être une deuxième fois. »

C'est une **exigence d'architecture**, pas un réglage de performance, et elle justifie à elle
seule que `connector-riot` possède une base — ce que le §3 de la migration lui accordait déjà
(base `riot`), sans qu'on sache encore pourquoi.

Le piège serait d'écrire « un cache » au singulier. Il y a **quatre natures de données** et
quatre politiques ; les confondre donne soit du gaspillage de quota, soit des chiffres faux.

| Donnée | Nature | Politique | Pourquoi |
|---|---|---|---|
| Détail d'une partie terminée | **immuable** | **permanent, jamais re-demandé** | une partie finie ne change plus jamais. C'est le cœur de l'exigence. |
| Liste des ids d'un joueur | **append-only** | **incrémental** par `startTime` | on ne redemande que ce qui est plus récent que le dernier relevé |
| Maîtrises de champions | évolue en jouant | TTL ~ 6 h | un pool de champions n'a pas besoin d'être à la seconde |
| Rang et LP | volatil | TTL ~ 1 h | afficher un LP d'hier serait un bug visible |
| Catalogue Data Dragon | immuable **par version** | permanent, clé = version | c'est ce qui permet de rouvrir une draft de mars et de la voir juste |

**Le point de mise en œuvre à ne pas rater** : les ids se demandent avec un paramètre
`startTime`, à partir du dernier horodatage relevé pour ce puuid. Mais une partie peut
apparaître dans l'historique avec du retard — donc on repart du relevé **moins une heure**, et on
dédoublonne sur le `matchId`. Le recouvrement coûte une lecture Mongo ; son absence coûte des
parties manquantes, qu'on ne voit jamais puisqu'on ne sait pas qu'elles existent.

**Corollaire pour le cœur : il ne stocke aucune partie.** Le domaine possède les équipes, les
membres, les compositions et les agrégats qu'il calcule ; les parties brutes vivent une seule
fois, dans le connecteur. Deux copies de la même donnée, c'est deux vérités et une divergence
garantie. Le cœur demande, le connecteur répond depuis sa base — c'est un appel local sur
l'overlay, il n'y a rien à économiser.

**Et le quota devient presque théorique.** Une fois l'historique constitué, un rafraîchissement
ne coûte que les parties nouvelles : quelques appels par jour et par joueur. Les limites de la
clé de développement (20 req/s, 100 req/2 min) ne sont un sujet qu'au **premier remplissage** —
c'est là, et seulement là, qu'il faut un étalement des appels.

### D.3 · Lots, dans l'ordre

| Lot | Contenu | Livre quoi |
|---|---|---|
| D.1 | Demande de clé de production Riot (administratif, en fond) | rien, mais tôt |
| D.2 | `connector-riot` : `account-v1`, `league-v4`, `champion-mastery-v4`, `match-v5` (ids + détail), Data Dragon, **les quatre politiques de cache** (D.2 ter), étalement du premier remplissage | le socle |
| D.3 | Liaison de compte : écran « lier mon compte Riot » (`Pseudo#TAG`), résolution du puuid, stockage sur le `User` | chacun existe |
| D.4 | Cœur, paquet `team` : `Team`, `TeamMember` (lié ou libre), écran de création, l'équipe apparaît sur le compte de ses membres | **une équipe existe** |
| D.5 | **Panneau 3 — pool de champions** : 5 colonnes par poste, maîtrises croisées au catalogue | premier panneau utile |
| D.6 | **Panneau 4 — préparateur de draft** : brouillons de composition, 5 × (rôle, champion, joueur), enregistrer, rouvrir, partager | l'outil se suffit déjà |
| D.7 | Constitution de l'historique : ids des 5 joueurs, dédoublonnage, détection des parties à **≥ 4 des 5** membres | la matière première |
| D.8 | **Panneau 1 — joueurs** : 5 colonnes de statistiques individuelles, rang, LP | |
| D.9 | **Panneau 2 — équipe** : résultats des parties d'équipe, toutes files, `queueId` affiché | le cœur de la demande |
| D.10 | Revue par joueur (notes attachées à une partie) | |
| D.11 | Planification : créneaux de disponibilité, session programmée, annonce dans un salon Discord (réutilise `connector-discord`) | |

**D.4 → D.6 livrent un outil complet sans qu'une seule partie ait été collectée** : créer son
équipe, voir les pools de champions, préparer des drafts. C'est la première version publiable, et
elle ne dépend d'aucune ingestion. D.7 ouvre ensuite tout le volet statistiques d'un coup.

**Sur le nommage** : plus de `scrim` dans le code (§D.0). Le paquet est `team`, l'objet central
est une partie d'équipe, et le mot « scrim » ne reste que dans le nom de ce document.

### À anticiper

- **RSO (Riot Sign On) n'est pas pour la v1.** Il demande une approbation séparée. La saisie
  manuelle du Riot ID suffit — au prix qu'on ne *vérifie* pas la propriété du compte. Acceptable
  dans une équipe de cinq personnes qui se connaissent ; à dire explicitement plutôt qu'à
  découvrir.
- **Riot ID ≠ nom d'invocateur.** Les `summonerName` sont morts. Tout passe par
  `gameName#tagLine` → `puuid`, et **le `puuid` est la seule clé stable** : un joueur peut changer
  de Riot ID. Ne jamais stocker un pseudo comme identifiant.
- **Routage régional** : `account-v1` et `match-v5` sont sur les routes *régionales* (`europe`),
  les autres sur les routes de *plateforme* (`euw1`). Les confondre donne des 404 qui ressemblent
  à des bugs de code.
- **Volume des données.** Une timeline de partie pèse plusieurs Mo. Cinq joueurs × 20 parties par
  semaine, c'est vite plusieurs Go. Décider dès D.4 : on stocke le match normalisé (petit) et on
  ne récupère la timeline **qu'à la demande**, sans la conserver — ou on la conserve avec une
  purge. Ne pas décider, c'est faire gonfler le volume Mongo de `dynamis` sans s'en apercevoir.
- **Le draft est à un seul écran — tranché le 18-09.** Une personne clique, les autres regardent.
  Pas de WebSocket, pas d'état de session serveur, pas de gestion des reconnexions : la règle
  « HTTP partout, pas de broker » du §5 tient aussi ici. Un draft temps réel multi-postes serait
  un autre projet, et il n'a pas été jugé rentable.
- **Ce qui a été demandé au lot D.6 n'est pas encore un simulateur de draft**, et c'est tant
  mieux : « choisir des champions et des joueurs par rôle et les enregistrer » est une
  **composition préparée**, sans bans, sans ordre de pick, sans minuteur. C'est quelques jours de
  travail au lieu de plusieurs semaines, et c'est ce qui sert réellement à préparer une partie. Le
  simulateur complet — phases de ban, ordre alterné, contre-pick — reste possible plus tard, en
  réutilisant le même modèle : une composition est l'état final d'une draft. Ne pas construire
  l'un en croyant faire l'autre.
- **Les données de champions dépendent du patch.** Data Dragon est versionné : figer la version
  au moment du draft, sinon une draft relue dans trois mois affiche des champions qui n'existaient
  pas.
- **Conditions d'utilisation Riot** : pas de monétisation, mention légale obligatoire, et le
  produit doit rester accessible. À lire avant la demande de clé, pas après le refus.

---

## 6. Ordre, et ce qui se parallélise

### La chaîne critique

```
A.0 décision identité ─► A.1 modèle droits ─► A.2 autorisation BFF ─► A.3 OAuth ─► A.5 écrans
                                                                                      ▲
B.1 tokens + B.0 i18n ─► B.2 storybook ─► B.3 primitives ─► B.4 verrou ────► AppShell ┘
                                                                            │
                                                                            ├─► C portfolio
                                                                            └─► D.3+ écrans LoL
D.2 connecteur riot ─────────────────────────────────────────────────────────────────┘
```

Quatre règles d'ordonnancement, chacune pour une raison précise :

1. **A.2 avant A.3.** Sécurité. Ouvrir la connexion avant l'autorisation, c'est ouvrir l'admin à
   tout Discord.
2. **B avant tout écran neuf.** Économie. A.5, C et D.3+ représentent une quinzaine d'écrans ;
   les écrire avant les primitives, c'est les écrire deux fois.
3. **B.0 (i18n) avec B.1, pas après.** Même argument, en pire : rattraper l'i18n, c'est rouvrir
   chaque fichier de chaque écran pour en extraire chaque chaîne. Fait dès le départ, c'est une
   habitude d'écriture qui ne coûte rien.
4. **D.1 tout de suite, même si D est traité en dernier.** Délai subi : la clé de production Riot
   s'obtient en semaines, pas en heures. *(La règle « D.0 d'abord » a disparu le 18-09 : le
   risque qu'elle couvrait n'existe pas — voir D.0.)*

### Découpage en fenêtres parallèles

Le découpage est **par dépôt** : deux sessions dans le même dépôt s'écrasent (c'est déjà arrivé
sur ce projet). Une fenêtre = un dépôt = une branche = une PR.

| Fenêtre | Dépôts touchés | Contenu | Démarre |
|---|---|---|---|
| **1 — Identité** | `schub-core`, `schub-back-bff`, `schub-connector-discord` | A.1, A.2, A.3, A.4 (A.6 après la prod) | immédiatement |
| **2 — Design system** | `schub-front-servers` | B.1 → B.4 | immédiatement |
| **3 — Riot** | `schub-connector-riot` | D.1, D.2 | immédiatement |
| **4 — Portfolio** | `schub-front-servers` | C | **après** la fenêtre 2 |
| **5 — Écrans d'admin** | `schub-front-servers` | A.5 | après 1 **et** 2 |
| **6 — Équipe LoL** | `schub-core` (paquet `team`) | D.4 → D.10 | après 1 **et** 3 |
| **7 — Infra** | `schub-infra-docker` | secrets OAuth et Riot, storybook nginx, retrait de `AUTH_ADMIN_*` | au fil de l'eau |

Les fenêtres 2, 4 et 5 touchent **le même dépôt front** : elles ne tournent pas en même temps,
ou alors dans des `git worktree` distincts avec des périmètres de fichiers disjoints — et même
là, `package.json` sera un point de collision.

La fenêtre 1 touche trois dépôts à la fois : c'est inévitable, le contrat traverse les trois.
Elle produit trois PR qui doivent être relues **ensemble** — le cœur qui expose `/users` sans le
BFF qui l'appelle ne se teste pas.

Depuis la décision n°7, la fenêtre 6 vit dans `schub-core`, donc **dans le même dépôt que la
fenêtre 1**. Ce n'est pas un problème d'ordonnancement — la fenêtre 1 est terminée depuis
longtemps quand la 6 démarre — mais c'en serait un si le chantier D était avancé. Si tu veux les
faire se chevaucher, alors `git worktree`, et le paquet `team` étant isolé par construction, les
collisions se limitent à `pom.xml` et au câblage `config/`.

### Vague 1 (maintenant) — trois fenêtres, aucune collision

- **F1** : A.1 + A.2 (le modèle et l'autorisation, sans OAuth). Livrable vérifiable : les routes
  existantes refusent un jeton sans la bonne permission.
- **F2** : B.1 + B.2 + B.4 (tokens, Storybook, verrou ESLint). Livrable : `npm run storybook`
  ouvre, et un `import` MUI hors design-system échoue au lint.
- **F3** : D.2 (le connecteur Riot). Livrable : les six appels câblés et **les quatre politiques
  de cache en place** — une partie déjà collectée n'est jamais redemandée. Plus, en fond, la
  demande de clé de production envoyée (D.1).

### Vague 2

- F1 continue sur A.3 + A.4 (OAuth, `admins`). A.6 — le retrait du compte local — attend une connexion Discord réussie en prod, et part dans sa propre PR.
- F2 continue sur B.3 (primitives) puis l'`AppShell`.
- F3 continue sur D.3 (liaison de compte) — qui touche aussi le front, donc à coordonner avec F2.

### Vague 3

- F4 (portfolio) et F5 (écrans d'admin) — en série sur le dépôt front, pas en parallèle.
- F6 démarre (paquet `team` du cœur).
- F7 suit chaque livraison.

---

## 7. Points transverses à ne pas découvrir en route

**Sept dépôts, une release — et ils restent sept.** C'est le bénéfice le plus concret de la
décision n°7 : pas de huitième entrée dans `SUBREPOS`, `.gitmodules`, `RELEASE_PAT` et
`release.yml`, pas de dépôt GitHub à créer avant la première release. `release.yml` traite les
sous-dépôts **en séquence** et attend nommément le workflow `release - docker image` de chacun ;
le §9 de la migration signale déjà que la séquence devient longue. Sa parallélisation (phase 6)
reste souhaitable, mais elle cesse d'être urgente.

**Les tags d'images se bumpent à la main** dans `docker-compose.yml` (`v2.0.1` aujourd'hui, ligne
par ligne). Chaque livraison de ces chantiers passe par là.

**Les secrets à créer avant déploiement** (secrets Swarm externes + `.env.dev.example`) :
`DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, `RIOT_API_KEY` et `TURNSTILE_SECRET`.

> ⚠️ **Le client secret Discord communiqué le 18-09 est à considérer comme compromis** : il a
> transité par un canal de conversation, donc par des journaux. Il doit être régénéré depuis le
> portail développeur (*OAuth2 → Reset Secret*) **avant** le premier déploiement, et le nouveau
> ne doit jamais quitter le secret Swarm et le `.env.dev` local. Le client id `449160985417089024`
> n'est pas un secret : il est public par conception. La clé Riot de développement expire d'
> elle-même en 24 h.

**Le compte OWNER de la prod était le mauvais — corrigé le 18-09.** `docker-compose.yml` portait
`DISCORD_ADMIN_ID: 245281978054737920` / `DISCORD_ADMIN_USERNAME: admin`, en dur, alors que
`.env.dev.example` a toujours porté le bon (`227883780512153610` / `pisel`). Au premier
déploiement, le compte semé en OWNER aurait donc été **un compte tiers** — et avec le SSO, ce
compte aurait tout obtenu pendant que toi tu serais arrivé en `VISITEUR`. La valeur est alignée
sur celle du dev ; à vérifier d'un œil avant de déployer, c'est un nombre et personne ne les lit.
Aucune base ni utilisateur Mongo à ajouter : `mongo-init-databases.js` crée déjà `bot`, `servers`
et `riot`, et le paquet `team` vit dans `servers`. À l'inverse, `AUTH_ADMIN_USERNAME` et
`AUTH_ADMIN_PASSWORD` sont à **retirer** des deux composes au lot A.6.

> **Trou trouvé le 18-09 en relisant la PR du connecteur Riot** : `MONGO_RIOT_PASSWORD` existe
> dans `.env.dev.example`, mais **pas** dans `docker-compose.yml` — ni comme secret Swarm externe,
> ni monté sur `schub-mongo`. Or `mongo-init-databases.js` le lit pour créer l'utilisateur `riot`.
> En l'état, `task db:init:prod` ne créerait pas cet utilisateur et le connecteur Riot ne pourrait
> pas se connecter en prod. À câbler exactement comme `MONGO_BOT_PASSWORD` et
> `MONGO_SERVERS_PASSWORD`, qui ont déjà ce montage.

### La passe infra à faire après les PR de la vague 1 (relevé le 18-09)

Aucun agent n'a touché au dépôt d'infra — c'était la consigne, trois agents dans le même compose
étant précisément la collision qu'on évite. Voici le relevé consolidé :

| Variable / secret | Service | Action |
|---|---|---|
| `DISCORD_ADMIN_ID`, `DISCORD_ADMIN_USERNAME` | `schub-core` | **ajouter** — c'est le cœur qui sème l'OWNER désormais |
| `DISCORD_ADMIN_ID` | `schub-bff` | **ajouter** |
| `DISCORD_ADMIN_ID`, `DISCORD_ADMIN_USERNAME` | `connector-discord` | **retirer** — plus rien ne les lit |
| `AUTH_JWT_EXPIRATION_SECONDS` | `schub-bff` | **passer de `3600` à `900`**, ou retirer |
| `RIOT_API_KEY` | `connector-riot` | **créer** (secret Swarm + `.env.dev.example`) |
| `MONGO_RIOT_PASSWORD` | `schub-mongo` | **créer** et monter — voir l'encadré ci-dessus |
| `MONGO_HOST/USERNAME/PASSWORD/DB=riot` | `connector-riot` | **ajouter** |
| service `dev-connector-riot` | compose de dev | **créer**, port hôte 18085 → 8080 |

> ⚠️ **`AUTH_JWT_EXPIRATION_SECONDS: 3600` est présent dans les deux composes** et l'emporte sur
> le défaut du dépôt. Tant qu'il n'est pas changé, **la décision n°3 (15 min + réémission
> glissante) est inerte** : le code est là, le réglage l'annule. C'est le genre d'écart qui ne se
> voit jamais, parce que tout fonctionne — juste pas comme décidé.

**Mongock possède le schéma.** Toute évolution de `servers` (rôles, users, `admins`) est un
`@ChangeUnit` dans `schub-core`, appliqué au démarrage. Rien à lancer à la main — sauf le
déplacement inter-bases décrit au §1, qui est justement ce qu'on évite en agissant maintenant.

**Le port-forwarding attend toujours** : le dry-run n'a pas encore été imprimé ni transcrit en
règles permanentes (§4 bis). Ce n'est pas dans ces chantiers, mais c'est la seule chose qui puisse
fermer Samba ou HomeAssistant par inadvertance. À ne pas laisser se faire pousser hors du champ
de vision par ces quatre projets.

**Un autre agent écrit dans cet arbre de travail.** Vérifier `git status` avant de commencer une
fenêtre, et ne jamais supposer que l'état trouvé est celui qu'on a laissé.

---

## 8. Décisions arrêtées le 2026-09-18

| # | Question | Décision | Détail |
|---|---|---|---|
| 1 | L'identité migre-t-elle vers `schub-core` ? | **oui, et maintenant** — prod vierge | §1 |
| 1 bis | Le compte admin local | **supprimé**, remplacé par un id Discord. Plus aucun login/mot de passe | §1, lot A.6 |
| 2 | `ROLE_MANAGE` | **réservé à `OWNER`**, non attribuable | A.1 |
| 3 | Fraîcheur du jeton | **15 min + réémission glissante**, pas de refresh token | A.2 |
| 4 | Transport du jeton | **cookie `httpOnly`** (arbitré par moi) | A.3 |
| 20 | Comment le front sait s'il est admin d'un serveur | **`viewerIsAdmin`**, booléen calculé pour le lecteur — pas la liste des admins | A.1 |
| 5 | Thème | **sombre par défaut**, clair conservé en alternatif | B.1 |
| 6 | Formulaire de contact | **MP Discord du bot**, avec repli salon + anti-spam | C |
| 7 | Domaine LoL | **dans le cœur**, paquet isolé ; ingestion au connecteur | D.2 |
| 8 | Draft | **un seul écran**, état dans l'URL, pas de temps réel | D.6 |
| 9 | Profil LinkedIn | **fourni et complet** (export PDF) | §9 |
| 10 | Que voit un compte sans rôle ? | rôle **`VISITEUR`**, consultation seule — d'où **trois** niveaux de visibilité d'un serveur | A.1 |
| 11 | Être admin d'un serveur donne quoi ? | **démarrer et arrêter**, rien d'autre | A.1 |
| 12 | Équipes LoL | **plusieurs équipes**, créées par n'importe quel compte ; page à onglets ; les membres la voient sur leur compte | D.2 bis |
| 13 | Storybook | **public**, lié en pied de page avec Discord / LinkedIn / GitHub | B.6, C |
| 14 | Files de jeu | **pas de partie personnalisée** : ranked flex, ranked 5v5, draft normale → le risque Tournament API **est levé** | D.0 |
| 15 | Seuil « partie d'équipe » | **au moins 4 des 5**, toutes files confondues | D.2 bis |
| 16 | Cache Riot | **exigence d'architecture** : ce qui a été collecté ne l'est plus jamais deux fois. Quatre politiques distinctes | D.2 ter |
| 17 | i18n | **FR/EN**, écrit dès B.0 et pas rattrapé ensuite | B.0 |
| 18 | Photo | **on s'en passe** pour l'instant | §9 |
| 19 | `DISCORD_ADMIN_ID` | la prod portait **un compte tiers** — corrigé le 18-09 | §7 |

**Trois conséquences de la réponse n°10 qui ne se voyaient pas dans la question.** « Tout le monde
peut se connecter » + « un visiteur peut voir » veut dire qu'un inconnu muni d'un compte Discord
voit ce que voit un membre. D'où : (a) le `GameServerDto` se scinde en trois projections et non
deux, (b) `deploymentId`, les ports et les admins passent derrière `SERVER_INFRA_VIEW`, (c) les
stories du Storybook public ne contiennent aucune donnée réelle.

**Sur le n°4, que tu m'as laissé arbitrer** : cookie `httpOnly`, et la raison décisive n'est pas
le XSS mais le **callback OAuth**. Un `localStorage` oblige à faire transiter le jeton par l'URL
de retour, donc dans l'historique du navigateur, le `Referer` et les journaux du proxy — on
choisit alors entre une mauvaise pratique et un contournement. Le cookie fait disparaître la
question, et il rend possible la réémission glissante du n°3 sans une ligne de code côté front.
Les deux décisions se tiennent ; c'est pour ça qu'elles se prennent ensemble.

## 9. Contenu du portfolio — reçu le 18-09

Export PDF LinkedIn fourni. Le parcours est complet, il n'y a plus de trou.

### Le parcours

| Période | Poste | Où |
|---|---|---|
| nov. 2024 → aujourd'hui | **Ingénieur Full Stack**, Liebherr Mining | Colmar |
| juil. 2023 → nov. 2024 | Ingénieur Full Stack, Librairie LDE — projet Poplab | Molsheim |
| sept. 2021 → juil. 2023 | Ingénieur Full Stack, SFEIR — projet Stellantis | Strasbourg |
| fév. → sept. 2021 | Stage de fin d'études, SFEIR — projet Sidel | Strasbourg |
| juil. 2020 | Stage, SDIS 67 — service GUNSI | Wolfisheim |
| juil. → sept. 2017 | Agent centre d'appels, Euro Protection Surveillance | Illkirch |

**Formation** : diplôme d'ingénieur en informatique, ENSISA (2018-2021) · semestre à la
Fachhochschule Aalen (2018) · DUT informatique, IUT Robert Schuman (2016-2018) · MPSI, lycée
Kléber (2015-2016).
**Langues** : français natif, anglais professionnel complet, allemand professionnel, alsacien.
**Compétences mises en avant sur LinkedIn** : Vue.js, PostgreSQL, GitFlow.

### Trois observations avant d'écrire une ligne

1. **Le fil conducteur est net, et LinkedIn ne le raconte pas.** Quatre ans d'ingénieur full
   stack en continu, chez un ESN puis chez deux industriels — Stellantis, puis l'édition
   scolaire, puis les engins miniers. Ce n'est pas une collection de missions, c'est quelqu'un
   qui livre du logiciel métier dans des environnements contraints. C'est l'accroche du site.
2. **Il y a un décalage à exploiter, pas à cacher.** LinkedIn dit *Vue.js, PostgreSQL, GitFlow*.
   Ce dépôt dit Spring Boot, React, Docker Swarm, MongoDB, sept microservices, un bot Discord,
   une découpe documentée et argumentée, du port-forwarding piloté par API. **La preuve est plus
   forte que la déclaration** : la section projets doit montrer Schub en premier, avec ce
   document et le précédent comme pièces — très peu de profils peuvent exhiber une décision
   d'architecture écrite, datée et corrigée après vérification.
3. **La sobriété du parcours plaide pour une page riche.** Un CV chronologique de six lignes ne
   remplit pas une page d'accueil. C'est ce qui tranche la question du ton : page d'ingénieur qui
   montre ce qu'il construit, avec le parcours en second rideau.

### Tranché le 18-09

- **Pas de photo** pour l'instant — la page se conçoit très bien sans, et elle s'en ajoutera une
  plus tard sans rien casser à condition de lui réserver sa place dans la maquette dès le départ.
- **FR/EN**, donc i18n partout : voir B.0, c'est ce qui la fait entrer dans le chantier B.

### Ce qui manque encore

1. **Deux ou trois phrases sur ce que tu fais aujourd'hui chez Liebherr**, avec la pile réelle —
   reporté à plus tard, et c'est tenable : c'est le seul paragraphe manquant. La page peut
   s'écrire entièrement autour, avec un emplacement réservé. **Mais elle ne se publie pas sans**,
   parce que c'est le premier paragraphe que lit un visiteur.
2. **Ton adresse `schultz.thomas@free.fr` : affichée ou non ?** Elle est dans le PDF, et le PDF
   ne sera pas publié. *Recommandation : ne pas l'afficher.* Le formulaire de contact existe
   précisément pour ça, et une adresse en clair sur une page indexée finit toujours dans les
   listes de diffusion. Les liens Discord, LinkedIn et GitHub du pied de page suffisent au reste.
3. **Les URL de tes profils Discord, LinkedIn et GitHub** pour le pied de page — LinkedIn je
   l'ai, les deux autres non.

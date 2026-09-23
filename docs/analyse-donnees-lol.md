# Analyse LoL — plan des données et des calculs

> Rédigé le 2026-09-23. Prolonge le §D de `evolutions-2026-09.md`. Chiffres mesurés sur la base
> de dev le même jour.

## 0. Verdict : est-ce qu'on est prêt ?

**Pour le stockage, oui. Pour la population de référence, non. Et la prochaine release ne doit
partir en prod qu'une fois ce point réglé.**

- Ce qui est immuable est bien en base et ne sera jamais redemandé : le JSON brut de chaque
  partie (`riot_match`), et la timeline brute des parties d'équipe.
- Tout ce qui est dérivé est versionné et se recalcule depuis le brut sans appel à Riot
  (`PROJECTION_VERSION`, `MatchEarlyStats.CURRENT_VERSION`). Ajouter tes métriques de partie
  ne demande aucun appel à Riot, même dans un an.
- **Le trou** : les référentiels par rang ont besoin du rang de chaque joueur *au moment de la
  partie*. Aujourd'hui, on n'a le rang que de **1 460 comptes sur 101 793** (7 580 participations
  sur 141 146, soit 5 %), et on ne garde que le dernier relevé. Un rang qu'on n'a pas relevé à
  l'époque de la partie est **perdu pour toujours** : c'est la seule donnée de ce plan qu'on ne
  peut pas rattraper.
- **Le biais** : la collecte suit les comptes croisés par l'équipe. Résultat en dev : 372 Platine,
  318 Émeraude, 1 Challenger, 1 Fer. Un « niveau Challenger » calculé sur un seul Challenger ne
  veut rien dire.

Donc : les métriques peuvent arriver après la release, puisqu'elles se recalculent. **La collecte
du rang et l'échantillonnage par palier doivent partir avec elle**, puisqu'ils ne se rattrapent
pas.

## 1. L'existant, collection par collection

| Collection | Contenu | Taille dev | Nature | Verdict |
|---|---|---|---|---|
| `riot_match` | JSON brut Riot | 13 461 × 80 ko (24 ko sur disque) | immuable | ✅ garder tel quel |
| `riot_match_timeline` | timeline brute, parties d'équipe | 275 × 826 ko (173 ko sur disque) | immuable | ✅ ; politique à étendre (§5) |
| `riot_participation` | une ligne par joueur et par partie | 141 146 × 0,8 ko | dérivé versionné | ✅ ; à enrichir (§3), reconstruction à revoir (§8) |
| `riot_match_early` | chiffres à 15 min, ganks | 275 | dérivé versionné | ✅ |
| `riot_match_rank` | rangs des dix joueurs relevés à la collecte | 275 | observation datée | ✅ ; seulement pour les parties d'équipe |
| `riot_ranking` | dernier rang connu, TTL 1 h | 1 460 | volatil, **écrasé** | ❌ perd l'historique (§4) |
| `riot_player_position` | sommes joueur × poste, `$out` **toutes les heures sur tout l'historique** | 85 560 | agrégat | ❌ ne tiendra pas à 20 M de lignes (§6) |
| `riot_metric_scale` | bornes p5/p95 par palier × poste, un seul document | 1 | référentiel | ❌ écrasé, non daté par patch (§6) |

Côté lecture, les moyennes d'un joueur se calculent déjà à la volée depuis `riot_participation`
(`ParticipationStatsService`), en **sommes et non en moyennes** : c'est le bon choix, on le garde.

## 2. Trois notions à ne jamais confondre

C'est ta crainte, et elle est fondée. Il y a trois questions différentes, avec trois calculs
différents. Le front doit les nommer différemment.

| Notion | Question | Calcul | Affichage |
|---|---|---|---|
| **A. Position dans son palier** | « Où suis-je parmi les Or supports ? » | percentile dans la population *de son rang*, au même poste | « 72ᵉ percentile des Or · Support » |
| **B. Échelle du ladder** | « À quel rang correspond cette valeur ? » | percentile dans la population *de tous les rangs*, pondérée par la répartition du ladder, puis lu sur tes seuils (Fer 3,96 %…) | l'icône de rang, infobulle « meilleur que 96 % des joueurs, tous rangs » |
| **C. Profil type d'un palier** | « Combien de CS/min fait un Diamant ? » | médiane de la population Diamant | valeur de comparaison, jamais une note |

**Le piège exact** : B et C ne donnent pas le même rang. Si la vision corrèle peu avec le rang, le
CS/min médian des Diamant peut se situer au 80ᵉ percentile global, soit « niveau Platine » sur
l'échelle B. Afficher une icône Diamant (B) sur une valeur qui vaut la médiane Or (C) est
cohérent mathématiquement et incompréhensible pour l'utilisateur. D'où la règle :

- **Une icône de rang, c'est toujours B.** Son infobulle dit toujours « tous rangs confondus ».
- **Un percentile chiffré, c'est toujours A**, et il nomme sa population.
- **C n'est jamais une note**, seulement une ligne de repère (« médiane Diamant : 7,8 »).

A est la vue principale : c'est ce que tu décris avec « filtrer par le rang du joueur ». B est la
touche ludique. Les deux sortent **du même calcul** (§6), donc ça ne coûte rien de plus.

### Les seuils de l'échelle B

Tes proportions, cumulées depuis le bas (renormalisées, la somme fait 100,01 %) :

| Rang | Part | Seuil bas (percentile) |
|---|---|---|
| Fer | 3,96 % | 0 |
| Bronze | 16,58 % | 3,96 |
| Argent | 21,46 % | 20,54 |
| Or | 23,62 % | 42,00 |
| Platine | 17,68 % | 65,62 |
| Émeraude | 12,22 % | 83,30 |
| Diamant | 3,69 % | 95,52 |
| Maître | 0,73 % | 99,21 |
| Grand Maître | 0,05 % | 99,94 |
| Challenger | 0,02 % | 99,98 |

Ces parts sont **une configuration datée**, pas une constante : elles changent à chaque saison.
Elles vivent dans un document `riot_ladder_distribution` (saison, source, date), et chaque
référentiel note la version utilisée.

**Maître, GM et Challenger sont fusionnés en « Maître+ »** tant que la population ne permet pas
d'estimer un 99,98ᵉ percentile : il faut plusieurs milliers de joueurs *au-dessus* du seuil pour
qu'il soit stable, on n'en aura pas avant longtemps. Le seuil se sépare tout seul quand la
population le permet (au moins 30 joueurs au-dessus de chaque seuil publié).

## 3. Calculer une fois : les métriques de partie

Calculées à la projection, stockées sur `riot_participation` (`PROJECTION_VERSION` 3). Tout vient
du JSON brut déjà stocké, sauf la phase de laning, qui demande la timeline.

Choix : **stocker les valeurs brutes de la partie, pas les ratios**. On stocke `wardsKilled` et
`durationSeconds`, pas `wardsKilledPerMinute`. Les moyennes se font en rapport de sommes
(Σ valeurs / Σ minutes), comme aujourd'hui, et un ratio de partie se recalcule en une division.
Quelques champs précalculés ne servent que s'ils coûtent à recalculer (écarts face à l'adversaire).

| Famille | Métrique | Source Riot | Timeline | Sens |
|---|---|---|---|---|
| Revenus | CS/min | `totalMinionsKilled + neutralMinionsKilled` | non | ↑ |
| | Or/min | `goldEarned` | non | ↑ |
| Vision | Score de vision/min | `visionScore` | non | ↑ |
| | Balises détruites/min | `wardsKilled` | non | ↑ |
| | Balises de contrôle posées | `detectorWardsPlaced` | non | ↑ (ajout) |
| Combats | Dégâts/min | `totalDamageDealtToChampions` | non | ↑ |
| | Part des dégâts de l'équipe | dégâts ÷ Σ équipe (calculé, pas `challenges.teamDamagePercentage`) | non | ↑ |
| | Participation aux kills | (K + A) ÷ kills de l'équipe | non | ↑ |
| | Part des morts de l'équipe | D ÷ morts de l'équipe | non | ↓ |
| Survie | Morts/10 min | `deaths` | non | ↓ |
| | KDA | (K + A) ÷ max(D, 1) | non | ↑ |
| | Temps mort | `totalTimeSpentDead` ÷ durée | non | ↓ (ajout) |
| Objectifs | Dégâts aux tours/min | `damageDealtToTurrets` | non | ↑ |
| | Tours participées | `turretTakedowns` | non | ↑ |
| | Dégâts aux monstres épiques/min | `damageDealtToEpicMonsters` | non | ↑ |
| Laning | Écart d'or à 15 min | cadre de 15 min, face à l'adversaire du même poste | **oui** | ↑ |
| | Écart de CS à 15 min | idem | **oui** | ↑ |
| | Écart de kills à 15 min | événements `CHAMPION_KILL` ≤ 15 min | **oui** | ↑ |
| | Écart de plaques | `challenges.turretPlatesTaken`, lui − adversaire | non | ↑ |

Trois corrections par rapport à ta liste :

- **« Dégâts aux objectifs »** : `damageDealtToObjectives` de Riot *inclut les tours*. Le compter à
  côté des dégâts aux tours revient à compter les tours deux fois. On prend
  `damageDealtToEpicMonsters` (dragons, nashor, héraut, larves).
- **Les plaques n'ont pas besoin de la timeline** : elles tombent à 14:00, donc le total de fin
  de partie *est* le total à 15 min. Seul l'or, le CS et les kills à 15 min la demandent.
- **On calcule soi-même au lieu de lire `challenges`** quand les champs de base suffisent :
  `challenges` est absent de certains modes et Riot en change le contenu sans prévenir.

**L'adversaire de couloir** = le joueur de l'autre camp au même `teamPosition`. Quand les postes
sont inconnus ou en double (remake, normale en aveugle), les écarts restent vides : pas de
métrique plutôt qu'une fausse.

Coût : environ 25 champs de plus, la ligne passe de 0,8 à ~1,3 ko. À 20 millions de
participations, ~26 Go plus les index. Rien à côté des 3 To.

## 4. Le rang : le vrai goulot

Tout le plan repose sur « ce joueur était Or quand il a joué cette partie ». Aujourd'hui, un rang
coûte un appel par joueur (`league-v4/entries/by-puuid`). Trois changements :

**4.1 Relever les rangs en masse.** `league-v4` sert aussi les classements par division :
`/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{division}?page=N` rend **205 joueurs par appel**,
avec leur puuid, et `challengerleagues`, `grandmasterleagues`, `masterleagues` rendent toute la
ligue en un appel. C'est 200 fois moins cher que le relevé joueur par joueur.

**4.2 Garder l'historique.** Nouvelle collection `riot_rank_history` : une ligne
`(puuid, file, tier, division, lp, observedAt)`, écrite **seulement quand le rang change**.
`riot_ranking` reste le cache « rang courant ». Le rang d'une participation = le relevé le plus
proche de la date de partie, s'il est à moins de 30 jours. Au-delà : pas de rang, la
participation est exclue des référentiels (elle reste dans les stats du joueur).

**4.3 Échantillonner par palier.** La collecte de fond garde son rôle actuel (comptes croisés par
les utilisateurs de Schub), et gagne une seconde source : des **graines** tirées des pages de
classement, avec un quota par palier et par fenêtre de patch. Pour chaque graine, ses 20
dernières parties classées.

- Une graine donne son rang exact. Ses neuf co-joueurs, eux, reçoivent le **rang de la partie**
  (celui de la graine), marqué `estimé` : le matchmaking classé en solo tient les parties à un
  palier près. On mesure l'écart sur les joueurs dont on connaît aussi le rang réel avant de s'y
  fier ; si l'accord est sous 70 % au palier près, on n'utilise que les rangs exacts.
- Budget : 300 graines par palier et par fenêtre de 4 semaines, 8 paliers, ~41 appels par graine
  (1 liste d'ids + 20 parties + 20 timelines) ≈ 100 000 appels, soit **1,4 jour de quota** sur
  28. Le quota n'est pas la limite, le reste va à la collecte habituelle.

Ce lot doit partir **avec** la release qui lance l'ingest de prod.

## 5. Les timelines : quoi garder

La phase de laning demande la timeline, et un référentiel de laning demande des timelines pour
toute la population, pas seulement pour l'équipe.

Mesuré sur une timeline de dev : 354 ko, dont 176 ko pour les seuls `CHAMPION_KILL` (le détail
des dégâts reçus par la victime) et 136 ko pour les cadres par minute. Les achats, sorts et
montées de niveau pèsent le reste.

Décision :

- **Parties d'équipe et parties des comptes liés à Schub : timeline brute**, comme aujourd'hui.
- **Parties classées de l'échantillon : un condensé**, collection `riot_timeline_digest` : par
  minute et par joueur `(or, xp, cs, cs jungle, niveau, x, y)`, et les événements `CHAMPION_KILL`
  (sans le détail des dégâts), `BUILDING_KILL`, `TURRET_PLATE_DESTROYED`, `ELITE_MONSTER_KILL`,
  `WARD_PLACED`, `WARD_KILL`. Estimé à 25–35 ko contre 826 ko, à mesurer sur 100 timelines
  avant de figer le format.
- Les autres parties de la collecte de fond : pas de timeline.

Le condensé est un choix irréversible : si un jour on veut une métrique tirée des achats d'objets
sur la population, elle ne sera calculable que sur les parties collectées après. Le format garde
volontairement les positions par minute, qui servent déjà aux ganks et serviront au pathing.

## 6. Calculer périodiquement : les référentiels

**Fréquence : une fois par jour** (5 h). Le toutes-les-heures actuel est du calcul perdu : sur une
fenêtre de quatre semaines, une journée de parties en plus déplace un percentile de moins de 1 %.
Plus souvent, c'est possible (le calcul prend quelques minutes) et inutile. Un recalcul est aussi
déclenché au changement de patch.

**Deux distributions par métrique, pas une.** C'est la correction la plus importante de ton plan :

| Distribution | Ce qu'on compare | Population |
|---|---|---|
| **par partie** | une partie isolée | toutes les participations classées de la fenêtre |
| **par moyenne** | la moyenne d'un joueur | les joueurs à ≥ 10 parties au poste dans la fenêtre, en rapport de sommes |

Une partie isolée varie beaucoup plus qu'une moyenne. Noter une partie avec la distribution des
moyennes classe une bonne partie sur deux « Challenger » et une mauvaise sur deux « Fer ». Noter
une moyenne avec la distribution des parties écrase tout le monde vers le milieu. Chaque note
utilise la distribution qui correspond à ce qu'elle note.

**Ce qu'on stocke** : collection `riot_reference`, un document par
`(fenêtre, portée, poste, palier, métrique)` avec une grille de quantiles (p1 à p99, plus p99,5 et
p99,9) et l'effectif. 8 paliers × 5 postes × ~20 métriques × 2 portées ≈ 1 600 documents de
~1 ko par fenêtre : **quelques Mo par an**, on garde tout l'historique.

- A se lit directement dans la grille du palier du joueur.
- B = le mélange des grilles des paliers pondéré par `riot_ladder_distribution`, stocké dans le
  même document sous forme de seuils (la valeur à atteindre pour chaque icône). Le mélange
  corrige le biais d'échantillonnage : peu importe qu'on ait 3 fois plus de Platine que de Fer,
  chaque palier pèse ce qu'il pèse dans le ladder.
- C = la médiane de la grille du palier.

**La fenêtre de référence** = les 2 derniers patchs, parties classées solo et flex seulement (420,
440). Les normales et le Swiftplay ne jouent pas au même rythme. Au début d'un patch, tant que la
nouvelle fenêtre n'a pas l'effectif minimum, on garde la précédente. Une partie est notée avec la
référence de **son** patch : une partie d'il y a six mois garde sa note d'alors.

**Le calcul** : Mongo 7.0 (vérifié en dev) a l'accumulateur `$percentile`. Un `$group` par
`(poste, palier)` sur les participations de la fenêtre, filtrées sur un index
`{patch, queueId, position}`, rend directement la grille. Pour la portée « moyenne », un premier
`$group` par `(puuid, poste)` avant. Plus de `$out` sur tout l'historique : `riot_player_position`
disparaît.

## 7. Calculer à la lecture : les moyennes du joueur

**Ne pas les persister.** Un joueur a au plus quelques milliers de participations ; les lire par
l'index `{puuid, startedAt}` et les sommer prend quelques millisecondes. Persister une moyenne, c'est
une valeur fausse dès la partie suivante et un invalidateur à maintenir, pour rien.

Le bouton « Mettre à jour » garde son rôle actuel : **aller chercher les parties nouvelles**. Les
moyennes, elles, sont toujours recalculées à l'affichage, donc toujours justes.

**Les cinq fenêtres en une seule passe** : un `$group` par `(puuid, poste)` avec des sommes
conditionnelles (`$cond` sur la date ou le patch) donne les cinq fenêtres d'un coup, sans cinq
requêtes. J'ai lu « 1-2 derniers patchs » et « 3-4 derniers patchs » comme **les 2 derniers** et
**les 4 derniers** patchs : des fenêtres emboîtées, comme les autres. Fenêtres retenues :

| Fenêtre | Remplace |
|---|---|
| 2 derniers patchs | 30 jours |
| 4 derniers patchs | — |
| 90 jours | 90 jours |
| 180 jours | 180 jours |
| Tout | Tout |

365 jours disparaît, puisque l'historique Riot ne remonte guère plus loin. Une fenêtre à moins de
5 parties au poste affiche la moyenne sans note : pas d'icône sur 2 parties.

## 8. Reconstruire sans tout effacer

`ParticipationProjector.rebuildAll()` fait aujourd'hui `deleteAll()` puis reprojette tout. En dev,
13 000 parties, c'est une minute. En prod à 2 millions de parties, c'est plusieurs heures **sans
aucune statistique**. Le passage en version 3 (§3) le déclencherait.

Correction : reprojection par lots en écrasant sur place (même `_id`), sélection par
`projectionVersion < courante`, reprise possible si le service redémarre. Les lignes anciennes
restent lisibles pendant la reconstruction. À faire **avant** la version 3.

## 9. Calculer dans le front : les notes

Le front reçoit des valeurs et des seuils, et place l'une dans les autres. Aucune note n'est
stockée : changer la répartition du ladder ou la fenêtre ne réécrit rien.

- **Une partie** : ses valeurs (déjà dans le détail), plus la grille « par partie » de son patch,
  de son poste et du palier du joueur, plus les seuils B. Payload : 20 métriques × ~100 nombres,
  ~15 ko, une fois par écran.
- **Une moyenne** : les cinq fenêtres (§7), plus la grille « par moyenne ».
- Percentile = interpolation linéaire entre les deux quantiles qui encadrent la valeur ; inversé
  pour les métriques où moins vaut mieux.

## 10. Ce qui ne bouge pas dans le front

Tout ce qui est affiché aujourd'hui reste : rang courant, LP, `RankBadge`, `RankedStandings`,
tableau des KPI, colonnes alignées, début de partie, ganks, onglets d'équipe. Ce qui change :

- **Chaque KPI gagne une icône de rang** (échelle B), avec l'infobulle « meilleur que 87 % des
  joueurs au poste Support, tous rangs · 72ᵉ percentile des Or ». Les icônes de rang existent déjà
  dans `RankBadge`.
- **Le radar passe en percentiles.** Il normalise aujourd'hui entre p5 et p95, ce qui écrase tout
  ce qui dépasse. En percentile de la population choisie, l'axe se lit directement : 0 à 100.
  Le sélecteur « équipe / adversaires / palier » reste.
- **Les fenêtres** passent à celles du §7.
- **Nouvelles familles** : les métriques ajoutées au §3 rejoignent le catalogue de `metrics.ts`,
  qui reste la seule source des libellés et des sens.

## 11. Les champions

Le même calcul, un axe de plus. Les participations portent déjà `championId`.

- Référentiel `(champion, poste, groupe de paliers)` : 8 paliers × 170 champions × 5 postes, c'est
  trop fin pour avoir des effectifs. On regroupe en **cinq groupes** : Fer–Bronze, Argent–Or,
  Platine–Émeraude, Diamant, Maître+.
- En dessous de 200 parties dans la case, on retombe sur le référentiel du poste, et le front le
  dit (« comparé à tous les supports, pas assez de Nautilus Or »).
- Pour ce joueur sur ce champion : les cinq fenêtres, comme au §7, groupées par `championId`.
  `ParticipationStatsService` le fait déjà pour les sommes.

## 12. L'équipe

Les parties d'équipe ont déjà leur timeline et leur début de partie. Le même principe s'applique
au niveau de l'équipe : métriques d'équipe par partie (écart d'or à 15 min du camp, dragons et
larves à 15 min, premières tours), comparées à la distribution des mêmes métriques dans les
parties classées de l'échantillon, au palier moyen de la partie. La matière existe, c'est un lot
d'agrégation et d'écran, sans nouvelle collecte.

## 13. Lots, dans l'ordre

| Lot | Contenu | Dépôts | Réversible ? |
|---|---|---|---|
| **R.1** | Historique des rangs, relevé en masse par `league-v4` | riot | **non**, rang perdu si non relevé |
| **R.2** | Graines par palier, rang de la partie « estimé », mesure de l'accord | riot | **non**, biais de la collecte |
| **R.3** | Condensé de timeline pour les parties classées de l'échantillon | riot | **non**, timeline Riot limitée dans le temps |
| **R.4** | Reconstruction sur place, par lots | riot | oui |
| — | **Release, lancement de l'ingest de prod** | | |
| R.5 | Projection v3 : métriques du §3, écarts de laning | riot | oui, depuis le brut |
| R.6 | `riot_ladder_distribution`, `riot_reference` quotidien, deux portées, seuils B | riot | oui |
| R.7 | Cinq fenêtres en une passe, grilles servies au cœur | riot, core | oui |
| R.8 | Front : icônes par KPI, infobulles, radar en percentiles, fenêtres | front | oui |
| R.9 | Champions | riot, core, front | oui |
| R.10 | Équipe | core, front | oui |

R.1 à R.4 conditionnent la release : ils touchent à ce qu'on collecte, et une collecte ratée ne
se rejoue pas. R.5 et la suite peuvent arriver pendant que l'ingest tourne : ils se recalculent
depuis le brut.

## 14. À surveiller

- **La répartition du ladder change à chaque saison.** À remettre à jour à la main dans
  `riot_ladder_distribution` au reset ; le référentiel note la version qu'il utilise.
- **Le poids de la base** : l'alerte de volume existe (`storage-alert-bytes`, 2 To). À ajouter :
  un relevé par collection dans l'écran de configuration, pour voir *ce qui* grossit.
- **Riot peut renommer un champ.** La projection lit des champs de base, pas `challenges`, sauf
  pour les plaques. Un test sur une partie brute figée par patch détecte un champ disparu.
- **Les index de `riot_participation`** : six aujourd'hui, un de plus avec R.6. Sur la plus grosse
  collection, chaque index coûte à l'écriture. `searchName` y fait doublon avec
  `riot_known_account`, à vérifier avant de le retirer.

## 15. Avancement et écarts au plan — 23 septembre, fin de journée

Tous les lots sont codés. Aucun n'a encore tourné sur le dev.

| Lots | Dépôts | PR |
|---|---|---|
| R.1 à R.4, avec le début de partie | riot, core, front | riot #20, core #28, front #29 → `develop` |
| R.5 à R.8 | riot, core, bff, front | riot #21, core #29, bff #26, front #30, empilées |
| R.9, R.10, retrait de l'ancien radar | riot, core, bff, front | branches `feat/champions-et-equipe`, empilées |

Ce qui a changé en route, et pourquoi :

- **La répartition du ladder vit dans la configuration** (`riot.ladder.shares`), pas dans une
  collection : elle change une fois par saison, un redéploiement suffit, et elle est versionnée avec
  le code.
- **Le rang de chaque partie est figé à la projection** (`rank` sur la participation), depuis
  l'historique des rangs, sinon depuis le rang estimé de la graine. La passe quotidienne reprojette
  les parties de la fenêtre restées sans rang.
- **`patches=N` est traduit en jours** par le cœur (jours depuis la première partie collectée du plus
  ancien des N patchs) : les services ne connaissent que des jours, l'imprécision est d'un jour.
- **Le KDA moyen du référentiel est (ΣK + ΣA) / ΣD**, comme celui du cœur ; par partie, une partie
  sans mort compte pour une. Sinon la note serait légèrement faussée.
- **La timeline résumée garde la forme de la brute** : 41 ko sur disque contre 169, et l'analyse du
  début de partie tourne dessus sans changement (parité vérifiée sur 40 parties réelles).
- **Champions** : comparés tous postes confondus, en cinq groupes de paliers, sur les moyennes des
  joueurs à 5 parties ou plus ; sous 30 joueurs, repli sur le poste, dit au survol.
- **Équipe** : chaque partie d'équipe se situe parmi les camps de même palier (`riot_team_side`) ; la
  note est la moyenne des percentiles, pas le percentile de la moyenne.
- **`riot_player_position` et `riot_metric_scale` sont supprimées** au démarrage. Le radar « palier »
  lit les grilles ; les adversaires rencontrés se calculent à la demande sur la période.

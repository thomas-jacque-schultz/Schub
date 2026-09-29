# R&D — détecteurs, combats, itemisation (27/09/2026)

Scripts exécutés dans un conteneur Python jetable sur le réseau du dev, avec l'utilisateur Mongo `rd` en lecture
seule sur la base `riot` (voir `commun.py`). Données du dev ce jour-là : 71 187 parties (détail complet),
42 805 digests de timeline (échantillon par palier : positions à la minute et éliminations, sans assistances ni
dégâts reçus), 275 timelines complètes (parties d'équipe).

Les taux de victoire comparent des joueurs ou des équipes dans des situations semblables ; ils disent un lien,
pas une cause. Chaque verdict dit ce qu'on en fait dans le moteur (Schub#37).

## Schub#14 — Détecteurs de comportement (`14_detecteurs.py`, 4 000 digests)

| Détecteur | Mesure | Lien avec la victoire | Verdict |
|---|---|---|---|
| Mort isolée (plus proche allié à plus de 2 000 unités) | La position à la minute ne permet de conclure que pour **12 % des morts** (l'incertitude d'interpolation dépasse souvent la distance). Isolées sûres : 6 % des morts. | 0 → 52,1 % ; 1 → 44,7 % ; 2 → 40,8 % ; 3+ → 39,6 % (joueur) | **Industrialiser**, avec le critère « sûr » (borne basse de la distance), sur les digests et les timelines. Fréquence presque plate d'un palier à l'autre (0,31 à 0,39 par partie). |
| Absence à l'objectif (à plus de 5 000 unités 15 s avant, vivant, sans téléportation) | Contre-intuitif seul : plus d'absents, plus de victoires. | Ce qui pèse, c'est l'objectif **cédé sans échange** : 18 à 22 % de victoires quel que soit le nombre d'absents, contre 32 à 45 % quand l'équipe prend une tour, une plaque ou un monstre dans la minute. | **Approcher autrement** : la règle devient « objectif cédé sans contrepartie », à l'échelle de l'équipe. L'absence seule n'est pas un comportement perdant. |
| Jeu à 4 contre 5 (morts en chaîne dans les 30 s) | Part des morts de l'équipe suivies d'une autre (un compte brut mesurerait la défaite elle-même). | 0–25 % → 98 % ; 25–50 % → 69 % ; 50–75 % → 17 % | **Industrialiser comme conséquence** (catégorie CONSEQUENCE), pas comme action : c'est la trace d'un combat perdu plus qu'une décision. |
| Cause de chaque mort (timelines complètes, `victimDamageReceived`) | **100 % des morts classables** : combat à 3+ ennemis 41 %, 2 contre 1 30 %, échange perdu face à l'adversaire direct 11 %, pris seul par un autre ennemi 11 %, gank avant 15 min 6 %. | — | **Industrialiser** pour les parties d'équipe. Le trou de vision n'est pas observable (les balises posées n'ont pas de position). |

Règles à écrire (portée GAME, parties d'équipe) : `mort-isolee` (compte de morts isolées sûres, rampe 1 → 3),
`objectif-cede-sans-echange` (portée TEAM), `morts-en-chaine` (part 0,4 → 0,7, CONSEQUENCE), une règle par cause de
mort dominante (`meurt-en-gank`, `echanges-perdus`).

## Schub#26 — Combats d'équipe (`26_combats.py`, 4 000 digests + timelines complètes)

27 207 combats détectés (au moins 3 éliminations espacées de 20 s au plus, à moins de 3 000 unités).

| Mesure | Résultat | Verdict |
|---|---|---|
| Qui meurt en premier | Le camp qui perd le premier joueur ne gagne le combat que **27,3 %** du temps. | **Industrialiser** : « perd souvent le premier joueur » (TEAM et joueur : qui est ce premier mort). |
| Engagement en infériorité (timelines complètes : tueurs, victimes, assistances des deux premières éliminations) | À moins nombreux : **27 %** de combats gagnés ; à égalité : 50 %. | **Industrialiser** sur les parties d'équipe (assistances nécessaires). |
| Part des combats gagnés après 15 min | Moins d'un tiers → 3,6 % de victoires ; plus des deux tiers → 96,4 %. | **Industrialiser comme conséquence** : il dit l'issue, pas la cause. |
| Présence groupée à un dragon ou un baron (dernière image, 3 000 unités) | 0 membre → objectif pris 32 % ; 1 → 49 % ; 2 → 59 % ; 3 → 66 % ; 4 → 71 % ; 5 → 70 %. | **Industrialiser** : « arrive dispersé aux objectifs » (moins de trois à portée). La position à la minute suffit ici. |

## Schub#19 — Itemisation (`19_itemisation.py`)

**Couverture.** Le « quoi » (build final face aux dégâts subis par type) est jugeable sur les 71 187 parties. Le
« quand » (achat trop tardif) seulement sur les 42 805 digests et les 275 timelines. 40 % des participations n'ont
pas de palier connu : les comparaisons par palier se font sur les autres.

**Source des items : Data Dragon**, `item.json` par version (16.19.1 : 870 items). Les blessures graves ne sont que
dans le texte des descriptions ; les y chercher trouve 12 items, qu'une petite table maintenue à la main doit
confirmer à chaque patch. Catalogue à mettre en cache par patch dans le connecteur, comme les champions.

| Règle | Déclenchement | Lien avec la victoire | Verdict |
|---|---|---|---|
| Anti-heal (soins adverses dans le quart supérieur, aucun item à blessures graves dans l'équipe) | 12,9 % des équipes | 33,9 % contre 36,2 % avec blessures graves (+2,3 points) | **Ajuster** : le moment compte plus que la présence ; refaire avec « pas d'anti-heal avant 20 min » sur les digests. |
| Armure contre critique (deux porteurs de critique en face ; combattant du haut ou de la jungle à 60+ d'armure sans Randuin ni Tabi) | 20 % des cas éligibles | 45,9 % contre 48,4 % (+2,5 points) | **Industrialiser.** |
| Résistance adaptée — côté magique (plus de 70 % des dégâts subis magiques, plus d'armure que de résistance magique) | 1 082 joueurs | 43,4 % contre 45,5 % (+2,1 points ; +1,5 au seuil de 60 %) | **Industrialiser au seuil de 70 %.** |
| Résistance adaptée — côté physique | 4 897 joueurs | Aucun écart (58,5 % contre 57,8 %) | **Abandonner.** |
| Effet corrigé d'un item (synergie normalisée) | — | Volumes insuffisants par champion (ci-dessous) | **Reporter.** |

**Référentiel par champion.** Sur les deux derniers patchs, 227 couples champion × poste sur 951 (24 %) ont
200 parties ou plus. Au-delà, regrouper paliers et patchs, ou raisonner par profils de build (tags dominants :
critique, létalité, puissance, tank).

**« Les joueurs qui te ressemblent » (usage 2 de #18).** Un joueur relevé a une médiane de 28 parties sur son
champion le plus joué (premier quartile 13, dernier 63) : trop peu pour mesurer l'effet d'un item sur lui seul.
L'élargissement suppose des constats de style sur beaucoup de joueurs ; ils ne sont aujourd'hui calculés que pour
les joueurs relevés. À reprendre quand le moteur tournera sur l'échantillon par palier.

**Sous-tickets de code pour #18** : catalogue des items par patch dans le connecteur ; capteurs de build et
règles « armure contre critique » et « résistance magique » dans le moteur (catégorie BUILD, affichées dans le
détail d'une partie) ; anti-heal réécrit avec le moment d'achat ; usage 2 plus tard.

## Schub#39 — Anti-heal : le moment de l'achat (`39_antiheal_moment.py`, 28/09/2026)

Sur les 42 805 digests : 31 507 parties de la Faille de 25 min et plus (une partie plus courte n'a pas eu besoin
d'anti-heal). Équipes exposées : soins adverses dans le quart supérieur (57 809 et plus), soit 15 755 équipes.
Premier achat par un membre d'un des 12 items à blessures graves de Data Dragon 16.19.1, composants compris.
Comparaison à écart d'or égal à 15 min, pour ne pas mesurer l'avance de l'équipe qui achète plus tôt.

| Écart d'or à 15 min | Avant 15 min | 15 à 20 min | Après 20 min | Jamais |
|---|---|---|---|---|
| En retard (< −1 500) | 19,3 % (507) | 25,3 % (570) | 28,4 % (1 847) | 23,4 % (2 586) |
| À égalité (± 1 500) | 36,6 % (593) | 37,3 % (638) | 37,6 % (2 348) | 34,8 % (2 862) |
| En avance (> +1 500) | 50,4 % (369) | 45,4 % (390) | 46,1 % (1 367) | 47,0 % (1 678) |

Règle candidate « pas d'anti-heal avant 20 min », à écart d'or égal : −3,0 points en retard, +0,9 à égalité,
+1,2 en avance. Ni régulier, ni significatif.

**Verdict : abandonner**, le moment comme la présence.
- Le moment de l'achat ne sépare pas les équipes qui gagnent de celles qui perdent. En retard, l'achat précoce fait même
  moins bien, parce qu'il coûte l'or d'un objet de dégâts.
- La présence seule, peu importe quand, vaut au mieux 2 à 3 points, et rien en avance. C'est l'écart déjà vu en #19.
- La mesure de l'exposition est biaisée : les soins adverses sont comptés sur toute la partie, et une équipe qui gagne
  soigne plus (les équipes exposées ne gagnent que 35 % de leurs parties).

Reprise possible, mais pas prioritaire vu la taille de l'effet : mesurer l'exposition avant la partie, par les
champions à soins de la composition adverse, plutôt que par les soins réalisés.

## Schub#41 — Seuils des habitudes de timeline (28/09/2026)

Moyennes par partie des signaux de timeline (`GET /stats/players/{puuid}/timeline-habits` du connecteur, même code
que le moteur), pour 320 joueurs tirés de l'échantillon par palier (40 par groupe). 106 ont des parties avec
timeline, 76 en ont au moins 5 (médiane 8).

| Moyenne par partie | 10e | 25e | 50e | 75e | 90e centile |
|---|---|---|---|---|---|
| Morts isolées | 0,08 | 0,17 | 0,36 | 0,60 | 0,90 |
| Premier mort d'un combat | 0,27 | 0,43 | 0,62 | 0,73 | 1,10 |
| Part des morts en chaîne (équipe) | 0,39 | 0,42 | 0,45 | 0,47 | 0,50 |
| Présence groupée aux dragons et barons | 0,15 | 0,20 | 0,24 | 0,29 | 0,34 |
| Objectifs cédés sans contrepartie (équipe) | 0,63 | 0,79 | 1,07 | 1,50 | 1,65 |

**Règles retenues (V020, portée HABIT, au moins 5 parties analysées)** : morts isolées (0,6 → 0,9), premier mort
des combats (0,75 → 1,1), dispersé aux objectifs (0,2 → 0,15). Rampes du 75e au 90e centile, ou du 25e au 10e.

**Écartées** : les morts en chaîne (80 % des joueurs entre 0,39 et 0,50, et c'est un signal d'équipe) et les objectifs
cédés (équipe). Les morts en gank, les duels perdus et les combats en infériorité exigent une timeline complète
(parties d'équipe) : aucun joueur de l'échantillon n'en a, donc pas de base pour un seuil.

Les morts isolées montent avec le palier (médiane 0,17 de Fer à Argent, 0,37 de Diamant au sommet) : les
joueurs forts jouent plus seuls, notamment en poussant une voie. Les seuils sont communs à tous les paliers faute
de volume par palier (17 joueurs de Fer à Argent). Une grille par palier viendra avec plus de digests.

## Schub#64 — Pousser une voie déjà ouverte (30/09/2026)

Capteur `pushVoieOuverte` (`64_push_voie_ouverte.js`, mongosh sur les digests du dev) : après la chute du premier
inhibiteur adverse, part des minutes où le joueur est dans la moitié adverse d'un couloir **ouvert** (ses trois tours
et son inhibiteur tombés, inhibiteur pas encore réapparu), sans allié à moins de 2 000 unités, alors qu'un autre
couloir garde au moins une tour. Les minutes à moins de 90 s d'un dragon, d'un Héraut ou d'un Nashor sont exclues.
300 parties classées solo par palier (lobby), 8 400 joueurs dont l'équipe a pris un inhibiteur.

| Palier | Capteur non nul | Moyenne | Moyenne en victoire | Moyenne en défaite |
|---|---|---|---|---|
| Fer | 6,6 % | 1,0 % | 1,1 % | 0,8 % |
| Argent | 5,6 % | 1,1 % | 1,2 % | 0,5 % |
| Or | 5,8 % | 1,1 % | 1,2 % | 0,5 % |
| Émeraude | 4,6 % | 0,9 % | 1,0 % | 0,4 % |
| Diamant | 6,8 % | 1,4 % | 1,5 % | 1,0 % |
| Maître | 6,6 % | 1,6 % | 1,7 % | 0,6 % |
| Challenger | 5,3 % | 1,1 % | 1,1 % | 1,3 % |

Variante plus large (couloir ouvert dès ses trois tours tombées) : même allure, 6 à 10 % de capteurs non nuls,
moyenne de 1,1 à 1,8 % sans pente, plus haute en victoire partout sauf en Challenger.

**Verdict : abandonner.** Le capteur ne baisse pas quand le palier monte, et il est plus fort dans les parties
gagnées (sauf en Challenger) : il mesure une équipe qui finit la partie, pas un défaut de macro. Son 70e centile vaut zéro dans chaque
palier, donc aucun seuil de faiblesse n'est possible. Une position par minute ne distingue pas un split-push voulu
d'une errance ; il faudrait l'intention (appel, ping), que la timeline ne donne pas.

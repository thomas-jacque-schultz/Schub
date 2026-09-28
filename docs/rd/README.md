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

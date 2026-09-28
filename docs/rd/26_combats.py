"""Schub#26 — Combats d'équipe et coordination après 15 minutes.

Un combat : au moins trois éliminations espacées de 20 s au plus, à moins de 3 000 unités de leur centre.
Sur les digests : issue, premier mort, lien avec la victoire. Sur les timelines complètes (assistances connues) :
combats engagés en infériorité numérique. Présence groupée aux objectifs : sur les deux.
"""
import sys
from collections import Counter

from commun import FILES_FAILLE, base, compteur, distance, evenements, resume

ECART_MS = 20000
RAYON = 3000
MINIMUM = 3
GROUPE = 3000
APRES_MS = 15 * 60000
ECHANTILLON = int(sys.argv[1]) if len(sys.argv) > 1 else 4000

db = base()


def combats(kills):
    groupes, courant = [], []
    for k in kills:
        if courant:
            cx = sum(x["position"]["x"] for x in courant) / len(courant)
            cy = sum(x["position"]["y"] for x in courant) / len(courant)
            proche = distance(k["position"], {"x": cx, "y": cy}) <= RAYON
            if k["timestamp"] - courant[-1]["timestamp"] <= ECART_MS and proche:
                courant.append(k)
                continue
            if len(courant) >= MINIMUM:
                groupes.append(courant)
        courant = [k]
    if len(courant) >= MINIMUM:
        groupes.append(courant)
    return groupes


def camps(info_match, participants_timeline):
    par_puuid = {p["puuid"]: p for p in info_match["participants"]}
    camp = {p["participantId"]: par_puuid[p["puuid"]]["teamId"] for p in participants_timeline if p["puuid"] in par_puuid}
    victoire = {c: next(par_puuid[p["puuid"]]["win"] for p in participants_timeline
                        if p["puuid"] in par_puuid and par_puuid[p["puuid"]]["teamId"] == c) for c in (100, 200)}
    return camp, victoire


issue_premier_mort = compteur()     # le camp qui perd le premier joueur gagne-t-il le combat ?
partie_par_part = compteur()        # part des combats gagnés après 15 min → victoire de la partie
inferiorite = compteur()            # timelines complètes : combat engagé à moins nombreux → combat gagné ?
groupes_objectifs = compteur()      # membres à moins de 3 000 unités de l'objectif → objectif pris ?
parties = n_combats = 0


def analyse(frames, camp, victoire, complet):
    global n_combats
    kills = [k for k in evenements(frames, "CHAMPION_KILL") if k.get("victimId") in camp and k.get("killerId") in camp]
    gagnes = Counter()
    total = 0
    for c in combats(kills):
        n_combats += 1
        pertes = Counter(camp[k["victimId"]] for k in c)
        vainqueur = min((100, 200), key=lambda s: pertes[s]) if pertes[100] != pertes[200] else None
        premier = camp[c[0]["victimId"]]
        if vainqueur is not None:
            issue_premier_mort["le camp du premier mort gagne le combat"][0] += vainqueur == premier
            issue_premier_mort["le camp du premier mort gagne le combat"][1] += 1
            if c[0]["timestamp"] >= APRES_MS:
                gagnes[vainqueur] += 1
                total += 1
        if complet and vainqueur is not None:
            impliques = {100: set(), 200: set()}
            for k in c[:2]:
                impliques[camp[k["killerId"]]].add(k["killerId"])
                impliques[camp[k["victimId"]]].add(k["victimId"])
                for a in k.get("assistingParticipantIds", []) or []:
                    if a in camp:
                        impliques[camp[a]].add(a)
            for s in (100, 200):
                autre = 300 - s
                if len(impliques[s]) < len(impliques[autre]):
                    inferiorite["engagé à moins nombreux"][0] += vainqueur == s
                    inferiorite["engagé à moins nombreux"][1] += 1
                elif len(impliques[s]) == len(impliques[autre]):
                    inferiorite["à égalité"][0] += vainqueur == s
                    inferiorite["à égalité"][1] += 1
    if total:
        for s in (100, 200):
            part = gagnes[s] / total
            tranche = "combats gagnés : " + ("moins d'un tiers" if part < 1 / 3 else "entre un et deux tiers" if part <= 2 / 3 else "plus des deux tiers")
            partie_par_part[tranche][0] += victoire[s]
            partie_par_part[tranche][1] += 1
    for e in evenements(frames, "ELITE_MONSTER_KILL"):
        if e.get("monsterType") not in ("DRAGON", "BARON_NASHOR"):
            continue
        image = max((f for f in frames if f["timestamp"] <= e["timestamp"]), key=lambda f: f["timestamp"], default=None)
        if image is None:
            continue
        for s in (100, 200):
            presents = sum(1 for pid, c in camp.items() if c == s
                           and (pos := image["participantFrames"].get(str(pid), {}).get("position"))
                           and distance(pos, e["position"]) <= GROUPE)
            groupes_objectifs[f"{presents} membre(s) à portée"][0] += e.get("killerTeamId") == s
            groupes_objectifs[f"{presents} membre(s) à portée"][1] += 1


for source, complet, limite in (("riot_timeline_digest", False, ECHANTILLON), ("riot_match_timeline", True, 0)):
    curseur = db[source].find({}, {"raw.info.frames": 1, "raw.info.participants": 1})
    if limite:
        curseur = curseur.limit(limite)
    lot = list(curseur)
    details = {m["_id"]: m["raw"]["info"] for m in db.riot_match.find(
        {"_id": {"$in": [d["_id"] for d in lot]}},
        {"raw.info.queueId": 1, "raw.info.participants.puuid": 1, "raw.info.participants.teamId": 1,
         "raw.info.participants.win": 1})}
    for d in lot:
        info = details.get(d["_id"])
        if not info or info.get("queueId") not in FILES_FAILLE:
            continue
        camp, victoire = camps(info, d["raw"]["info"]["participants"])
        if len(camp) != 10:
            continue
        parties += 1
        analyse(d["raw"]["info"]["frames"], camp, victoire, complet)

print(f"{parties} parties, {n_combats} combats (≥ {MINIMUM} éliminations, ≤ {ECART_MS // 1000} s, ≤ {RAYON} unités)")
print(resume("Premier mort", issue_premier_mort))
print(resume("Engagement (timelines complètes : tueurs, victimes et assistances des deux premières éliminations)", inferiorite))
print(resume("Part des combats gagnés après 15 min → victoire de la partie", partie_par_part))
print(resume("Membres à moins de 3 000 unités d'un dragon ou d'un baron à la dernière image → objectif pris", groupes_objectifs))

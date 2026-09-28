"""Schub#14 — Détecteurs de comportement sur les timelines match-v5.

Pour chaque détecteur : fréquence, lien avec la défaite, part des cas où la position à la minute permet de
conclure. Les digests (échantillon par palier) portent positions et éliminations ; les timelines complètes
(parties d'équipe) ajoutent les dégâts reçus à chaque mort, qui servent à classer la cause.
"""
import sys
from collections import Counter, defaultdict

from commun import FILES_FAILLE, TELEPORTATION, base, compteur, distance, evenements, position, resume

ISOLE = 2000          # plus proche allié au-delà : mort isolée
OBJECTIF_LOIN = 5000  # distance à l'objectif au-delà de laquelle on n'y est pas
CHAINE_MS = 30000     # une seconde mort alliée dans les 30 s : la première n'a pas ralenti l'équipe
ECHANTILLON = int(sys.argv[1]) if len(sys.argv) > 1 else 4000

db = base()

digests = list(db.riot_timeline_digest.find({}, {"raw.info.frames": 1, "raw.info.participants": 1})
               .limit(ECHANTILLON))
ids = [d["_id"] for d in digests]
details = {m["_id"]: m["raw"]["info"] for m in db.riot_match.find(
    {"_id": {"$in": ids}},
    {"raw.info.queueId": 1, "raw.info.participants.puuid": 1, "raw.info.participants.teamId": 1,
     "raw.info.participants.win": 1, "raw.info.participants.teamPosition": 1,
     "raw.info.participants.summoner1Id": 1, "raw.info.participants.summoner2Id": 1})}
paliers = {(p["matchId"], p["puuid"]): (p.get("rank") or {}).get("tier") for p in db.riot_participation.find(
    {"matchId": {"$in": ids}}, {"matchId": 1, "puuid": 1, "rank.tier": 1})}

isolees = compteur()          # nombre de morts isolées sûres par joueur et par partie → victoires
isolees_palier = defaultdict(Counter)
chaines = compteur()
absences = compteur()          # joueurs absents de l'équipe à un objectif pris par l'adversaire
morts_total = morts_sures = morts_isolees = 0
objectifs_total = 0
parties = 0

for d in digests:
    info = details.get(d["_id"])
    if not info or info.get("queueId") not in FILES_FAILLE:
        continue
    frames = d["raw"]["info"]["frames"]
    pid_puuid = {p["participantId"]: p["puuid"] for p in d["raw"]["info"]["participants"]}
    joueurs = {p["puuid"]: p for p in info["participants"]}
    equipe = {pid: joueurs[pu]["teamId"] for pid, pu in pid_puuid.items() if pu in joueurs}
    if len(equipe) != 10:
        continue
    parties += 1
    victoire = {pid: joueurs[pid_puuid[pid]]["win"] for pid in equipe}
    tp = {pid: TELEPORTATION in (joueurs[pid_puuid[pid]]["summoner1Id"], joueurs[pid_puuid[pid]]["summoner2Id"])
          for pid in equipe}

    kills = [e for e in evenements(frames, "CHAMPION_KILL") if e.get("victimId") in equipe]
    par_joueur = Counter()
    for e in kills:
        v, t = e["victimId"], e["timestamp"]
        morts_total += 1
        allies = [a for a in equipe if equipe[a] == equipe[v] and a != v]
        bornes = []
        for a in allies:
            p, inc = position(frames, a, t)
            if p is not None and inc is not None:
                bornes.append((distance(p, e["position"]) - inc, distance(p, e["position"]) + inc))
        if not bornes:
            continue
        plus_proche_min = min(b[0] for b in bornes)
        plus_proche_max = min(b[1] for b in bornes)
        if plus_proche_min > ISOLE:
            morts_sures += 1
            morts_isolees += 1
            par_joueur[v] += 1
        elif plus_proche_max <= ISOLE:
            morts_sures += 1
    for pid in equipe:
        n = min(par_joueur[pid], 3)
        isolees[f"{n}{'+' if n == 3 else ''} mort(s) isolée(s)"][0] += victoire[pid]
        isolees[f"{n}{'+' if n == 3 else ''} mort(s) isolée(s)"][1] += 1
        tier = paliers.get((d["_id"], pid_puuid[pid]))
        if tier:
            isolees_palier[tier][par_joueur[pid]] += 1

    # Morts en chaîne : la part des morts de l'équipe suivies d'une autre mort alliée dans les 30 s. Une part
    # plutôt qu'un nombre : l'équipe qui perd meurt davantage, un compte brut mesurerait la défaite elle-même.
    morts_equipe = Counter(equipe[e["victimId"]] for e in kills)
    enchainees = Counter()
    for i, e in enumerate(kills):
        if any(x["timestamp"] - e["timestamp"] <= CHAINE_MS and equipe[x["victimId"]] == equipe[e["victimId"]]
               for x in kills[i + 1:]):
            enchainees[equipe[e["victimId"]]] += 1
    for camp in (100, 200):
        if morts_equipe[camp] < 5:
            continue
        gagne = next(victoire[p] for p in equipe if equipe[p] == camp)
        part = enchainees[camp] / morts_equipe[camp]
        tranche = f"{int(part * 4) * 25}–{int(part * 4) * 25 + 25} % enchaînées" if part < 1 else "100 % enchaînées"
        chaines[tranche][0] += gagne
        chaines[tranche][1] += 1

    # Absence à l'objectif : loin à la dernière image au moins 15 s avant sa prise, vivant, sans téléportation.
    for e in evenements(frames, "ELITE_MONSTER_KILL"):
        if e.get("monsterType") not in ("DRAGON", "BARON_NASHOR", "RIFTHERALD", "HORDE"):
            continue
        objectifs_total += 1
        t = e["timestamp"]
        image = max((f for f in frames if f["timestamp"] <= t - 15000), key=lambda f: f["timestamp"], default=None)
        if image is None:
            continue
        morts_recentes = {k["victimId"] for k in kills if t - 30000 <= k["timestamp"] <= t}
        for camp in (100, 200):
            if camp == e.get("killerTeamId"):
                continue
            absents = 0
            for pid in (p for p in equipe if equipe[p] == camp):
                pos = image["participantFrames"].get(str(pid), {}).get("position")
                if pos and distance(pos, e["position"]) > OBJECTIF_LOIN and pid not in morts_recentes and not tp[pid]:
                    absents += 1
            gagne = next(victoire[p] for p in equipe if equipe[p] == camp)
            # BUILDING_KILL et plaques portent l'équipe DU BÂTIMENT : l'autre camp l'a pris.
            echange = any(((x.get("killerTeamId") == camp) if x["type"] == "ELITE_MONSTER_KILL" else (x.get("teamId") not in (None, camp)))
                          for x in evenements(frames, "BUILDING_KILL", "TURRET_PLATE_DESTROYED", "ELITE_MONSTER_KILL")
                          if abs(x["timestamp"] - t) <= 60000 and x is not e)
            cle = f"{min(absents, 3)}{'+' if absents >= 3 else ''} absent(s), {'échange' if echange else 'sans échange'}"
            absences[cle][0] += gagne
            absences[cle][1] += 1

# Cause des morts, sur les timelines complètes : qui a infligé les dégâts reçus.
causes = Counter()
classables = 0
for t in db.riot_match_timeline.find({}, {"raw.info.frames": 1, "raw.info.participants": 1}):
    info_t = t["raw"]["info"]
    detail = db.riot_match.find_one({"_id": t["_id"]}, {"raw.info.participants.puuid": 1,
                                                         "raw.info.participants.teamPosition": 1,
                                                         "raw.info.participants.teamId": 1})
    if not detail:
        continue
    par_puuid = {p["puuid"]: p for p in detail["raw"]["info"]["participants"]}
    poste = {p["participantId"]: par_puuid.get(p["puuid"], {}).get("teamPosition") for p in info_t["participants"]}
    for e in evenements(info_t["frames"], "CHAMPION_KILL"):
        recus = e.get("victimDamageReceived") or []
        ennemis = {x["participantId"] for x in recus if x.get("type") == "OTHER" and x.get("participantId") in poste
                   and x["participantId"] != e["victimId"]}
        tours = any(x.get("type") == "TOWER" for x in recus)
        if not recus:
            continue
        classables += 1
        v = e["victimId"]
        if len(ennemis) >= 3:
            causes["combat (3 ennemis ou plus)"] += 1
        elif len(ennemis) == 2 and any(poste.get(x) == "JUNGLE" for x in ennemis) and e["timestamp"] < 15 * 60000:
            causes["gank (jungler et laner, avant 15 min)"] += 1
        elif len(ennemis) == 2:
            causes["2 contre 1"] += 1
        elif len(ennemis) == 1 and poste.get(next(iter(ennemis))) == poste.get(v):
            causes["échange perdu face à son adversaire direct"] += 1
        elif len(ennemis) == 1:
            causes["pris seul par un autre ennemi"] += 1
        elif tours:
            causes["tour"] += 1
        else:
            causes["autre"] += 1

print(f"Échantillon : {parties} parties (digests), {morts_total} morts, {objectifs_total} objectifs épiques.")
print(f"\n1. Mort isolée (plus proche allié à plus de {ISOLE} unités)")
print(f"  Morts dont la position à la minute permet de conclure : {morts_sures}/{morts_total} "
      f"({morts_sures / max(morts_total, 1):.0%}) ; isolées sûres : {morts_isolees} "
      f"({morts_isolees / max(morts_total, 1):.0%} des morts)")
print(resume("Taux de victoire du joueur selon ses morts isolées sûres", isolees))
print("  Morts isolées sûres par joueur et par partie, selon le palier :")
for tier, c in sorted(isolees_palier.items()):
    n = sum(c.values())
    moyenne = sum(k * v for k, v in c.items()) / n
    print(f"    {tier:<12} {n:>6} joueurs-parties   {moyenne:.2f} en moyenne")
print(f"\n2. Absence à l'objectif (à plus de {OBJECTIF_LOIN} unités 15 s avant, vivant, sans téléportation)")
print(resume("Taux de victoire de l'équipe qui perd l'objectif, selon ses absents", absences))
print(f"\n3. Morts en chaîne (une autre mort alliée dans les {CHAINE_MS // 1000} s)")
print(resume("Taux de victoire selon le nombre d'enchaînements de l'équipe", chaines))
print(f"\n4. Cause des morts (timelines complètes, {classables} morts avec dégâts reçus)")
for cause, n in causes.most_common():
    print(f"    {cause:<46} {n:>5}  {n / max(classables, 1):.0%}")

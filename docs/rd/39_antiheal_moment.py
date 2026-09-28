"""Schub#39 — Anti-heal : le moment du premier achat à blessures graves, pas seulement sa présence.

Sur les digests de timeline (achats horodatés, or de chaque joueur à la minute), pour chaque équipe qui affronte des
soins dans le quart supérieur : minute du premier achat d'un item à blessures graves par un membre, composants compris.

Deux biais à neutraliser :
- une partie finie avant 20 min n'a pas eu besoin d'anti-heal : on ne garde que les parties de 25 min et plus ;
- une équipe en avance achète plus tôt parce qu'elle a plus d'or : on compare à écart d'or égal à 15 min.
"""
import re

import requests

from commun import FILES_FAILLE, base, compteur, resume

db = base()

version = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=20).json()[0]
items = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json", timeout=20).json()["data"]
BLESSURES = {int(i) for i, it in items.items() if re.search(r"Grievous\s*Wounds", it.get("description", ""), re.I)}
noms = sorted(items[str(i)]["name"] for i in BLESSURES)
print(f"Data Dragon {version} : {len(BLESSURES)} items à blessures graves — {', '.join(noms)}")

DUREE_MIN_S = 25 * 60
MINUTE_ECART_OR = 15

CHAMPS = {"raw.info.queueId": 1, "raw.info.gameDuration": 1,
          **{f"raw.info.participants.{c}": 1 for c in ("participantId", "teamId", "win", "totalHeal")}}

equipes = []  # (soins adverses, minute du premier achat ou None, écart d'or à 15 min, victoire)
lus = 0
for digest in db.riot_timeline_digest.find({}, {"raw.info.frames": 1}):
    lus += 1
    partie = db.riot_match.find_one({"_id": digest["_id"]}, CHAMPS)
    if partie is None:
        continue
    info = partie["raw"]["info"]
    if info.get("queueId") not in FILES_FAILLE or info.get("gameDuration", 0) < DUREE_MIN_S:
        continue
    joueurs = info.get("participants", [])
    if len(joueurs) != 10:
        continue
    frames = digest["raw"]["info"]["frames"]
    if len(frames) <= MINUTE_ECART_OR:
        continue
    camp_de = {p["participantId"]: p["teamId"] for p in joueurs}

    premier = {}
    for frame in frames:
        for e in frame.get("events", []):
            if e.get("type") == "ITEM_PURCHASED" and e.get("itemId") in BLESSURES:
                camp = camp_de.get(e.get("participantId"))
                if camp is not None and camp not in premier:
                    premier[camp] = e["timestamp"] / 60000

    or_15 = {100: 0, 200: 0}
    for pid, pf in frames[MINUTE_ECART_OR]["participantFrames"].items():
        camp = camp_de.get(int(pid))
        if camp is not None:
            or_15[camp] += pf.get("totalGold", 0)

    for camp in (100, 200):
        adverse = 300 - camp
        soins = sum(p.get("totalHeal", 0) for p in joueurs if p["teamId"] == adverse)
        gagne = next(p["win"] for p in joueurs if p["teamId"] == camp)
        equipes.append((soins, premier.get(camp), or_15[camp] - or_15[adverse], gagne))

print(f"\n{lus} digests lus, {len(equipes) // 2} parties de la Faille de 25 min et plus avec leur détail.")

soins_tries = sorted(e[0] for e in equipes)
seuil = soins_tries[int(len(soins_tries) * 0.75)]
exposees = [e for e in equipes if e[0] >= seuil]
print(f"Soins adverses dans le quart supérieur : au moins {seuil:,} ({len(exposees)} équipes).".replace(",", " "))


def moment(minute):
    if minute is None:
        return "4. jamais"
    if minute < 15:
        return "1. avant 15 min"
    if minute < 20:
        return "2. entre 15 et 20 min"
    return "3. après 20 min"


def ecart(delta):
    if delta < -1500:
        return "en retard (< -1 500 d'or)"
    if delta > 1500:
        return "en avance (> +1 500 d'or)"
    return "à égalité (±1 500)"


global_ = compteur()
for soins, minute, delta, gagne in exposees:
    global_[moment(minute)][0] += gagne
    global_[moment(minute)][1] += 1
print("\n1. Toutes équipes exposées")
print(resume("Premier achat à blessures graves", global_))

print("\n2. À écart d'or égal à 15 min")
for tranche in ("en retard (< -1 500 d'or)", "à égalité (±1 500)", "en avance (> +1 500 d'or)"):
    c = compteur()
    for soins, minute, delta, gagne in exposees:
        if ecart(delta) == tranche:
            c[moment(minute)][0] += gagne
            c[moment(minute)][1] += 1
    print(resume(tranche, c))

print("\n3. Règle candidate « pas d'anti-heal avant 20 min », à écart d'or égal")
for tranche in ("en retard (< -1 500 d'or)", "à égalité (±1 500)", "en avance (> +1 500 d'or)"):
    c = compteur()
    for soins, minute, delta, gagne in exposees:
        if ecart(delta) == tranche:
            cle = "avant 20 min" if minute is not None and minute < 20 else "pas avant 20 min (déclenchée)"
            c[cle][0] += gagne
            c[cle][1] += 1
    print(resume(tranche, c))

temoin = compteur()
for soins, minute, delta, gagne in equipes:
    if soins < seuil:
        cle = "avant 20 min" if minute is not None and minute < 20 else "pas avant 20 min"
        temoin[cle][0] += gagne
        temoin[cle][1] += 1
print("\n4. Témoin : équipes face à peu de soins (un effet ici serait celui de l'or, pas de l'anti-heal)")
print(resume("Premier achat à blessures graves", temoin))

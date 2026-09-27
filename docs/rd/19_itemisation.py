"""Schub#19 — Itemisation : données disponibles, source des items, trois règles prototypées.

Source des items : Data Dragon (item.json de la dernière version). Les blessures graves ne sont que dans le
texte des descriptions : on les y cherche, faute de champ structuré.
"""
import re
from collections import Counter, defaultdict

import requests

from commun import FILES_FAILLE, base, compteur, resume

db = base()

# --- Catalogue Data Dragon -------------------------------------------------------------------------------
version = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=20).json()[0]
items = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json", timeout=20).json()["data"]
BLESSURES = {int(i) for i, it in items.items() if re.search(r"Grievous\s*Wounds", it.get("description", ""), re.I)}
CRITIQUE = {int(i) for i, it in items.items() if "CriticalStrike" in it.get("tags", []) and it["gold"]["total"] >= 2500}
ANTI_CRITIQUE = {3143, 3047}  # Présage de Randuin (réduit les critiques), Tabi ninja (réduit les attaques de base)
ARMURE = {int(i): it.get("stats", {}).get("FlatArmorMod", 0) for i, it in items.items()}
RESISTANCE = {int(i): it.get("stats", {}).get("FlatSpellBlockMod", 0) for i, it in items.items()}
print(f"Data Dragon {version} : {len(items)} items, {len(BLESSURES)} à blessures graves (repérés dans le texte), "
      f"{len(CRITIQUE)} items de critique complets.")

# --- 1. Couverture ---------------------------------------------------------------------------------------
print("\n1. Couverture des données")
print(f"  Parties (détail, build final et dégâts subis par type) : {db.riot_match.estimated_document_count()}")
print(f"  Digests de timeline (achats horodatés, sans ITEM_DESTROYED) : {db.riot_timeline_digest.estimated_document_count()}")
print(f"  Timelines complètes (parties d'équipe) : {db.riot_match_timeline.estimated_document_count()}")
par_palier = {r["_id"]: r["n"] for r in db.riot_participation.aggregate(
    [{"$group": {"_id": "$rank.tier", "n": {"$sum": 1}}}], allowDiskUse=True)}
print("  Participations par palier : " + ", ".join(f"{k or '?'} {v}" for k, v in sorted(par_palier.items(), key=lambda kv: str(kv[0]))))

# --- 2. Les trois règles ---------------------------------------------------------------------------------
CHAMPS = {f"raw.info.participants.{c}": 1 for c in (
    "teamId", "win", "teamPosition", "championId", "totalHeal", "magicDamageTaken", "physicalDamageTaken",
    "trueDamageTaken", *[f"item{i}" for i in range(7)])}
CHAMPS["raw.info.queueId"] = 1
parties = [m["raw"]["info"] for m in db.riot_match.find({}, CHAMPS)]
parties = [p for p in parties if p.get("queueId") in FILES_FAILLE and len(p.get("participants", [])) == 10]
print(f"\n2. Règles, sur {len(parties)} parties de la Faille")


def build(p):
    return {p.get(f"item{i}") for i in range(7)} - {0, None}


# Anti-heal : soins adverses dans le quart supérieur, et personne de l'équipe avec un item à blessures graves.
soins_equipe = []
for m in parties:
    for camp in (100, 200):
        soins_equipe.append(sum(p["totalHeal"] for p in m["participants"] if p["teamId"] != camp))
seuil_soins = sorted(soins_equipe)[int(len(soins_equipe) * 0.75)]
anti_heal = compteur()
declenchements = 0
for m in parties:
    for camp in (100, 200):
        soins = sum(p["totalHeal"] for p in m["participants"] if p["teamId"] != camp)
        if soins < seuil_soins:
            continue
        a_blessures = any(build(p) & BLESSURES for p in m["participants"] if p["teamId"] == camp)
        gagne = next(p["win"] for p in m["participants"] if p["teamId"] == camp)
        cle = "avec blessures graves" if a_blessures else "sans blessures graves (règle déclenchée)"
        declenchements += not a_blessures
        anti_heal[cle][0] += gagne
        anti_heal[cle][1] += 1
print(f"  a) Anti-heal — soins adverses au-delà de {seuil_soins} (quart supérieur)")
print(resume("Taux de victoire de l'équipe", anti_heal))
print(f"     déclenchée sur {declenchements / (len(parties) * 2):.1%} des équipes")

# Armure contre critique : deux porteurs de critique en face ; combattants du haut et de la jungle bien armés.
anti_crit = compteur()
for m in parties:
    for p in m["participants"]:
        if p.get("teamPosition") not in ("TOP", "JUNGLE"):
            continue
        armure = sum(ARMURE.get(i, 0) for i in build(p))
        if armure < 60:
            continue
        porteurs = sum(1 for e in m["participants"] if e["teamId"] != p["teamId"] and len(build(e) & CRITIQUE) >= 2)
        if porteurs < 2:
            continue
        cle = "avec Randuin ou Tabi" if build(p) & ANTI_CRITIQUE else "sans (règle déclenchée)"
        anti_crit[cle][0] += p["win"]
        anti_crit[cle][1] += 1
print("  b) Armure contre critique — deux porteurs de critique en face, combattant du haut ou de la jungle à 60+ d'armure")
print(resume("Taux de victoire du joueur", anti_crit))

# Résistance adaptée : une part des dégâts subis magiques au-delà du seuil, et plus d'armure que de résistance magique.
import sys
SEUIL_MAGIQUE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.6
resistance = compteur()
for m in parties:
    for p in m["participants"]:
        total = p["magicDamageTaken"] + p["physicalDamageTaken"]
        if total <= 0:
            continue
        part_magique = p["magicDamageTaken"] / total
        armure = sum(ARMURE.get(i, 0) for i in build(p))
        rm = sum(RESISTANCE.get(i, 0) for i in build(p))
        if armure + rm < 60:
            continue
        if part_magique > SEUIL_MAGIQUE:
            cle = "subit du magique, s'arme contre le physique (règle déclenchée)" if armure > rm else "subit du magique, s'arme contre le magique"
        elif part_magique < 1 - SEUIL_MAGIQUE:
            cle = "subit du physique, s'arme contre le magique (règle déclenchée)" if rm > armure else "subit du physique, s'arme contre le physique"
        else:
            continue
        resistance[cle][0] += p["win"]
        resistance[cle][1] += 1
print(f"  c) Résistance adaptée — seuil {SEUIL_MAGIQUE:.0%}, joueurs à 60+ de résistances cumulées")
print(resume("Taux de victoire du joueur", resistance))

# --- 3. Référentiel par champion -------------------------------------------------------------------------
# Tri numérique : en chaînes, « 16.9 » passerait devant « 16.19 ».
patchs = sorted((p["_id"] for p in db.riot_participation.aggregate([{"$group": {"_id": "$patch"}}]) if p["_id"]),
                key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)[:2]
volumes = Counter()
for r in db.riot_participation.aggregate([
        {"$match": {"patch": {"$in": patchs}}},
        {"$group": {"_id": {"c": "$championId", "p": "$position"}, "n": {"$sum": 1}}}], allowDiskUse=True):
    volumes[(r["_id"]["c"], r["_id"]["p"])] = r["n"]
assez = sum(1 for n in volumes.values() if n >= 200)
print(f"\n3. Référentiel de builds par champion et poste, patchs {', '.join(patchs)}")
print(f"  {len(volumes)} couples champion × poste ; {assez} ont 200 parties ou plus ({assez / max(len(volumes), 1):.0%}).")

# --- 4. Joueurs qui te ressemblent -----------------------------------------------------------------------
suivis = [c["_id"] for c in db.riot_player_cursor.find({}, {"_id": 1})]
par_champion = defaultdict(Counter)
for r in db.riot_participation.aggregate([
        {"$match": {"puuid": {"$in": suivis}}},
        {"$group": {"_id": {"u": "$puuid", "c": "$championId"}, "n": {"$sum": 1}}}], allowDiskUse=True):
    par_champion[r["_id"]["u"]][r["_id"]["c"]] = r["n"]
principal = sorted(max(c.values()) for c in par_champion.values() if c)
if principal:
    print(f"\n4. Parties sur le champion le plus joué, {len(principal)} joueurs relevés : médiane {principal[len(principal) // 2]}, "
          f"premier quartile {principal[len(principal) // 4]}, dernier quartile {principal[3 * len(principal) // 4]}")

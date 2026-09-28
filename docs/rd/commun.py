"""Accès en lecture seule à la base Riot du dev, et outils partagés par les scripts de R&D.

Lancé dans un conteneur Python jetable sur le réseau du dev :
    docker run --rm --network schub-dev_schub-dev -e RDPW=... -v <ce dossier>:/rd python:3.12-slim \
        sh -c "pip install -q pymongo && python /rd/<script>.py"
L'utilisateur Mongo `rd` n'a que le rôle `read` sur la base `riot`.
"""
import math
import os
from collections import defaultdict

import pymongo

# Faille de l'invocateur, 5 contre 5 : classées solo et flex, normales, Clash.
FILES_FAILLE = {400, 420, 430, 440, 490, 700}
TELEPORTATION = 12
UNITES_PAR_SECONDE_MAX = 450  # vitesse de déplacement élevée, pour borner l'interpolation entre deux images


def base():
    client = pymongo.MongoClient(os.environ.get("MONGO_HOST", "dev-schub-mongo"), username="rd",
                                 password=os.environ["RDPW"], authSource="riot")
    return client["riot"]


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def position(frames, pid, t_ms):
    """Position d'un joueur à l'instant t, par interpolation linéaire entre deux images d'une minute.

    Rend aussi l'incertitude : l'écart maximal possible avec la vraie position, borné par la vitesse.
    """
    i = min(int(t_ms // 60000), len(frames) - 1)
    avant = frames[i]["participantFrames"].get(str(pid), {}).get("position")
    if avant is None:
        return None, None
    if i + 1 >= len(frames):
        return avant, UNITES_PAR_SECONDE_MAX * (t_ms - frames[i]["timestamp"]) / 1000
    apres = frames[i + 1]["participantFrames"].get(str(pid), {}).get("position")
    if apres is None:
        return avant, None
    t0, t1 = frames[i]["timestamp"], frames[i + 1]["timestamp"]
    r = 0 if t1 == t0 else (t_ms - t0) / (t1 - t0)
    p = {"x": avant["x"] + r * (apres["x"] - avant["x"]), "y": avant["y"] + r * (apres["y"] - avant["y"])}
    incertitude = UNITES_PAR_SECONDE_MAX * min(t_ms - t0, t1 - t_ms) / 1000
    return p, incertitude


def evenements(frames, *types):
    for f in frames:
        for e in f.get("events", []):
            if e["type"] in types:
                yield e


def taux(v, n):
    return None if n == 0 else v / n


def resume(nom, compte):
    """compte : {cle: [victoires, parties]} → lignes lisibles."""
    lignes = [f"  {nom}"]
    for cle, (v, n) in sorted(compte.items(), key=lambda kv: str(kv[0])):
        t = taux(v, n)
        lignes.append(f"    {cle!s:<28} {n:>6} parties   {'—' if t is None else f'{t:.1%}':>7} de victoires")
    return "\n".join(lignes)


def compteur():
    return defaultdict(lambda: [0, 0])

// Schub#64 — « pousse une voie déjà ouverte alors qu'une autre tient encore ».
// mongosh, en lecture, sur la base riot du dev : mongosh <connexion> riot docs/rd/64_push_voie_ouverte.js
// Variante « trois tours tombées » : remplacer la condition d'ouverture par `tours >= 3`.
const PALIERS = ["IRON","BRONZE","SILVER","GOLD","PLATINUM","EMERALD","DIAMOND","MASTER","GRANDMASTER","CHALLENGER"];
const PAR_PALIER = 300, SEUL = 2000, AUTOUR_OBJECTIF = 90000, REPOP_INHIB = 300000, BORD = 14870;
const COULOIRS = ["TOP_LANE","MID_LANE","BOT_LANE"];
const TOURS = ["OUTER_TURRET","INNER_TURRET","BASE_TURRET"];

const couloirDe = (p) => {
  const { x, y } = p;
  if ((x < 4200 && y < 4200) || (x > 10700 && y > 10700)) return null; // bases
  if (Math.abs(x - y) < 2000) return "MID_LANE";
  if (x < 3000 || y > 11900) return "TOP_LANE";
  if (x > 11900 || y < 3000) return "BOT_LANE";
  return null;
};
const chezEux = (p, equipe) => equipe === 100 ? p.x + p.y > BORD : p.x + p.y < BORD;

const resultats = {};
for (const palier of PALIERS) {
  const ids = db.riot_match_lobby.find({ tier: palier }, { _id: 1 }).limit(4000).toArray().map(d => d._id);
  const soloIds = db.riot_match.find({ _id: { $in: ids }, "raw.info.queueId": 420 }, { _id: 1 }).limit(PAR_PALIER * 3).toArray().map(d => d._id);
  const valeurs = []; const victoires = []; let parties = 0;
  db.riot_timeline_digest.find({ _id: { $in: soloIds } }).limit(PAR_PALIER).forEach(doc => {
    const frames = doc.raw.info.frames;
    const events = frames.flatMap(f => f.events || []);
    const batiments = events.filter(e => e.type === "BUILDING_KILL");
    const objectifs = events.filter(e => e.type === "ELITE_MONSTER_KILL").map(e => e.timestamp);
    const fin = events.find(e => e.type === "GAME_END");
    const gagnant = fin ? fin.winningTeam : null;
    parties++;
    for (const equipe of [100, 200]) {
      const adverse = equipe === 100 ? 200 : 100;
      const leurs = batiments.filter(b => b.teamId === adverse);
      const premierInhib = leurs.find(b => b.buildingType === "INHIBITOR_BUILDING");
      if (!premierInhib) continue;
      const etat = (t) => {
        const ouverts = [], tiennent = [];
        for (const c of COULOIRS) {
          const tours = leurs.filter(b => b.laneType === c && b.buildingType === "TOWER_BUILDING" && TOURS.includes(b.towerType) && b.timestamp <= t).length;
          const inhib = leurs.some(b => b.laneType === c && b.buildingType === "INHIBITOR_BUILDING" && b.timestamp <= t && t - b.timestamp < REPOP_INHIB);
          if (tours >= 3 && inhib) ouverts.push(c); else if (tours < 3) tiennent.push(c);
        }
        return { ouverts, tiennent };
      };
      const ids = equipe === 100 ? [1,2,3,4,5] : [6,7,8,9,10];
      for (const pid of ids) {
        let minutes = 0, pousse = 0;
        for (const f of frames) {
          if (f.timestamp < premierInhib.timestamp) continue;
          const moi = f.participantFrames && f.participantFrames[String(pid)];
          if (!moi || !moi.position) continue;
          minutes++;
          const { ouverts, tiennent } = etat(f.timestamp);
          if (tiennent.length === 0 || ouverts.length === 0) continue;
          if (objectifs.some(t => Math.abs(t - f.timestamp) < AUTOUR_OBJECTIF)) continue;
          const c = couloirDe(moi.position);
          if (!c || !ouverts.includes(c) || !chezEux(moi.position, equipe)) continue;
          const seul = ids.filter(a => a !== pid).every(a => {
            const p = f.participantFrames[String(a)] && f.participantFrames[String(a)].position;
            return !p || Math.hypot(p.x - moi.position.x, p.y - moi.position.y) > SEUL;
          });
          if (seul) pousse++;
        }
        if (minutes >= 3) { valeurs.push(pousse / minutes); victoires.push(gagnant === equipe); }
      }
    }
  });
  const tri = [...valeurs].sort((a, b) => a - b);
  const q = (p) => tri.length ? tri[Math.min(tri.length - 1, Math.floor(p * tri.length))] : null;
  const moy = (arr) => arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : null;
  const gagnes = valeurs.filter((_, i) => victoires[i]), perdus = valeurs.filter((_, i) => !victoires[i]);
  resultats[palier] = { parties, joueurs: valeurs.length, nonNuls: valeurs.filter(v => v > 0).length,
    moyenne: moy(valeurs), mediane: q(0.5), p70: q(0.7), p90: q(0.9), moyGagnes: moy(gagnes), moyPerdus: moy(perdus) };
}
printjson(resultats);

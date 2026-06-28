"""StatsBomb Open Data — event data histórico para ENTRENAR el modelo de xG.

No cubre WC2026 (llega a 2022). Cacheamos crudo a data/raw/statsbomb/ por
competición/partido. La normalización a tablas se decide al atacar el xG (el
schema de 91 columnas es muy distinto: no se fuerza al modelo unificado aún).

Open Data User Agreement: uso no comercial + atribución a StatsBomb.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("mova.statsbomb")

# Torneos de selección relevantes para entrenar (competition_id, season_id, label).
TRAIN_COMPS = [
    (43, 106, "wc-2022"),
    (43, 3, "wc-2018"),
]


def collect(raw_dir: Path, comps=TRAIN_COMPS, max_matches: int | None = None) -> dict:
    from statsbombpy import sb  # import perezoso

    raw_dir = Path(raw_dir)
    total_matches = total_events = 0
    for cid, sid, label in comps:
        cdir = raw_dir / label
        cdir.mkdir(parents=True, exist_ok=True)
        matches = sb.matches(competition_id=cid, season_id=sid)
        matches.to_csv(cdir / "_matches.csv", index=False)
        ids = list(matches["match_id"].astype(int))
        if max_matches:
            ids = ids[:max_matches]
        logger.info("%s: %d partidos", label, len(ids))
        for mid in ids:
            out = cdir / f"{mid}.json"
            if out.exists():
                total_matches += 1
                continue
            try:
                ev = sb.events(match_id=mid)
                out.write_text(ev.to_json(orient="records"))
                total_matches += 1
                total_events += len(ev)
            except Exception as e:
                logger.warning("evento %s falló: %s", mid, e)
    logger.info("StatsBomb cache: %d partidos, %d eventos nuevos", total_matches, total_events)
    return {"matches": total_matches, "new_events": total_events}

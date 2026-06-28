"""Enlace de partidos entre fuentes por par de equipos canónicos.

Un par de selecciones juega una sola vez en el torneo → la clave
sorted(team_a, team_b) identifica el partido sin depender de la fecha
(evita desfases de zona horaria) ni de la orientación local/visitante.
"""
from __future__ import annotations

import logging

from .teams import resolve

logger = logging.getLogger("mova.match_map")


def _key(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


def build_match_map(conn) -> dict:
    rows: dict[str, dict] = {}

    def upsert(home, away, date, **ids):
        ch, ca = resolve(conn, home), resolve(conn, away)
        if not ch or not ca:          # placeholder / no-clasificado → no mapear
            return False
        k = _key(ch, ca)
        a, b = sorted([ch, ca])
        r = rows.setdefault(k, {"team_a": a, "team_b": b, "match_date": (date or "")[:10]})
        if not r.get("match_date") and date:
            r["match_date"] = date[:10]
        r.update({kk: vv for kk, vv in ids.items() if vv is not None})
        return True

    for mid, h, a, dt in conn.execute(
            "SELECT match_id, home_team, away_team, start_utc FROM matches"):
        upsert(h, a, dt, whoscored_id=mid)
    for eid, h, a, dt in conn.execute(
            "SELECT espn_id, home_team, away_team, date_utc FROM espn_fixtures"):
        upsert(h, a, dt, espn_id=eid)
    for eid, h, a, dt in conn.execute(
            "SELECT DISTINCT event_id, home_team, away_team, commence_time "
            "FROM odds_quotes WHERE scope='match'"):
        upsert(h, a, dt, oddsapi_event_id=eid)

    conn.execute("DELETE FROM match_map")
    conn.executemany(
        """INSERT INTO match_map
           (match_key, team_a, team_b, match_date, whoscored_id, espn_id, oddsapi_event_id)
           VALUES (?,?,?,?,?,?,?)""",
        [(k, r["team_a"], r["team_b"], r.get("match_date"), r.get("whoscored_id"),
          r.get("espn_id"), r.get("oddsapi_event_id")) for k, r in rows.items()],
    )
    conn.commit()

    n = len(rows)
    triple = sum(1 for r in rows.values()
                 if r.get("whoscored_id") and r.get("espn_id") and r.get("oddsapi_event_id"))
    ws_espn = sum(1 for r in rows.values() if r.get("whoscored_id") and r.get("espn_id"))
    logger.info("match_map: %d partidos | WS+ESPN: %d | con las 3 fuentes: %d",
                n, ws_espn, triple)
    return {"matches": n, "ws_espn": ws_espn, "all_three": triple}

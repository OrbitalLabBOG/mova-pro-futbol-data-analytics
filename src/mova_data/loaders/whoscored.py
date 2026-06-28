"""Carga el cache JSON de WhoScored a SQLite. Idempotente (UNIQUE evita duplicados)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..db import get_db, init_db

logger = logging.getLogger("mova.loader.whoscored")
SOURCE = "whoscored"


def _round_from_stage(stage_name: str) -> str:
    return "group" if (stage_name or "").startswith("Group") else "knockout"


def upsert_fixtures(fixtures: list[dict], conn) -> None:
    """Inserta/actualiza filas de `matches` desde el discovery."""
    for f in fixtures:
        conn.execute(
            """INSERT INTO matches
               (match_id, source, competition, stage_id, stage_name, round,
                status, is_finished, start_utc, home_team_id, home_team,
                away_team_id, away_team, home_score, away_score, match_is_opta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(match_id) DO UPDATE SET
                 status=excluded.status, is_finished=excluded.is_finished,
                 home_score=excluded.home_score, away_score=excluded.away_score,
                 stage_name=excluded.stage_name, round=excluded.round""",
            (f["match_id"], SOURCE, "FIFA World Cup 2026", f["stage_id"],
             f["stage_name"], _round_from_stage(f["stage_name"]), f["status"],
             f["is_finished"], f["start_utc"], f["home_team_id"], f["home_team"],
             f["away_team_id"], f["away_team"], f["home_score"], f["away_score"],
             f["match_is_opta"]),
        )
    conn.commit()


def load_match(json_path: Path, conn) -> dict:
    data = json.loads(Path(json_path).read_text())
    mcd = data.get("matchCentreData")
    if not mcd:
        return {"status": "skipped", "reason": "no_mcd"}
    match_id = data.get("matchId") or int(Path(json_path).stem)

    home, away = mcd["home"], mcd["away"]
    team_names = {home["teamId"]: home["name"], away["teamId"]: away["name"]}

    # teams
    for t in (home, away):
        conn.execute(
            "INSERT OR IGNORE INTO teams (team_id, source, name) VALUES (?,?,?)",
            (t["teamId"], SOURCE, t["name"]),
        )

    # player name dictionary
    pdict = {}
    for k, v in (mcd.get("playerIdNameDictionary") or {}).items():
        try:
            pdict[int(k)] = v
        except (ValueError, TypeError):
            pass
    for pid, name in pdict.items():
        conn.execute(
            "INSERT OR IGNORE INTO players (player_id, source, name) VALUES (?,?,?)",
            (pid, SOURCE, name),
        )

    # lineups
    for side in (home, away):
        for p in side.get("players", []):
            conn.execute(
                """INSERT OR REPLACE INTO lineups
                   (match_id, team_id, player_id, source, name, shirt_no,
                    position, is_starter, is_motm, age, height)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, side["teamId"], p.get("playerId"), SOURCE, p.get("name"),
                 p.get("shirtNo"), p.get("position"), int(p.get("isFirstEleven", False)),
                 int(p.get("isManOfTheMatch", False)), p.get("age"), p.get("height")),
            )

    # events
    events = mcd.get("events", [])
    inserted = 0
    for e in events:
        card = e.get("cardType")
        card = card.get("displayName") if isinstance(card, dict) else None
        try:
            conn.execute(
                """INSERT OR IGNORE INTO events
                   (source, match_id, ws_event_id, event_id, minute, second,
                    expanded_minute, period, event_type, outcome, team_id, team_name,
                    player_id, player_name, x, y, end_x, end_y, goal_mouth_y,
                    goal_mouth_z, blocked_x, blocked_y, is_touch, is_shot, is_goal,
                    card_type, related_event_id, related_player_id, qualifiers)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (SOURCE, match_id, e.get("id"), e.get("eventId"), e.get("minute"),
                 e.get("second"), e.get("expandedMinute"),
                 (e.get("period") or {}).get("displayName") if isinstance(e.get("period"), dict) else None,
                 (e.get("type") or {}).get("displayName") if isinstance(e.get("type"), dict) else None,
                 (e.get("outcomeType") or {}).get("displayName") if isinstance(e.get("outcomeType"), dict) else None,
                 e.get("teamId"), team_names.get(e.get("teamId")),
                 e.get("playerId"), pdict.get(e.get("playerId")),
                 e.get("x"), e.get("y"), e.get("endX"), e.get("endY"),
                 e.get("goalMouthY"), e.get("goalMouthZ"), e.get("blockedX"), e.get("blockedY"),
                 int(e.get("isTouch", False)), int(e.get("isShot", False)), int(e.get("isGoal", False)),
                 card, e.get("relatedEventId"), e.get("relatedPlayerId"),
                 json.dumps(e.get("qualifiers", []))),
            )
            inserted += 1
        except Exception as ex:
            logger.warning("evento %s match %s: %s", e.get("id"), match_id, ex)

    # enrich match row con datos del match centre.
    # n_events = filas realmente cargadas (deduplicadas), no el conteo crudo:
    # WhoScored a veces trae ids de evento duplicados que UNIQUE descarta.
    ref = mcd.get("referee") or {}
    loaded = conn.execute(
        "SELECT count(*) FROM events WHERE source=? AND match_id=?", (SOURCE, match_id)
    ).fetchone()[0]
    conn.execute(
        """UPDATE matches SET venue=?, attendance=?, referee=?, ht_score=?,
           et_score=?, pk_score=?, n_events=?, scraped_at=? WHERE match_id=?""",
        (mcd.get("venueName"), mcd.get("attendance"), ref.get("name"),
         mcd.get("htScore"), mcd.get("etScore"), mcd.get("pkScore"),
         loaded, datetime.now(timezone.utc).isoformat(), match_id),
    )
    conn.commit()
    return {"status": "loaded", "match_id": match_id, "events": inserted}


def load_dir(raw_dir: Path) -> dict:
    init_db()
    files = sorted(Path(raw_dir).glob("*.json"))
    loaded = total = skipped = 0
    with get_db() as conn:
        for p in files:
            r = load_match(p, conn)
            if r["status"] == "loaded":
                loaded += 1
                total += r["events"]
            else:
                skipped += 1
    summary = {"files": len(files), "loaded": loaded, "events": total, "skipped": skipped}
    logger.info("Load: %s", summary)
    return summary

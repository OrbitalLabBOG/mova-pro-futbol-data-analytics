"""Loader para procesar los JSONs crudos de FPL e insertarlos en SQLite (mundial.db)."""
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any

from src.mova_data.db import get_db, DB_PATH

def load_fpl_bootstrap(bootstrap_path: Path, db_path: Path = DB_PATH) -> Dict[str, int]:
    """Carga bootstrap_static.json en fpl_teams, fpl_players y fpl_gameweeks."""
    if not bootstrap_path.exists():
        return {"teams": 0, "players": 0, "gameweeks": 0}

    with open(bootstrap_path, encoding="utf-8") as f:
        data = json.load(f)

    counts = {"teams": 0, "players": 0, "gameweeks": 0}

    with get_db(db_path) as conn:
        # 1. Equipos
        for t in data.get("teams", []):
            conn.execute("""
                INSERT OR REPLACE INTO fpl_teams (
                    id, name, short_name, strength,
                    strength_overall_home, strength_overall_away,
                    strength_attack_home, strength_attack_away,
                    strength_defence_home, strength_defence_away, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t["id"], t["name"], t["short_name"], t.get("strength"),
                t.get("strength_overall_home"), t.get("strength_overall_away"),
                t.get("strength_attack_home"), t.get("strength_attack_away"),
                t.get("strength_defence_home"), t.get("strength_defence_away"), t.get("position")
            ))
            counts["teams"] += 1

        # 2. Jugadores
        for p in data.get("elements", []):
            conn.execute("""
                INSERT OR REPLACE INTO fpl_players (
                    id, first_name, second_name, web_name, team_id, element_type,
                    now_cost, status, total_points, minutes, goals_scored, assists,
                    clean_sheets, goals_conceded, yellow_cards, red_cards, saves, starts,
                    expected_goals, expected_assists, expected_goal_involvements,
                    expected_goals_conceded, influence, creativity, threat, ict_index,
                    expected_goals_per_90, expected_assists_per_90, form, points_per_game,
                    selected_by_percent, bonus, bps, transfers_in, transfers_out,
                    penalties_missed, penalties_saved, own_goals,
                    chance_of_playing_next_round, news
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["id"], p.get("first_name"), p.get("second_name"), p["web_name"], p.get("team"), p.get("element_type"),
                p.get("now_cost"), p.get("status"), p.get("total_points"), p.get("minutes"), p.get("goals_scored"), p.get("assists"),
                p.get("clean_sheets"), p.get("goals_conceded"), p.get("yellow_cards"), p.get("red_cards"), p.get("saves"), p.get("starts", 0),
                float(p.get("expected_goals") or 0.0), float(p.get("expected_assists") or 0.0), float(p.get("expected_goal_involvements") or 0.0),
                float(p.get("expected_goals_conceded") or 0.0), float(p.get("influence") or 0.0), float(p.get("creativity") or 0.0), float(p.get("threat") or 0.0), float(p.get("ict_index") or 0.0),
                float(p.get("expected_goals_per_90") or 0.0), float(p.get("expected_assists_per_90") or 0.0), float(p.get("form") or 0.0), float(p.get("points_per_game") or 0.0),
                float(p.get("selected_by_percent") or 0.0), p.get("bonus", 0), p.get("bps", 0), p.get("transfers_in", 0), p.get("transfers_out", 0),
                p.get("penalties_missed", 0), p.get("penalties_saved", 0), p.get("own_goals", 0),
                p.get("chance_of_playing_next_round"), p.get("news")
            ))
            counts["players"] += 1

        # 3. Gameweeks
        for g in data.get("events", []):
            conn.execute("""
                INSERT OR REPLACE INTO fpl_gameweeks (
                    id, deadline_time, finished, average_entry_score,
                    highest_score, most_selected, most_captained, top_element
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                g["id"], g.get("deadline_time"), int(g.get("finished", False)), g.get("average_entry_score"),
                g.get("highest_score"), g.get("most_selected"), g.get("most_captained"), g.get("top_element")
            ))
            counts["gameweeks"] += 1

        conn.commit()

    return counts


def load_fpl_fixtures(fixtures_path: Path, db_path: Path = DB_PATH) -> int:
    """Carga fixtures.json en fpl_fixtures."""
    if not fixtures_path.exists():
        return 0

    with open(fixtures_path, encoding="utf-8") as f:
        fixtures = json.load(f)

    count = 0
    with get_db(db_path) as conn:
        for f in fixtures:
            conn.execute("""
                INSERT OR REPLACE INTO fpl_fixtures (
                    id, event, team_h, team_a, team_h_score, team_a_score,
                    kickoff_time, finished, team_h_difficulty, team_a_difficulty
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f["id"], f.get("event"), f.get("team_h"), f.get("team_a"),
                f.get("team_h_score"), f.get("team_a_score"), f.get("kickoff_time"),
                int(f.get("finished", False)), f.get("team_h_difficulty"), f.get("team_a_difficulty")
            ))
            count += 1
        conn.commit()

    return count


def load_fpl_player_summary(summary_path: Path, player_id: int, db_path: Path = DB_PATH) -> int:
    """Carga element-summary de un jugador en fpl_player_history."""
    if not summary_path.exists():
        return 0

    with open(summary_path, encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("history", [])
    count = 0

    with get_db(db_path) as conn:
        for h in history:
            conn.execute("""
                INSERT OR REPLACE INTO fpl_player_history (
                    player_id, gameweek, opponent_team, was_home, minutes,
                    goals_scored, assists, clean_sheets, total_points,
                    expected_goals, expected_assists, influence, creativity,
                    threat, value, selected, transfers_in, transfers_out
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                player_id, h.get("round"), h.get("opponent_team"), int(h.get("was_home", False)), h.get("minutes", 0),
                h.get("goals_scored", 0), h.get("assists", 0), h.get("clean_sheets", 0), h.get("total_points", 0),
                float(h.get("expected_goals") or 0.0), float(h.get("expected_assists") or 0.0),
                float(h.get("influence") or 0.0), float(h.get("creativity") or 0.0), float(h.get("threat") or 0.0),
                h.get("value", 0), h.get("selected", 0), h.get("transfers_in", 0), h.get("transfers_out", 0)
            ))
            count += 1
        conn.commit()

    return count

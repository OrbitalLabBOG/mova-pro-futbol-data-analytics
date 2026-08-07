"""Script de migración idempotente.

Copia tablas de Fantasy Premier League (teams, players, gameweeks, fixtures, player_history)
y eventos Opta / partidos desde premier.db (local/VPS) hacia mundial.db de MOVA.
"""
import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEST_DB = ROOT / "data" / "mundial.db"
SRC_DB = Path("/home/jzuluaga/code/orbital-lab/premier-league/data/premier.db")

if not SRC_DB.exists():
    SRC_DB = Path("/opt/orbital/services/premier-league-api/data/premier.db")

def migrate():
    print(f"📦 Iniciando migración desde: {SRC_DB}")
    print(f"🎯 Destino: {DEST_DB}")

    if not SRC_DB.exists():
        print(f"❌ Error: No se encontró la base fuente {SRC_DB}")
        return

    from src.mova_data.db import init_db
    init_db(DEST_DB)

    src_conn = sqlite3.connect(SRC_DB)
    dest_conn = sqlite3.connect(DEST_DB)

    src_conn.row_factory = sqlite3.Row

    # 1. Migrar fpl_teams
    print("➡️ Migrando fpl_teams...")
    teams = src_conn.execute("SELECT * FROM teams").fetchall()
    for t in teams:
        dest_conn.execute("""
            INSERT OR REPLACE INTO fpl_teams (
                id, name, short_name, strength,
                strength_overall_home, strength_overall_away,
                strength_attack_home, strength_attack_away,
                strength_defence_home, strength_defence_away, position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t["id"], t["name"], t["short_name"], t["strength"],
            t["strength_overall_home"], t["strength_overall_away"],
            t["strength_attack_home"], t["strength_attack_away"],
            t["strength_defence_home"], t["strength_defence_away"], t["position"]
        ))
    print(f"  ✓ {len(teams)} equipos migrados.")

    # 2. Migrar fpl_players
    print("➡️ Migrando fpl_players...")
    players_rows = src_conn.execute("SELECT * FROM players").fetchall()
    for row in players_rows:
        p = dict(row)
        dest_conn.execute("""
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
            p["id"], p["first_name"], p["second_name"], p["web_name"], p["team_id"], p["element_type"],
            p["now_cost"], p["status"], p["total_points"], p["minutes"], p["goals_scored"], p["assists"],
            p["clean_sheets"], p["goals_conceded"], p["yellow_cards"], p["red_cards"], p["saves"], p.get("starts", 0),
            p.get("expected_goals", 0.0), p.get("expected_assists", 0.0), p.get("expected_goal_involvements", 0.0),
            p.get("expected_goals_conceded", 0.0), p.get("influence", 0.0), p.get("creativity", 0.0), p.get("threat", 0.0), p.get("ict_index", 0.0),
            p.get("expected_goals_per_90", 0.0), p.get("expected_assists_per_90", 0.0), p.get("form", 0.0), p.get("points_per_game", 0.0),
            p.get("selected_by_percent", 0.0), p.get("bonus", 0), p.get("bps", 0), p.get("transfers_in", 0), p.get("transfers_out", 0),
            p.get("penalties_missed", 0), p.get("penalties_saved", 0), p.get("own_goals", 0),
            p.get("chance_of_playing_next_round"), p.get("news")
        ))
    print(f"  ✓ {len(players_rows)} jugadores migrados.")

    # 3. Migrar fpl_gameweeks
    print("➡️ Migrando fpl_gameweeks...")
    gws = src_conn.execute("SELECT * FROM gameweeks").fetchall()
    for g in gws:
        dest_conn.execute("""
            INSERT OR REPLACE INTO fpl_gameweeks (
                id, deadline_time, finished, average_entry_score,
                highest_score, most_selected, most_captained, top_element
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g["id"], g["deadline_time"], g["finished"], g["average_entry_score"],
            g["highest_score"], g["most_selected"], g["most_captained"], g["top_element"]
        ))
    print(f"  ✓ {len(gws)} gameweeks migradas.")

    # 4. Migrar fpl_fixtures
    print("➡️ Migrando fpl_fixtures...")
    fxs = src_conn.execute("SELECT * FROM fixtures").fetchall()
    for f in fxs:
        dest_conn.execute("""
            INSERT OR REPLACE INTO fpl_fixtures (
                id, event, team_h, team_a, team_h_score, team_a_score,
                kickoff_time, finished, team_h_difficulty, team_a_difficulty
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f["id"], f["event"], f["team_h"], f["team_a"], f["team_h_score"], f["team_a_score"],
            f["kickoff_time"], f["finished"], f["team_h_difficulty"], f["team_a_difficulty"]
        ))
    print(f"  ✓ {len(fxs)} fixtures migrados.")

    # 5. Migrar fpl_player_history
    print("➡️ Migrando fpl_player_history...")
    ph = src_conn.execute("SELECT * FROM player_history").fetchall()
    for row in ph:
        h = dict(row)
        dest_conn.execute("""
            INSERT OR REPLACE INTO fpl_player_history (
                player_id, gameweek, opponent_team, was_home, minutes,
                goals_scored, assists, clean_sheets, total_points,
                expected_goals, expected_assists, influence, creativity,
                threat, value, selected, transfers_in, transfers_out
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h["player_id"], h["gameweek"], h["opponent_team"], h["was_home"], h["minutes"],
            h["goals_scored"], h["assists"], h["clean_sheets"], h["total_points"],
            h.get("expected_goals", 0.0), h.get("expected_assists", 0.0), h.get("influence", 0.0),
            h.get("creativity", 0.0), h.get("threat", 0.0), h["value"], h.get("selected", 0),
            h.get("transfers_in", 0), h.get("transfers_out", 0)
        ))
    print(f"  ✓ {len(ph)} registros de historial de jugadores migrados.")

    # 6. Migrar partidos (matches)
    print("➡️ Migrando matches de Premier League...")
    matches = src_conn.execute("SELECT * FROM matches").fetchall()
    match_id_map = {}
    for row in matches:
        m = dict(row)
        target_match_id = m.get("whoscored_id") or (m["id"] + 100000)
        match_id_map[m["id"]] = target_match_id
        dest_conn.execute("""
            INSERT OR REPLACE INTO matches (
                match_id, source, competition, stage_name, round,
                status, is_finished, start_utc, home_team, away_team,
                home_score, away_score, referee, n_events
            ) VALUES (?, 'premier_league', 'Premier League 2025-26', 'Regular Season', 'regular',
                        6, 1, ?, ?, ?, ?, ?, ?, 0)
        """, (
            target_match_id, m.get("date"), m["home_team"], m["away_team"],
            m.get("fthg"), m.get("ftag"), m.get("referee")
        ))
    print(f"  ✓ {len(matches)} partidos migrados.")

    # 7. Migrar eventos (events)
    print("➡️ Migrando eventos de Premier League...")
    events = src_conn.execute("SELECT * FROM events").fetchall()
    count = 0
    for row in events:
        e = dict(row)
        mapped_match_id = match_id_map.get(e["match_id"], e["match_id"] + 100000)
        ws_evt_id = e.get("ws_event_id") or e.get("id")
        dest_conn.execute("""
            INSERT OR IGNORE INTO events (
                source, match_id, ws_event_id, event_id, minute, second,
                expanded_minute, period, event_type, outcome, team_name,
                player_name, x, y, end_x, end_y, goal_mouth_y, goal_mouth_z,
                blocked_x, blocked_y, is_touch, is_shot, is_goal, card_type,
                qualifiers
            ) VALUES ('whoscored_pl', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mapped_match_id, ws_evt_id, e.get("event_id"), e.get("minute"), e.get("second"),
            e.get("expanded_minute"), e.get("period"), e.get("event_type"), e.get("outcome"), e.get("team_name"),
            e.get("player_name"), e.get("x"), e.get("y"), e.get("end_x"), e.get("end_y"),
            e.get("goal_mouth_y"), e.get("goal_mouth_z"), e.get("blocked_x"), e.get("blocked_y"),
            e.get("is_touch", 0), e.get("is_shot", 0), e.get("is_goal", 0), e.get("card_type"),
            e.get("qualifiers", '[]')
        ))
        count += 1
    print(f"  ✓ {count} eventos Opta migrados.")

    dest_conn.commit()
    src_conn.close()
    dest_conn.close()

    print("🎉 Migración completada exitosamente.")

if __name__ == "__main__":
    migrate()

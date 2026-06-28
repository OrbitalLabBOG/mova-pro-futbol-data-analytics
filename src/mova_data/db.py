"""Esquema y acceso a SQLite — diseñado source-agnostic y training-ready.

Toda tabla de hechos lleva columna `source` para poder mezclar proveedores
(WhoScored hoy; StatsBomb / API en el futuro) sin romper el modelo.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id        INTEGER PRIMARY KEY,   -- id del proveedor (WhoScored)
    source          TEXT NOT NULL DEFAULT 'whoscored',
    competition     TEXT,                  -- 'FIFA World Cup 2026'
    stage_id        INTEGER,
    stage_name      TEXT,                  -- 'Group K', 'Final Stage'
    round           TEXT,                  -- 'group' | 'R32' | 'R16' ...
    status          INTEGER,               -- código WhoScored
    is_finished     INTEGER DEFAULT 0,
    start_utc       TEXT,
    home_team_id    INTEGER,
    home_team       TEXT,
    away_team_id    INTEGER,
    away_team       TEXT,
    home_score      INTEGER,
    away_score      INTEGER,
    ht_score        TEXT,
    et_score        TEXT,
    pk_score        TEXT,
    venue           TEXT,
    attendance      INTEGER,
    referee         TEXT,
    match_is_opta   INTEGER,
    n_events        INTEGER,
    scraped_at      TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    team_id      INTEGER,
    source       TEXT NOT NULL DEFAULT 'whoscored',
    name         TEXT,
    country_code TEXT,
    PRIMARY KEY (source, team_id)
);

CREATE TABLE IF NOT EXISTS players (
    player_id  INTEGER,
    source     TEXT NOT NULL DEFAULT 'whoscored',
    name       TEXT,
    PRIMARY KEY (source, player_id)
);

CREATE TABLE IF NOT EXISTS lineups (
    match_id    INTEGER,
    team_id     INTEGER,
    player_id   INTEGER,
    source      TEXT NOT NULL DEFAULT 'whoscored',
    name        TEXT,
    shirt_no    INTEGER,
    position    TEXT,
    is_starter  INTEGER,
    is_motm     INTEGER,
    age         INTEGER,
    height      INTEGER,
    PRIMARY KEY (source, match_id, player_id)
);

CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL DEFAULT 'whoscored',
    match_id          INTEGER NOT NULL,
    ws_event_id       REAL,
    event_id          INTEGER,
    minute            INTEGER,
    second            INTEGER,
    expanded_minute   INTEGER,
    period            TEXT,
    event_type        TEXT,
    outcome           TEXT,
    team_id           INTEGER,
    team_name         TEXT,
    player_id         INTEGER,
    player_name       TEXT,
    x                 REAL,
    y                 REAL,
    end_x             REAL,
    end_y             REAL,
    goal_mouth_y      REAL,
    goal_mouth_z      REAL,
    blocked_x         REAL,
    blocked_y         REAL,
    is_touch          INTEGER,
    is_shot           INTEGER,
    is_goal           INTEGER,
    card_type         TEXT,
    related_event_id  INTEGER,
    related_player_id INTEGER,
    qualifiers        TEXT,
    UNIQUE (source, match_id, ws_event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_match   ON events(match_id);
CREATE INDEX IF NOT EXISTS idx_events_type    ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_player  ON events(player_id);
CREATE INDEX IF NOT EXISTS idx_events_shot    ON events(is_shot) WHERE is_shot = 1;
CREATE INDEX IF NOT EXISTS idx_matches_stage  ON matches(stage_id);
"""


def init_db(path: Path = DB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_db(path: Path = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()

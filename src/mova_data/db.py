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

-- ── Fuentes de contexto (diseño en docs/06 §5, campos confirmados) ──

CREATE TABLE IF NOT EXISTS elo_ratings (
    source        TEXT NOT NULL DEFAULT 'eloratings',
    snapshot_date TEXT NOT NULL,        -- YYYY-MM-DD de la captura
    iso           TEXT,                 -- código eloratings (AR, ES, EN, SCO...)
    team          TEXT,                 -- nombre mapeado a WhoScored (si aplica)
    rank          INTEGER,
    rating        INTEGER,
    PRIMARY KEY (source, snapshot_date, iso)
);

CREATE TABLE IF NOT EXISTS market_odds (
    source       TEXT NOT NULL,         -- kalshi | polymarket | espn | oddsapi
    captured_at  TEXT NOT NULL,         -- ISO timestamp de la captura (serie temporal)
    market_type  TEXT NOT NULL,         -- 'winner' | 'match_ml' ...
    entity       TEXT NOT NULL,         -- equipo / resultado
    prob         REAL,                  -- probabilidad implícita 0-1
    yes_bid      REAL,
    yes_ask      REAL,
    last_price   REAL,
    ticker       TEXT,
    PRIMARY KEY (source, market_type, entity, captured_at)
);

CREATE TABLE IF NOT EXISTS espn_fixtures (
    espn_id     INTEGER PRIMARY KEY,
    date_utc    TEXT,
    status      TEXT,
    home_team   TEXT,
    away_team   TEXT,
    home_score  INTEGER,
    away_score  INTEGER,
    ml_home     INTEGER,                -- moneyline american odds (DraftKings)
    ml_draw     INTEGER,
    ml_away     INTEGER,
    venue       TEXT,
    updated_at  TEXT
);

-- The Odds API: granular por casa (no se pierde ninguna casa/mercado).
CREATE TABLE IF NOT EXISTS odds_quotes (
    source         TEXT NOT NULL DEFAULT 'oddsapi',
    captured_at    TEXT NOT NULL,
    scope          TEXT NOT NULL,       -- 'winner' | 'match'
    event_id       TEXT,
    commence_time  TEXT,
    home_team      TEXT,
    away_team      TEXT,
    bookmaker      TEXT,
    market         TEXT,                -- outrights | h2h | totals | spreads
    outcome        TEXT,                -- equipo / Over / Under / Draw
    price          REAL,                -- cuota decimal
    point          REAL,                -- línea (totals/spreads)
    PRIMARY KEY (source, captured_at, scope, event_id, bookmaker, market, outcome, point)
);

-- Identidad canónica de equipos: cualquier alias/código → nombre canónico (WhoScored).
CREATE TABLE IF NOT EXISTS team_aliases (
    alias_norm TEXT PRIMARY KEY,        -- alias normalizado (lower, sin acentos/puntuación)
    alias      TEXT,                    -- alias tal cual se vio
    canonical  TEXT NOT NULL,           -- nombre canónico (= teams.name de WhoScored)
    kind       TEXT                     -- 'identity' | 'override' | 'iso'
);

CREATE INDEX IF NOT EXISTS idx_odds_entity ON market_odds(entity);
CREATE INDEX IF NOT EXISTS idx_elo_team    ON elo_ratings(team);
CREATE INDEX IF NOT EXISTS idx_quotes_evt  ON odds_quotes(event_id);
CREATE INDEX IF NOT EXISTS idx_quotes_scope ON odds_quotes(scope);
CREATE INDEX IF NOT EXISTS idx_aliases_canon ON team_aliases(canonical);

-- Vista unificada: cada equipo canónico con Elo + prob. de cada mercado
-- (resuelve nombres entre fuentes vía team_aliases).
CREATE VIEW IF NOT EXISTS v_team_board AS
SELECT
  t.name AS team,
  (SELECT e.rating FROM elo_ratings e
     WHERE e.team = t.name ORDER BY e.snapshot_date DESC LIMIT 1) AS elo,
  (SELECT mo.prob FROM market_odds mo JOIN team_aliases a ON a.alias = mo.entity
     WHERE a.canonical = t.name AND mo.source='kalshi'
     ORDER BY mo.captured_at DESC LIMIT 1) AS p_kalshi,
  (SELECT mo.prob FROM market_odds mo JOIN team_aliases a ON a.alias = mo.entity
     WHERE a.canonical = t.name AND mo.source='polymarket'
     ORDER BY mo.captured_at DESC LIMIT 1) AS p_polymarket,
  (SELECT mo.prob FROM market_odds mo JOIN team_aliases a ON a.alias = mo.entity
     WHERE a.canonical = t.name AND mo.source='oddsapi'
     ORDER BY mo.captured_at DESC LIMIT 1) AS p_oddsapi
FROM (SELECT DISTINCT name FROM teams WHERE name IS NOT NULL) t;
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

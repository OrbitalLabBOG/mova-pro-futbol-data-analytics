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

-- Enlace de partidos entre fuentes (WhoScored ↔ ESPN ↔ OddsAPI).
-- Clave = par de equipos canónicos ordenado (un par juega 1 vez en el torneo).
CREATE TABLE IF NOT EXISTS match_map (
    match_key        TEXT PRIMARY KEY,  -- 'team_a|team_b' (canónicos, ordenados)
    team_a           TEXT,
    team_b           TEXT,
    match_date       TEXT,
    whoscored_id     INTEGER,
    espn_id          INTEGER,
    oddsapi_event_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_mmap_ws ON match_map(whoscored_id);

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

-- Partidos enlazados: WhoScored + ids de ESPN/OddsAPI + nº de eventos y cuotas.
CREATE VIEW IF NOT EXISTS v_match AS
SELECT
  mm.match_key, mm.team_a, mm.team_b, mm.match_date,
  mm.whoscored_id, mm.espn_id, mm.oddsapi_event_id,
  m.stage_name, m.home_team, m.away_team, m.home_score, m.away_score,
  m.n_events,
  (SELECT count(*) FROM odds_quotes q
     WHERE q.scope='match' AND q.event_id = mm.oddsapi_event_id) AS n_quotes
FROM match_map mm
LEFT JOIN matches m ON m.match_id = mm.whoscored_id;

-- ════════════════════ CAPA FANTASY PREMIER LEAGUE (FPL) ════════════════════

CREATE TABLE IF NOT EXISTS fpl_teams (
    id                            INTEGER PRIMARY KEY,
    name                          TEXT NOT NULL,
    short_name                    TEXT,
    strength                      INTEGER,
    strength_overall_home        INTEGER,
    strength_overall_away        INTEGER,
    strength_attack_home         INTEGER,
    strength_attack_away         INTEGER,
    strength_defence_home        INTEGER,
    strength_defence_away        INTEGER,
    position                      INTEGER
);

CREATE TABLE IF NOT EXISTS fpl_players (
    id                            INTEGER PRIMARY KEY,
    first_name                    TEXT,
    second_name                   TEXT,
    web_name                      TEXT NOT NULL,
    team_id                       INTEGER REFERENCES fpl_teams(id),
    element_type                  INTEGER, -- 1:GKP, 2:DEF, 3:MID, 4:FWD
    now_cost                      INTEGER, -- precio en 0.1M (ej. 100 = £10.0M)
    status                        TEXT,
    total_points                  INTEGER,
    minutes                       INTEGER,
    goals_scored                  INTEGER,
    assists                       INTEGER,
    clean_sheets                  INTEGER,
    goals_conceded                INTEGER,
    yellow_cards                  INTEGER,
    red_cards                     INTEGER,
    saves                         INTEGER,
    starts                        INTEGER,
    expected_goals                REAL,
    expected_assists              REAL,
    expected_goal_involvements    REAL,
    expected_goals_conceded       REAL,
    influence                     REAL,
    creativity                    REAL,
    threat                        REAL,
    ict_index                     REAL,
    expected_goals_per_90         REAL,
    expected_assists_per_90       REAL,
    form                          REAL,
    points_per_game               REAL,
    selected_by_percent           REAL,
    bonus                         INTEGER,
    bps                           INTEGER,
    transfers_in                  INTEGER,
    transfers_out                 INTEGER,
    penalties_missed              INTEGER,
    penalties_saved               INTEGER,
    own_goals                     INTEGER,
    chance_of_playing_next_round INTEGER,
    news                          TEXT
);

CREATE TABLE IF NOT EXISTS fpl_gameweeks (
    id                            INTEGER PRIMARY KEY,
    deadline_time                 TEXT,
    finished                      INTEGER,
    average_entry_score           INTEGER,
    highest_score                 INTEGER,
    most_selected                 INTEGER,
    most_captained                INTEGER,
    top_element                   INTEGER
);

CREATE TABLE IF NOT EXISTS fpl_fixtures (
    id                            INTEGER PRIMARY KEY,
    event                         INTEGER,
    team_h                        INTEGER REFERENCES fpl_teams(id),
    team_a                        INTEGER REFERENCES fpl_teams(id),
    team_h_score                  INTEGER,
    team_a_score                  INTEGER,
    kickoff_time                  TEXT,
    finished                      INTEGER,
    team_h_difficulty             INTEGER,
    team_a_difficulty             INTEGER
);

CREATE TABLE IF NOT EXISTS fpl_player_history (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id                     INTEGER REFERENCES fpl_players(id),
    gameweek                      INTEGER,
    opponent_team                 INTEGER,
    was_home                      INTEGER,
    minutes                       INTEGER,
    goals_scored                  INTEGER,
    assists                       INTEGER,
    clean_sheets                  INTEGER,
    total_points                  INTEGER,
    expected_goals                REAL,
    expected_assists              REAL,
    influence                     REAL,
    creativity                    REAL,
    threat                        REAL,
    value                         INTEGER,
    selected                      INTEGER,
    transfers_in                  INTEGER,
    transfers_out                 INTEGER,
    UNIQUE(player_id, gameweek)
);

CREATE INDEX IF NOT EXISTS idx_fpl_players_team ON fpl_players(team_id);
CREATE INDEX IF NOT EXISTS idx_fpl_players_type ON fpl_players(element_type);
CREATE INDEX IF NOT EXISTS idx_fpl_fixtures_evt ON fpl_fixtures(event);
CREATE INDEX IF NOT EXISTS idx_fpl_history_player ON fpl_player_history(player_id);

-- ════════════════════ TABLAS Y VISTAS MAESTRAS DE ANALÍTICA ════════════════════

-- Vista Maestra por Jugador y Gameweek (FPL + Rendimiento + Valor)
CREATE VIEW IF NOT EXISTS v_master_player_gw AS
SELECT
    ph.player_id,
    p.web_name AS player_name,
    p.first_name || ' ' || p.second_name AS full_name,
    t.name AS team_name,
    t.short_name AS team_short,
    p.element_type,
    CASE p.element_type
        WHEN 1 THEN 'GKP'
        WHEN 2 THEN 'DEF'
        WHEN 3 THEN 'MID'
        WHEN 4 THEN 'FWD'
    END AS position_name,
    ph.gameweek,
    ph.opponent_team,
    opt.short_name AS opponent_short,
    ph.was_home,
    ph.minutes,
    ph.total_points,
    ph.goals_scored,
    ph.assists,
    ph.clean_sheets,
    ph.expected_goals AS gw_xg,
    ph.expected_assists AS gw_xa,
    ph.influence,
    ph.creativity,
    ph.threat,
    (ph.influence + ph.creativity + ph.threat) AS ict_sum,
    ph.value / 10.0 AS cost_millions,
    ph.selected AS gw_selected_by,
    p.form AS current_form,
    p.selected_by_percent AS total_selected_pct
FROM fpl_player_history ph
JOIN fpl_players p ON p.id = ph.player_id
LEFT JOIN fpl_teams t ON t.id = p.team_id
LEFT JOIN fpl_teams opt ON opt.id = ph.opponent_team;

-- Vista Maestra de Analítica de Partidos (Partidos + Cuotas + Eventos + Goles)
CREATE VIEW IF NOT EXISTS v_master_match_analytics AS
SELECT
    m.match_id,
    m.source,
    m.competition,
    m.start_utc AS match_date,
    m.home_team,
    m.away_team,
    m.home_score,
    m.away_score,
    m.n_events,
    (SELECT COUNT(*) FROM events e WHERE e.match_id = m.match_id AND e.is_shot = 1) AS n_shots,
    (SELECT COUNT(*) FROM events e WHERE e.match_id = m.match_id AND e.is_goal = 1) AS n_goals,
    (SELECT mo.prob FROM market_odds mo WHERE mo.entity = m.home_team ORDER BY mo.captured_at DESC LIMIT 1) AS p_home_win,
    (SELECT mo.prob FROM market_odds mo WHERE mo.entity = m.away_team ORDER BY mo.captured_at DESC LIMIT 1) AS p_away_win
FROM matches m;


-- ════════════════════ CAPA DE MODELO (Fase 2) ════════════════════

-- Histórico internacional (martj42) + Elo pre-partido calculado por nosotros.
CREATE TABLE IF NOT EXISTS intl_results (
    source        TEXT NOT NULL DEFAULT 'martj42',
    match_date    TEXT NOT NULL,
    home_team     TEXT NOT NULL,        -- nombre martj42 (crudo)
    away_team     TEXT NOT NULL,
    home_score    INTEGER,
    away_score    INTEGER,
    tournament    TEXT,
    neutral       INTEGER,
    home_elo_pre  REAL,                 -- Elo antes del partido (calculado)
    away_elo_pre  REAL,
    PRIMARY KEY (source, match_date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_intl_date ON intl_results(match_date);

-- Elo actual calculado por nosotros sobre todo el histórico martj42.
CREATE TABLE IF NOT EXISTS elo_computed (
    team_raw     TEXT PRIMARY KEY,      -- nombre martj42
    team         TEXT,                  -- canónico (teams.resolve), NULL si no se reconoce
    rating       REAL,
    n_matches    INTEGER,
    last_date    TEXT,
    computed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_elocomp_team ON elo_computed(team);

-- xG por tiro (ambos proveedores; SB lleva target, WS lleva predicción de nuestro modelo).
CREATE TABLE IF NOT EXISTS shot_xg (
    source        TEXT NOT NULL,        -- 'whoscored' | 'statsbomb'
    match_id      TEXT NOT NULL,
    shot_uid      TEXT NOT NULL,
    team          TEXT,                 -- canónico
    player_id     INTEGER,
    minute        INTEGER,
    dist_m        REAL,
    angle_rad     REAL,
    body_part     TEXT,                 -- foot | head | other
    play_type     TEXT,                 -- open | setpiece | corner | freekick | penalty
    is_big_chance INTEGER,
    xg_model      REAL,                 -- nuestro xG
    xg_statsbomb  REAL,                 -- target SB (NULL en WS)
    is_goal       INTEGER,
    model_version TEXT,
    generated_at  TEXT,
    PRIMARY KEY (source, match_id, shot_uid)
);
CREATE INDEX IF NOT EXISTS idx_shotxg_team ON shot_xg(team);

-- Fuerzas/features por equipo (recomputado cada corrida).
CREATE TABLE IF NOT EXISTS team_features (
    team          TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    as_of_date    TEXT,
    n_matches     INTEGER,
    xgf_per_match REAL,
    xga_per_match REAL,
    att_strength  REAL,
    def_strength  REAL,
    elo_rating    REAL,
    elo_rank      INTEGER,
    generated_at  TEXT,
    PRIMARY KEY (team, run_id)
);

-- Predicciones por partido (1X2: modelo, mercado, blend).
CREATE TABLE IF NOT EXISTS match_predictions (
    match_key     TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    home_team     TEXT,
    away_team     TEXT,
    match_date    TEXT,
    lambda_home   REAL,
    lambda_away   REAL,
    p_home_model  REAL, p_draw_model REAL, p_away_model REAL,
    p_home_mkt    REAL, p_draw_mkt   REAL, p_away_mkt   REAL,
    p_home        REAL, p_draw       REAL, p_away       REAL,
    w_blend       REAL,
    n_quotes      INTEGER,
    generated_at  TEXT,
    PRIMARY KEY (match_key, run_id)
);

-- Simulación del torneo (salida estrella): P(avance/campeón) por equipo.
CREATE TABLE IF NOT EXISTS tournament_sim (
    team         TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    n_sims       INTEGER,
    p_r16 REAL, p_qf REAL, p_sf REAL, p_final REAL, p_champion REAL,
    p_group_adv  REAL,
    seed         INTEGER,
    generated_at TEXT,
    PRIMARY KEY (team, run_id)
);

-- Registro de corridas (auditoría / idempotencia).
CREATE TABLE IF NOT EXISTS model_runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT,
    finished_at   TEXT,
    barrier_date  TEXT,
    xg_version    TEXT,
    dc_version    TEXT,
    w_blend       REAL,
    n_sims        INTEGER,
    seed          INTEGER,
    n_matches_pred INTEGER,
    stages        TEXT,
    status        TEXT
);
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

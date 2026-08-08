"""Esquema de la traza (ADR-005): SQLite del proyecto, no el Supabase del Lab.

Es data de experimento, no de negocio. Nunca se edita retroactivamente: una
correccion genera una corrida nueva.
"""
from __future__ import annotations

DDL = [
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        run_id        TEXT PRIMARY KEY,
        started_at    TEXT NOT NULL,
        finished_at   TEXT,
        season        TEXT NOT NULL,
        mode          TEXT NOT NULL,          -- named | anonymized
        policy        TEXT NOT NULL,
        horizon       INTEGER NOT NULL,
        seed          INTEGER NOT NULL,
        git_sha       TEXT,
        config_json   TEXT,
        status        TEXT NOT NULL,          -- running | completed | failed | interrupted
        total_points  INTEGER,
        notes         TEXT
    )""",
    """
    CREATE TABLE IF NOT EXISTS gw_decisions (
        run_id            TEXT NOT NULL,
        gw                INTEGER NOT NULL,
        state             TEXT NOT NULL,      -- projected | committed | reconciled
        fingerprint       TEXT NOT NULL,
        squad_15          TEXT NOT NULL,
        starters          TEXT NOT NULL,
        captain           INTEGER,
        vice_captain      INTEGER,
        bench_order       TEXT,
        transfers_in      TEXT,
        transfers_out     TEXT,
        hits              INTEGER DEFAULT 0,
        chip              TEXT,
        expected_points   REAL,
        total_cost        REAL,
        actual_points     INTEGER,
        captain_points    INTEGER,
        auto_subs         TEXT,
        train_rows        INTEGER,
        notes             TEXT,
        PRIMARY KEY (run_id, gw)
    )""",
    """
    CREATE TABLE IF NOT EXISTS benchmarks (
        run_id     TEXT NOT NULL,
        gw         INTEGER NOT NULL,
        baseline   TEXT NOT NULL,
        points     INTEGER NOT NULL,
        PRIMARY KEY (run_id, gw, baseline)
    )""",
    """
    CREATE TABLE IF NOT EXISTS model_versions (
        name        TEXT NOT NULL,
        version     TEXT NOT NULL,
        git_sha     TEXT,
        trained_at  TEXT,
        train_rows  INTEGER,
        metrics     TEXT,
        PRIMARY KEY (name, version)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_dec_run ON gw_decisions(run_id, gw)",
    "CREATE INDEX IF NOT EXISTS idx_bench_run ON benchmarks(run_id, baseline)",
]

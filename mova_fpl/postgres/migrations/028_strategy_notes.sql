-- Shadow projection of the append-only copilot memory (ADR-021).
-- The SQLite writer keeps the immutable originals; this table mirrors them.
create table if not exists agent.strategy_notes (
  note_id text primary key,
  cycle_id text not null,
  season text not null,
  gw integer not null check (gw between 1 and 38),
  kind text not null check (kind in ('reason','owner_preference','hypothesis',
    'constraint','post_mortem','decision')),
  text text not null check (length(text) between 1 and 2000),
  players jsonb not null,
  source text not null check (source in ('owner','assistant')),
  actor text not null,
  reason text not null,
  idempotency_key text not null unique,
  request_sha256 char(64) not null,
  created_at timestamptz not null,
  supersedes_note_id text references agent.strategy_notes(note_id)
);
create index if not exists strategy_notes_gw_idx
  on agent.strategy_notes(season, gw, created_at);
grant select on agent.strategy_notes to mova_readonly;
grant select,insert,update on agent.strategy_notes to mova_app;

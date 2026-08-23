-- MOVA PostgreSQL shadow store v1.
-- El writer productivo continúa en SQLite hasta un cutover aprobado.

revoke create on schema public from public;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'mova_app') then
    create role mova_app nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'mova_readonly') then
    create role mova_readonly nologin;
  end if;
end $$;

create schema if not exists mova_meta;
create schema if not exists raw;
create schema if not exists analytics;
create schema if not exists game;
create schema if not exists research;
create schema if not exists agent;
create schema if not exists ops;

create table if not exists mova_meta.schema_migrations (
  version integer primary key,
  name text not null unique,
  checksum char(64) not null check (length(checksum) = 64),
  applied_at timestamptz not null default now()
);

create table if not exists mova_meta.import_runs (
  import_run_id text primary key,
  idempotency_key text not null unique,
  actor text not null,
  reason text not null,
  status text not null check (status in ('running','completed','failed')),
  git_sha text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  ops_sha256 char(64) not null check (length(ops_sha256) = 64),
  canonical_sha256 char(64) not null check (length(canonical_sha256) = 64),
  trace_sha256 char(64) not null check (length(trace_sha256) = 64),
  artifact_path text not null,
  manifest_sha256 char(64) not null check (length(manifest_sha256) = 64),
  error_detail text
);

create table if not exists mova_meta.import_table_checks (
  import_run_id text not null references mova_meta.import_runs(import_run_id) on delete cascade,
  source_db text not null,
  source_table text not null,
  target_table text not null,
  source_rows bigint not null check (source_rows >= 0),
  target_rows bigint not null check (target_rows >= 0),
  status text not null check (status in ('pass','fail')),
  detail jsonb not null default '{}'::jsonb,
  primary key (import_run_id, source_db, source_table)
);

create table if not exists raw.source_snapshots (
  snapshot_id text primary key,
  job_id text,
  cycle_id text not null,
  source_name text not null,
  captured_at timestamptz not null,
  artifact_path text not null,
  manifest_sha256 char(64) not null,
  payload_sha256 char(64) not null,
  freshness_seconds integer not null check (freshness_seconds >= 0),
  quality_status text not null check (quality_status in ('valid','degraded','quarantined')),
  quality jsonb not null,
  unique (source_name, payload_sha256)
);
create index if not exists source_snapshots_cycle_captured_idx
  on raw.source_snapshots (cycle_id, captured_at desc);

create table if not exists analytics.player_gameweek (
  source_row_id bigint primary key,
  season text,
  gw integer,
  element integer,
  fixture integer,
  player_key text,
  name text,
  opponent_team integer,
  was_home boolean,
  kickoff_time timestamptz,
  round integer,
  minutes integer,
  total_points integer,
  goals_scored integer,
  assists integer,
  clean_sheets integer,
  goals_conceded integer,
  own_goals integer,
  penalties_saved integer,
  penalties_missed integer,
  yellow_cards integer,
  red_cards integer,
  saves integer,
  bonus integer,
  bps integer,
  influence double precision,
  creativity double precision,
  threat integer,
  ict_index double precision,
  value integer,
  selected bigint,
  transfers_in bigint,
  transfers_out bigint,
  transfers_balance bigint,
  team_a_score integer,
  team_h_score integer,
  position text,
  team text,
  xp_official double precision,
  expected_goals double precision,
  expected_assists double precision,
  expected_goal_involvements double precision,
  expected_goals_conceded double precision,
  starts double precision,
  clearances_blocks_interceptions integer,
  recoveries integer,
  tackles integer,
  defensive_contribution double precision,
  key_passes integer,
  big_chances_created integer,
  big_chances_missed integer,
  errors_leading_to_goal integer,
  open_play_crosses integer,
  dribbles integer,
  fouls integer,
  offside integer,
  penalties_conceded integer,
  winning_goals integer,
  attempted_passes integer,
  completed_passes integer,
  target_missed integer,
  tackled integer
);
create index if not exists player_gameweek_season_gw_idx
  on analytics.player_gameweek (season, gw);
create index if not exists player_gameweek_player_asof_idx
  on analytics.player_gameweek (player_key, season, gw);
create index if not exists player_gameweek_fixture_idx
  on analytics.player_gameweek (fixture);

create table if not exists analytics.dataset_releases (
  dataset_id text primary key,
  dataset_name text not null,
  version text not null,
  as_of_at timestamptz not null,
  row_count bigint not null check (row_count >= 0),
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  leakage_audit jsonb not null,
  created_at timestamptz not null,
  unique (dataset_name, version)
);

create table if not exists analytics.model_releases (
  model_release_id text primary key,
  model_name text not null,
  version text not null,
  dataset_id text references analytics.dataset_releases(dataset_id),
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  metrics jsonb not null,
  status text not null check (status in ('candidate','shadow','approved','retired')),
  created_at timestamptz not null,
  unique (model_name, version)
);
create index if not exists model_releases_dataset_idx
  on analytics.model_releases (dataset_id);

create table if not exists analytics.projection_runs (
  projection_id text primary key,
  job_id text,
  cycle_id text not null,
  model_manifest jsonb not null,
  input_manifest_sha256 char(64) not null,
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  player_count integer not null check (player_count > 0),
  created_at timestamptz not null
);
create index if not exists projection_runs_cycle_created_idx
  on analytics.projection_runs (cycle_id, created_at desc);

create table if not exists analytics.legacy_model_versions (
  name text not null,
  version text not null,
  git_sha text,
  trained_at timestamptz,
  train_rows bigint,
  metrics jsonb,
  primary key (name, version)
);

create table if not exists game.seasons (
  season_code text primary key,
  first_gw integer not null default 1 check (first_gw = 1),
  last_gw integer not null default 38 check (last_gw between 1 and 38),
  rules_sha256 char(64),
  status text not null check (status in ('planned','active','complete')),
  created_at timestamptz not null
);

create table if not exists game.cycles (
  cycle_id text primary key,
  season text not null,
  gw integer not null check (gw between 1 and 38),
  deadline_at timestamptz not null,
  phase text not null,
  status text not null,
  revision integer not null default 1 check (revision >= 1),
  first_observed_at timestamptz not null,
  last_observed_at timestamptz not null,
  unique (season, gw)
);

create table if not exists game.team_snapshots (
  team_state_id text primary key,
  job_id text,
  cycle_id text not null references game.cycles(cycle_id),
  observed_at timestamptz not null,
  source_name text not null,
  squad jsonb not null,
  free_transfers integer not null check (free_transfers between 0 and 5),
  bank_tenths integer not null,
  chips jsonb not null,
  fingerprint text not null,
  artifact_path text,
  manifest_sha256 char(64),
  quality_status text check (quality_status in ('valid','degraded','quarantined')),
  unique (cycle_id, source_name, observed_at)
);
create index if not exists team_snapshots_cycle_observed_idx
  on game.team_snapshots (cycle_id, observed_at desc);
create index if not exists team_snapshots_fingerprint_idx
  on game.team_snapshots (cycle_id, fingerprint, observed_at desc);

create table if not exists research.signals (
  signal_id text primary key,
  job_id text,
  cycle_id text not null references game.cycles(cycle_id),
  player_element integer,
  claim_type text not null,
  claim_text text not null,
  source_url text not null,
  source_tier text not null,
  observed_at timestamptz not null,
  published_at timestamptz,
  expires_at timestamptz not null,
  confidence double precision not null check (confidence between 0 and 1),
  conflict_status text not null check (conflict_status in ('none','unresolved','resolved')),
  content_sha256 char(64) not null,
  unique (cycle_id, player_element, claim_type, source_url, content_sha256)
);
create index if not exists signals_cycle_observed_idx
  on research.signals (cycle_id, observed_at desc);

create table if not exists agent.intervention_runs (
  intervention_id text primary key,
  job_id text,
  cycle_id text not null references game.cycles(cycle_id),
  policy_version text not null,
  payload jsonb not null,
  payload_sha256 char(64) not null,
  rationale text not null,
  rationale_sha256 char(64) not null,
  created_at timestamptz not null
);
create index if not exists intervention_runs_cycle_created_idx
  on agent.intervention_runs (cycle_id, created_at desc);

create table if not exists agent.decision_runs (
  decision_id text primary key,
  job_id text,
  cycle_id text not null references game.cycles(cycle_id),
  revision integer not null check (revision >= 1),
  mode text not null,
  policy_version text not null,
  status text not null,
  expected_points double precision,
  chip text,
  fingerprint text,
  manifest_sha256 char(64),
  artifact_path text,
  created_at timestamptz not null,
  unique (cycle_id, revision)
);
create index if not exists decision_runs_job_idx on agent.decision_runs (job_id);

create table if not exists agent.decision_players (
  decision_id text not null references agent.decision_runs(decision_id) on delete cascade,
  element integer not null,
  squad_position integer not null check (squad_position between 1 and 15),
  role text not null check (role in ('starter','bench')),
  is_captain boolean not null default false,
  is_vice_captain boolean not null default false,
  transfer_direction text check (transfer_direction in ('in','out')),
  expected_points double precision,
  primary key (decision_id, element),
  unique (decision_id, squad_position)
);

create table if not exists agent.chip_strategy_runs (
  strategy_id text primary key,
  job_id text,
  cycle_id text not null references game.cycles(cycle_id),
  window_name text not null,
  policy_version text not null,
  inventory jsonb not null,
  recommended_chip text,
  status text not null,
  manifest_sha256 char(64),
  created_at timestamptz not null
);
create index if not exists chip_strategy_runs_cycle_created_idx
  on agent.chip_strategy_runs (cycle_id, created_at desc);

create table if not exists agent.chip_candidates (
  candidate_id text primary key,
  strategy_id text not null references agent.chip_strategy_runs(strategy_id) on delete cascade,
  chip text not null,
  gw integer not null check (gw between 1 and 38),
  expected_value double precision not null,
  p10 double precision,
  p50 double precision,
  p90 double precision,
  threshold double precision,
  schedule_confidence double precision
    check (schedule_confidence is null or schedule_confidence between 0 and 1),
  action text not null check (action in ('play','hold','blocked','unavailable')),
  reason text not null,
  unique (strategy_id, chip, gw)
);

create table if not exists agent.web_executions (
  execution_id text primary key,
  decision_id text not null references agent.decision_runs(decision_id),
  action_level text not null,
  envelope_sha256 char(64) not null,
  status text not null,
  started_at timestamptz,
  finished_at timestamptz,
  evidence_path text,
  evidence_sha256 char(64),
  error_code text,
  error_detail text,
  unique (decision_id, action_level)
);

create table if not exists agent.verification_checks (
  check_id text primary key,
  execution_id text not null references agent.web_executions(execution_id) on delete cascade,
  check_name text not null,
  expected jsonb not null,
  observed jsonb not null,
  passed boolean not null,
  checked_at timestamptz not null,
  unique (execution_id, check_name)
);

create table if not exists agent.legacy_agent_runs (
  run_id text primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  season text not null,
  mode text not null,
  policy text not null,
  horizon integer not null,
  seed integer not null,
  git_sha text,
  config jsonb,
  status text not null,
  total_points integer,
  notes text
);

create table if not exists agent.legacy_gw_decisions (
  run_id text not null references agent.legacy_agent_runs(run_id) on delete cascade,
  gw integer not null,
  state text not null,
  fingerprint text not null,
  squad_15 jsonb not null,
  starters jsonb not null,
  captain integer,
  vice_captain integer,
  bench_order jsonb,
  transfers_in jsonb,
  transfers_out jsonb,
  hits integer default 0,
  chip text,
  expected_points double precision,
  total_cost double precision,
  actual_points integer,
  captain_points integer,
  auto_subs jsonb,
  train_rows bigint,
  notes text,
  primary key (run_id, gw)
);

create table if not exists agent.legacy_benchmarks (
  run_id text not null references agent.legacy_agent_runs(run_id) on delete cascade,
  gw integer not null,
  baseline text not null,
  points integer not null,
  primary key (run_id, gw, baseline)
);
create index if not exists legacy_benchmarks_run_baseline_idx
  on agent.legacy_benchmarks (run_id, baseline);

create table if not exists agent.legacy_interventions (
  run_id text not null references agent.legacy_agent_runs(run_id) on delete cascade,
  gw integer not null,
  seq integer not null,
  author text not null,
  rationale text,
  payload jsonb not null,
  changed boolean,
  expected_delta double precision,
  realized_delta integer,
  points_with integer,
  points_without integer,
  detail jsonb,
  created_at timestamptz not null,
  primary key (run_id, gw, seq)
);

create table if not exists ops.runtime_controls (
  control_id bigint primary key,
  control_key text not null,
  value jsonb not null,
  effective_at timestamptz not null,
  actor text not null,
  reason text not null
);
create index if not exists runtime_controls_latest_idx
  on ops.runtime_controls (control_key, effective_at desc, control_id desc);

create table if not exists ops.sqlite_schema_migrations (
  version integer primary key,
  name text not null,
  checksum char(64) not null,
  applied_at timestamptz not null
);

create table if not exists ops.job_runs (
  job_id text primary key,
  idempotency_key text not null unique,
  correlation_id text not null,
  cycle_id text references game.cycles(cycle_id),
  job_type text not null,
  status text not null check (status in ('running','completed','degraded','failed','skipped')),
  attempt integer not null default 1 check (attempt >= 1),
  started_at timestamptz not null,
  finished_at timestamptz,
  input_sha256 char(64),
  output_sha256 char(64),
  metrics jsonb not null default '{}'::jsonb,
  error_code text,
  error_detail text
);
create index if not exists job_runs_type_started_idx
  on ops.job_runs (job_type, started_at desc);
create index if not exists job_runs_cycle_started_idx
  on ops.job_runs (cycle_id, started_at desc);

create table if not exists ops.job_steps (
  step_id text primary key,
  job_id text not null references ops.job_runs(job_id) on delete cascade,
  step_name text not null,
  attempt integer not null default 1 check (attempt >= 1),
  status text not null check (status in ('running','completed','degraded','failed','skipped')),
  started_at timestamptz not null,
  finished_at timestamptz,
  duration_ms integer,
  output_sha256 char(64),
  detail jsonb not null default '{}'::jsonb,
  error_code text,
  error_detail text,
  unique (job_id, step_name, attempt)
);

create table if not exists ops.health_samples (
  sample_id text primary key,
  observed_at timestamptz not null,
  service text not null,
  status text not null check (status in ('ok','degraded','down')),
  memory_available_bytes bigint,
  disk_free_bytes bigint,
  load_1m double precision,
  sqlite_version text not null,
  detail jsonb not null default '{}'::jsonb
);
create index if not exists health_samples_observed_idx
  on ops.health_samples (observed_at desc);

create table if not exists ops.audit_events (
  event_id text primary key,
  occurred_at timestamptz not null,
  severity text not null check (severity in ('debug','info','warning','error','critical')),
  event_type text not null,
  actor text not null,
  correlation_id text,
  cycle_id text references game.cycles(cycle_id),
  job_id text references ops.job_runs(job_id),
  subject_type text,
  subject_id text,
  payload jsonb not null default '{}'::jsonb,
  payload_sha256 char(64) not null
);
create index if not exists audit_events_time_idx on ops.audit_events (occurred_at desc);
create index if not exists audit_events_correlation_idx
  on ops.audit_events (correlation_id, occurred_at);

create table if not exists ops.incidents (
  incident_id text primary key,
  opened_at timestamptz not null,
  closed_at timestamptz,
  severity text not null check (severity in ('P0','P1','P2','P3')),
  status text not null check (status in ('open','acknowledged','resolved')),
  title text not null,
  owner text,
  correlation_id text,
  cycle_id text references game.cycles(cycle_id),
  job_id text references ops.job_runs(job_id),
  detail jsonb not null default '{}'::jsonb,
  resolution text
);
create index if not exists incidents_open_idx
  on ops.incidents (status, severity, opened_at desc);

create table if not exists ops.outbox_events (
  outbox_id text primary key,
  event_key text not null unique,
  created_at timestamptz not null,
  available_at timestamptz not null,
  event_type text not null,
  severity text not null,
  status text not null check (status in ('pending','sending','sent','acknowledged','dead')),
  attempts integer not null default 0 check (attempts >= 0),
  payload jsonb not null,
  sent_at timestamptz,
  acknowledged_at timestamptz,
  last_error text
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'source_snapshots_job_fkey') then
    alter table raw.source_snapshots add constraint source_snapshots_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'source_snapshots_cycle_fkey') then
    alter table raw.source_snapshots add constraint source_snapshots_cycle_fkey
      foreign key (cycle_id) references game.cycles(cycle_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'team_snapshots_job_fkey') then
    alter table game.team_snapshots add constraint team_snapshots_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'signals_job_fkey') then
    alter table research.signals add constraint signals_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'projection_runs_job_fkey') then
    alter table analytics.projection_runs add constraint projection_runs_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'projection_runs_cycle_fkey') then
    alter table analytics.projection_runs add constraint projection_runs_cycle_fkey
      foreign key (cycle_id) references game.cycles(cycle_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'intervention_runs_job_fkey') then
    alter table agent.intervention_runs add constraint intervention_runs_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'decision_runs_job_fkey') then
    alter table agent.decision_runs add constraint decision_runs_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'chip_strategy_runs_job_fkey') then
    alter table agent.chip_strategy_runs add constraint chip_strategy_runs_job_fkey
      foreign key (job_id) references ops.job_runs(job_id);
  end if;
end $$;

create index if not exists source_snapshots_job_idx on raw.source_snapshots (job_id);
create index if not exists team_snapshots_job_idx on game.team_snapshots (job_id);
create index if not exists signals_job_idx on research.signals (job_id);
create index if not exists projection_runs_job_idx on analytics.projection_runs (job_id);
create index if not exists intervention_runs_job_idx on agent.intervention_runs (job_id);
create index if not exists chip_strategy_runs_job_idx on agent.chip_strategy_runs (job_id);
create index if not exists audit_events_cycle_idx on ops.audit_events (cycle_id);
create index if not exists audit_events_job_idx on ops.audit_events (job_id);
create index if not exists incidents_cycle_idx on ops.incidents (cycle_id);
create index if not exists incidents_job_idx on ops.incidents (job_id);

do $$
begin
  execute format('grant connect on database %I to mova_app, mova_readonly', current_database());
end $$;
grant usage on schema mova_meta, raw, analytics, game, research, agent, ops
  to mova_app, mova_readonly;
grant select on all tables in schema mova_meta, raw, analytics, game, research, agent, ops
  to mova_readonly;
grant select, insert, update on all tables in schema
  mova_meta, raw, analytics, game, research, agent, ops to mova_app;
grant usage, select on all sequences in schema
  mova_meta, raw, analytics, game, research, agent, ops to mova_app;

alter default privileges in schema mova_meta, raw, analytics, game, research, agent, ops
  grant select on tables to mova_readonly;
alter default privileges in schema mova_meta, raw, analytics, game, research, agent, ops
  grant select, insert, update on tables to mova_app;
alter default privileges in schema mova_meta, raw, analytics, game, research, agent, ops
  grant usage, select on sequences to mova_app;

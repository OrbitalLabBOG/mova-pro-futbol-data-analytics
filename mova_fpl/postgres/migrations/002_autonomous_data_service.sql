-- Autonomous data service v1: append-only provenance plus queryable source data.

create table if not exists raw.ingestion_runs (
  run_id text primary key,
  job_id text,
  source_name text not null,
  status text not null check (status in ('running','completed','degraded','failed','skipped')),
  started_at timestamptz not null,
  finished_at timestamptz,
  artifact_path text,
  payload_sha256 char(64),
  manifest_sha256 char(64),
  quality jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  error_code text,
  error_detail text
);
create index if not exists ingestion_runs_source_started_idx
  on raw.ingestion_runs (source_name, started_at desc);

create table if not exists raw.source_cursors (
  source_name text primary key,
  last_attempt_at timestamptz,
  last_success_at timestamptz,
  last_payload_sha256 char(64),
  last_status text not null check (last_status in ('never','completed','degraded','failed')),
  consecutive_failures integer not null default 0 check (consecutive_failures >= 0),
  cadence_seconds integer not null check (cadence_seconds > 0),
  detail jsonb not null default '{}'::jsonb
);

create table if not exists raw.source_artifacts (
  artifact_id text primary key,
  run_id text not null references raw.ingestion_runs(run_id) on delete cascade,
  source_name text not null,
  season text not null,
  observed_at timestamptz not null,
  artifact_path text not null,
  payload_sha256 char(64) not null,
  manifest_sha256 char(64) not null,
  byte_count bigint not null check (byte_count >= 0),
  row_count bigint not null check (row_count >= 0),
  quality_status text not null check (quality_status in ('valid','degraded','quarantined')),
  quality jsonb not null,
  unique (source_name, payload_sha256)
);
create index if not exists source_artifacts_source_observed_idx
  on raw.source_artifacts (source_name, observed_at desc);

create table if not exists raw.quality_checks (
  check_id text primary key,
  run_id text not null references raw.ingestion_runs(run_id) on delete cascade,
  source_name text not null,
  check_name text not null,
  passed boolean not null,
  expected jsonb not null default '{}'::jsonb,
  observed jsonb not null default '{}'::jsonb,
  checked_at timestamptz not null default now(),
  unique (run_id, check_name)
);

create table if not exists analytics.fpl_player_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  element integer not null,
  player_code integer,
  team_id integer not null,
  element_type integer not null,
  web_name text not null,
  now_cost integer not null,
  status text,
  chance_next integer,
  selected_by_percent double precision,
  total_points integer,
  minutes integer,
  starts integer,
  form double precision,
  points_per_game double precision,
  expected_goals double precision,
  expected_assists double precision,
  expected_goal_involvements double precision,
  expected_goals_conceded double precision,
  news text,
  payload jsonb not null,
  primary key (artifact_id, element)
);
create index if not exists fpl_player_obs_element_time_idx
  on analytics.fpl_player_observations (element, observed_at desc);

create table if not exists analytics.fpl_fixture_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  fixture_id integer not null,
  event integer,
  kickoff_time timestamptz,
  team_h integer not null,
  team_a integer not null,
  team_h_score integer,
  team_a_score integer,
  started boolean,
  finished boolean,
  finished_provisional boolean,
  minutes integer,
  stats jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  primary key (artifact_id, fixture_id)
);
create index if not exists fpl_fixture_obs_fixture_time_idx
  on analytics.fpl_fixture_observations (fixture_id, observed_at desc);
create index if not exists fpl_fixture_obs_event_idx
  on analytics.fpl_fixture_observations (season, event, kickoff_time);

create table if not exists game.fpl_entry_observations (
  artifact_id text primary key references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  entry_id bigint not null,
  overall_points integer,
  overall_rank bigint,
  event_points integer,
  event_rank bigint,
  current_event integer,
  entry_payload jsonb not null,
  history_payload jsonb not null
);
create index if not exists fpl_entry_obs_entry_time_idx
  on game.fpl_entry_observations (entry_id, observed_at desc);

create table if not exists game.fpl_pick_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  entry_id bigint not null,
  event integer not null,
  element integer not null,
  position integer not null,
  multiplier integer not null,
  is_captain boolean not null,
  is_vice_captain boolean not null,
  selling_price integer,
  purchase_price integer,
  payload jsonb not null,
  primary key (artifact_id, event, element)
);

create table if not exists analytics.match_odds_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  match_key text not null,
  match_date date,
  kickoff_time time,
  home_team text not null,
  away_team text not null,
  full_time_home_goals integer,
  full_time_away_goals integer,
  full_time_result text,
  b365_home double precision,
  b365_draw double precision,
  b365_away double precision,
  b365_close_home double precision,
  b365_close_draw double precision,
  b365_close_away double precision,
  market_avg_home double precision,
  market_avg_draw double precision,
  market_avg_away double precision,
  market_avg_close_home double precision,
  market_avg_close_draw double precision,
  market_avg_close_away double precision,
  row_payload jsonb not null,
  primary key (artifact_id, match_key)
);
create index if not exists match_odds_match_time_idx
  on analytics.match_odds_observations (season, home_team, away_team, observed_at desc);

create table if not exists analytics.whoscored_schedule_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  ws_match_id bigint not null,
  kickoff_time timestamptz,
  home_team text,
  away_team text,
  status text,
  payload jsonb not null,
  primary key (artifact_id, ws_match_id)
);
create index if not exists ws_schedule_match_time_idx
  on analytics.whoscored_schedule_observations (ws_match_id, observed_at desc);

create table if not exists analytics.whoscored_matches (
  ws_match_id bigint primary key,
  season text not null,
  kickoff_time timestamptz,
  home_team text not null,
  away_team text not null,
  status_code integer not null,
  home_score integer,
  away_score integer,
  event_count integer not null check (event_count >= 0),
  typed_events integer not null check (typed_events >= 0),
  located_events integer not null check (located_events >= 0),
  artifact_id text not null references raw.source_artifacts(artifact_id),
  payload_sha256 char(64) not null,
  collected_at timestamptz not null
);
create index if not exists ws_matches_season_kickoff_idx
  on analytics.whoscored_matches (season, kickoff_time);

create table if not exists analytics.whoscored_events (
  ws_match_id bigint not null references analytics.whoscored_matches(ws_match_id) on delete cascade,
  ws_event_id bigint not null,
  event_id bigint not null,
  minute integer not null,
  second integer,
  expanded_minute integer,
  period text,
  event_type text,
  outcome text,
  team_id bigint,
  player_id bigint,
  x double precision,
  y double precision,
  end_x double precision,
  end_y double precision,
  is_touch boolean not null default false,
  is_shot boolean not null default false,
  is_goal boolean not null default false,
  related_event_id bigint,
  related_player_id bigint,
  qualifiers jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  primary key (ws_match_id, ws_event_id, event_id)
);
create index if not exists ws_events_player_idx
  on analytics.whoscored_events (player_id, ws_match_id);
create index if not exists ws_events_type_idx
  on analytics.whoscored_events (event_type, ws_match_id);

create or replace view ops.v_data_source_health as
select c.source_name, c.last_status, c.last_attempt_at, c.last_success_at,
       extract(epoch from (now() - c.last_success_at))::bigint as age_seconds,
       c.cadence_seconds, c.consecutive_failures,
       case
         when c.last_success_at is null then 'missing'
         when now() - c.last_success_at > make_interval(secs => c.cadence_seconds * 2)
           then 'stale'
         when c.last_status in ('failed','degraded') then c.last_status
         else 'healthy'
       end as health,
       c.detail
from raw.source_cursors c;

grant select on raw.ingestion_runs, raw.source_cursors, raw.source_artifacts,
  raw.quality_checks, analytics.fpl_player_observations,
  analytics.fpl_fixture_observations, analytics.match_odds_observations,
  analytics.whoscored_schedule_observations, analytics.whoscored_matches,
  analytics.whoscored_events, game.fpl_entry_observations,
  game.fpl_pick_observations, ops.v_data_source_health to mova_readonly;
grant select, insert, update on raw.ingestion_runs, raw.source_cursors,
  raw.source_artifacts, raw.quality_checks, analytics.fpl_player_observations,
  analytics.fpl_fixture_observations, analytics.match_odds_observations,
  analytics.whoscored_schedule_observations, analytics.whoscored_matches,
  analytics.whoscored_events, game.fpl_entry_observations,
  game.fpl_pick_observations to mova_app;

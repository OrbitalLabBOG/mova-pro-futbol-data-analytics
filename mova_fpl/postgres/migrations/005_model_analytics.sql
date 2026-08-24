-- Analytics observability: immutable projections and per-GW reconciliation.

create table if not exists analytics.fpl_event_live_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  event integer not null check (event between 1 and 38),
  element integer not null,
  total_points integer not null,
  minutes integer not null check (minutes >= 0),
  stats jsonb not null,
  explain jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  primary key (artifact_id,event,element)
);
create index if not exists fpl_event_live_event_time_idx
  on analytics.fpl_event_live_observations(season,event,observed_at desc);

create table if not exists analytics.model_projection_batches (
  batch_id text primary key,
  idempotency_key char(64) not null unique,
  season text not null,
  target_gw integer not null check (target_gw between 1 and 38),
  variant text not null,
  model_versions jsonb not null,
  cutoff_at timestamptz not null,
  generated_at timestamptz not null default now(),
  input_artifact_id text references raw.source_artifacts(artifact_id),
  input_manifest jsonb not null,
  player_count integer not null check (player_count >= 0),
  status text not null check (status in ('shadow','approved','superseded')),
  artifact_path text,
  artifact_sha256 char(64),
  unique(season,target_gw,variant,generated_at)
);
create index if not exists model_batches_target_idx
  on analytics.model_projection_batches(season,target_gw,variant,generated_at desc);

create table if not exists analytics.player_projections (
  batch_id text not null references analytics.model_projection_batches(batch_id)
    on delete cascade,
  element integer not null,
  fixture_id integer,
  player_name text not null,
  position text not null,
  team text not null,
  opponent_team integer,
  xp double precision not null,
  xp_sd double precision,
  p_play double precision check (p_play between 0 and 1),
  p_60 double precision check (p_60 between 0 and 1),
  components jsonb not null,
  context jsonb not null default '{}'::jsonb,
  primary key(batch_id,element)
);

create table if not exists analytics.model_evaluation_runs (
  evaluation_id text primary key,
  idempotency_key char(64) not null unique,
  batch_id text not null references analytics.model_projection_batches(batch_id),
  season text not null,
  gw integer not null check (gw between 1 and 38),
  variant text not null,
  evaluated_at timestamptz not null default now(),
  settlement_status text not null check (settlement_status in ('provisional','final')),
  sample_size integer not null check (sample_size >= 0),
  metrics jsonb not null,
  drift_status text not null check (drift_status in
    ('insufficient','healthy','watch','alert')),
  drift jsonb not null,
  actual_artifact_id text not null references raw.source_artifacts(artifact_id),
  unique(batch_id,actual_artifact_id,settlement_status)
);
create index if not exists model_evaluations_gw_idx
  on analytics.model_evaluation_runs(season,gw,variant,evaluated_at desc);

create table if not exists analytics.model_evaluation_components (
  evaluation_id text not null references analytics.model_evaluation_runs(evaluation_id)
    on delete cascade,
  component text not null,
  predicted_total double precision not null,
  actual_total double precision not null,
  bias double precision not null,
  relative_bias double precision,
  mae double precision not null,
  primary key(evaluation_id,component)
);

create or replace view analytics.v_model_latest_scorecard as
select distinct on(season,gw,variant) evaluation_id,batch_id,season,gw,variant,
  evaluated_at,settlement_status,sample_size,metrics,drift_status,drift
from analytics.model_evaluation_runs
order by season,gw,variant,evaluated_at desc;

grant select on analytics.fpl_event_live_observations,
  analytics.model_projection_batches,analytics.player_projections,
  analytics.model_evaluation_runs,analytics.model_evaluation_components,
  analytics.v_model_latest_scorecard to mova_readonly;
grant select,insert,update on analytics.fpl_event_live_observations,
  analytics.model_projection_batches,analytics.player_projections,
  analytics.model_evaluation_runs,analytics.model_evaluation_components to mova_app;

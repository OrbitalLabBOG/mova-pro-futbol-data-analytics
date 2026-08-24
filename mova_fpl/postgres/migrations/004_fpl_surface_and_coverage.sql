-- Normaliza la superficie estratégica del bootstrap FPL para consulta del harness.

create table if not exists analytics.fpl_team_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  team_id integer not null,
  name text not null,
  short_name text not null,
  strength integer,
  payload jsonb not null,
  primary key (artifact_id, team_id)
);
create index if not exists fpl_team_obs_team_time_idx
  on analytics.fpl_team_observations (team_id, observed_at desc);

create table if not exists analytics.fpl_event_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  season text not null,
  observed_at timestamptz not null,
  event_id integer not null,
  name text not null,
  deadline_time timestamptz not null,
  finished boolean not null default false,
  data_checked boolean not null default false,
  is_previous boolean not null default false,
  is_current boolean not null default false,
  is_next boolean not null default false,
  payload jsonb not null,
  primary key (artifact_id, event_id)
);
create index if not exists fpl_event_obs_deadline_idx
  on analytics.fpl_event_observations (season, deadline_time, observed_at desc);

grant select on analytics.fpl_team_observations,
  analytics.fpl_event_observations to mova_readonly;
grant select, insert, update on analytics.fpl_team_observations,
  analytics.fpl_event_observations to mova_app;

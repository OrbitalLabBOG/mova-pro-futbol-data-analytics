-- The Odds API snapshots: preserve every bookmaker, market, outcome and line.

create table if not exists analytics.market_odds_observations (
  artifact_id text not null references raw.source_artifacts(artifact_id),
  observation_key char(64) not null,
  provider text not null,
  provider_event_id text not null,
  season text not null,
  observed_at timestamptz not null,
  sport_key text not null,
  commence_time timestamptz not null,
  home_team text not null,
  away_team text not null,
  bookmaker_key text not null,
  bookmaker_title text not null,
  bookmaker_last_update timestamptz,
  market_key text not null check (market_key in ('h2h','totals')),
  market_last_update timestamptz,
  outcome_name text not null,
  outcome_description text,
  price numeric(12,6) not null check (price > 1),
  point numeric(12,4),
  row_payload jsonb not null,
  primary key (artifact_id, observation_key)
);

create index if not exists market_odds_event_observed_idx
  on analytics.market_odds_observations
  (season, provider_event_id, observed_at desc);
create index if not exists market_odds_fixture_observed_idx
  on analytics.market_odds_observations
  (season, home_team, away_team, commence_time, observed_at desc);
create index if not exists market_odds_book_market_idx
  on analytics.market_odds_observations
  (bookmaker_key, market_key, observed_at desc);

-- Conserva la última observación operativa del adapter retirado, pero cambia
-- su identidad lógica para que health no mantenga una fuente fantasma.
insert into raw.source_cursors(
  source_name,last_attempt_at,last_success_at,last_payload_sha256,last_status,
  consecutive_failures,cadence_seconds,detail
)
select 'market_odds',last_attempt_at,last_success_at,last_payload_sha256,last_status,
       consecutive_failures,28800,detail || '{"migrated_from":"football_data_odds"}'::jsonb
from raw.source_cursors where source_name='football_data_odds'
on conflict(source_name) do nothing;
delete from raw.source_cursors where source_name='football_data_odds';

grant select on analytics.market_odds_observations to mova_readonly;
grant select, insert, update on analytics.market_odds_observations to mova_app;

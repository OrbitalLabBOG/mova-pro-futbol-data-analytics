-- Post-settlement memory. SQLite remains the control-plane writer; shadow import mirrors it.

create table if not exists game.gameweek_settlements (
  settlement_id text primary key,
  idempotency_key text not null unique,
  job_id text not null references ops.job_runs(job_id),
  cycle_id text not null references game.cycles(cycle_id),
  source_artifact_id text not null,
  settled_at timestamptz not null,
  entry_points integer not null,
  entry_rank bigint,
  average_points integer,
  bench_points integer not null check (bench_points >= 0),
  hit_cost integer not null default 0 check (hit_cost >= 0),
  captain_points integer not null,
  auto_subs jsonb not null default '[]'::jsonb,
  official jsonb not null,
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  unique (cycle_id, source_artifact_id)
);
create index if not exists gameweek_settlements_cycle_idx
  on game.gameweek_settlements(cycle_id, settled_at desc);

create table if not exists agent.gw_reviews (
  review_id text primary key,
  job_id text not null references ops.job_runs(job_id),
  settlement_id text not null references game.gameweek_settlements(settlement_id),
  decision_id text not null references agent.decision_runs(decision_id),
  review_type text not null check (review_type in ('causal','retrospective')),
  causality_status text not null check (causality_status in
    ('eligible','not_eligible_no_predeadline_batch','paired_intervention')),
  expected_points double precision not null,
  actual_points integer not null,
  comparator_label text,
  comparator_expected_points double precision,
  comparator_actual_points integer,
  realized_delta integer,
  metrics jsonb not null,
  findings jsonb not null,
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  created_at timestamptz not null,
  unique (settlement_id, review_type)
);
create index if not exists gw_reviews_settlement_idx
  on agent.gw_reviews(settlement_id, created_at desc);

create table if not exists agent.gw_review_player_outcomes (
  review_id text not null references agent.gw_reviews(review_id) on delete cascade,
  scenario text not null check (scenario in ('selected','comparator')),
  element integer not null,
  player_name text not null,
  role text not null check (role in ('starter','bench')),
  is_captain boolean not null default false,
  expected_points double precision not null,
  p60 double precision check (p60 is null or p60 between 0 and 1),
  actual_points integer not null,
  minutes integer not null check (minutes >= 0),
  effective_points integer not null,
  primary key (review_id, scenario, element)
);

create table if not exists agent.change_proposals (
  proposal_id text primary key,
  review_id text not null references agent.gw_reviews(review_id) on delete cascade,
  category text not null check (category in
    ('data','model','optimizer','research','strategy','execution','variance')),
  change_level text not null check (change_level in ('C0','C1','C2','C3')),
  priority text not null check (priority in ('P0','P1','P2','P3')),
  title text not null,
  hypothesis text not null,
  evidence jsonb not null,
  acceptance jsonb not null,
  status text not null check (status in ('proposed','testing','accepted','rejected')),
  created_at timestamptz not null,
  unique (review_id, title)
);

grant select on game.gameweek_settlements, agent.gw_reviews,
  agent.gw_review_player_outcomes, agent.change_proposals to mova_readonly;
grant select,insert,update on game.gameweek_settlements, agent.gw_reviews,
  agent.gw_review_player_outcomes, agent.change_proposals to mova_app;

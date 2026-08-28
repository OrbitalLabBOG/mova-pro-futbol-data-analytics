-- Mirror read model for HV1-06A. SQLite remains the operational writer.

create table if not exists agent.cycle_manifests (
  manifest_id text primary key,
  cycle_id text not null references game.cycles(cycle_id),
  revision integer not null check (revision >= 1),
  as_of_at timestamptz not null,
  deadline_at timestamptz not null,
  phase text not null,
  team_state_id text,
  plan_id text,
  source_manifest jsonb not null,
  analytics_manifest jsonb not null,
  research_summary jsonb not null,
  artifact_path text not null,
  content_sha256 char(64) not null,
  created_at timestamptz not null,
  unique (cycle_id, revision),
  unique (cycle_id, content_sha256)
);

create table if not exists agent.decision_envelopes (
  envelope_id text primary key,
  job_id text references ops.job_runs(job_id),
  cycle_id text not null references game.cycles(cycle_id),
  decision_id text not null unique references agent.decision_runs(decision_id) on delete cascade,
  manifest_id text not null references agent.cycle_manifests(manifest_id),
  schema_version text not null,
  policy_version text not null,
  status text not null check (status in ('blocked','staged','superseded')),
  selected_candidate_key text not null,
  content_sha256 char(64) not null unique,
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  created_at timestamptz not null
);
create index if not exists decision_envelopes_cycle_created_idx
  on agent.decision_envelopes(cycle_id, created_at desc);

create table if not exists agent.decision_candidates (
  envelope_id text not null references agent.decision_envelopes(envelope_id) on delete cascade,
  candidate_key text not null,
  label text not null,
  selected boolean not null,
  decision jsonb not null,
  fingerprint text not null,
  expected_points double precision not null,
  primary key (envelope_id, candidate_key)
);

create table if not exists agent.decision_validation_checks (
  check_id text primary key,
  envelope_id text not null references agent.decision_envelopes(envelope_id) on delete cascade,
  code text not null,
  severity text not null check (severity in ('info','warning','block')),
  passed boolean not null,
  summary text not null,
  detail jsonb not null,
  created_at timestamptz not null,
  unique (envelope_id, code)
);

grant select on agent.cycle_manifests, agent.decision_envelopes, agent.decision_candidates,
  agent.decision_validation_checks to mova_readonly;
grant select,insert,update on agent.cycle_manifests, agent.decision_envelopes, agent.decision_candidates,
  agent.decision_validation_checks to mova_app;

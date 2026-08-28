-- Shadow mirror for HV1-06B. SQLite remains the operational writer.

create table if not exists agent.decision_deliberations (
  deliberation_id text primary key,
  cycle_id text not null references game.cycles(cycle_id),
  envelope_id text not null unique references agent.decision_envelopes(envelope_id)
    on delete cascade,
  manifest_id text not null references agent.cycle_manifests(manifest_id),
  provider text not null,
  status text not null check (status in (
    'queued','running','completed','accepted','review_required','blocked','rejected','failed')),
  request_path text not null,
  request_sha256 text not null unique,
  result_path text,
  result_sha256 text,
  preferred_candidate_key text,
  critic_verdict text check (critic_verdict is null or critic_verdict in (
    'accept','revise','block')),
  strategist jsonb,
  critic jsonb,
  intervention jsonb,
  intervention_sha256 text,
  usage jsonb not null default '{}'::jsonb,
  error_code text,
  error_detail text,
  queued_at timestamptz not null,
  finished_at timestamptz,
  imported_at timestamptz
);

create index if not exists decision_deliberations_cycle_queued_idx
  on agent.decision_deliberations(cycle_id, queued_at desc);

create table if not exists agent.decision_deliberation_risks (
  risk_id text primary key,
  deliberation_id text not null references agent.decision_deliberations(deliberation_id)
    on delete cascade,
  code text not null,
  severity text not null check (severity in ('info','warning','block')),
  candidate_key text,
  claim text not null,
  mitigation text not null,
  created_at timestamptz not null,
  unique (deliberation_id, code)
);


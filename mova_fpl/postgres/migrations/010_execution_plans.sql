-- Shadow mirror for HV1-07A/B. SQLite remains the operational writer.

create table if not exists agent.execution_plans (
  plan_id text primary key,
  cycle_id text not null references game.cycles(cycle_id),
  envelope_id text not null references agent.decision_envelopes(envelope_id),
  decision_id text not null,
  policy_version text not null,
  risk_class text not null check (risk_class in ('R0','R2','R3')),
  required_action_level text not null check (required_action_level in ('A0','A2','A3')),
  status text not null check (status in ('blocked','authorized','noop','superseded')),
  idempotency_key text not null unique,
  content_sha256 char(64) not null unique,
  artifact_path text not null,
  artifact_sha256 char(64) not null,
  expected_pre_fingerprint text,
  expected_post_fingerprint text not null,
  deadline_at timestamptz not null,
  created_at timestamptz not null
);

create index if not exists execution_plans_cycle_created_idx
  on agent.execution_plans(cycle_id, created_at desc);

create table if not exists agent.execution_preflight_checks (
  check_id text primary key,
  plan_id text not null references agent.execution_plans(plan_id) on delete cascade,
  code text not null,
  severity text not null check (severity = 'block'),
  passed boolean not null,
  summary text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null,
  unique (plan_id, code)
);

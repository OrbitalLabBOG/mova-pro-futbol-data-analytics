-- Apply-once executor ledger. SQLite remains the only operational writer.

create table if not exists agent.execution_attempts (
  execution_id text primary key,
  plan_id text not null unique references agent.execution_plans(plan_id),
  job_id text not null unique references ops.job_runs(job_id),
  idempotency_key text not null unique,
  adapter text not null check (adapter in ('disabled','fixture','browser')),
  command_path text not null,
  command_sha256 char(64) not null,
  status text not null check (status in (
    'prepared','claimed','applying','ambiguous','verified','failed','blocked','expired'
  )),
  claim_token_sha256 char(64) unique,
  claimed_by text,
  claimed_at timestamptz,
  lease_expires_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  expected_pre_fingerprint text,
  observed_pre_fingerprint text,
  expected_post_fingerprint text not null,
  observed_post_fingerprint text,
  evidence_path text,
  evidence_sha256 char(64),
  result_sha256 char(64),
  error_code text,
  error_detail text,
  created_at timestamptz not null
);

create index if not exists execution_attempts_status_created_idx
  on agent.execution_attempts(status, created_at desc);

create table if not exists agent.execution_attempt_events (
  attempt_event_id text primary key,
  execution_id text not null references agent.execution_attempts(execution_id) on delete cascade,
  sequence integer not null check (sequence >= 1),
  from_status text,
  to_status text not null,
  actor text not null,
  reason text not null,
  detail jsonb not null default '{}'::jsonb,
  detail_sha256 char(64) not null,
  occurred_at timestamptz not null,
  unique (execution_id, sequence)
);

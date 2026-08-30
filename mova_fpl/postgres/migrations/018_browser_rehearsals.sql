-- Durable browser rehearsal evidence. SQLite remains the sole operational writer.

create table if not exists agent.browser_rehearsals (
  rehearsal_id text primary key,
  cycle_id text not null references game.cycles(cycle_id),
  capability text not null check (capability in ('captaincy','lineup','r3')),
  contract_version text not null,
  evidence_mode text not null check (evidence_mode in ('read_only_probe','validate_only')),
  status text not null check (status in ('passed','failed')),
  writes_attempted boolean not null check (writes_attempted = false),
  checks jsonb not null,
  evidence_path text not null,
  evidence_sha256 char(64) not null,
  content_sha256 char(64) not null unique,
  idempotency_key text not null unique,
  actor text not null,
  reason text not null,
  observed_at timestamptz not null,
  created_at timestamptz not null
);

create unique index if not exists browser_rehearsal_pass_once_idx
  on agent.browser_rehearsals(cycle_id, capability, contract_version)
  where status = 'passed';
create index if not exists browser_rehearsal_capability_time_idx
  on agent.browser_rehearsals(capability, contract_version, observed_at desc);

grant select on agent.browser_rehearsals to mova_readonly;
grant select,insert,update on agent.browser_rehearsals to mova_app;

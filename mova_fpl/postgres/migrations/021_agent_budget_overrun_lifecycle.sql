-- Review lifecycle for per-job agent budget overruns; SQLite remains authority.

create table if not exists agent.budget_overrun_events (
  event_id text primary key,
  reservation_id text not null references agent.budget_reservations(reservation_id),
  sequence integer not null check (sequence >= 1),
  from_status text check (from_status is null or from_status in ('open','reviewed')),
  to_status text not null check (to_status in ('reviewed','resolved','waived')),
  action text not null check (action in (
    'optimize_prompt','reduce_scope','adjust_limit','verified_followup','accept_variance')),
  followup_reservation_id text references agent.budget_reservations(reservation_id),
  actual_tokens integer not null check (actual_tokens > 0),
  job_limit integer not null check (job_limit > 0),
  excess_tokens integer not null check (excess_tokens > 0),
  evidence jsonb not null,
  evidence_sha256 text not null check (length(evidence_sha256) = 64),
  idempotency_key text not null unique,
  actor text not null,
  reason text not null,
  created_at timestamptz not null,
  unique (reservation_id, sequence)
);
create index if not exists budget_overrun_events_reservation_idx
  on agent.budget_overrun_events(reservation_id, sequence desc);

grant select on agent.budget_overrun_events to mova_readonly;
grant select,insert,update on agent.budget_overrun_events to mova_app;

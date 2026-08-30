-- Ledger de inferencia y reservas fail-closed; SQLite conserva autoridad.

create table if not exists agent.cost_ledger (
  cost_id text primary key,
  research_run_id text,
  provider text not null,
  model text,
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  estimated_cost_usd double precision
    check (estimated_cost_usd is null or estimated_cost_usd >= 0),
  subscription_usage boolean not null default false,
  detail jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null,
  cycle_id text references game.cycles(cycle_id),
  subject_type text check (subject_type is null or subject_type in ('research','deliberation')),
  subject_id text,
  category text,
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  search_requests integer check (search_requests is null or search_requests >= 0)
);
create unique index if not exists cost_ledger_subject_idx
  on agent.cost_ledger(subject_type, subject_id) where subject_id is not null;
create index if not exists cost_ledger_cycle_occurred_idx
  on agent.cost_ledger(cycle_id, occurred_at desc);

create table if not exists agent.budget_reservations (
  reservation_id text primary key,
  cycle_id text not null references game.cycles(cycle_id),
  subject_type text not null check (subject_type in ('research','deliberation')),
  subject_id text not null unique,
  provider text not null,
  reserved_tokens integer not null check (reserved_tokens > 0),
  actual_tokens integer check (actual_tokens is null or actual_tokens >= 0),
  status text not null check (status in ('reserved','charged','settled','released')),
  policy jsonb not null,
  created_at timestamptz not null,
  settled_at timestamptz,
  released_at timestamptz
);
create index if not exists budget_reservations_cycle_status_idx
  on agent.budget_reservations(cycle_id, status, created_at desc);

grant select on agent.cost_ledger, agent.budget_reservations to mova_readonly;
grant select,insert,update on agent.cost_ledger, agent.budget_reservations to mova_app;

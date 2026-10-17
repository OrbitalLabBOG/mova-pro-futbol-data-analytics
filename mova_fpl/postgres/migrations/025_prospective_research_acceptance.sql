-- SQLite remains the writer. Mirror preregistration and deterministic run binding.
create table if not exists research.acceptance_cohorts (
  cohort_id text primary key,
  idempotency_key text not null unique,
  manifest jsonb not null,
  manifest_sha256 text not null check(length(manifest_sha256)=64),
  registered_at timestamptz not null,
  actor text not null,
  reason text not null
);
create table if not exists research.acceptance_slots (
  cohort_id text not null references research.acceptance_cohorts(cohort_id),
  cycle_id text not null,
  research_run_id text not null unique references research.runs(research_run_id),
  contract_sha256 text not null,
  bound_at timestamptz not null,
  primary key(cohort_id,cycle_id)
);
grant select on research.acceptance_cohorts, research.acceptance_slots to mova_readonly;
grant select,insert,update on research.acceptance_cohorts, research.acceptance_slots to mova_app;

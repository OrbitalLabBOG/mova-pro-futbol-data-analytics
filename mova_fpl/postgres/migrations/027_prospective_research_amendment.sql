-- Shadow projection only; immutable originals remain in the SQLite writer.
create table if not exists research.acceptance_amendments (
  amendment_id text primary key,
  cohort_id text not null unique references research.acceptance_cohorts(cohort_id),
  idempotency_key text not null unique,
  request jsonb not null,
  request_sha256 char(64) not null,
  manifest jsonb not null,
  manifest_sha256 char(64) not null,
  registered_at timestamptz not null,
  actor text not null,
  reason text not null
);
grant select on research.acceptance_amendments to mova_readonly;
grant select,insert,update on research.acceptance_amendments to mova_app;

-- Align the PostgreSQL shadow with SQLite migration 005. The strategic
-- research workflow remains SQLite-authored; PostgreSQL only mirrors it.

alter table research.signals
  add column if not exists research_run_id text,
  add column if not exists subject_name text,
  add column if not exists direction text
    check (direction is null or direction in ('positive','negative','neutral','uncertain')),
  add column if not exists validation_status text
    check (validation_status is null or validation_status in ('accepted','candidate','rejected')),
  add column if not exists evidence jsonb;

grant select on research.signals to mova_readonly;
grant select,insert,update on research.signals to mova_app;

-- Complete SQLite -> PostgreSQL shadow provenance for execution plans.

alter table agent.execution_plans
  add column if not exists job_id text references ops.job_runs(job_id);

create unique index if not exists execution_plans_job_id_idx
  on agent.execution_plans(job_id)
  where job_id is not null;

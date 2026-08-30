-- Longitudinal strategic memory embedded in each immutable cycle manifest.

alter table agent.cycle_manifests
  add column if not exists memory_summary jsonb not null default '{}'::jsonb;

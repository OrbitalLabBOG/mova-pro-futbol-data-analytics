-- Mirror sealed research runs, source documents and conflicts from SQLite.
-- PostgreSQL remains read-only shadow; SQLite is still the sole writer.

create table if not exists research.runs (
  research_run_id text primary key,
  job_id text,
  cycle_id text not null,
  manifest_id text not null,
  provider text not null,
  status text not null,
  request_path text not null,
  request_sha256 text not null,
  result_path text,
  result_sha256 text,
  usage jsonb not null default '{}'::jsonb,
  error_code text,
  error_detail text,
  queued_at timestamptz not null,
  started_at timestamptz,
  finished_at timestamptz,
  imported_at timestamptz,
  result_schema text not null,
  coverage jsonb not null default '{}'::jsonb,
  coverage_status text not null,
  coverage_ratio double precision check (coverage_ratio is null or coverage_ratio between 0 and 1),
  evidence_ratio double precision check (evidence_ratio is null or evidence_ratio between 0 and 1)
);
create index if not exists research_runs_cycle_queued_idx
  on research.runs(cycle_id, queued_at desc);

create table if not exists research.documents (
  document_id text primary key,
  research_run_id text not null references research.runs(research_run_id) on delete cascade,
  source_url text not null,
  title text not null,
  publisher text not null,
  published_at timestamptz,
  observed_at timestamptz not null,
  source_tier text not null,
  content_sha256 text not null,
  final_url text,
  fetch_status text not null,
  http_status integer,
  content_type text,
  body_sha256 text,
  normalized_sha256 text,
  storage_mode text,
  locator_type text,
  locator text,
  excerpt text,
  excerpt_sha256 text,
  artifact_path text,
  artifact_sha256 text,
  fetch_error_code text,
  unique(research_run_id, source_url)
);

create table if not exists research.conflicts (
  conflict_id text primary key,
  research_run_id text not null references research.runs(research_run_id) on delete cascade,
  cycle_id text not null,
  subject text not null,
  claim_type text not null,
  description text not null,
  source_urls jsonb not null,
  status text not null,
  created_at timestamptz not null
);

grant select on research.runs, research.documents, research.conflicts to mova_readonly;
grant select,insert,update on research.runs, research.documents, research.conflicts to mova_app;

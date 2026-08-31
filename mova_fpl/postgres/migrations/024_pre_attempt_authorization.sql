-- Permiso durable host -> worker antes de cada ejecución física.

create table if not exists agent.attempt_authorizations (
  authorization_id text primary key,
  subject_type text not null check (subject_type in ('research','deliberation')),
  subject_id text not null,
  request_sha256 text not null check (length(request_sha256) = 64),
  attempt_number integer not null check (attempt_number between 1 and 2),
  status text not null check (status in ('preparing','authorized','started','finished','expired')),
  budget_snapshot_json jsonb not null,
  deadline_at timestamptz not null,
  expires_at timestamptz not null,
  permit_path text not null,
  permit_sha256 text check (permit_sha256 is null or length(permit_sha256) = 64),
  attempt_id text,
  created_at timestamptz not null,
  started_at timestamptz,
  finished_at timestamptz,
  unique (subject_id, authorization_id)
);
create index if not exists attempt_authorization_subject_idx
  on agent.attempt_authorizations(subject_type,subject_id,created_at desc);

alter table agent.worker_attempt_events
  add column if not exists authorization_id text;
create index if not exists worker_attempt_authorization_idx
  on agent.worker_attempt_events(authorization_id,event_type);

grant select on agent.attempt_authorizations to mova_readonly;
grant select,insert,update,delete on agent.attempt_authorizations to mova_app;

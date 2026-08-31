-- Recibos append-only del worker aislado; SQLite conserva autoridad.

create table if not exists agent.worker_attempt_events (
  event_id text primary key,
  attempt_id text not null,
  subject_type text not null check (subject_type in ('research','deliberation')),
  subject_id text not null,
  request_sha256 text not null check (length(request_sha256) = 64),
  event_type text not null check (event_type in ('started','finished')),
  status text not null check (status in ('running','succeeded','failed')),
  model text not null,
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  error_code text,
  output_present boolean,
  receipt_path text not null,
  receipt_sha256 text not null check (length(receipt_sha256) = 64),
  occurred_at timestamptz not null,
  unique (attempt_id, event_type),
  check ((event_type='started' and status='running') or event_type='finished'),
  check ((status='failed' and error_code is not null) or status!='failed')
);
create index if not exists worker_attempt_subject_idx
  on agent.worker_attempt_events(subject_type, subject_id, occurred_at desc);

grant select on agent.worker_attempt_events to mova_readonly;
grant select,insert,update,delete on agent.worker_attempt_events to mova_app;

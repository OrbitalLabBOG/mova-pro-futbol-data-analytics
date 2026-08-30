-- Evaluaciones y lecciones promovidas; SQLite conserva autoridad de escritura.

create table if not exists agent.change_proposal_evaluations (
  evaluation_id text primary key,
  proposal_id text not null references agent.change_proposals(proposal_id) on delete cascade,
  idempotency_key text not null unique,
  from_status text not null check (from_status in
    ('proposed','testing','accepted','rejected')),
  to_status text not null check (to_status in ('testing','accepted','rejected')),
  evidence jsonb not null,
  evidence_sha256 char(64) not null,
  actor text not null,
  reason text not null,
  created_at timestamptz not null
);
create index if not exists change_proposal_evaluations_proposal_created_idx
  on agent.change_proposal_evaluations(proposal_id, created_at desc);

create table if not exists agent.lessons (
  lesson_id text primary key,
  proposal_id text not null unique references agent.change_proposals(proposal_id),
  review_id text not null references agent.gw_reviews(review_id),
  category text not null,
  statement text not null,
  evidence jsonb not null,
  status text not null check (status in ('validated','retired')),
  created_at timestamptz not null,
  retired_at timestamptz
);
create index if not exists lessons_status_created_idx
  on agent.lessons(status, created_at desc);

grant select on agent.change_proposal_evaluations, agent.lessons to mova_readonly;
grant select,insert,update on agent.change_proposal_evaluations, agent.lessons to mova_app;

-- Controlled model-bundle releases mirrored from the SQLite writer.

create table if not exists agent.model_bundle_releases (
  release_id text primary key,
  proposal_id text not null unique references agent.change_proposals(proposal_id),
  prepare_idempotency_key text not null unique,
  candidate_manifest jsonb not null,
  baseline_manifest jsonb not null,
  promotion_policy jsonb not null,
  status text not null check (status in
    ('prepared','shadow','promoted','superseded','rolled_back')),
  content_sha256 char(64) not null check (length(content_sha256) = 64),
  created_at timestamptz not null,
  updated_at timestamptz not null
);
create unique index if not exists model_bundle_single_shadow_idx
  on agent.model_bundle_releases ((true)) where status='shadow';
create unique index if not exists model_bundle_single_promoted_idx
  on agent.model_bundle_releases ((true)) where status='promoted';

create table if not exists agent.model_bundle_release_events (
  release_event_id text primary key,
  release_id text not null references agent.model_bundle_releases(release_id)
    on delete cascade,
  sequence integer not null check (sequence >= 1),
  idempotency_key text not null unique,
  from_status text check (from_status is null or from_status in
    ('prepared','shadow','promoted','superseded','rolled_back')),
  to_status text not null check (to_status in
    ('prepared','shadow','promoted','superseded','rolled_back')),
  actor text not null,
  reason text not null,
  evidence jsonb not null,
  evidence_sha256 char(64) not null check (length(evidence_sha256) = 64),
  occurred_at timestamptz not null,
  unique (release_id, sequence)
);
create index if not exists model_bundle_events_release_time_idx
  on agent.model_bundle_release_events(release_id,occurred_at desc);

grant select on agent.model_bundle_releases, agent.model_bundle_release_events
  to mova_readonly;
grant select,insert,update on agent.model_bundle_releases,
  agent.model_bundle_release_events to mova_app;

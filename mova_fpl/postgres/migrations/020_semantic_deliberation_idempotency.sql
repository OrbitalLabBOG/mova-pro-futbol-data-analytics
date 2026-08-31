alter table agent.decision_deliberations
  add column if not exists semantic_input_sha256 text;

create unique index if not exists decision_deliberations_semantic_once_idx
  on agent.decision_deliberations(cycle_id, provider, semantic_input_sha256)
  where semantic_input_sha256 is not null;

create table if not exists agent.decision_deliberation_bindings (
  envelope_id text primary key references agent.decision_envelopes(envelope_id)
    on delete cascade,
  deliberation_id text not null references agent.decision_deliberations(deliberation_id)
    on delete cascade,
  semantic_input_sha256 text not null,
  binding_type text not null check (binding_type in ('original','semantic_reuse')),
  created_at timestamptz not null
);

create index if not exists decision_deliberation_bindings_deliberation_idx
  on agent.decision_deliberation_bindings(deliberation_id, created_at desc);

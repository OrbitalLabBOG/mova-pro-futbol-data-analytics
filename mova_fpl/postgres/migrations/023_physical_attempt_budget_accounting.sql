-- Contabilidad del presupuesto por ejecución física, no sólo por subject lógico.

alter table agent.budget_reservations
  add column if not exists accounting_mode text
    check (accounting_mode is null or accounting_mode in ('exact','conservative','legacy'));
alter table agent.budget_reservations
  add column if not exists attempt_count integer
    check (attempt_count is null or attempt_count >= 1);
alter table agent.budget_reservations
  add column if not exists estimated_tokens bigint
    check (estimated_tokens is null or estimated_tokens >= 0);

update agent.budget_reservations
set accounting_mode = case
      when status='charged' then 'conservative'
      when status='settled' then 'legacy'
    end,
    attempt_count = case when status in ('charged','settled') then 1 end,
    estimated_tokens = case
      when status='charged' then reserved_tokens
      when status='settled' then 0
    end
where accounting_mode is null;

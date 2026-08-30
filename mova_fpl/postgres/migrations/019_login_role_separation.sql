do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'mova_app_runtime') then
    create role mova_app_runtime login inherit nosuperuser nocreatedb nocreaterole
      noreplication connection limit 8;
  else
    alter role mova_app_runtime login inherit nosuperuser nocreatedb nocreaterole
      noreplication connection limit 8;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'mova_readonly_runtime') then
    create role mova_readonly_runtime login inherit nosuperuser nocreatedb nocreaterole
      noreplication connection limit 4;
  else
    alter role mova_readonly_runtime login inherit nosuperuser nocreatedb nocreaterole
      noreplication connection limit 4;
  end if;
  execute format(
    'revoke temporary on database %I from public', current_database()
  );
  execute format(
    'grant connect on database %I to mova_app_runtime, mova_readonly_runtime',
    current_database()
  );
end $$;

grant mova_app to mova_app_runtime;
grant mova_readonly to mova_readonly_runtime;
revoke mova_app from mova_readonly_runtime;

alter role mova_app_runtime set statement_timeout = '15s';
alter role mova_app_runtime set lock_timeout = '3s';
alter role mova_app_runtime set idle_in_transaction_session_timeout = '30s';
alter role mova_readonly_runtime set default_transaction_read_only = on;
alter role mova_readonly_runtime set statement_timeout = '15s';
alter role mova_readonly_runtime set lock_timeout = '3s';
alter role mova_readonly_runtime set idle_in_transaction_session_timeout = '30s';

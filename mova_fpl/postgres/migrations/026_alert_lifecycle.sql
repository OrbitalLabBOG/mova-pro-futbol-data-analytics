-- Mirror the SQLite writer's terminal obsolete-notification state.
alter table ops.outbox_events drop constraint outbox_events_status_check;
alter table ops.outbox_events add constraint outbox_events_status_check
  check(status in ('pending','sending','sent','acknowledged','dead','superseded'));

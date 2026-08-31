alter table runs
  add column if not exists cancellation_requested_at timestamptz,
  add column if not exists cancellation_reason text,
  add column if not exists cancelled_by uuid references users(id) on delete restrict;

alter table tasks
  drop constraint if exists tasks_status_check;

alter table tasks
  add constraint tasks_status_check
  check (
    status in (
      'pending',
      'ready',
      'running',
      'waiting_approval',
      'retry_wait',
      'succeeded',
      'failed',
      'cancelled'
    )
  );

alter table tasks
  add column if not exists next_retry_at timestamptz,
  add column if not exists last_error_type text,
  add column if not exists last_error_message text;

alter table task_attempts
  drop constraint if exists task_attempts_status_check;

alter table task_attempts
  add constraint task_attempts_status_check
  check (status in ('running', 'succeeded', 'failed', 'abandoned', 'waiting_approval'));

alter table task_attempts
  add column if not exists worker_id text,
  add column if not exists fencing_token uuid,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists heartbeat_at timestamptz,
  add column if not exists error_type text,
  add column if not exists error_message text,
  add column if not exists retryable boolean not null default false;

create unique index if not exists idx_task_attempt_fencing_token
  on task_attempts(fencing_token)
  where fencing_token is not null;

create table if not exists outbox_messages (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  aggregate_type text not null,
  aggregate_id uuid not null,
  message_type text not null,
  stream_name text not null,
  partition_key text not null,
  payload jsonb not null default '{}'::jsonb,
  published_at timestamptz,
  attempts integer not null default 0,
  last_error text,
  created_at timestamptz not null default now(),
  available_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create unique index if not exists idx_outbox_task_requested_once
  on outbox_messages(tenant_id, aggregate_id, message_type)
  where message_type = 'task.execute.requested' and published_at is null;

create index if not exists idx_outbox_due_unpublished
  on outbox_messages(available_at, created_at)
  where published_at is null;

create table if not exists inbox_messages (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  message_id uuid not null,
  handler_name text not null,
  status text not null check (status in ('processing', 'succeeded', 'failed', 'skipped')),
  received_at timestamptz not null default now(),
  completed_at timestamptz,
  error_message text,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  unique (message_id, handler_name)
);

create table if not exists checkpoints (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid not null references tasks(id) on delete restrict,
  attempt_id uuid not null references task_attempts(id) on delete restrict,
  checkpoint_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create table if not exists dead_letters (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid references runs(id) on delete restrict,
  task_id uuid references tasks(id) on delete restrict,
  message_id uuid,
  reason text not null,
  sanitized_payload jsonb not null default '{}'::jsonb,
  retryable boolean not null default false,
  requeued_at timestamptz,
  requeued_by uuid references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create index if not exists idx_inbox_message_handler on inbox_messages(message_id, handler_name);
create index if not exists idx_checkpoints_task_created on checkpoints(task_id, created_at desc);
create index if not exists idx_dead_letters_workspace_created
  on dead_letters(tenant_id, workspace_id, created_at desc);
create index if not exists idx_tasks_retry_due
  on tasks(next_retry_at)
  where status = 'retry_wait';
create index if not exists idx_task_attempts_expired_lease
  on task_attempts(lease_expires_at)
  where status = 'running';

grant select, insert, update, delete on outbox_messages to forge_runtime;
grant select, insert, update, delete on inbox_messages to forge_runtime;
grant select, insert, update, delete on checkpoints to forge_runtime;
grant select, insert, update, delete on dead_letters to forge_runtime;

alter table outbox_messages enable row level security;
alter table outbox_messages force row level security;
alter table inbox_messages enable row level security;
alter table inbox_messages force row level security;
alter table checkpoints enable row level security;
alter table checkpoints force row level security;
alter table dead_letters enable row level security;
alter table dead_letters force row level security;

drop policy if exists outbox_messages_scope on outbox_messages;
create policy outbox_messages_scope on outbox_messages
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists outbox_messages_actor_select on outbox_messages;
create policy outbox_messages_actor_select on outbox_messages
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = outbox_messages.tenant_id
        and m.workspace_id = outbox_messages.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists outbox_messages_worker on outbox_messages;
create policy outbox_messages_worker on outbox_messages
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists inbox_messages_scope on inbox_messages;
create policy inbox_messages_scope on inbox_messages
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists inbox_messages_actor_select on inbox_messages;
create policy inbox_messages_actor_select on inbox_messages
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = inbox_messages.tenant_id
        and m.workspace_id = inbox_messages.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists inbox_messages_worker on inbox_messages;
create policy inbox_messages_worker on inbox_messages
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists checkpoints_scope on checkpoints;
create policy checkpoints_scope on checkpoints
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists checkpoints_actor_select on checkpoints;
create policy checkpoints_actor_select on checkpoints
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = checkpoints.tenant_id
        and m.workspace_id = checkpoints.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists checkpoints_worker on checkpoints;
create policy checkpoints_worker on checkpoints
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists dead_letters_scope on dead_letters;
create policy dead_letters_scope on dead_letters
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists dead_letters_actor_select on dead_letters;
create policy dead_letters_actor_select on dead_letters
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = dead_letters.tenant_id
        and m.workspace_id = dead_letters.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists dead_letters_worker on dead_letters;
create policy dead_letters_worker on dead_letters
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists runs_worker on runs;
create policy runs_worker on runs
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists tasks_worker on tasks;
create policy tasks_worker on tasks
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists task_attempts_worker on task_attempts;
create policy task_attempts_worker on task_attempts
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists task_dependencies_worker on task_dependencies;
create policy task_dependencies_worker on task_dependencies
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists execution_events_worker on execution_events;
create policy execution_events_worker on execution_events
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

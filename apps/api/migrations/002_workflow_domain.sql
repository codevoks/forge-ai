create table if not exists workflow_templates (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  name text not null check (char_length(name) between 2 and 120),
  created_by uuid not null references users(id) on delete restrict,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists workflow_versions (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  template_id uuid not null references workflow_templates(id) on delete restrict,
  version_number integer not null check (version_number > 0),
  status text not null check (status in ('published')),
  name text not null check (char_length(name) between 2 and 120),
  schema_version integer not null default 1,
  created_by uuid not null references users(id) on delete restrict,
  published_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (template_id, version_number),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists workflow_steps (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  workflow_version_id uuid not null references workflow_versions(id) on delete restrict,
  step_key text not null check (char_length(step_key) between 1 and 64),
  name text not null check (char_length(name) between 2 and 120),
  kind text not null check (kind in ('manual', 'deterministic', 'tool', 'agent')),
  input jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (workflow_version_id, step_key),
  unique (tenant_id, workflow_version_id, step_key),
  foreign key (tenant_id, workspace_id, workflow_version_id)
    references workflow_versions(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists workflow_edges (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  workflow_version_id uuid not null references workflow_versions(id) on delete restrict,
  from_step_key text not null,
  to_step_key text not null,
  created_at timestamptz not null default now(),
  unique (workflow_version_id, from_step_key, to_step_key),
  check (from_step_key <> to_step_key),
  foreign key (tenant_id, workspace_id, workflow_version_id)
    references workflow_versions(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workflow_version_id, from_step_key)
    references workflow_steps(tenant_id, workflow_version_id, step_key) on delete restrict,
  foreign key (tenant_id, workflow_version_id, to_step_key)
    references workflow_steps(tenant_id, workflow_version_id, step_key) on delete restrict
);

create table if not exists objectives (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  created_by uuid not null references users(id) on delete restrict,
  objective text not null check (char_length(objective) between 2 and 4096),
  constraints jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists runs (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  objective_id uuid not null references objectives(id) on delete restrict,
  workflow_version_id uuid not null references workflow_versions(id) on delete restrict,
  status text not null check (status in ('created', 'running', 'succeeded', 'failed', 'cancelled')),
  version integer not null default 1,
  created_by uuid not null references users(id) on delete restrict,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, workflow_version_id)
    references workflow_versions(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists tasks (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  workflow_version_id uuid not null references workflow_versions(id) on delete restrict,
  step_key text not null,
  name text not null check (char_length(name) between 2 and 120),
  kind text not null check (kind in ('manual', 'deterministic', 'tool', 'agent')),
  input jsonb not null default '{}'::jsonb,
  status text not null check (status in ('pending', 'ready', 'running', 'succeeded', 'failed', 'cancelled')),
  result jsonb,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  unique (run_id, step_key),
  unique (tenant_id, run_id, step_key),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, workflow_version_id)
    references workflow_versions(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists task_dependencies (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  from_task_id uuid not null references tasks(id) on delete restrict,
  to_task_id uuid not null references tasks(id) on delete restrict,
  from_step_key text not null,
  to_step_key text not null,
  satisfaction_rule text not null default 'succeeded' check (satisfaction_rule in ('succeeded')),
  created_at timestamptz not null default now(),
  unique (run_id, from_step_key, to_step_key),
  check (from_task_id <> to_task_id),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, run_id, from_step_key) references tasks(tenant_id, run_id, step_key) on delete restrict,
  foreign key (tenant_id, run_id, to_step_key) references tasks(tenant_id, run_id, step_key) on delete restrict
);

create table if not exists task_attempts (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid not null references tasks(id) on delete restrict,
  attempt_number integer not null check (attempt_number > 0),
  status text not null check (status in ('running', 'succeeded', 'failed')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  result jsonb,
  unique (task_id, attempt_number),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict
);

create unique index if not exists idx_one_active_task_attempt
  on task_attempts(task_id)
  where status = 'running';

create table if not exists execution_events (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid references runs(id) on delete restrict,
  task_id uuid references tasks(id) on delete restrict,
  aggregate_type text not null,
  aggregate_id uuid not null,
  event_type text not null,
  sequence integer not null,
  actor_id uuid not null references users(id) on delete restrict,
  causation_id uuid,
  correlation_id uuid not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (tenant_id, run_id, sequence),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create index if not exists idx_workflow_versions_workspace on workflow_versions(tenant_id, workspace_id, created_at desc);
create index if not exists idx_runs_workspace_created on runs(tenant_id, workspace_id, created_at desc);
create index if not exists idx_tasks_run_status on tasks(run_id, status);
create index if not exists idx_events_run_sequence on execution_events(run_id, sequence);

grant select, insert, update, delete on workflow_templates to forge_runtime;
grant select, insert, update, delete on workflow_versions to forge_runtime;
grant select, insert, update, delete on workflow_steps to forge_runtime;
grant select, insert, update, delete on workflow_edges to forge_runtime;
grant select, insert, update, delete on objectives to forge_runtime;
grant select, insert, update, delete on runs to forge_runtime;
grant select, insert, update, delete on tasks to forge_runtime;
grant select, insert, update, delete on task_dependencies to forge_runtime;
grant select, insert, update, delete on task_attempts to forge_runtime;
grant select, insert, update, delete on execution_events to forge_runtime;

alter table workflow_templates enable row level security;
alter table workflow_templates force row level security;
alter table workflow_versions enable row level security;
alter table workflow_versions force row level security;
alter table workflow_steps enable row level security;
alter table workflow_steps force row level security;
alter table workflow_edges enable row level security;
alter table workflow_edges force row level security;
alter table objectives enable row level security;
alter table objectives force row level security;
alter table runs enable row level security;
alter table runs force row level security;
alter table tasks enable row level security;
alter table tasks force row level security;
alter table task_dependencies enable row level security;
alter table task_dependencies force row level security;
alter table task_attempts enable row level security;
alter table task_attempts force row level security;
alter table execution_events enable row level security;
alter table execution_events force row level security;

drop policy if exists workflow_templates_scope on workflow_templates;
create policy workflow_templates_scope on workflow_templates
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workflow_templates_actor_select on workflow_templates;
create policy workflow_templates_actor_select on workflow_templates
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = workflow_templates.tenant_id
        and m.workspace_id = workflow_templates.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists workflow_versions_scope on workflow_versions;
create policy workflow_versions_scope on workflow_versions
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workflow_versions_actor_select on workflow_versions;
create policy workflow_versions_actor_select on workflow_versions
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = workflow_versions.tenant_id
        and m.workspace_id = workflow_versions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists workflow_steps_scope on workflow_steps;
create policy workflow_steps_scope on workflow_steps
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workflow_steps_actor_select on workflow_steps;
create policy workflow_steps_actor_select on workflow_steps
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = workflow_steps.tenant_id
        and m.workspace_id = workflow_steps.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists workflow_edges_scope on workflow_edges;
create policy workflow_edges_scope on workflow_edges
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workflow_edges_actor_select on workflow_edges;
create policy workflow_edges_actor_select on workflow_edges
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = workflow_edges.tenant_id
        and m.workspace_id = workflow_edges.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists objectives_scope on objectives;
create policy objectives_scope on objectives
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists objectives_actor_select on objectives;
create policy objectives_actor_select on objectives
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = objectives.tenant_id
        and m.workspace_id = objectives.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists runs_scope on runs;
create policy runs_scope on runs
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists runs_actor_select on runs;
create policy runs_actor_select on runs
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = runs.tenant_id
        and m.workspace_id = runs.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists tasks_scope on tasks;
create policy tasks_scope on tasks
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists tasks_actor_select on tasks;
create policy tasks_actor_select on tasks
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = tasks.tenant_id
        and m.workspace_id = tasks.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists task_dependencies_scope on task_dependencies;
create policy task_dependencies_scope on task_dependencies
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists task_dependencies_actor_select on task_dependencies;
create policy task_dependencies_actor_select on task_dependencies
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = task_dependencies.tenant_id
        and m.workspace_id = task_dependencies.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists task_attempts_scope on task_attempts;
create policy task_attempts_scope on task_attempts
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists task_attempts_actor_select on task_attempts;
create policy task_attempts_actor_select on task_attempts
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = task_attempts.tenant_id
        and m.workspace_id = task_attempts.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists execution_events_scope on execution_events;
create policy execution_events_scope on execution_events
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists execution_events_actor_select on execution_events;
create policy execution_events_actor_select on execution_events
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = execution_events.tenant_id
        and m.workspace_id = execution_events.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

create or replace function prevent_workflow_version_mutation()
returns trigger
language plpgsql
as $$
begin
  if current_user = 'forge_runtime' then
    raise exception 'published workflow versions are immutable';
  end if;
  return old;
end;
$$;

drop trigger if exists workflow_versions_immutable_update on workflow_versions;
create trigger workflow_versions_immutable_update
  before update or delete on workflow_versions
  for each row execute function prevent_workflow_version_mutation();

drop trigger if exists workflow_steps_immutable_update on workflow_steps;
create trigger workflow_steps_immutable_update
  before update or delete on workflow_steps
  for each row execute function prevent_workflow_version_mutation();

drop trigger if exists workflow_edges_immutable_update on workflow_edges;
create trigger workflow_edges_immutable_update
  before update or delete on workflow_edges
  for each row execute function prevent_workflow_version_mutation();

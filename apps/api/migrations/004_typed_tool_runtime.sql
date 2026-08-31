alter table workflow_steps
  drop constraint if exists workflow_steps_kind_check;

alter table workflow_steps
  add constraint workflow_steps_kind_check
  check (kind in ('manual', 'deterministic', 'tool', 'agent'));

alter table tasks
  drop constraint if exists tasks_kind_check;

alter table tasks
  add constraint tasks_kind_check
  check (kind in ('manual', 'deterministic', 'tool', 'agent'));

create table if not exists tool_definitions (
  id uuid primary key,
  tenant_id uuid references tenants(id) on delete restrict,
  workspace_id uuid,
  name text not null check (char_length(name) between 2 and 120),
  display_name text not null check (char_length(display_name) between 2 and 120),
  description text not null check (char_length(description) between 2 and 1000),
  origin text not null check (origin in ('code')),
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists tool_versions (
  id uuid primary key,
  tenant_id uuid references tenants(id) on delete restrict,
  workspace_id uuid,
  tool_definition_id uuid not null references tool_definitions(id) on delete restrict,
  name text not null check (char_length(name) between 2 and 120),
  version integer not null check (version > 0),
  status text not null check (status in ('active', 'retired')),
  risk text not null check (risk in ('read_only', 'simulated_effect')),
  input_schema jsonb not null,
  output_schema jsonb not null,
  timeout_ms integer not null check (timeout_ms between 1 and 10000),
  retryable boolean not null default false,
  idempotency_required boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tool_definition_id, version),
  unique (tenant_id, workspace_id, name, version),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists run_tool_grants (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  tool_version_id uuid not null references tool_versions(id) on delete restrict,
  tool_name text not null,
  tool_version integer not null,
  risk text not null,
  granted_by uuid not null references users(id) on delete restrict,
  granted_at timestamptz not null default now(),
  unique (run_id, tool_version_id),
  unique (run_id, tool_name, tool_version),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create table if not exists tool_invocations (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid not null references tasks(id) on delete restrict,
  attempt_id uuid references task_attempts(id) on delete restrict,
  tool_version_id uuid not null references tool_versions(id) on delete restrict,
  tool_name text not null,
  tool_version integer not null,
  risk text not null,
  action_hash text not null,
  idempotency_key text not null,
  status text not null check (
    status in (
      'intent_recorded',
      'approval_required',
      'authorized',
      'executing',
      'succeeded',
      'failed',
      'policy_denied',
      'outcome_unknown'
    )
  ),
  input jsonb not null,
  output jsonb,
  error_type text,
  error_message text,
  provider_operation_id text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, run_id, task_id, tool_version_id, action_hash),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create table if not exists evidence_items (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid references tasks(id) on delete restrict,
  tool_invocation_id uuid references tool_invocations(id) on delete restrict,
  source_type text not null check (source_type in ('tool_output')),
  source_name text not null,
  trust_label text not null check (trust_label in ('trusted_local_fixture', 'untrusted_tool_output')),
  content_hash text not null,
  summary jsonb not null,
  retention_policy text not null default 'local_demo',
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create index if not exists idx_tool_versions_name_version
  on tool_versions(name, version);
create index if not exists idx_run_tool_grants_run on run_tool_grants(run_id);
create index if not exists idx_tool_invocations_run_created
  on tool_invocations(run_id, created_at desc);
create index if not exists idx_evidence_items_run_created
  on evidence_items(run_id, created_at desc);

grant select, insert, update, delete on tool_definitions to forge_runtime;
grant select, insert, update, delete on tool_versions to forge_runtime;
grant select, insert, update, delete on run_tool_grants to forge_runtime;
grant select, insert, update, delete on tool_invocations to forge_runtime;
grant select, insert, update, delete on evidence_items to forge_runtime;

alter table tool_definitions enable row level security;
alter table tool_definitions force row level security;
alter table tool_versions enable row level security;
alter table tool_versions force row level security;
alter table run_tool_grants enable row level security;
alter table run_tool_grants force row level security;
alter table tool_invocations enable row level security;
alter table tool_invocations force row level security;
alter table evidence_items enable row level security;
alter table evidence_items force row level security;

drop policy if exists tool_definitions_scope on tool_definitions;
create policy tool_definitions_scope on tool_definitions
  using (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  )
  with check (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  );

drop policy if exists tool_definitions_actor_select on tool_definitions;
create policy tool_definitions_actor_select on tool_definitions
  for select
  using (
    tenant_id is null
    or exists (
      select 1 from memberships m
      where m.tenant_id = tool_definitions.tenant_id
        and m.workspace_id = tool_definitions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists tool_definitions_worker on tool_definitions;
create policy tool_definitions_worker on tool_definitions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists tool_versions_scope on tool_versions;
create policy tool_versions_scope on tool_versions
  using (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  )
  with check (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  );

drop policy if exists tool_versions_actor_select on tool_versions;
create policy tool_versions_actor_select on tool_versions
  for select
  using (
    tenant_id is null
    or exists (
      select 1 from memberships m
      where m.tenant_id = tool_versions.tenant_id
        and m.workspace_id = tool_versions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists tool_versions_worker on tool_versions;
create policy tool_versions_worker on tool_versions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists run_tool_grants_scope on run_tool_grants;
create policy run_tool_grants_scope on run_tool_grants
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists run_tool_grants_actor_select on run_tool_grants;
create policy run_tool_grants_actor_select on run_tool_grants
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = run_tool_grants.tenant_id
        and m.workspace_id = run_tool_grants.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists run_tool_grants_worker on run_tool_grants;
create policy run_tool_grants_worker on run_tool_grants
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists tool_invocations_scope on tool_invocations;
create policy tool_invocations_scope on tool_invocations
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists tool_invocations_actor_select on tool_invocations;
create policy tool_invocations_actor_select on tool_invocations
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = tool_invocations.tenant_id
        and m.workspace_id = tool_invocations.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists tool_invocations_worker on tool_invocations;
create policy tool_invocations_worker on tool_invocations
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists evidence_items_scope on evidence_items;
create policy evidence_items_scope on evidence_items
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evidence_items_actor_select on evidence_items;
create policy evidence_items_actor_select on evidence_items
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evidence_items.tenant_id
        and m.workspace_id = evidence_items.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists evidence_items_worker on evidence_items;
create policy evidence_items_worker on evidence_items
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

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

alter table task_attempts
  drop constraint if exists task_attempts_status_check;

alter table task_attempts
  add constraint task_attempts_status_check
  check (status in ('running', 'succeeded', 'failed', 'abandoned', 'waiting_approval'));

alter table tool_invocations
  drop constraint if exists tool_invocations_status_check;

alter table tool_invocations
  add constraint tool_invocations_status_check
  check (
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
  );

create table if not exists policy_versions (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  version integer not null check (version > 0),
  status text not null check (status in ('active', 'retired')),
  approval_required_risks jsonb not null default '["simulated_effect"]'::jsonb,
  separation_of_duty boolean not null default true,
  max_pending_approvals_per_run integer not null default 10
    check (max_pending_approvals_per_run between 1 and 100),
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, version),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create unique index if not exists idx_policy_versions_one_active
  on policy_versions(tenant_id, workspace_id)
  where status = 'active';

create table if not exists integration_connections (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  name text not null check (char_length(name) between 2 and 120),
  provider text not null check (char_length(provider) between 2 and 120),
  mode text not null check (mode in ('local_fake', 'external_opt_in')),
  secret_reference text,
  status text not null check (status in ('active', 'disabled')),
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  check (secret_reference is null or secret_reference like 'secretref://%')
);

create table if not exists approval_requests (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid not null references tasks(id) on delete restrict,
  tool_invocation_id uuid not null references tool_invocations(id) on delete restrict,
  tool_version_id uuid not null references tool_versions(id) on delete restrict,
  requester_id uuid not null references users(id) on delete restrict,
  action_hash text not null,
  binding_hash text not null,
  risk text not null,
  reason text not null check (char_length(reason) between 2 and 500),
  action_summary jsonb not null,
  status text not null check (status in ('pending', 'approved', 'rejected', 'expired', 'consumed')),
  request_version integer not null default 1,
  expires_at timestamptz not null,
  decided_by uuid references users(id) on delete restrict,
  decided_at timestamptz,
  decision_reason text,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, id),
  unique (tool_invocation_id, action_hash),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create unique index if not exists idx_approval_requests_one_pending_invocation
  on approval_requests(tool_invocation_id)
  where status = 'pending';

create index if not exists idx_approval_requests_workspace_status
  on approval_requests(tenant_id, workspace_id, status, created_at desc);

create table if not exists approval_decisions (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  approval_request_id uuid not null references approval_requests(id) on delete restrict,
  decision text not null check (decision in ('approved', 'rejected')),
  decided_by uuid not null references users(id) on delete restrict,
  reason text not null check (char_length(reason) between 2 and 500),
  request_version integer not null,
  binding_hash text not null,
  created_at timestamptz not null default now(),
  unique (approval_request_id),
  foreign key (tenant_id, workspace_id, approval_request_id)
    references approval_requests(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

grant select, insert, update, delete on policy_versions to forge_runtime;
grant select, insert, update, delete on integration_connections to forge_runtime;
grant select, insert, update, delete on approval_requests to forge_runtime;
grant select, insert, update, delete on approval_decisions to forge_runtime;

alter table policy_versions enable row level security;
alter table policy_versions force row level security;
alter table integration_connections enable row level security;
alter table integration_connections force row level security;
alter table approval_requests enable row level security;
alter table approval_requests force row level security;
alter table approval_decisions enable row level security;
alter table approval_decisions force row level security;

drop policy if exists policy_versions_scope on policy_versions;
create policy policy_versions_scope on policy_versions
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists policy_versions_actor_select on policy_versions;
create policy policy_versions_actor_select on policy_versions
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = policy_versions.tenant_id
        and m.workspace_id = policy_versions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists policy_versions_worker on policy_versions;
create policy policy_versions_worker on policy_versions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists integration_connections_scope on integration_connections;
create policy integration_connections_scope on integration_connections
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists integration_connections_actor_select on integration_connections;
create policy integration_connections_actor_select on integration_connections
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = integration_connections.tenant_id
        and m.workspace_id = integration_connections.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists integration_connections_worker on integration_connections;
create policy integration_connections_worker on integration_connections
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists approval_requests_scope on approval_requests;
create policy approval_requests_scope on approval_requests
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists approval_requests_actor_select on approval_requests;
create policy approval_requests_actor_select on approval_requests
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = approval_requests.tenant_id
        and m.workspace_id = approval_requests.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists approval_requests_worker on approval_requests;
create policy approval_requests_worker on approval_requests
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists approval_decisions_scope on approval_decisions;
create policy approval_decisions_scope on approval_decisions
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists approval_decisions_actor_select on approval_decisions;
create policy approval_decisions_actor_select on approval_decisions
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = approval_decisions.tenant_id
        and m.workspace_id = approval_decisions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists approval_decisions_worker on approval_decisions;
create policy approval_decisions_worker on approval_decisions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

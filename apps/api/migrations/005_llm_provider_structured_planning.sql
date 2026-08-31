create table if not exists prompt_versions (
  id uuid primary key,
  tenant_id uuid references tenants(id) on delete restrict,
  workspace_id uuid,
  name text not null check (char_length(name) between 2 and 120),
  version integer not null check (version > 0),
  status text not null check (status in ('active', 'retired')),
  purpose text not null check (char_length(purpose) between 2 and 200),
  template text not null check (char_length(template) between 20 and 8000),
  schema_name text not null check (char_length(schema_name) between 2 and 120),
  schema_version integer not null check (schema_version > 0),
  retention_policy text not null default 'local_demo',
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name, version),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists model_calls (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  prompt_version_id uuid not null references prompt_versions(id) on delete restrict,
  provider text not null check (char_length(provider) between 2 and 120),
  model_name text not null check (char_length(model_name) between 2 and 160),
  status text not null check (
    status in ('succeeded', 'failed', 'refused', 'malformed', 'policy_denied', 'timeout')
  ),
  request_hash text not null,
  request_summary jsonb not null,
  response_summary jsonb not null default '{}'::jsonb,
  error_type text,
  error_message text,
  input_tokens integer not null default 0 check (input_tokens >= 0),
  output_tokens integer not null default 0 check (output_tokens >= 0),
  total_tokens integer not null default 0 check (total_tokens >= 0),
  estimated_cost_minor integer not null default 0 check (estimated_cost_minor >= 0),
  latency_ms integer not null default 0 check (latency_ms >= 0),
  live_provider boolean not null default false,
  external_request_id text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create table if not exists plan_versions (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  version_number integer not null check (version_number > 0),
  source_model_call_id uuid not null references model_calls(id) on delete restrict,
  prompt_version_id uuid not null references prompt_versions(id) on delete restrict,
  status text not null check (status in ('validated', 'rejected', 'superseded')),
  objective text not null check (char_length(objective) between 2 and 4096),
  summary text not null check (char_length(summary) between 2 and 1000),
  validation_errors jsonb not null default '[]'::jsonb,
  supersedes_plan_version_id uuid references plan_versions(id) on delete restrict,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (run_id, version_number),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create table if not exists plan_nodes (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  plan_version_id uuid not null references plan_versions(id) on delete restrict,
  node_key text not null check (char_length(node_key) between 1 and 64),
  title text not null check (char_length(title) between 2 and 120),
  kind text not null check (kind in ('deterministic', 'tool', 'manual')),
  tool_name text,
  tool_version integer,
  rationale text not null check (char_length(rationale) between 2 and 1000),
  input jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (plan_version_id, node_key),
  unique (tenant_id, plan_version_id, node_key),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict,
  foreign key (tenant_id, workspace_id, plan_version_id)
    references plan_versions(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists plan_edges (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  plan_version_id uuid not null references plan_versions(id) on delete restrict,
  from_node_key text not null,
  to_node_key text not null,
  created_at timestamptz not null default now(),
  unique (plan_version_id, from_node_key, to_node_key),
  check (from_node_key <> to_node_key),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict,
  foreign key (tenant_id, workspace_id, plan_version_id)
    references plan_versions(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, plan_version_id, from_node_key)
    references plan_nodes(tenant_id, plan_version_id, node_key) on delete restrict,
  foreign key (tenant_id, plan_version_id, to_node_key)
    references plan_nodes(tenant_id, plan_version_id, node_key) on delete restrict
);

create index if not exists idx_model_calls_run_created on model_calls(run_id, created_at desc);
create index if not exists idx_plan_versions_run_version on plan_versions(run_id, version_number desc);
create index if not exists idx_plan_nodes_plan on plan_nodes(plan_version_id);
create index if not exists idx_plan_edges_plan on plan_edges(plan_version_id);

grant select, insert, update, delete on prompt_versions to forge_runtime;
grant select, insert, update, delete on model_calls to forge_runtime;
grant select, insert, update, delete on plan_versions to forge_runtime;
grant select, insert, update, delete on plan_nodes to forge_runtime;
grant select, insert, update, delete on plan_edges to forge_runtime;

alter table prompt_versions enable row level security;
alter table prompt_versions force row level security;
alter table model_calls enable row level security;
alter table model_calls force row level security;
alter table plan_versions enable row level security;
alter table plan_versions force row level security;
alter table plan_nodes enable row level security;
alter table plan_nodes force row level security;
alter table plan_edges enable row level security;
alter table plan_edges force row level security;

drop policy if exists prompt_versions_scope on prompt_versions;
create policy prompt_versions_scope on prompt_versions
  using (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  )
  with check (
    tenant_id::text = current_setting('forge.tenant_id', true)
    or tenant_id is null
  );

drop policy if exists prompt_versions_actor_select on prompt_versions;
create policy prompt_versions_actor_select on prompt_versions
  for select
  using (
    tenant_id is null
    or exists (
      select 1 from memberships m
      where m.tenant_id = prompt_versions.tenant_id
        and m.workspace_id = prompt_versions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists prompt_versions_worker on prompt_versions;
create policy prompt_versions_worker on prompt_versions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists model_calls_scope on model_calls;
create policy model_calls_scope on model_calls
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists model_calls_actor_select on model_calls;
create policy model_calls_actor_select on model_calls
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = model_calls.tenant_id
        and m.workspace_id = model_calls.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists model_calls_worker on model_calls;
create policy model_calls_worker on model_calls
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists plan_versions_scope on plan_versions;
create policy plan_versions_scope on plan_versions
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists plan_versions_actor_select on plan_versions;
create policy plan_versions_actor_select on plan_versions
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = plan_versions.tenant_id
        and m.workspace_id = plan_versions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists plan_versions_worker on plan_versions;
create policy plan_versions_worker on plan_versions
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists plan_nodes_scope on plan_nodes;
create policy plan_nodes_scope on plan_nodes
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists plan_nodes_actor_select on plan_nodes;
create policy plan_nodes_actor_select on plan_nodes
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = plan_nodes.tenant_id
        and m.workspace_id = plan_nodes.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists plan_nodes_worker on plan_nodes;
create policy plan_nodes_worker on plan_nodes
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists plan_edges_scope on plan_edges;
create policy plan_edges_scope on plan_edges
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists plan_edges_actor_select on plan_edges;
create policy plan_edges_actor_select on plan_edges
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = plan_edges.tenant_id
        and m.workspace_id = plan_edges.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists plan_edges_worker on plan_edges;
create policy plan_edges_worker on plan_edges
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

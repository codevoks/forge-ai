alter table tool_definitions
  drop constraint if exists tool_definitions_origin_check;

alter table tool_definitions
  add constraint tool_definitions_origin_check
  check (origin in ('code', 'mcp'));

alter table tool_versions
  add column if not exists trust_label text
  not null default 'untrusted_tool_output'
  check (trust_label in ('trusted_local_fixture', 'untrusted_tool_output'));

create table if not exists mcp_servers (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  name text not null check (char_length(name) between 2 and 120),
  transport text not null check (transport in ('stdio', 'http')),
  trust_level text not null check (trust_level in ('local', 'remote')),
  connection_config jsonb not null,
  auth_secret_reference text,
  status text not null default 'draft'
    check (status in ('draft', 'healthy', 'unreachable', 'auth_expired', 'disabled')),
  enabled boolean not null default true,
  last_health_checked_at timestamptz,
  last_health_status text,
  last_error text,
  version integer not null default 1,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists mcp_capability_snapshots (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  mcp_server_id uuid not null references mcp_servers(id) on delete restrict,
  captured_at timestamptz not null default now(),
  protocol_version text not null,
  capability_hash text not null,
  tool_count integer not null check (tool_count >= 0),
  tools jsonb not null,
  created_by uuid not null references users(id) on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists mcp_tool_mappings (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  mcp_server_id uuid not null references mcp_servers(id) on delete restrict,
  remote_tool_name text not null check (char_length(remote_tool_name) between 1 and 80),
  forge_tool_name text,
  status text not null default 'discovered'
    check (status in ('discovered', 'enabled', 'disabled', 'drifted', 'removed')),
  risk text check (risk in ('read_only', 'simulated_effect')),
  latest_snapshot_id uuid references mcp_capability_snapshots(id) on delete restrict,
  schema_hash text not null,
  mapped_tool_definition_id uuid references tool_definitions(id) on delete restrict,
  mapped_tool_version_id uuid references tool_versions(id) on delete restrict,
  reviewed_by uuid references users(id) on delete restrict,
  reviewed_at timestamptz,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (mcp_server_id, remote_tool_name),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

alter table tool_invocations
  add column if not exists mcp_server_id uuid references mcp_servers(id) on delete restrict;

alter table tool_invocations
  add column if not exists mcp_provenance jsonb;

create index if not exists idx_mcp_servers_workspace on mcp_servers(tenant_id, workspace_id);
create index if not exists idx_mcp_snapshots_server_captured
  on mcp_capability_snapshots(mcp_server_id, captured_at desc);
create index if not exists idx_mcp_mappings_server on mcp_tool_mappings(mcp_server_id, status);
create index if not exists idx_tool_invocations_mcp_server on tool_invocations(mcp_server_id);

grant select, insert, update, delete on mcp_servers to forge_runtime;
grant select, insert, update, delete on mcp_capability_snapshots to forge_runtime;
grant select, insert, update, delete on mcp_tool_mappings to forge_runtime;

alter table mcp_servers enable row level security;
alter table mcp_servers force row level security;
alter table mcp_capability_snapshots enable row level security;
alter table mcp_capability_snapshots force row level security;
alter table mcp_tool_mappings enable row level security;
alter table mcp_tool_mappings force row level security;

drop policy if exists mcp_servers_scope on mcp_servers;
create policy mcp_servers_scope on mcp_servers
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists mcp_servers_actor_select on mcp_servers;
create policy mcp_servers_actor_select on mcp_servers
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = mcp_servers.tenant_id
        and m.workspace_id = mcp_servers.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists mcp_servers_worker on mcp_servers;
create policy mcp_servers_worker on mcp_servers
  for select
  using (current_setting('forge.worker_id', true) <> '');

drop policy if exists mcp_snapshots_scope on mcp_capability_snapshots;
create policy mcp_snapshots_scope on mcp_capability_snapshots
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists mcp_snapshots_actor_select on mcp_capability_snapshots;
create policy mcp_snapshots_actor_select on mcp_capability_snapshots
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = mcp_capability_snapshots.tenant_id
        and m.workspace_id = mcp_capability_snapshots.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists mcp_mappings_scope on mcp_tool_mappings;
create policy mcp_mappings_scope on mcp_tool_mappings
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists mcp_mappings_actor_select on mcp_tool_mappings;
create policy mcp_mappings_actor_select on mcp_tool_mappings
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = mcp_tool_mappings.tenant_id
        and m.workspace_id = mcp_tool_mappings.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists mcp_mappings_worker on mcp_tool_mappings;
create policy mcp_mappings_worker on mcp_tool_mappings
  for select
  using (current_setting('forge.worker_id', true) <> '');

create extension if not exists pgcrypto;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'forge_runtime') then
    create role forge_runtime login password 'forge_runtime' nosuperuser nocreatedb nocreaterole;
  end if;
end
$$;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  external_issuer text not null,
  external_subject text not null,
  email text not null,
  display_name text not null,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (external_issuer, external_subject)
);

create table if not exists tenants (
  id uuid primary key,
  name text not null check (char_length(name) between 2 and 100),
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists workspaces (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  name text not null check (char_length(name) between 2 and 100),
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, id)
);

create table if not exists memberships (
  tenant_id uuid not null,
  workspace_id uuid not null,
  user_id uuid not null references users(id) on delete restrict,
  role text not null check (role in ('tenant_admin', 'workspace_admin', 'operator', 'approver', 'viewer')),
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, workspace_id, user_id),
  foreign key (tenant_id) references tenants(id) on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists idempotency_records (
  id uuid primary key default gen_random_uuid(),
  scope text not null,
  key text not null,
  request_hash text not null,
  response_payload jsonb not null,
  status_code integer not null,
  created_at timestamptz not null default now(),
  unique (scope, key)
);

create table if not exists security_audit_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete restrict,
  actor_id uuid,
  event_type text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_workspaces_tenant on workspaces(tenant_id);
create index if not exists idx_memberships_user on memberships(user_id);
create index if not exists idx_audit_tenant_created on security_audit_events(tenant_id, created_at desc);

grant usage on schema public to forge_runtime;
grant select, insert, update, delete on users to forge_runtime;
grant select, insert, update, delete on tenants to forge_runtime;
grant select, insert, update, delete on workspaces to forge_runtime;
grant select, insert, update, delete on memberships to forge_runtime;
grant select, insert, update, delete on idempotency_records to forge_runtime;
grant select, insert, update, delete on security_audit_events to forge_runtime;

alter table tenants enable row level security;
alter table tenants force row level security;
alter table workspaces enable row level security;
alter table workspaces force row level security;
alter table memberships enable row level security;
alter table memberships force row level security;
alter table security_audit_events enable row level security;
alter table security_audit_events force row level security;

drop policy if exists tenant_scope on tenants;
create policy tenant_scope on tenants
  using (id::text = current_setting('forge.tenant_id', true))
  with check (id::text = current_setting('forge.tenant_id', true));

drop policy if exists workspace_scope on workspaces;
create policy workspace_scope on workspaces
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workspace_actor_membership on workspaces;
create policy workspace_actor_membership on workspaces
  for select
  using (
    exists (
      select 1
      from memberships m
      where m.tenant_id = workspaces.tenant_id
        and m.workspace_id = workspaces.id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists membership_scope on memberships;
create policy membership_scope on memberships
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists membership_actor_self on memberships;
create policy membership_actor_self on memberships
  for select
  using (user_id::text = current_setting('forge.actor_id', true));

drop policy if exists audit_scope on security_audit_events;
create policy audit_scope on security_audit_events
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

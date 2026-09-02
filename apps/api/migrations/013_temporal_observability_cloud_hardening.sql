-- Phase 13: hierarchical budgets, OTel trace correlation columns already exist
-- (execution_events.trace_context/correlation_id from migration 001), so this
-- migration only adds the budget subsystem. No Temporal linkage table is
-- added: Phase 13's evidence-backed comparison rejects adoption (see
-- decisions.md Q-005), so there is no workflow-history reconciliation state
-- to persist.

create table if not exists budget_policies (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid,
  scope text not null check (scope in ('tenant', 'workspace')),
  max_requests_per_day integer not null check (max_requests_per_day > 0),
  max_tokens_per_day integer not null check (max_tokens_per_day >= 0),
  max_currency_minor_per_day integer not null check (max_currency_minor_per_day >= 0),
  rate_card_version integer not null default 1 check (rate_card_version > 0),
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, scope),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists budget_usage_daily (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  usage_date date not null,
  requests_used integer not null default 0 check (requests_used >= 0),
  tokens_used integer not null default 0 check (tokens_used >= 0),
  currency_minor_used integer not null default 0 check (currency_minor_used >= 0),
  updated_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, usage_date),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists budget_reservations (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid references runs(id) on delete restrict,
  task_id uuid references tasks(id) on delete restrict,
  operation text not null check (char_length(operation) between 2 and 120),
  status text not null check (status in ('reserved', 'settled', 'released')),
  estimated_requests integer not null check (estimated_requests >= 0),
  estimated_tokens integer not null check (estimated_tokens >= 0),
  estimated_currency_minor integer not null check (estimated_currency_minor >= 0),
  actual_requests integer,
  actual_tokens integer,
  actual_currency_minor integer,
  usage_date date not null,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict
);

create index if not exists idx_budget_usage_daily_lookup
  on budget_usage_daily(tenant_id, workspace_id, usage_date);
create index if not exists idx_budget_reservations_run
  on budget_reservations(run_id, status);

grant select, insert, update, delete on budget_policies to forge_runtime;
grant select, insert, update, delete on budget_usage_daily to forge_runtime;
grant select, insert, update, delete on budget_reservations to forge_runtime;

alter table budget_policies enable row level security;
alter table budget_policies force row level security;
alter table budget_usage_daily enable row level security;
alter table budget_usage_daily force row level security;
alter table budget_reservations enable row level security;
alter table budget_reservations force row level security;

drop policy if exists budget_policies_scope on budget_policies;
create policy budget_policies_scope on budget_policies
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists budget_policies_actor_select on budget_policies;
create policy budget_policies_actor_select on budget_policies
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = budget_policies.tenant_id
        and (budget_policies.workspace_id is null or m.workspace_id = budget_policies.workspace_id)
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists budget_policies_worker on budget_policies;
create policy budget_policies_worker on budget_policies
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists budget_usage_daily_scope on budget_usage_daily;
create policy budget_usage_daily_scope on budget_usage_daily
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists budget_usage_daily_actor_select on budget_usage_daily;
create policy budget_usage_daily_actor_select on budget_usage_daily
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = budget_usage_daily.tenant_id
        and m.workspace_id = budget_usage_daily.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists budget_usage_daily_worker on budget_usage_daily;
create policy budget_usage_daily_worker on budget_usage_daily
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

drop policy if exists budget_reservations_scope on budget_reservations;
create policy budget_reservations_scope on budget_reservations
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists budget_reservations_actor_select on budget_reservations;
create policy budget_reservations_actor_select on budget_reservations
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = budget_reservations.tenant_id
        and m.workspace_id = budget_reservations.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists budget_reservations_worker on budget_reservations;
create policy budget_reservations_worker on budget_reservations
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

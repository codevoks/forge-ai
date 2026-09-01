-- Multi-agent synthesis steps intentionally reuse the existing 'deterministic'
-- step kind (tagged via input.mode = 'multi_agent_synthesize') rather than
-- adding a new kind value to workflow_steps_kind_check/tasks_kind_check.
-- Those constraints are unconditionally re-declared by migrations 004 and 007
-- on every replay (this project replays every migration file on every
-- `pnpm db:migrate`, with no per-migration version tracking); widening them
-- here would pass on a fresh database but then fail on every subsequent
-- replay once a 'synthesize' row exists, because 004/007 would try to
-- re-narrow the constraint against already-violating data. Reusing an
-- already-allowed kind avoids that hazard entirely without touching any
-- completed phase's migration.

alter table runs
  add column if not exists strategy_kind text not null default 'single_agentic',
  add column if not exists strategy_version text not null default 'single-agentic-v1',
  add column if not exists strategy_metadata jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'runs_strategy_kind_check'
  ) then
    alter table runs
      add constraint runs_strategy_kind_check
      check (strategy_kind in ('single_agentic', 'multi_agent_parallel'));
  end if;
end $$;

alter table tasks
  add column if not exists agent_role text;

alter table tasks
  drop constraint if exists tasks_agent_role_length_check;

alter table tasks
  add constraint tasks_agent_role_length_check
  check (agent_role is null or char_length(agent_role) between 2 and 60);

create table if not exists strategy_comparisons (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  single_agent_run_id uuid not null references runs(id) on delete restrict,
  multi_agent_run_id uuid not null references runs(id) on delete restrict,
  objective text not null check (char_length(objective) between 2 and 4096),
  metrics jsonb not null default '{}'::jsonb,
  caveats text not null default '',
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, single_agent_run_id)
    references runs(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, multi_agent_run_id)
    references runs(tenant_id, workspace_id, id) on delete restrict
);

create index if not exists idx_strategy_comparisons_workspace_created
  on strategy_comparisons(tenant_id, workspace_id, created_at desc);

grant select, insert, update, delete on strategy_comparisons to forge_runtime;

alter table strategy_comparisons enable row level security;
alter table strategy_comparisons force row level security;

drop policy if exists strategy_comparisons_scope on strategy_comparisons;
create policy strategy_comparisons_scope on strategy_comparisons
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists strategy_comparisons_actor_select on strategy_comparisons;
create policy strategy_comparisons_actor_select on strategy_comparisons
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = strategy_comparisons.tenant_id
        and m.workspace_id = strategy_comparisons.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

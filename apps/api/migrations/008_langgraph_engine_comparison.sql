alter table runs
  add column if not exists engine_kind text not null default 'custom',
  add column if not exists engine_version text not null default 'custom-agent-v1',
  add column if not exists engine_metadata jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'runs_engine_kind_check'
  ) then
    alter table runs
      add constraint runs_engine_kind_check check (engine_kind in ('custom', 'langgraph'));
  end if;
end $$;

create table if not exists workflow_engine_checkpoints (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid references tasks(id) on delete restrict,
  attempt_id uuid references task_attempts(id) on delete restrict,
  engine_kind text not null check (engine_kind in ('custom', 'langgraph')),
  engine_version text not null check (char_length(engine_version) between 2 and 120),
  namespace text not null check (char_length(namespace) between 1 and 120),
  checkpoint_id text not null check (char_length(checkpoint_id) between 1 and 200),
  node_name text not null check (char_length(node_name) between 1 and 120),
  state_summary jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (tenant_id, run_id, task_id, engine_kind, namespace, checkpoint_id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict
);

create index if not exists idx_engine_checkpoints_run_created
  on workflow_engine_checkpoints(run_id, created_at);

grant select, insert, update, delete on workflow_engine_checkpoints to forge_runtime;

alter table workflow_engine_checkpoints enable row level security;
alter table workflow_engine_checkpoints force row level security;

drop policy if exists workflow_engine_checkpoints_scope on workflow_engine_checkpoints;
create policy workflow_engine_checkpoints_scope on workflow_engine_checkpoints
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists workflow_engine_checkpoints_actor_select on workflow_engine_checkpoints;
create policy workflow_engine_checkpoints_actor_select on workflow_engine_checkpoints
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = workflow_engine_checkpoints.tenant_id
        and m.workspace_id = workflow_engine_checkpoints.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists workflow_engine_checkpoints_worker on workflow_engine_checkpoints;
create policy workflow_engine_checkpoints_worker on workflow_engine_checkpoints
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

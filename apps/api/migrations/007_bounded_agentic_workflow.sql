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

create table if not exists agent_iterations (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  task_id uuid not null references tasks(id) on delete restrict,
  attempt_id uuid not null references task_attempts(id) on delete restrict,
  iteration_number integer not null check (iteration_number > 0 and iteration_number <= 6),
  model_call_id uuid not null references model_calls(id) on delete restrict,
  tool_invocation_id uuid references tool_invocations(id) on delete restrict,
  evidence_item_id uuid references evidence_items(id) on delete restrict,
  decision_type text not null check (
    decision_type in ('tool_call', 'complete', 'fail', 'request_replan')
  ),
  decision_status text not null check (decision_status in ('validated', 'rejected')),
  context_hash text not null,
  counters_snapshot jsonb not null,
  decision jsonb not null,
  validation_errors jsonb not null default '[]'::jsonb,
  result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (task_id, iteration_number),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id)
    on delete restrict,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create index if not exists idx_agent_iterations_run
  on agent_iterations(run_id, iteration_number);
create index if not exists idx_agent_iterations_task
  on agent_iterations(task_id, iteration_number);

grant select, insert, update, delete on agent_iterations to forge_runtime;

alter table agent_iterations enable row level security;
alter table agent_iterations force row level security;

drop policy if exists agent_iterations_scope on agent_iterations;
create policy agent_iterations_scope on agent_iterations
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists agent_iterations_actor_select on agent_iterations;
create policy agent_iterations_actor_select on agent_iterations
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = agent_iterations.tenant_id
        and m.workspace_id = agent_iterations.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists agent_iterations_worker on agent_iterations;
create policy agent_iterations_worker on agent_iterations
  using (current_setting('forge.worker_id', true) <> '')
  with check (current_setting('forge.worker_id', true) <> '');

alter table execution_events
  add column if not exists schema_version integer not null default 1,
  add column if not exists trace_context jsonb not null default '{}'::jsonb,
  add column if not exists sanitized_diff jsonb not null default '{}'::jsonb,
  add column if not exists retention_class text not null default 'standard',
  add column if not exists payload_hash text;

create index if not exists idx_events_run_cursor
  on execution_events(run_id, sequence, id);

create index if not exists idx_events_correlation
  on execution_events(tenant_id, workspace_id, correlation_id);

create table if not exists debugger_projection_verifications (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  status text not null check (status in ('passed', 'failed')),
  checked_event_count integer not null check (checked_event_count >= 0),
  expected_run_status text not null,
  actual_run_status text not null,
  expected_task_statuses jsonb not null default '{}'::jsonb,
  actual_task_statuses jsonb not null default '{}'::jsonb,
  mismatch_count integer not null check (mismatch_count >= 0),
  mismatches jsonb not null default '[]'::jsonb,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists debugger_replay_sessions (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  source_run_id uuid not null references runs(id) on delete restrict,
  mode text not null check (mode in ('simulation', 'effect_replay')),
  status text not null check (status in ('passed', 'blocked', 'failed')),
  policy jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, source_run_id) references runs(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists debugger_replay_artifacts (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  replay_session_id uuid not null references debugger_replay_sessions(id) on delete restrict,
  artifact_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  unique (replay_session_id, artifact_type)
);

create table if not exists debugger_trace_exports (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  run_id uuid not null references runs(id) on delete restrict,
  exporter text not null,
  status text not null check (status in ('local_artifact', 'disabled', 'blocked', 'failed')),
  live_export boolean not null default false,
  artifact jsonb not null default '{}'::jsonb,
  error_message text,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, run_id) references runs(tenant_id, workspace_id, id) on delete restrict
);

create index if not exists idx_projection_verifications_run_created
  on debugger_projection_verifications(run_id, created_at desc);

create index if not exists idx_replay_sessions_run_created
  on debugger_replay_sessions(source_run_id, created_at desc);

create index if not exists idx_trace_exports_run_created
  on debugger_trace_exports(run_id, created_at desc);

grant select, insert, update, delete on debugger_projection_verifications to forge_runtime;
grant select, insert, update, delete on debugger_replay_sessions to forge_runtime;
grant select, insert, update, delete on debugger_replay_artifacts to forge_runtime;
grant select, insert, update, delete on debugger_trace_exports to forge_runtime;

alter table debugger_projection_verifications enable row level security;
alter table debugger_projection_verifications force row level security;
alter table debugger_replay_sessions enable row level security;
alter table debugger_replay_sessions force row level security;
alter table debugger_replay_artifacts enable row level security;
alter table debugger_replay_artifacts force row level security;
alter table debugger_trace_exports enable row level security;
alter table debugger_trace_exports force row level security;

drop policy if exists debugger_projection_verifications_scope on debugger_projection_verifications;
create policy debugger_projection_verifications_scope on debugger_projection_verifications
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists debugger_projection_verifications_actor_select on debugger_projection_verifications;
create policy debugger_projection_verifications_actor_select on debugger_projection_verifications
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = debugger_projection_verifications.tenant_id
        and m.workspace_id = debugger_projection_verifications.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists debugger_replay_sessions_scope on debugger_replay_sessions;
create policy debugger_replay_sessions_scope on debugger_replay_sessions
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists debugger_replay_sessions_actor_select on debugger_replay_sessions;
create policy debugger_replay_sessions_actor_select on debugger_replay_sessions
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = debugger_replay_sessions.tenant_id
        and m.workspace_id = debugger_replay_sessions.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists debugger_replay_artifacts_scope on debugger_replay_artifacts;
create policy debugger_replay_artifacts_scope on debugger_replay_artifacts
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists debugger_replay_artifacts_actor_select on debugger_replay_artifacts;
create policy debugger_replay_artifacts_actor_select on debugger_replay_artifacts
  for select
  using (
    exists (
      select 1
      from debugger_replay_sessions s
      join memberships m on m.tenant_id = s.tenant_id and m.workspace_id = s.workspace_id
      where s.id = debugger_replay_artifacts.replay_session_id
        and s.tenant_id = debugger_replay_artifacts.tenant_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists debugger_trace_exports_scope on debugger_trace_exports;
create policy debugger_trace_exports_scope on debugger_trace_exports
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists debugger_trace_exports_actor_select on debugger_trace_exports;
create policy debugger_trace_exports_actor_select on debugger_trace_exports
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = debugger_trace_exports.tenant_id
        and m.workspace_id = debugger_trace_exports.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

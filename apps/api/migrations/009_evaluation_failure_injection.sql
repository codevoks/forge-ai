create table if not exists evaluation_suites (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  name text not null check (char_length(name) between 2 and 120),
  version integer not null check (version > 0),
  description text not null check (char_length(description) between 2 and 500),
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, name, version),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict
);

create table if not exists evaluation_cases (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  suite_id uuid not null references evaluation_suites(id) on delete restrict,
  case_key text not null check (char_length(case_key) between 2 and 120),
  category text not null check (category in ('planning', 'agent', 'security', 'failure')),
  description text not null check (char_length(description) between 2 and 500),
  security_critical boolean not null default false,
  expected_outcome jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (suite_id, case_key),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, suite_id)
    references evaluation_suites(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists evaluation_runs (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  suite_id uuid not null references evaluation_suites(id) on delete restrict,
  status text not null check (status in ('running', 'passed', 'failed')),
  provider_path text not null check (char_length(provider_path) between 2 and 120),
  engine_matrix jsonb not null default '[]'::jsonb,
  external_integrations text not null check (external_integrations in ('disabled', 'enabled')),
  langsmith_export_mode text not null check (langsmith_export_mode in ('local', 'disabled', 'enabled')),
  config jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  created_by uuid not null references users(id) on delete restrict,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, suite_id)
    references evaluation_suites(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists evaluation_case_results (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  evaluation_run_id uuid not null references evaluation_runs(id) on delete restrict,
  case_id uuid not null references evaluation_cases(id) on delete restrict,
  case_key text not null check (char_length(case_key) between 2 and 120),
  category text not null check (category in ('planning', 'agent', 'security', 'failure')),
  status text not null check (status in ('passed', 'failed')),
  security_critical boolean not null default false,
  provider text not null check (char_length(provider) between 2 and 120),
  engine_kind text,
  metrics jsonb not null default '{}'::jsonb,
  artifacts jsonb not null default '{}'::jsonb,
  failure_message text,
  created_at timestamptz not null default now(),
  unique (evaluation_run_id, case_key),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, evaluation_run_id)
    references evaluation_runs(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, case_id)
    references evaluation_cases(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists metric_values (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  evaluation_run_id uuid not null references evaluation_runs(id) on delete restrict,
  case_result_id uuid references evaluation_case_results(id) on delete restrict,
  metric_name text not null check (char_length(metric_name) between 2 and 120),
  metric_value numeric not null,
  unit text not null check (char_length(unit) between 1 and 40),
  provenance text not null check (provenance in ('deterministic', 'synthetic', 'measured_local')),
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, evaluation_run_id)
    references evaluation_runs(tenant_id, workspace_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, case_result_id)
    references evaluation_case_results(tenant_id, workspace_id, id) on delete restrict
);

create table if not exists evaluation_exports (
  id uuid primary key,
  tenant_id uuid not null references tenants(id) on delete restrict,
  workspace_id uuid not null,
  evaluation_run_id uuid not null references evaluation_runs(id) on delete restrict,
  exporter text not null check (exporter in ('langsmith')),
  status text not null check (status in ('disabled', 'local_artifact', 'blocked', 'exported')),
  live_export boolean not null default false,
  artifact jsonb not null default '{}'::jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  unique (tenant_id, workspace_id, id),
  foreign key (tenant_id, workspace_id) references workspaces(tenant_id, id) on delete restrict,
  foreign key (tenant_id, workspace_id, evaluation_run_id)
    references evaluation_runs(tenant_id, workspace_id, id) on delete restrict
);

create index if not exists idx_evaluation_runs_workspace_created
  on evaluation_runs(workspace_id, created_at desc);
create index if not exists idx_evaluation_case_results_run
  on evaluation_case_results(evaluation_run_id, case_key);
create index if not exists idx_metric_values_run
  on metric_values(evaluation_run_id, metric_name);
create index if not exists idx_evaluation_exports_run
  on evaluation_exports(evaluation_run_id, exporter);

grant select, insert, update, delete on evaluation_suites to forge_runtime;
grant select, insert, update, delete on evaluation_cases to forge_runtime;
grant select, insert, update, delete on evaluation_runs to forge_runtime;
grant select, insert, update, delete on evaluation_case_results to forge_runtime;
grant select, insert, update, delete on metric_values to forge_runtime;
grant select, insert, update, delete on evaluation_exports to forge_runtime;

alter table evaluation_suites enable row level security;
alter table evaluation_suites force row level security;
alter table evaluation_cases enable row level security;
alter table evaluation_cases force row level security;
alter table evaluation_runs enable row level security;
alter table evaluation_runs force row level security;
alter table evaluation_case_results enable row level security;
alter table evaluation_case_results force row level security;
alter table metric_values enable row level security;
alter table metric_values force row level security;
alter table evaluation_exports enable row level security;
alter table evaluation_exports force row level security;

drop policy if exists evaluation_suites_scope on evaluation_suites;
create policy evaluation_suites_scope on evaluation_suites
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evaluation_suites_actor_select on evaluation_suites;
create policy evaluation_suites_actor_select on evaluation_suites
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evaluation_suites.tenant_id
        and m.workspace_id = evaluation_suites.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists evaluation_cases_scope on evaluation_cases;
create policy evaluation_cases_scope on evaluation_cases
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evaluation_cases_actor_select on evaluation_cases;
create policy evaluation_cases_actor_select on evaluation_cases
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evaluation_cases.tenant_id
        and m.workspace_id = evaluation_cases.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists evaluation_runs_scope on evaluation_runs;
create policy evaluation_runs_scope on evaluation_runs
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evaluation_runs_actor_select on evaluation_runs;
create policy evaluation_runs_actor_select on evaluation_runs
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evaluation_runs.tenant_id
        and m.workspace_id = evaluation_runs.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists evaluation_case_results_scope on evaluation_case_results;
create policy evaluation_case_results_scope on evaluation_case_results
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evaluation_case_results_actor_select on evaluation_case_results;
create policy evaluation_case_results_actor_select on evaluation_case_results
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evaluation_case_results.tenant_id
        and m.workspace_id = evaluation_case_results.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists metric_values_scope on metric_values;
create policy metric_values_scope on metric_values
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists metric_values_actor_select on metric_values;
create policy metric_values_actor_select on metric_values
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = metric_values.tenant_id
        and m.workspace_id = metric_values.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

drop policy if exists evaluation_exports_scope on evaluation_exports;
create policy evaluation_exports_scope on evaluation_exports
  using (tenant_id::text = current_setting('forge.tenant_id', true))
  with check (tenant_id::text = current_setting('forge.tenant_id', true));

drop policy if exists evaluation_exports_actor_select on evaluation_exports;
create policy evaluation_exports_actor_select on evaluation_exports
  for select
  using (
    exists (
      select 1 from memberships m
      where m.tenant_id = evaluation_exports.tenant_id
        and m.workspace_id = evaluation_exports.workspace_id
        and m.user_id::text = current_setting('forge.actor_id', true)
    )
  );

import json
from urllib.parse import urlparse

from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.planning_repositories import PromptRegistryRepository
from forge_api.infrastructure.repositories import IdentityRepository, TenantRepository
from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

TENANT_ID = "018f0000-0000-7000-8000-000000000001"
WORKSPACE_ID = "018f0000-0000-7000-8000-000000000101"
WORKFLOW_TEMPLATE_ID = "018f0000-0000-7000-8000-000000000201"
WORKFLOW_VERSION_ID = "018f0000-0000-7000-8000-000000000202"
TOOL_WORKFLOW_TEMPLATE_ID = "018f0000-0000-7000-8000-000000000301"
TOOL_WORKFLOW_VERSION_ID = "018f0000-0000-7000-8000-000000000302"
AGENT_WORKFLOW_TEMPLATE_ID = "018f0000-0000-7000-8000-000000000401"
AGENT_WORKFLOW_VERSION_ID = "018f0000-0000-7000-8000-000000000402"
MULTI_AGENT_WORKFLOW_TEMPLATE_ID = "018f0000-0000-7000-8000-000000000501"
MULTI_AGENT_WORKFLOW_VERSION_ID = "018f0000-0000-7000-8000-000000000502"


def _assert_local_database_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("The local demo seed can only reset a loopback PostgreSQL database.")


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_database_url(settings.migration_database_url)
    database = Database(settings.migration_database_url)
    with database.transaction(
        tenant_id=TENANT_ID,
        actor_id="00000000-0000-0000-0000-000000000000",
    ) as conn:
        conn.execute("delete from evaluation_exports")
        conn.execute("delete from metric_values")
        conn.execute("delete from evaluation_case_results")
        conn.execute("delete from evaluation_runs")
        conn.execute("delete from evaluation_cases")
        conn.execute("delete from evaluation_suites")
        conn.execute("delete from debugger_trace_exports")
        conn.execute("delete from debugger_replay_artifacts")
        conn.execute("delete from debugger_replay_sessions")
        conn.execute("delete from debugger_projection_verifications")
        conn.execute("delete from plan_edges")
        conn.execute("delete from plan_nodes")
        conn.execute("delete from plan_versions")
        conn.execute("delete from workflow_engine_checkpoints")
        conn.execute("delete from agent_iterations")
        conn.execute("delete from model_calls")
        conn.execute("delete from prompt_versions")
        conn.execute("delete from approval_decisions")
        conn.execute("delete from approval_requests")
        conn.execute("delete from evidence_items")
        conn.execute("delete from tool_invocations")
        conn.execute("delete from run_tool_grants")
        conn.execute("delete from integration_connections")
        conn.execute("delete from policy_versions")
        conn.execute("delete from dead_letters")
        conn.execute("delete from checkpoints")
        conn.execute("delete from inbox_messages")
        conn.execute("delete from outbox_messages")
        conn.execute("delete from execution_events")
        conn.execute("delete from task_attempts")
        conn.execute("delete from task_dependencies")
        conn.execute("delete from tasks")
        conn.execute("delete from strategy_comparisons")
        conn.execute("delete from runs")
        conn.execute("delete from objectives")
        conn.execute("delete from workflow_edges")
        conn.execute("delete from workflow_steps")
        conn.execute("delete from workflow_versions")
        conn.execute("delete from workflow_templates")
        conn.execute("delete from mcp_tool_mappings")
        conn.execute("delete from mcp_capability_snapshots")
        conn.execute("delete from mcp_servers")
        conn.execute("delete from tool_versions")
        conn.execute("delete from tool_definitions")
        conn.execute("delete from security_audit_events")
        conn.execute("delete from idempotency_records")
        conn.execute("delete from memberships")
        conn.execute("delete from workspaces")
        conn.execute("delete from tenants")
        conn.execute("delete from users where external_issuer = %s", (settings.oidc_issuer,))

        alice = IdentityRepository(conn).upsert_user_from_claims(
            {
                "iss": settings.oidc_issuer,
                "sub": "oidc|alice",
                "email": "alice@forge.local",
                "name": "Alice Admin",
            }
        )
        ava = IdentityRepository(conn).upsert_user_from_claims(
            {
                "iss": settings.oidc_issuer,
                "sub": "oidc|ava",
                "email": "ava@forge.local",
                "name": "Ava Approver",
            }
        )
        bob = IdentityRepository(conn).upsert_user_from_claims(
            {
                "iss": settings.oidc_issuer,
                "sub": "oidc|bob",
                "email": "bob@forge.local",
                "name": "Bob Viewer",
            }
        )
        conn.execute(
            "insert into tenants (id, name) values (%s, %s) on conflict (id) do nothing",
            (TENANT_ID, "Forge Local Demo"),
        )
        conn.execute(
            """
            insert into workspaces (id, tenant_id, name)
            values (%s, %s, %s)
            on conflict (id) do nothing
            """,
            (WORKSPACE_ID, TENANT_ID, "Security Demo Workspace"),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'tenant_admin')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, WORKSPACE_ID, alice["id"]),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'viewer')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, WORKSPACE_ID, bob["id"]),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'approver')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, WORKSPACE_ID, ava["id"]),
        )
        conn.execute(
            """
            insert into policy_versions
              (id, tenant_id, workspace_id, version, status, created_by)
            values (gen_random_uuid(), %s, %s, 1, 'active', %s)
            on conflict (tenant_id, workspace_id, version) do update
              set status = 'active'
            """,
            (TENANT_ID, WORKSPACE_ID, alice["id"]),
        )
        conn.execute(
            """
            insert into integration_connections
              (id, tenant_id, workspace_id, name, provider, mode,
               secret_reference, status, created_by)
            values (gen_random_uuid(), %s, %s, 'local-ticket-demo', 'local-fake-ticket',
                    'local_fake', 'secretref://local/ticket-demo', 'active', %s)
            on conflict (tenant_id, workspace_id, name) do update
              set mode = excluded.mode,
                  secret_reference = excluded.secret_reference,
                  status = excluded.status
            """,
            (TENANT_ID, WORKSPACE_ID, alice["id"]),
        )
        conn.execute(
            """
            insert into workflow_templates (id, tenant_id, workspace_id, name, created_by)
            values (%s, %s, %s, %s, %s)
            """,
            (
                WORKFLOW_TEMPLATE_ID,
                TENANT_ID,
                WORKSPACE_ID,
                "Incident Response Demo",
                alice["id"],
            ),
        )
        conn.execute(
            """
            insert into workflow_versions
              (id, tenant_id, workspace_id, template_id, version_number, status, name, created_by)
            values (%s, %s, %s, %s, 1, 'published', %s, %s)
            """,
            (
                WORKFLOW_VERSION_ID,
                TENANT_ID,
                WORKSPACE_ID,
                WORKFLOW_TEMPLATE_ID,
                "Incident Response Demo",
                alice["id"],
            ),
        )
        ToolRegistryRepository(conn).sync_code_registered_tools()
        PromptRegistryRepository(conn).sync_builtin_prompts()
        steps = [
            ("collect_logs", "Collect logs", "deterministic"),
            ("inspect_metrics", "Inspect metrics", "deterministic"),
            ("correlate", "Correlate evidence", "deterministic"),
            ("summarize", "Summarize findings", "deterministic"),
        ]
        for step_key, name, kind in steps:
            conn.execute(
                """
                insert into workflow_steps
                  (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
                values (gen_random_uuid(), %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (TENANT_ID, WORKSPACE_ID, WORKFLOW_VERSION_ID, step_key, name, kind),
            )
        edges = [
            ("collect_logs", "correlate"),
            ("inspect_metrics", "correlate"),
            ("correlate", "summarize"),
        ]
        for from_step, to_step in edges:
            conn.execute(
                """
                insert into workflow_edges
                  (id, tenant_id, workspace_id, workflow_version_id, from_step_key, to_step_key)
                values (gen_random_uuid(), %s, %s, %s, %s, %s)
                """,
                (TENANT_ID, WORKSPACE_ID, WORKFLOW_VERSION_ID, from_step, to_step),
            )
        conn.execute(
            """
            insert into workflow_templates (id, tenant_id, workspace_id, name, created_by)
            values (%s, %s, %s, %s, %s)
            """,
            (
                TOOL_WORKFLOW_TEMPLATE_ID,
                TENANT_ID,
                WORKSPACE_ID,
                "Typed Tool Demo",
                alice["id"],
            ),
        )
        conn.execute(
            """
            insert into workflow_versions
              (id, tenant_id, workspace_id, template_id, version_number, status, name, created_by)
            values (%s, %s, %s, %s, 1, 'published', %s, %s)
            """,
            (
                TOOL_WORKFLOW_VERSION_ID,
                TENANT_ID,
                WORKSPACE_ID,
                TOOL_WORKFLOW_TEMPLATE_ID,
                "Typed Tool Demo",
                alice["id"],
            ),
        )
        tool_steps = [
            (
                "deployment_history",
                "Read deployment history",
                {
                    "tool_name": "deployment_history.lookup",
                    "tool_version": 1,
                    "arguments": {"service": "api", "environment": "production"},
                },
            ),
            (
                "customer_reports",
                "Search customer reports",
                {
                    "tool_name": "customer_reports.search",
                    "tool_version": 1,
                    "arguments": {"product_area": "worker", "severity": "medium"},
                },
            ),
            (
                "simulated_ticket",
                "Create simulated ticket",
                {
                    "tool_name": "ticket.create_simulated",
                    "tool_version": 1,
                    "arguments": {
                        "title": "Investigate local worker signal",
                        "severity": "medium",
                        "dry_run": True,
                    },
                },
            ),
        ]
        for step_key, name, tool_input in tool_steps:
            conn.execute(
                """
                insert into workflow_steps
                  (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
                values (gen_random_uuid(), %s, %s, %s, %s, %s, 'tool', %s)
                """,
                (
                    TENANT_ID,
                    WORKSPACE_ID,
                    TOOL_WORKFLOW_VERSION_ID,
                    step_key,
                    name,
                    json.dumps(tool_input),
                ),
            )
        for from_step, to_step in [
            ("deployment_history", "simulated_ticket"),
            ("customer_reports", "simulated_ticket"),
        ]:
            conn.execute(
                """
                insert into workflow_edges
                  (id, tenant_id, workspace_id, workflow_version_id, from_step_key, to_step_key)
                values (gen_random_uuid(), %s, %s, %s, %s, %s)
                """,
                (TENANT_ID, WORKSPACE_ID, TOOL_WORKFLOW_VERSION_ID, from_step, to_step),
            )
        conn.execute(
            """
            insert into workflow_templates (id, tenant_id, workspace_id, name, created_by)
            values (%s, %s, %s, %s, %s)
            """,
            (
                AGENT_WORKFLOW_TEMPLATE_ID,
                TENANT_ID,
                WORKSPACE_ID,
                "Bounded Agent Demo",
                alice["id"],
            ),
        )
        conn.execute(
            """
            insert into workflow_versions
              (id, tenant_id, workspace_id, template_id, version_number, status, name, created_by)
            values (%s, %s, %s, %s, 1, 'published', %s, %s)
            """,
            (
                AGENT_WORKFLOW_VERSION_ID,
                TENANT_ID,
                WORKSPACE_ID,
                AGENT_WORKFLOW_TEMPLATE_ID,
                "Bounded Agent Demo",
                alice["id"],
            ),
        )
        agent_input = {
            "scenario": "success",
            "objective": (
                "Investigate the local deployment signal, collect evidence, and produce a "
                "cited conclusion without using live providers."
            ),
            "allowed_tools": [
                {"tool_name": "deployment_history.lookup", "tool_version": 1},
                {"tool_name": "customer_reports.search", "tool_version": 1},
            ],
            "budgets": {
                "max_iterations": 4,
                "max_tool_calls": 2,
                "max_model_calls": 4,
                "max_context_items": 4,
                "max_invalid_decisions": 1,
                "max_no_progress_decisions": 1,
                "max_output_tokens": 800,
            },
        }
        conn.execute(
            """
            insert into workflow_steps
              (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
            values (gen_random_uuid(), %s, %s, %s, 'bounded_agent',
                    'Run bounded agent investigation', 'agent', %s)
            """,
            (
                TENANT_ID,
                WORKSPACE_ID,
                AGENT_WORKFLOW_VERSION_ID,
                json.dumps(agent_input),
            ),
        )
        conn.execute(
            """
            insert into workflow_templates (id, tenant_id, workspace_id, name, created_by)
            values (%s, %s, %s, %s, %s)
            """,
            (
                MULTI_AGENT_WORKFLOW_TEMPLATE_ID,
                TENANT_ID,
                WORKSPACE_ID,
                "Multi-Agent Investigation Demo",
                alice["id"],
            ),
        )
        conn.execute(
            """
            insert into workflow_versions
              (id, tenant_id, workspace_id, template_id, version_number, status, name, created_by)
            values (%s, %s, %s, %s, 1, 'published', %s, %s)
            """,
            (
                MULTI_AGENT_WORKFLOW_VERSION_ID,
                TENANT_ID,
                WORKSPACE_ID,
                MULTI_AGENT_WORKFLOW_TEMPLATE_ID,
                "Multi-Agent Investigation Demo",
                alice["id"],
            ),
        )
        specialist_budgets = {
            "max_iterations": 4,
            "max_tool_calls": 2,
            "max_model_calls": 4,
            "max_context_items": 4,
            "max_invalid_decisions": 1,
            "max_no_progress_decisions": 1,
            "max_output_tokens": 800,
        }
        specialist_steps = [
            (
                "deployment_specialist",
                "Deployment specialist investigation",
                {
                    "scenario": "success",
                    "objective": "Investigate recent deployment history for regressions.",
                    "agent_role": "deployment_specialist",
                    "allowed_tools": [
                        {"tool_name": "deployment_history.lookup", "tool_version": 1}
                    ],
                    "budgets": specialist_budgets,
                },
            ),
            (
                "customer_impact_specialist",
                "Customer impact specialist investigation",
                {
                    "scenario": "success",
                    "objective": "Investigate customer-reported symptoms and severity.",
                    "agent_role": "customer_impact_specialist",
                    "allowed_tools": [{"tool_name": "customer_reports.search", "tool_version": 1}],
                    "budgets": specialist_budgets,
                },
            ),
            (
                "remediation_specialist",
                "Remediation specialist proposal",
                {
                    "scenario": "approval_interrupt",
                    "objective": "Propose a remediation ticket for exact-action approval.",
                    "agent_role": "remediation_specialist",
                    "allowed_tools": [{"tool_name": "ticket.create_simulated", "tool_version": 1}],
                    "budgets": specialist_budgets,
                },
            ),
        ]
        for step_key, name, agent_input in specialist_steps:
            conn.execute(
                """
                insert into workflow_steps
                  (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
                values (gen_random_uuid(), %s, %s, %s, %s, %s, 'agent', %s)
                """,
                (
                    TENANT_ID,
                    WORKSPACE_ID,
                    MULTI_AGENT_WORKFLOW_VERSION_ID,
                    step_key,
                    name,
                    json.dumps(agent_input),
                ),
            )
        conn.execute(
            """
            insert into workflow_steps
              (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
            values (gen_random_uuid(), %s, %s, %s, 'synthesize_findings',
                    'Synthesize specialist findings', 'deterministic', %s)
            """,
            (
                TENANT_ID,
                WORKSPACE_ID,
                MULTI_AGENT_WORKFLOW_VERSION_ID,
                json.dumps({"mode": "multi_agent_synthesize"}),
            ),
        )
        for from_step, _name, _agent_input in specialist_steps:
            conn.execute(
                """
                insert into workflow_edges
                  (id, tenant_id, workspace_id, workflow_version_id, from_step_key, to_step_key)
                values (gen_random_uuid(), %s, %s, %s, %s, 'synthesize_findings')
                """,
                (TENANT_ID, WORKSPACE_ID, MULTI_AGENT_WORKFLOW_VERSION_ID, from_step),
            )
        TenantRepository(conn).audit(
            "local.seeded",
            TENANT_ID,
            str(alice["id"]),
            {
                "workspace_id": WORKSPACE_ID,
                "workflow_version_id": WORKFLOW_VERSION_ID,
                "tool_workflow_version_id": TOOL_WORKFLOW_VERSION_ID,
                "agent_workflow_version_id": AGENT_WORKFLOW_VERSION_ID,
                "multi_agent_workflow_version_id": MULTI_AGENT_WORKFLOW_VERSION_ID,
            },
        )
    print("Forge local demo data seeded.")


if __name__ == "__main__":
    main()

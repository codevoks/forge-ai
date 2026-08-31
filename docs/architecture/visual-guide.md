# Forge AI visual guide

These diagrams are learning aids for the written contracts. They deliberately show where authority, durability, and security decisions live; they are not deployment claims.

## System topology and authority

PostgreSQL is the only authoritative execution store. Redis carries disposable scheduling hints. The API and workers share domain/application contracts while external systems remain behind ports.

```mermaid
flowchart LR
    U[User / browser]

    subgraph Presentation[Presentation boundary]
        WEB[Next.js web\nsession and UI]
    end

    subgraph Forge[Forge modular monolith]
        API[FastAPI /v1\ncommands and queries]
        APP[Application services\ntransaction orchestration]
        DOMAIN[Domain + policy\nstate, authz, approval, budgets]
        DISPATCH[Outbox dispatcher]
        WORKER[Python workers\nclaims and bounded execution]
        RUNTIME[Runtime / planner / tool ports]
    end

    subgraph Durable[Durable authority]
        PG[(PostgreSQL\nstate + events + outbox)]
    end

    subgraph Coordination[Disposable coordination]
        REDIS[(Redis Streams\nqueue / rate / cache)]
    end

    subgraph External[Untrusted or external boundaries]
        MODEL[Model providers]
        TOOLS[Internal tools + integrations]
        MCP[MCP servers]
    end

    OBS[OpenTelemetry\nLangfuse adapter]

    U --> WEB --> API --> APP --> DOMAIN
    APP -->|transaction| PG
    DISPATCH -->|read outbox| PG
    DISPATCH -->|publish at least once| REDIS
    REDIS -->|delivery may duplicate| WORKER
    WORKER -->|claim / result transaction| PG
    WORKER --> RUNTIME
    RUNTIME --> MODEL
    RUNTIME --> TOOLS
    RUNTIME --> MCP
    API -. traces .-> OBS
    WORKER -. traces .-> OBS
    RUNTIME -. traces .-> OBS
```

## Durable command and worker sequence

The two critical rules are visible here: commit state and outbox together, and acknowledge the queue only after the result transaction. Duplicate publication/delivery is expected.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as FastAPI
    participant PG as PostgreSQL
    participant D as Outbox dispatcher
    participant Q as Redis Streams
    participant W as Worker
    participant X as Model / tool provider

    User->>API: Create run + Idempotency-Key
    API->>PG: Begin transaction
    API->>PG: Write run, tasks, event, outbox
    API->>PG: Commit
    API-->>User: Accepted run
    D->>PG: Read unpublished outbox
    D->>Q: Publish durable IDs
    Note over D,Q: Crash here may publish twice
    D->>PG: Mark outbox published
    Q-->>W: Deliver message
    W->>PG: Atomically claim task + lease/fencing
    W->>PG: Persist authorized invocation intent
    W->>X: Bounded request with stable idempotency key
    X-->>W: Result or ambiguous timeout
    W->>PG: Commit result, event, checkpoint, next outbox
    W->>Q: Acknowledge message
    Note over W,Q: Crash before ack causes redelivery; durable state deduplicates
```

## Model proposal to authorized effect

The model never crosses directly into execution. Each deterministic gate can deny, suspend, or bound the proposal.

```mermaid
flowchart TD
    MODEL[Model proposes\nstructured plan or tool call]
    SCHEMA{Schema and semantic\nvalidation pass?}
    GRANT{Exact tool version\ngranted to this run?}
    AUTHZ{Actor and tenant\nauthorized?}
    RISK[Code classifies risk]
    BUDGET{Budget and limits\navailable?}
    APPROVAL{Exact-action approval\nrequired?}
    WAIT[Persist approval request\nand suspend]
    VALID{Valid, current, matching\napproval consumed?}
    INTENT[Persist invocation intent\nand idempotency identity]
    EXEC[Execute bounded adapter call]
    RESULT[Validate and label output\nas untrusted evidence]
    DENY[Fail closed and audit]

    MODEL --> SCHEMA
    SCHEMA -- no --> DENY
    SCHEMA -- yes --> GRANT
    GRANT -- no --> DENY
    GRANT -- yes --> AUTHZ
    AUTHZ -- no --> DENY
    AUTHZ -- yes --> RISK --> BUDGET
    BUDGET -- no --> DENY
    BUDGET -- yes --> APPROVAL
    APPROVAL -- no --> INTENT
    APPROVAL -- yes --> WAIT --> VALID
    VALID -- no --> DENY
    VALID -- yes --> INTENT --> EXEC --> RESULT
```

## Structured planning sequence

Phase 5 persists model interaction evidence separately from plan versions. A model call can fail or produce an invalid proposal while still leaving an auditable ledger entry. Only validated proposals receive persisted nodes and edges.

```mermaid
sequenceDiagram
    autonumber
    actor Operator
    participant API as FastAPI planning route
    participant APP as PlannerService
    participant PG as PostgreSQL
    participant MP as ModelProvider
    participant VAL as PlanValidator

    Operator->>API: POST /v1/runs/{id}:plan + Idempotency-Key
    API->>APP: ActorContext + run id + scenario/provider
    APP->>PG: Authorize run, load prompt version, tools, evidence
    APP->>MP: StructuredModelRequest
    MP-->>APP: StructuredModelResult
    APP->>VAL: Parse schema + validate DAG and allowed tools
    APP->>PG: Record model_call + plan_version + plan event
    alt valid
        APP-->>Operator: validated plan with nodes/edges
    else rejected
        APP-->>Operator: rejected plan with safe validation errors
    end
```

## Exact-action approval sequence

The worker cannot execute a high-risk simulated effect just because a model, workflow step, or queue message asks for it. The approval request is committed first, then the worker exits. Approval later revalidates the exact action and requeues the same task.

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker
    participant PG as PostgreSQL
    participant A as Approver API
    participant Q as Redis Streams
    participant T as Tool adapter

    W->>PG: Claim tool task + persist invocation intent
    W->>PG: Compute action hash + binding hash
    W->>PG: Insert approval_request pending
    W->>PG: Mark task waiting_approval
    W-->>Q: Ack original queue message
    Note over W,T: Adapter is not invoked while approval is pending
    A->>PG: Approve/reject with Idempotency-Key + If-Match
    PG->>PG: Revalidate approver, version, expiry, state, binding hash
    alt approved exact action
        PG->>PG: Mark invocation authorized + task ready
        PG->>PG: Add outbox task.execute.requested
        Q-->>W: Deliver resumed task
        W->>PG: Consume approval once
        W->>T: Execute bounded local adapter
        W->>PG: Persist result, event, checkpoint, evidence
    else rejected, expired, stale, or mutated
        PG->>PG: Mark invocation policy_denied and fail task/run
    end
```

## Workflow shape and bounded autonomy

Forge keeps the user/planner work graph acyclic. Model-controlled iteration lives inside one task and is bounded independently, so dependency scheduling and termination remain explainable.

```mermaid
flowchart LR
    subgraph RunDAG[Validated immutable plan version]
        A[Collect deployment history]
        B[Collect customer reports]
        C[Correlate evidence]
        D[Propose remediation]
        E[Request exact-action approval]
        F[Produce final result]
        A --> C
        B --> C
        C --> D --> E --> F
    end

    subgraph AgentTask[Bounded agent loop inside a task]
        P[Perceive selected state + evidence]
        DECIDE{Structured decision}
        RECORD[Persist model_call + agent_iteration + checkpoint]
        ACT[Authorized tool call]
        DONE[Complete or fail closed]
        P --> DECIDE
        DECIDE --> RECORD
        RECORD -->|tool call within grants and limits| ACT --> P
        RECORD -->|success, invalid, budget, timeout, no progress| DONE
    end

    C -. may use .-> AgentTask
```

## Lifecycle visuals

The canonical run and task state diagrams live beside their invariants in the [domain and workflow model](domain-workflow-model.md). The [failure model](failure-model.md) explains what happens at every crash, retry, cancellation, and ambiguous-effect edge.

## Current typed tool runtime subset

The current implementation adds typed, versioned tools to the worker path without allowing arbitrary browser-triggered execution. A workflow step references a registered tool, run creation snapshots an exact grant, and the worker revalidates that grant before executing a deterministic local adapter.

```mermaid
flowchart TD
    CODE[Code-registered tool catalog]
    DEF[tool_definitions]
    VER[tool_versions\nschema + risk + limits]
    WSTEP[Workflow step\nkind=tool + name/version/args]
    RUN[Run creation]
    GRANT[run_tool_grants\nexact version snapshot]
    OUTBOX[Outbox + Redis\nminimal task IDs]
    WORKER[Worker claim\nlease + tenant scope]
    VALIDATE{Grant, schema,\nrisk policy valid?}
    INTENT[tool_invocations\nintent + action hash]
    ADAPTER[Deterministic local adapter]
    UNKNOWN[outcome_unknown\nreconciliation needed]
    EVIDENCE[evidence_items\ntrust label + content hash]
    DENY[Fail closed\nsafe error]

    CODE --> DEF --> VER
    WSTEP --> RUN --> GRANT
    RUN --> OUTBOX --> WORKER --> VALIDATE
    VER --> VALIDATE
    GRANT --> VALIDATE
    VALIDATE -- no --> DENY
    VALIDATE -- yes --> INTENT --> ADAPTER
    ADAPTER -- success --> EVIDENCE
    ADAPTER -- ambiguous --> UNKNOWN
```

## Current durable workflow execution subset

The current implementation persists immutable workflow versions, instantiates a run-scoped task DAG, evaluates dependency readiness transactionally, writes outbox records beside state transitions, dispatches work through local Redis Streams, and has workers claim, lease, checkpoint, retry, dead-letter, cancel, and recover tasks. Typed deterministic tools now execute through the worker runtime with run-scoped grants, invocation ledgers, and evidence provenance. Model calls, approvals, replay UI, MCP mediation, and multi-agent routing remain behind later-phase boundaries.

```mermaid
flowchart TD
    WFV[Published WorkflowVersion\nimmutable DAG snapshot]
    OBJ[Objective\nuser text + constraints]
    RUN[Run\ncreated -> running -> succeeded]
    TASKS[Tasks\npending / ready / running / retry_wait / succeeded / failed / cancelled]
    DEPS[TaskDependencies\nadjacency rows]
    EVENTS[ExecutionEvents\nappend-only transition history]
    OUTBOX[OutboxMessages\nminimal durable IDs]
    REDIS[Redis Streams\nat-least-once queue]
    WORKER[WorkerConsumer\nclaim + lease + fencing]
    ATTEMPT[TaskAttempt\nworker, lease, fencing token]
    CHECKPOINT[Checkpoint\nvalidated task result]
    DEAD[DeadLetter\nsanitized failure]
    RECOVERY[Recovery scan\nleases, retries, republish]
    MANUAL[Manual deterministic advance\nlocal fallback]

    WFV -->|pin version| RUN
    OBJ -->|snapshot| RUN
    WFV -->|instantiate steps| TASKS
    WFV -->|instantiate edges| DEPS
    RUN --> TASKS
    TASKS --> DEPS
    TASKS -->|ready event in same transaction| OUTBOX
    OUTBOX -->|dispatch| REDIS
    REDIS -->|duplicate delivery possible| WORKER
    WORKER -->|atomic claim| ATTEMPT
    ATTEMPT -->|success| CHECKPOINT
    ATTEMPT -->|retryable failure| TASKS
    ATTEMPT -->|exhausted / permanent failure| DEAD
    CHECKPOINT --> EVENTS
    DEAD --> EVENTS
    RECOVERY -->|expired lease / due retry / Redis loss| OUTBOX
    MANUAL -->|debug path| TASKS
```

## Recovery and duplicate-delivery decision flow

PostgreSQL decides whether a job is still legal. Redis loss or duplicate delivery cannot advance state by itself.

```mermaid
flowchart TD
    MSG[Queue message\nminimal IDs]
    INBOX{Inbox already\nsucceeded?}
    LOAD[Reload run/task\nunder tenant scope]
    LEGAL{Run running and\ntask ready?}
    CLAIM[Create attempt\nlease + fencing token]
    EXEC[Execute bounded\ndeterministic unit]
    COMMIT{Attempt + fencing\nstill current?}
    OK[Persist task success,\ncheckpoint, event,\nnext outbox]
    RETRY[Persist retry_wait\nwith backoff]
    DLQ[Persist sanitized\ndead letter]
    SKIP[Skip / acknowledge\nwithout state change]
    RECOVER[Recovery scanner\nrequeues eligible work]

    MSG --> INBOX
    INBOX -- yes --> SKIP
    INBOX -- no --> LOAD
    LOAD --> LEGAL
    LEGAL -- no --> SKIP
    LEGAL -- yes --> CLAIM --> EXEC --> COMMIT
    COMMIT -- stale --> SKIP
    COMMIT -- success --> OK
    COMMIT -- retryable failure --> RETRY --> RECOVER
    COMMIT -- permanent failure --> DLQ
    RECOVER --> MSG
```

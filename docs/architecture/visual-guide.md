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
        ACT[Authorized tool call]
        DONE[Complete or fail]
        P --> DECIDE
        DECIDE -->|tool call within limits| ACT --> P
        DECIDE -->|success, failure, budget, timeout, no progress| DONE
    end

    C -. may use .-> AgentTask
```

## Lifecycle visuals

The canonical run and task state diagrams live beside their invariants in the [domain and workflow model](domain-workflow-model.md). The [failure model](failure-model.md) explains what happens at every crash, retry, cancellation, and ambiguous-effect edge.


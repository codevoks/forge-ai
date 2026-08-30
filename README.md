# Forge AI

Forge AI is a durable agent and workflow platform built as a production-grade learning project. It starts as a modular monolith with separate web, API, and worker processes, PostgreSQL as the authoritative store, and deterministic local infrastructure for development and demonstrations.

## Local development

The default local path is zero-cost. It uses local services and deterministic fixtures, and it does not require billing credentials, paid model APIs, cloud infrastructure, or a purchased domain.

```bash
pnpm install
pnpm demo
```

The demo command starts the local database, applies migrations, seeds a deterministic identity scenario, and starts the web, API, and worker health shells.

## Quality checks

```bash
pnpm lint
pnpm test
pnpm test:security
```

Live providers and cloud infrastructure are not part of the default commands.

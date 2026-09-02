# Build from the repository root: docker build -f apps/web/Dockerfile .
# Uses Next.js "standalone" output (next.config.ts) to ship only the
# traced production dependency subset, not the full node_modules tree.

FROM node:22.12.0-slim AS builder
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/api/package.json apps/api/package.json
COPY apps/worker/package.json apps/worker/package.json
COPY packages/config/package.json packages/config/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
# --ignore-scripts: the root postinstall provisions a Python venv for the
# API/worker packages, which this JS-only image build neither needs nor
# has an interpreter for.
RUN pnpm install --frozen-lockfile --filter @forge/web... --ignore-scripts
COPY apps/web apps/web
COPY packages/config packages/config
COPY packages/shared-types packages/shared-types
RUN pnpm --filter @forge/web build

FROM node:22.12.0-slim AS runtime
RUN groupadd --system --gid 10001 forge \
    && useradd --system --uid 10001 --gid forge --no-create-home --shell /usr/sbin/nologin forge
WORKDIR /app
COPY --from=builder /repo/apps/web/.next/standalone ./
COPY --from=builder /repo/apps/web/.next/static ./apps/web/.next/static
# No apps/web/public directory exists yet (Phase 1 minimal health shell has
# no static assets); add a COPY line here if/when one is introduced.
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
USER 10001:10001
EXPOSE 3000
ENTRYPOINT ["node", "apps/web/server.js"]

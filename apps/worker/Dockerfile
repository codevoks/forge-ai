# Build from the repository root: docker build -f apps/worker/Dockerfile .
#
# forge_worker.main imports forge_api directly (application/domain/
# infrastructure reuse across the worker/API boundary) but apps/worker's own
# pyproject.toml does not declare forge-api as a dependency — a real,
# pre-existing packaging gap this Dockerfile works around the same way
# local dev does (installing both packages into one environment), not a
# gap introduced or fixed here.

FROM python:3.11-slim AS builder
WORKDIR /build
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY apps/worker/src apps/worker/src
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir ./apps/api ./apps/worker

FROM python:3.11-slim AS runtime
RUN groupadd --system --gid 10001 forge \
    && useradd --system --uid 10001 --gid forge --no-create-home --shell /usr/sbin/nologin forge
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "-m", "forge_worker.main"]

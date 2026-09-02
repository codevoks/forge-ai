# Build from the repository root: docker build -f apps/api/Dockerfile .
# Multi-stage: the builder stage has pip/build tooling; the runtime stage
# ships only a venv and the interpreter, runs as a non-root user, and never
# needs a writable root filesystem at startup.

FROM python:3.11-slim AS builder
WORKDIR /build
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir ./apps/api

FROM python:3.11-slim AS runtime
RUN groupadd --system --gid 10001 forge \
    && useradd --system --uid 10001 --gid forge --no-create-home --shell /usr/sbin/nologin forge
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["uvicorn", "forge_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

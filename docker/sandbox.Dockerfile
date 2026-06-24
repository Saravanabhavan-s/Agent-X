FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

COPY agentx/ ./agentx/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Non-root user for isolation
RUN useradd -m -u 1000 agentx
USER agentx

WORKDIR /workspace

ENTRYPOINT ["python", "-m", "agentx.cli.main"]

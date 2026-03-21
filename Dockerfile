FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY data/ data/

# uv.lock may not exist yet
COPY uv.loc* ./

RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ---------------------------------------------------------------------------
FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 18420

ENTRYPOINT ["kani"]
CMD ["serve", "--config", "/app/config.yaml"]

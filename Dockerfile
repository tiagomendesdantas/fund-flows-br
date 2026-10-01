FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY web ./web
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && chown -R app /app
USER app

# Railway injects PORT and DATABASE_URL. One replica: the scheduler thread runs in this process.
CMD ["sh", "-c", ".venv/bin/uvicorn flows.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

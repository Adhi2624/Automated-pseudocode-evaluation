FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first for better layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY common ./common
COPY pseudo_evaluation ./pseudo_evaluation
COPY fastapi ./fastapi
COPY questions.json ./

RUN useradd --system --no-create-home app && chown -R app /app
USER app

ENV PORT=8000
EXPOSE 8000

# Web app by default; the Render cron job overrides this with the grader command.
CMD ["sh", "-c", "exec uvicorn main:app --app-dir fastapi --host 0.0.0.0 --port ${PORT}"]

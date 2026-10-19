FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --extra test --no-dev

COPY . .
CMD ["uv", "run", "--no-sync", "fastframe", "--help"]

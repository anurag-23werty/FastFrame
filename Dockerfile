FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --extra test --no-dev --no-install-project

COPY . .
RUN uv sync --locked --extra test --no-dev

RUN useradd --create-home --uid 10001 fastframe \
    && chown -R fastframe:fastframe /app
ENV PATH="/app/.venv/bin:$PATH" \
    UV_OFFLINE=1 \
    UV_PYTHON_DOWNLOADS=never
USER fastframe
ENTRYPOINT ["fastframe"]
CMD ["--help"]

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY ptbr_benchmark ./ptbr_benchmark
RUN uv sync --frozen --no-dev

COPY tasks ./tasks

RUN useradd --create-home --uid 10001 benchmark && chown -R benchmark:benchmark /app
USER benchmark

ENV PATH="/app/.venv/bin:${PATH}" \
    PTBR_BENCHMARK_RESULTS_DIR=/data/results \
    PTBR_BENCHMARK_DOCS_DIR=/data/docs \
    PTBR_BENCHMARK_SITE_DIR=/data/site \
    PTBR_BENCHMARK_CACHE_PATH=/data/cache.sqlite

VOLUME ["/data"]
ENTRYPOINT ["ptbr-benchmark"]
CMD ["--help"]

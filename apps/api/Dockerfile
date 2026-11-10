# trixie ships ffmpeg 7.x
FROM python:3.12-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# The venv lives outside the bind-mounted source tree.
# NUMBA_CPU_NAME=generic: Docker Desktop's arm64 VM advertises CPU features (SVE2) it cannot
# execute, so host-tuned JIT code (librosa uses numba) dies with SIGILL.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NUMBA_CPU_NAME=generic \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /repo/apps/api
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY . .

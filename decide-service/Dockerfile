# SoldierIQ decide-service: base d1-omni-600M (int8) on CPU. Railway sets PORT.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    HF_HOME=/data/hf HF_HUB_DISABLE_TELEMETRY=1
RUN pip install --no-cache-dir uv==0.6.14

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY model.py server.py ./

# The model (~860 MB) downloads from the private HF repo on first start (needs HF_TOKEN) into
# HF_HOME. Mount a Railway volume at /data so restarts and redeploys reuse it instead of re-downloading.
CMD ["uv", "run", "--no-sync", "python", "server.py"]

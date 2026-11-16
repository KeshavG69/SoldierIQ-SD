# SoldierIQ Sensor Hub - cloud mode (Railway sets PORT; HTTPS is terminated by the platform).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.6.14

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY server.py ./
COPY static ./static

# Run ONE instance: live frames and phone connections live in memory.
CMD ["uv", "run", "--no-sync", "python", "server.py"]

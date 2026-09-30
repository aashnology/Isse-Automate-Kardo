FROM python:3.12-slim

WORKDIR /app

# Install deps first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY .env.example ./.env.example

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    MCP_SERVER_PORT=8000

EXPOSE 8000

WORKDIR /app/src

# Data is regenerated deterministically (seeded) on first boot if missing --
# see synthetic_data.py -- so nothing needs to be baked into the image.
CMD ["python", "mcp_server.py"]

FROM python:3.12-slim

WORKDIR /app

# Install deps first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY web/ ./web/
COPY .env.example ./.env.example

ENV PYTHONUNBUFFERED=1 \
    MCP_SERVER_PORT=8000 \
    WEB_PORT=5000

# 8000: MCP server (Streamable HTTP, protocol 2025-11-25+) at /mcp
# 5000: Hexi web demo and /api/agent, which calls the MCP server
EXPOSE 8000 5000

# One image, two services. The default command is the MCP server; the web
# service overrides it (see docker-compose.yml, or `docker run ... python /app/web/server.py`).
# Data is regenerated deterministically (seeded) on first boot if missing --
# see synthetic_data.py -- so nothing needs to be baked into the image.
WORKDIR /app/src
CMD ["python", "mcp_server.py"]

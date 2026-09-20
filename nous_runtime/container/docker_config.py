# -*- coding: utf-8 -*-
"""Docker configuration generation."""
from __future__ import annotations

DOCKER_COMPOSE_TEMPLATE = """version: "3.8"
services:
  nous-runtime:
    build: .
    container_name: nous-runtime
    ports:
      - "9770:9770"
      - "8080:8080"
    volumes:
      - nous_data:/opt/nous/data
      - ./config:/opt/nous/config:ro
    environment:
      - NOUS_HOME=/opt/nous
      - NOUS_HOST=0.0.0.0
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "nous_runtime.cli.main", "doctor"]
      interval: 30s
      timeout: 10s
      retries: 3

  nous-worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    container_name: nous-worker
    volumes:
      - nous_data:/opt/nous/data
    environment:
      - NOUS_HOME=/opt/nous
      - NOUS_CONTROL_PLANE=nous-runtime:9770
    restart: unless-stopped

volumes:
  nous_data:
"""

DOCKERFILE_TEMPLATE = """FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/nous

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV NOUS_HOME=/opt/nous
ENV PYTHONUNBUFFERED=1

EXPOSE 9770 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -m nous_runtime.cli.main doctor

CMD ["python", "-m", "nous_runtime.cli.main", "server", "start"]
"""

def generate_docker_compose(port: int = 9770, api_port: int = 8080) -> str:
    """Generate docker-compose.yml content."""
    return DOCKER_COMPOSE_TEMPLATE.replace("9770:9770", f"{port}:9770").replace("8080:8080", f"{api_port}:8080")

def generate_dockerfile() -> str:
    """Generate Dockerfile content."""
    return DOCKERFILE_TEMPLATE

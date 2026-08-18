# Imagen multi-stage: una etapa por entorno (dev / prod).
# La etapa se elige desde el docker-compose de cada entorno (build.target).
#
# dev  → instala dev deps y NO copia el código (el compose montea el repo como volumen).
# prod → solo runtime deps, código copiado dentro de la imagen.

# ETAPA 1: Base común
FROM python:3.13-slim-trixie AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PREFECT_HOME=/app/.prefect \
    UV_SYSTEM_PYTHON=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/ /app/requirements/

# ETAPA 2: Desarrollo (local)
FROM base AS dev
RUN uv pip install --no-cache -r requirements/dev.txt
RUN groupadd -r etlgroup && useradd -r -m -g etlgroup etluser
USER etluser
CMD ["bash", "/app/.deploy/entrypoint.sh"]

# ETAPA 3: Producción
FROM base AS prod
RUN uv pip install --no-cache -r requirements/prod.txt
COPY . /app
RUN groupadd -r etlgroup && useradd -r -m -g etlgroup etluser && \
    chown -R etluser:etlgroup /app
USER etluser
CMD ["bash", "/app/.deploy/entrypoint.sh"]

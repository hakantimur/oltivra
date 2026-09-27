# Reproducible Cloud Run image for the Oltivra backend.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY seed ./seed

RUN useradd --uid 10001 --no-create-home oltivra
USER oltivra

ENV PORT=8080
CMD ["sh", "-c", "exec uvicorn app.main:app_from_env --factory --host 0.0.0.0 --port ${PORT} --workers 1"]

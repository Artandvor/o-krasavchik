# syntax=docker/dockerfile:1.7
# ---------- 1. зависимости (сборочный слой) ----------
FROM python:3.12.8-slim-bookworm AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --prefix=/install -r /tmp/requirements.txt

# ---------- 2. пайплайн данных и тесты (docker compose --profile pipeline) ----------
FROM python:3.12.8-slim-bookworm AS pipeline
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
COPY --from=deps /install /usr/local
COPY requirements-pipeline.txt /tmp/requirements-pipeline.txt
RUN pip install -r /tmp/requirements-pipeline.txt && useradd -m -u 10001 app
WORKDIR /app
COPY --chown=app:app . .
USER app
CMD ["sh", "-c", "python scripts/fetch_data.py && python scripts/prepare_region.py && python scripts/run_agents.py --fresh"]

# ---------- 3. рантайм: только приложение и демо-данные ----------
FROM python:3.12.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=8080 ODIN_DB=/app/var/odin.sqlite
COPY --from=deps /install /usr/local
RUN useradd -m -u 10001 app
WORKDIR /app
COPY --chown=app:app . .
RUN mkdir -p /app/var && chown app:app /app/var
USER app
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"
CMD ["python", "run.py"]

# Multi-stage-friendly slim image. Pinned base for reproducible builds.
FROM python:3.12-slim

# Don't write .pyc files; flush stdout/stderr immediately for clean container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so this layer is cached unless requirements change.
# Create the non-root user before copying files so --chown works.
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Container-native health check so orchestrators can detect a wedged process.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]

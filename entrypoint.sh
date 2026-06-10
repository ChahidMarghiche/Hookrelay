#!/bin/sh
chown -R appuser:appuser /data 2>/dev/null || true
exec su -s /bin/sh appuser -c "uvicorn app.main:app --host 0.0.0.0 --port 8000"

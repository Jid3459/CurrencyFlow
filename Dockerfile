# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CurrencyFlow - Docker image
# Builds a small production image with gunicorn serving the Flask app.
# ---------------------------------------------------------------------------

FROM python:3.13-slim

# Don't write .pyc files; flush stdout/stderr immediately so Docker logs work.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so Docker can cache this layer separately from
# the source code (rebuilds only re-run when requirements.txt changes).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application source.
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Run as a non-root user for safety.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Healthcheck so Docker / orchestrators know when the container is ready.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:5000/health', timeout=3).status == 200 else 1)"

# Production WSGI server. We run 1 worker x 8 threads (instead of multiple
# workers) so that in-memory state - watchlist, alerts, recent conversions,
# cache - is shared across all concurrent requests. Multiple gunicorn workers
# fork separate memory spaces, which would split that state. To scale beyond
# 1 instance, move state to Redis/Postgres and bump workers.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--threads", "8", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]

# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Install dependencies before copying the source so this layer remains cached
# when only application code changes.
COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpotrace-dev \
    libagg-dev \
    pkg-config \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

# Copy only the production runtime files allowed by .dockerignore.
COPY . /app/

# Expose port 8000
EXPOSE 8000

# Local-only Flask web entry point. AWS Fargate overrides this command with
# ``python -u worker.py --task-id ...`` and never exposes the Flask server.
# One process keeps the local in-memory cache coherent across request threads.
CMD ["gunicorn", "--workers=1", "--threads=4", "--timeout=1200", "--bind", "0.0.0.0:8000", "--error-logfile=-", "--capture-output", "app:app"]

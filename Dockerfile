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

# Keep the image independently runnable. In the AWS host-mounted deployment,
# Kubernetes overlays /app with the checked-out repository at runtime.
COPY . /app/

# Expose port 8000
EXPOSE 8000

# FIX: Reduce workers to 1 so they share a single unified global memory cache space
CMD ["gunicorn", "--workers=1", "--threads=4", "--timeout=1200", "--bind", "0.0.0.0:8000", "--error-logfile=-", "--capture-output", "app:app"]

# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy server and scripts
COPY lib/ /app/lib/
COPY static/ /app/static/
COPY templates/ /app/templates/
COPY app.py /app/

# Expose port 8000
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# 3. Copy the requirements file first (optimizes Docker layer caching)
COPY requirements.txt .

RUN apt-get update && apt-get install -y \
    build-essential \
    libpotrace-dev \ 
    libagg-dev \ 
    pkg-config \ 
    python3-dev
    
# 4. Install the Python modules
RUN pip install --no-cache-dir -r requirements.txt

# Run the server
CMD ["gunicorn", "--workers=2", "--threads=4", "--timeout=1200", "--bind", "0.0.0.0:8000", "app:app"]



# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy server and scripts
COPY server.py /app/
COPY html/ /app/html/
COPY cgi-bin/ /app/cgi-bin/
COPY lib/ /app/lib/

# Expose port 8000
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# 3. Copy the requirements file first (optimizes Docker layer caching)
COPY requirements.txt .

# 4. Install the Python modules
RUN pip install --no-cache-dir -r requirements.txt

# Run the server
CMD ["python3", "server.py"]




FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p aidrin/data/uploads aidrin/data/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=aidrin.main

# Expose ports
EXPOSE 5000 5555

# Default command
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"] 
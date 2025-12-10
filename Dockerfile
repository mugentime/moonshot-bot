FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache buster - change this value to force rebuild
ARG CACHE_BUST=20251210-switch-to-momentum-hunter

# Copy application code
COPY . .

# Expose port for health checks
EXPOSE 8050

# Run the momentum hunter bot
CMD ["python", "main_momentum.py"]

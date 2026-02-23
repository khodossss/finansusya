FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cache-friendly)
COPY pyproject.toml ./
RUN pip install --no-cache-dir . 

# Copy application code
COPY app/ ./app/
COPY tests/ ./tests/
COPY notebooks/ ./notebooks/
COPY entrypoint.sh ./entrypoint.sh

# Install curl for ngrok health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create data & logs directories
RUN mkdir -p data logs

EXPOSE 8000

CMD ["python", "-m", "app"]

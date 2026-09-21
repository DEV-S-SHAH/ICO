# Intelligent Cache Optimization - Production Container Image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# Install minimal system dependencies for healthcheck & network tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root app user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

WORKDIR /app

# Copy dependency specifications first for layer caching
COPY pyproject.toml README.md ./
COPY requirements.txt* ./

# Install package dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Copy application and library source
COPY --chown=appuser:appuser . /app

# Ensure proper permissions for runtime storage
RUN mkdir -p /app/intelligent_cache_storage && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose API and Dashboard ports
EXPOSE 8000 8501

# Health check against FastAPI health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default execution: run the production FastAPI middleware server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

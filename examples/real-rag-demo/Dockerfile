FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY packages/ico-cache-py /app/packages/ico-cache-py
RUN pip install --no-cache-dir -e /app/packages/ico-cache-py

COPY examples/real-rag-demo/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY examples/real-rag-demo /app/examples/real-rag-demo

ENV PYTHONPATH="/app/packages/ico-cache-py/src:/app"
EXPOSE 8000

CMD ["python", "examples/real-rag-demo/src/main.py", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy concord-mcp application first to get requirements.txt
COPY concord-mcp/ /app/

# Install all Python dependencies (strip the -e ../medsafe_core editable line)
RUN grep -v 'medsafe_core' /app/requirements.txt > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Copy medsafe_core source and make it importable via PYTHONPATH
COPY medsafe_core/ /medsafe_core/
ENV PYTHONPATH="/"

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

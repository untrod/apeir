FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY remote_terminal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY remote_terminal/ .

# Data directory
RUN mkdir -p /app/data

EXPOSE 8770

CMD ["python", "brain.py"]

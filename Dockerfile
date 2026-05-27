FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio and media processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    opus-tools \
    libopus-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot.py .
COPY config/ ./config/
COPY data/ ./data/

# Create data directory for database if it doesn't exist
RUN mkdir -p /app/data

CMD ["python", "-u", "bot.py"]

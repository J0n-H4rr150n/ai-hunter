FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Copy poetry files
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Use ENTRYPOINT with shell form to run migrations then start server
ENTRYPOINT ["/bin/bash", "-c", "echo '🔄 Running migrations...' && alembic upgrade head && echo '🚀 Starting server...' && exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"]

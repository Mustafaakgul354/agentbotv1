
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

# Install Python deps (including optional extras used by the app)
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --upgrade pip \
    && pip install ".[browser,email]"

EXPOSE 8000

# Default command (docker-compose overrides with --reload for dev)
CMD ["uvicorn", "agentbot.app.main:app", "--host", "0.0.0.0", "--port", "8000"]



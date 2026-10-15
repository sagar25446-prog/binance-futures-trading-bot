FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot ./bot
COPY cli.py main.py ./

# Run as an unprivileged user; logs go to a writable directory.
RUN useradd --create-home --uid 1000 botuser \
    && mkdir -p /app/logs \
    && chown -R botuser /app
USER botuser

# Pass credentials at runtime, never bake them into the image:
#   docker run --rm --env-file .env trading-bot account
ENTRYPOINT ["python", "cli.py"]
CMD ["--help"]

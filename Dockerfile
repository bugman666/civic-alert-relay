# Slim image for a long-running self-hosted relay.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAR_HOST=0.0.0.0 \
    CAR_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1000 --create-home car

COPY pyproject.toml LICENSE README.md ./
COPY civic_alert_relay ./civic_alert_relay

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8080
USER car
CMD ["civic-alert-relay"]

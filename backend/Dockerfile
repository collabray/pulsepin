FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM base AS runtime
COPY --from=deps /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Run as a non-root user (Security Architecture: least-privilege).
RUN useradd --create-home --uid 1000 pulsepin
COPY . .
RUN chown -R pulsepin:pulsepin /app
USER pulsepin

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

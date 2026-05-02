# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY services/payment-service/requirements.txt .
# Mount an optional certs/ folder at repo root (never baked into the image).
# Create certs/ and drop your CA bundle (.crt files) there to fix pip SSL errors.
RUN --mount=type=bind,source=certs,target=/certs,required=false \
    if [ -d /certs ] && ls /certs/*.crt > /dev/null 2>&1; then \
      cp /certs/*.crt /usr/local/share/ca-certificates/ && \
      update-ca-certificates; \
    fi && \
    pip install --no-cache-dir -r requirements.txt
COPY services/payment-service/ .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

LABEL org.opencontainers.image.title="paperless-pay" \
      org.opencontainers.image.description="SEPA EPC-QR payment page for paperless-ngx" \
      org.opencontainers.image.source="https://github.com/cehser/paperless-pay" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

EXPOSE 8080

# Default: web app. Override with command: for the link worker.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]

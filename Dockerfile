FROM python:3.12-slim

LABEL org.opencontainers.image.title="paperless-pay" \
      org.opencontainers.image.description="SEPA EPC-QR payment page for paperless-ngx" \
      org.opencontainers.image.source="https://github.com/cehser/paperless-pay" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Default: Web-App. Für den Link-Worker mit command: überschreiben.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]

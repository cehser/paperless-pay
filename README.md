# paperless-pay

SEPA EPC-QR payment page for [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx).

Displays payment information, generates EPC QR codes, and lets you mark documents as paid – all via cookie passthrough, no separate auth layer required.

## Features

- **EPC QR Code** – SEPA Credit Transfer QR code (scannable with banking apps)
- **Payment overview** – IBAN, BIC, amount, remittance info from Paperless custom fields
- **PDF preview** – Document preview side-by-side with payment details
- **Mark as paid** – Sets a boolean custom field in Paperless
- **IBAN validation** – Via [schwifty](https://github.com/mdomke/schwifty) (ISO 13616)
- **Field editing** – Experimental, enabled via feature switch (`ENABLE_EDIT=true`)
- **Link worker** – Automatically sets pay-links in a URL custom field for all invoices
- **Remittance template** – Configurable with variables
- **Localization** – English and German included, selectable via `LANGUAGE` env variable

## Quickstart

### 1. Prerequisites

- Running **paperless-ngx** instance with Docker Compose
- Custom fields created in Paperless: IBAN, Amount, Remittance info, Paid (+ optionally BIC, Pay-Link)
- Reverse proxy (nginx etc.) that enables cookie passthrough

### 2. Compose setup

```bash
# Clone this repo as a subdirectory in your Paperless Compose directory
cd /opt/paperless            # ← your Paperless Compose dir
git clone https://github.com/eehser/paperless-pay.git pay-poc

# Create env files
cp pay-poc/.env.sample pay-poc/.env
cp pay-poc/.env.worker.sample pay-poc/.env.worker
# → Edit pay-poc/.env (custom field IDs, URLs, etc.)
# → Edit pay-poc/.env.worker (API token, pay-link field, filter)
```

### 3. Start

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker/compose.example.yml \
  up -d
```

> The compose file `docker/compose.example.yml` is an **example**.
> Adapt it to your setup (service names, networks, ports).

### 4. Test

1. Log in to Paperless in your browser
2. Navigate to: `https://your-domain.com/pay/doc/123`

## Image

The image is built automatically via GitHub Actions and published to GHCR:

```
ghcr.io/eehser/paperless-pay:latest
```

### Tags

| Tag | When | Example |
|---|---|---|
| `latest` | Every push to `main` | `ghcr.io/eehser/paperless-pay:latest` |
| `sha-<hash>` | Every push to `main` | `ghcr.io/eehser/paperless-pay:sha-abc1234` |
| `v1.2.3` | Git tag `v1.2.3` | `ghcr.io/eehser/paperless-pay:v1.2.3` |

### Architectures

`linux/amd64`, `linux/arm64`

### Update

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker/compose.example.yml \
  pull && \
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker/compose.example.yml \
  up -d
```

## Services

The image contains **two modes** – controlled via `command:` in Compose:

| Service | Command (default) | Description |
|---|---|---|
| **paperless-pay** | `uvicorn main:app ...` (default CMD) | Web app: payment page + QR code |
| **pay-link-worker** | `python -u worker.py` | Polling worker: sets pay-links in custom fields |

## Environment Variables

The web app and the link worker use **separate env files** for security
(the API token stays out of the web container).

See [.env.sample](.env.sample) and [.env.worker.sample](.env.worker.sample).

### Web App (``.env``)

| Variable | Required | Default | Description |
|---|---|---|---|
| `PAPERLESS_BASE_URL` | | `http://paperless:8000` | Paperless URL inside Docker network |
| `PAPERLESS_PUBLIC_URL` | | = `PAPERLESS_BASE_URL` | Public URL for PDF iframe |
| `APP_BASE_PATH` | | `/pay` | URL prefix for all routes |
| `LANGUAGE` | | `en` | GUI language (`en` or `de`) |
| `CF_IBAN` | ✓ | | Custom field ID: IBAN |
| `CF_BIC` | | | Custom field ID: BIC (optional) |
| `CF_AMOUNT` | ✓ | | Custom field ID: Amount |
| `CF_REMITTANCE` | ✓ | | Custom field ID: Remittance info |
| `CF_PAID` | ✓ | | Custom field ID: Paid (boolean) |
| `REMITTANCE_TEMPLATE` | | `{remittance}` | Template with `{remittance}`, `{title}`, `{correspondent}`, `{doc_id}` |
| `ENABLE_EDIT` | | `false` | Experimental: enable field editing |

### Link Worker (``.env.worker``)

| Variable | Required | Default | Description |
|---|---|---|---|
| `PAPERLESS_BASE_URL` | | `http://paperless:8000` | Paperless URL inside Docker network |
| `PAPERLESS_TOKEN` | ✓ | | API token (Paperless Admin → Tokens) |
| `CF_LINK` | ✓ | | Custom field ID: Pay-Link (type: URL) |
| `PAY_PUBLIC_URL` | ✓ | | Public URL, e.g. `https://docs.example.com/pay` |
| `WORKER_FILTER` | | `""` | Paperless API filter, e.g. `document_type__id=3` |
| `WORKER_INTERVAL` | | `60` | Polling interval in seconds |

### Creating an API Token

1. Paperless Admin → **Tokens** (or `/admin/authtoken/tokenproxy/`)
2. Create a new token for a user with write permissions
3. Set the token in `PAPERLESS_TOKEN`

## nginx

See [docker/nginx.example.conf](docker/nginx.example.conf) – paperless-pay and Paperless must run
behind the same reverse proxy so the browser sends session cookies to both paths.

## Routes

| Method | Path | Description |
|---|---|---|
| GET | `/pay/healthz` | Liveness check |
| GET | `/pay/doc/{id}` | Payment page with QR code |
| POST | `/pay/doc/{id}/paid` | Mark as paid (redirect) |
| POST | `/pay/doc/{id}/save` | Save fields (only when `ENABLE_EDIT=true`) |

## Development

### Local Build

```bash
# Instead of pulling from GHCR: build locally
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker/compose.example.yml \
  up -d --build
```

Uncomment the `build:` lines and comment out `image:` in `docker/compose.example.yml`.

### Without Docker

```bash
cd pay-poc/src
python -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
# Load .env (e.g. via direnv or manual export)
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Creating a Release

```bash
git tag v1.0.0
git push origin v1.0.0
# → GitHub Action builds + pushes ghcr.io/eehser/paperless-pay:v1.0.0
```

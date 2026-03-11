# paperless-pay

SEPA EPC-QR Zahlungsseite für [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx).

Zeigt Zahlungsinformationen, generiert EPC-QR-Codes und ermöglicht das Markieren von Dokumenten als bezahlt – alles über Cookie-Passthrough, kein eigener Auth-Layer.

## Features

- **EPC-QR-Code** – SEPA Credit Transfer QR-Code (scannbar mit Banking-Apps)
- **Zahlungsübersicht** – IBAN, BIC, Betrag, Verwendungszweck aus Paperless Custom Fields
- **PDF-Vorschau** – Dokument-Preview direkt neben den Zahlungsdaten
- **Als bezahlt markieren** – setzt ein Boolean Custom Field in Paperless
- **IBAN-Validierung** – via [schwifty](https://github.com/mdomke/schwifty) (ISO 13616)
- **Feld-Bearbeitung** – experimentell, per Feature Switch (`ENABLE_EDIT=true`)
- **Link-Worker** – setzt automatisch Pay-Links in ein URL Custom Field für alle Rechnungen
- **Verwendungszweck-Template** – konfigurierbar mit Variablen

## Quickstart

### 1. Voraussetzungen

- Laufende **paperless-ngx** Instanz mit Docker Compose
- Custom Fields in Paperless angelegt: IBAN, Betrag, Verwendungszweck, Bezahlt (+ optional BIC, Pay-Link)
- Reverse Proxy (nginx o.ä.) der Cookie-Passthrough ermöglicht

### 2. Compose einrichten

```bash
# Repo als Unterverzeichnis in dein Paperless-Compose-Verzeichnis klonen
cd /opt/paperless            # ← dein Paperless-Compose-Dir
git clone https://github.com/eehser/paperless-pay.git pay-poc

# ENV-Datei erstellen
cp pay-poc/.env.sample pay-poc/.env
# → pay-poc/.env anpassen (Custom Field IDs, URLs, etc.)
```

### 3. Starten

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay.example.yml \
  up -d
```

> Das Compose-File `docker-compose.pay.example.yml` ist ein **Beispiel**.
> Passe es an dein Setup an (Service-Namen, Netzwerke, Ports).

### 4. Testen

1. Im Browser bei Paperless einloggen
2. Aufrufen: `https://deine-domain.de/pay/doc/123`

## Image

Das Image wird automatisch über GitHub Actions gebaut und auf GHCR publiziert:

```
ghcr.io/eehser/paperless-pay:latest
```

### Tags

| Tag | Wann | Beispiel |
|---|---|---|
| `latest` | Jeder Push auf `main` | `ghcr.io/eehser/paperless-pay:latest` |
| `sha-<hash>` | Jeder Push auf `main` | `ghcr.io/eehser/paperless-pay:sha-abc1234` |
| `v1.2.3` | Git-Tag `v1.2.3` | `ghcr.io/eehser/paperless-pay:v1.2.3` |

### Architectures

`linux/amd64`, `linux/arm64`

### Update

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay.example.yml \
  pull && \
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay.example.yml \
  up -d
```

## Services

Das Image enthält **zwei Modi** – gesteuert über den `command:` in Compose:

| Service | Command (default) | Beschreibung |
|---|---|---|
| **paperless-pay** | `uvicorn main:app ...` (default CMD) | Web-App: Zahlungsseite + QR-Code |
| **pay-link-worker** | `python -u worker.py` | Polling-Worker: setzt Pay-Links in Custom Fields |

## ENV-Variablen

Siehe [.env.sample](.env.sample) für alle Variablen mit Erklärungen.

### Web-App

| Variable | Pflicht | Default | Beschreibung |
|---|---|---|---|
| `PAPERLESS_BASE_URL` | | `http://paperless:8000` | Paperless im Docker-Netz |
| `PAPERLESS_PUBLIC_URL` | | = `PAPERLESS_BASE_URL` | Öffentliche URL für PDF-iframe |
| `APP_BASE_PATH` | | `/pay` | URL-Prefix für alle Routes |
| `CF_IBAN` | ✓ | | Custom Field ID: IBAN |
| `CF_BIC` | | | Custom Field ID: BIC (optional) |
| `CF_BETRAG` | ✓ | | Custom Field ID: Betrag |
| `CF_VERWENDUNGSZWECK` | ✓ | | Custom Field ID: Verwendungszweck |
| `CF_BEZAHLT` | ✓ | | Custom Field ID: Bezahlt (boolean) |
| `VERWENDUNGSZWECK_TEMPLATE` | | `{verwendungszweck}` | Template mit `{verwendungszweck}`, `{title}`, `{correspondent}`, `{doc_id}` |
| `ENABLE_EDIT` | | `false` | Experimentell: Felder editierbar machen |

### Link-Worker

| Variable | Pflicht | Default | Beschreibung |
|---|---|---|---|
| `PAPERLESS_TOKEN` | ✓ | | API-Token (Paperless Admin → Tokens) |
| `CF_LINK` | ✓ | | Custom Field ID: Pay-Link (Typ: URL) |
| `PAY_PUBLIC_URL` | ✓ | | Öffentliche URL, z.B. `https://docs.xy.de/pay` |
| `WORKER_FILTER` | | `""` | Paperless API Filter, z.B. `document_type__id=3` |
| `WORKER_INTERVAL` | | `60` | Polling-Intervall in Sekunden |

### API-Token erstellen

1. Paperless Admin → **Tokens** (oder `/admin/authtoken/tokenproxy/`)
2. Neuen Token für einen Benutzer mit Schreibrechten erstellen
3. Token in `PAPERLESS_TOKEN` eintragen

## nginx

Siehe [nginx.example.conf](nginx.example.conf) – paperless-pay und Paperless müssen
hinter demselben Reverse Proxy laufen, damit der Browser die Session-Cookies an beide Pfade sendet.

## Routen

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/pay/healthz` | Liveness-Check |
| GET | `/pay/doc/{id}` | Zahlungsseite mit QR-Code |
| POST | `/pay/doc/{id}/paid` | Als bezahlt markieren (Redirect) |
| POST | `/pay/doc/{id}/save` | Felder speichern (nur bei `ENABLE_EDIT=true`) |

## Development

### Lokaler Build

```bash
# Statt Image aus GHCR: lokal bauen
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay.example.yml \
  up -d --build
```

Dazu in `docker-compose.pay.example.yml` die `build:`-Zeilen einkommentieren und `image:` auskommentieren.

### Ohne Docker

```bash
cd pay-poc/
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# .env laden (z.B. via direnv oder manuell export)
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Release erstellen

```bash
git tag v1.0.0
git push origin v1.0.0
# → GitHub Action baut + pusht ghcr.io/eehser/paperless-pay:v1.0.0
```

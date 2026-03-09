# cookie-passthrough-check

Super-minimaler PoC um zu testen, ob Cookie-Passthrough zur **paperless-ngx** API funktioniert.

## Idee

Du bist im Browser bei Paperless eingeloggt (Session-Cookie gesetzt).
Der PoC nimmt alle Cookies aus dem eingehenden Request und leitet sie
serverseitig an Paperless weiter. So siehst du sofort, ob die
Authentifizierung über Cookie-Forwarding klappt.

## Verzeichnisstruktur (Ziel)

Dieses Repo wird als **Unterverzeichnis** in dein bestehendes
Paperless-Compose-Projekt geklont. Danach sieht es so aus:

```
/opt/paperless/                         ← dein Paperless-Compose-Verzeichnis
├── docker-compose.yml                  ← dein bestehender Paperless-Stack
├── .env                                ← deine bestehende Paperless-ENV
├── …
└── pay-poc/                            ← dieses Repo (git clone)
    ├── docker-compose.pay-poc.override.yml
    ├── .env.sample
    ├── Dockerfile
    ├── main.py
    ├── requirements.txt
    ├── nginx.example.conf
    └── README.md
```

## Setup – Schritt für Schritt

```bash
# 1. In dein Paperless-Compose-Verzeichnis wechseln
cd /opt/paperless            # ← anpassen!

# 2. Dieses Repo als Unterverzeichnis klonen
git clone <REPO_URL> pay-poc

# 3. ENV-Datei aus Sample erzeugen
cp pay-poc/.env.sample pay-poc/.env

# 4. pay-poc/.env prüfen und ggf. anpassen
#    (Defaults passen, wenn dein Paperless-Service "paperless" heißt
#     und auf Port 8000 läuft – also der Standard.)
```

## Starten

```bash
# Aus dem Paperless-Compose-Verzeichnis:
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay-poc.override.yml \
  --env-file pay-poc/.env \
  up -d --build cookie-poc
```

> **Was passiert hier?**
> - `-f docker-compose.yml` → dein bestehender Paperless-Stack
> - `-f pay-poc/docker-compose.pay-poc.override.yml` → fügt den `cookie-poc` Service additiv hinzu
> - `--env-file pay-poc/.env` → lädt die PoC-spezifischen ENV-Variablen
> - Docker Compose merged beide Files. Der `cookie-poc` Service teilt automatisch das default-Netzwerk des Paperless-Stacks und kann `paperless:8000` direkt erreichen.

### Logs prüfen

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay-poc.override.yml \
  logs -f cookie-poc
```

### Stoppen (nur den PoC)

```bash
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay-poc.override.yml \
  rm -sf cookie-poc
```

## ENV-Variablen (`pay-poc/.env`)

| Variable             | Required | Default                    | Beschreibung                                      |
|----------------------|----------|----------------------------|---------------------------------------------------|
| `PAPERLESS_BASE_URL` | nein     | `http://paperless:8000`    | URL des Paperless-Service im Docker-Netz          |
| `APP_BASE_PATH`      | nein     | `/qr-poc`                  | Prefix für alle Routes (für Reverse-Proxy)         |
| `COOKIE_POC_PORT`    | nein     | `8081`                     | Host-Port des PoC                                 |
| `DEBUG_UPSTREAM`     | nein     | `false`                    | `1`/`true` → loggt + gibt alle Upstream-Header aus |

## Routen

| Methode | Pfad                 | Beschreibung                                 |
|---------|----------------------|----------------------------------------------|
| GET     | `/qr-poc/healthz`    | Liveness-Check: `{"ok": true}`               |
| GET     | `/qr-poc/probe`      | Cookie-Passthrough-Test gegen `/api/`        |
| GET     | `/qr-poc/doc/{id}`   | Dokument abfragen via `/api/documents/{id}/` |

## Testen

1. **Im Browser bei Paperless einloggen** (z. B. `https://docs.xy.de`).
2. **Im gleichen Browser** aufrufen:

| URL                                  | Erwartet                                     |
|--------------------------------------|----------------------------------------------|
| `https://docs.xy.de/qr-poc/healthz` | `{"ok": true}`                               |
| `https://docs.xy.de/qr-poc/probe`   | `"verdict": "OK (authenticated)"` bei Cookie |
| `https://docs.xy.de/qr-poc/doc/123` | Dokument-JSON oder `"NOT AUTHENTICATED"`     |

### Beispiel-Response `/probe` (authentifiziert)

```json
{
  "upstream_url": "http://paperless:8000/api/",
  "upstream_status": 200,
  "authenticated_guess": true,
  "upstream_headers_subset": { "content-type": "application/json" },
  "upstream_body_preview": "{\"documents\":\"http://paperless:8000/api/documents/\", ...}",
  "verdict": "OK (authenticated)"
}
```

### Beispiel-Response `/probe` (nicht authentifiziert)

```json
{
  "upstream_url": "http://paperless:8000/api/",
  "upstream_status": 403,
  "authenticated_guess": false,
  "upstream_headers_subset": { "content-type": "application/json" },
  "upstream_body_preview": "{\"detail\":\"Authentication credentials were not provided.\"}",
  "verdict": "NOT AUTHENTICATED"
}
```

## nginx

Siehe [nginx.example.conf](nginx.example.conf) – der PoC und Paperless
laufen hinter demselben nginx, damit der Browser die Session-Cookies an
beide Pfade schickt.

## Aufräumen

```bash
# PoC-Container entfernen
docker compose \
  -f docker-compose.yml \
  -f pay-poc/docker-compose.pay-poc.override.yml \
  rm -sf cookie-poc

# Image entfernen
docker image rm $(docker images -q '*cookie-poc*') 2>/dev/null

# Unterverzeichnis löschen
rm -rf pay-poc/
```

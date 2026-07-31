# JavLibrary Python Scraper

A Stash Community Scraper plugin for **JavLibrary** with interactive Cloudflare/CAPTCHA handling, persistent cookie storage, caching, and a modular Client/Server architecture.

---

## Architecture & Modes

The scraper supports two execution modes via `config.ini`:

1. **Local Mode** (`REMOTE_SERVER_ENABLED = False`, default):
   - Stash runs `JavLibrary_python.py` on each scraping task.
   - `JavLibrary_python.py` dynamically loads `JavLibrary_server.py` and executes scraping locally.

2. **Client/Server Mode** (`REMOTE_SERVER_ENABLED = True`):
   - `JavLibrary_server.py` runs as a standalone HTTP server daemon on your desktop/server machine.
   - `JavLibrary_python.py` acts as a lightweight dispatcher forwarding incoming Stash scrape requests to the desktop server over HTTP.

---

## Configuration (`config.ini`)

Location: `scrapers/JavLibrary_python/config.ini`

```ini
# Return tags or not
RETURN_TAGS = False

# Remote Desktop Server configuration
REMOTE_SERVER_ENABLED = False
REMOTE_SERVER_URL = http://127.0.0.1:8000
```

- `RETURN_TAGS`: Set to `True` to include genres/tags in scraped results.
- `REMOTE_SERVER_ENABLED`: Set to `True` to forward scrape requests to the desktop HTTP server.
- `REMOTE_SERVER_URL`: URL of the desktop HTTP server (e.g. `http://127.0.0.1:8000`).

---

## Running the Desktop HTTP Server

Start the desktop server using Python:

```bash
python3 JavLibrary_server.py
```

Optional CLI flags:
- `--port PORT`: Specify custom port (e.g. `python3 JavLibrary_server.py --port 8000`).

---

## Server API Endpoints & Manual `curl` Examples

### 1. Health Check (`GET /health`)
Verify that the desktop server is running:

```bash
curl http://127.0.0.1:8000/health
```
**Response:**
```json
{"status": "ok"}
```

---

### 2. Scrape Endpoint (`POST /scrape`)

#### Scrape by Filename (Default)
```bash
curl -X POST http://127.0.0.1:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"stash_request": {"title": "some_uploader@lulu00424_2_8k_cut_1.mp4"}, "args": []}'
```

#### Scrape by Search Name / DVD Code (`searchName` argument)
```bash
curl -X POST http://127.0.0.1:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"stash_request": {"name": "LULU-424"}, "args": ["searchName"]}'
```

---

### 3. Clear Cache (`POST /clear-cache`)
Clear cached HTTP responses:

```bash
curl -X POST http://127.0.0.1:8000/clear-cache
```
**Response:**
```json
{"status": "success", "message": "Cache cleared successfully."}
```

Or via CLI:
```bash
python3 JavLibrary_server.py --clear-cache
```

---

## Running Unit Tests

Run the test suite to verify filename parsing, clean queries, and caching:

```bash
python3 test_scraper.py
```

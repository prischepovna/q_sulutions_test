# Company Data Service & Impressum Extraction with DeepSeek (Apache + mod_wsgi + PostgreSQL)

Flask web service running in Docker Compose with PostgreSQL 16, Apache mod_wsgi, Camtasia-style video zoom post-processing, and DeepSeek-powered Impressum/Imprint legal entity extraction with token optimization.

- **web** — Apache with mod_wsgi serving the Flask app, ffmpeg for zoom rendering, and enrichment modules (host port 8000 -> container port 80).
- **db** — PostgreSQL 16 for persistent storage (`companies` and `videos` tables).

Data survives restarts thanks to named volumes: `db_data` (PostgreSQL) and `uploads` (media and sidecars).

---

## Task 3 Features: Impressum & Imprint Extraction with DeepSeek

### 1. Token Optimization ("Sandwich Cutting")
German Impressum pages often contain large amounts of boilerplate (navigation menus, cookie banners, shop categories, footers). `impressum.py` applies token optimization before sending text to DeepSeek:
1. **HTML Cleanup:** Strips `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<noscript>`, `<svg>`, `<iframe>`, and deobfuscates protected email addresses.
2. **Head Anchors:** Locates legal opening phrases (`Angaben gemäß § 5 TMG/DDG`, `Impressum`, `Anbieter`, etc.) with a 100-character safety margin.
3. **Tail Anchors:** Locates terminating identifiers (German phone numbers, VAT `DE\d{9}`, Handelsregister `HRB\d+`, `Geschäftsführer`, emails) with a 400-character safety margin.
4. **Budget Cap:** Slices the sandwich `[head - 100 : tail + 400]` capped at `MAX_TEXT_CHARS = 8000` (~2000 tokens heuristic: `len // 4`), logging token reduction percentage.

### 2. DeepSeek API Extraction (JSON Mode)
- **Endpoint:** `https://api.deepseek.com/chat/completions`
- **Model:** `deepseek-chat` (configurable via `DEEPSEEK_MODEL`)
- **JSON mode:** `response_format: {"type": "json_object"}`
- Extracts structured entity fields:
  * `legal_name`: Official legal company name
  * `postal_address`: `{street, house_no, postcode, city, country}`
  * `handelsregister`: Commercial register and court (e.g. `Amtsgericht Münster HRB 6160`)
  * `vat_number`: VAT ID / USt-IdNr (e.g. `DE 217 733 235`)
  * `phone`: Contact telephone
  * `email`: Contact email
  * `responsible_person`: Managing director(s) or responsible representative(s)

### 3. Status Codes
| Code | Name | Description |
|---|---|---|
| `NULL` | `PENDING` | Company imported from CSV, not yet enriched |
| `0` | `OK` | Impressum parsed and all 4 address fields (`street`, `house_no`, `postcode`, `city`) present |
| `1` | `NO_IMPRESSUM_LINK` | Homepage was reachable, but no Impressum/Imprint link was found |
| `2` | `PARSING_FAILED` | Impressum page was fetched, but DeepSeek returned empty fields |
| `3` | `ADDRESS_INCOMPLETE` | Legal fields parsed, but address is missing 1 or more required components |
| `4` | `ERROR` | Network/HTTP error (4xx/5xx, unreachable host, or API failure) |
| `5` | `NO_WEBSITE` | `Web` column in CSV is empty/blank |

---

## Project Structure

```
Dockerfile              Apache + mod_wsgi + Flask + ffmpeg image
docker-compose.yml      Docker Compose services (web, db), volumes, healthchecks
schema.sql              PostgreSQL schema for companies and videos tables
companies.csv           Sample CSV file with company websites (nutrimmun GmbH, Barolo & Champagne, etc.)
web_service.py          Flask app with CSV upload, company queries, and video endpoints
impressum.py            Impressum link discovery, HTML cleanup, sandwich token optimization, DeepSeek client
enrich_companies.py     CLI runner to process and enrich pending companies from PostgreSQL
apply_zoom.py           Camtasia-style zoom post-processing via ffmpeg zoompan
video_client.py         Client helper for video upload and processing
capture_video.py        Recording runner reading CSV and uploading videos
requirements.txt        Server dependencies (Flask, mod_wsgi, psycopg2, beautifulsoup4, requests, python-dotenv)
requirements-client.txt Client dependencies (requests, playwright, pytest, beautifulsoup4)
tests/                  Pytest suite (100+ tests: impressum, web service, enrich CLI, zoom)
```

---

## Configuration

Create `.env` based on `.env.example`:
```bash
cp .env.example .env
```

Set your DeepSeek API key:
```env
DB_NAME=videos
DB_USER=video_user
DB_PASSWORD=video_pass
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_MODEL=deepseek-chat
```

---

## Running the Service (Docker)

```bash
docker compose up --build -d
```
The service will be available at `http://localhost:8000`.

---

## API Endpoints

### 1. Upload Companies CSV
- **Form UI:** `GET http://localhost:8000/upload_companies`
- **API POST:** `POST http://localhost:8000/upload_companies`
```bash
curl -F "file=@companies.csv" http://localhost:8000/upload_companies
```
Response:
```json
{
  "status": "ok",
  "imported": 6,
  "updated": 0,
  "total_rows": 6
}
```
*Idempotent: Re-uploading updates base info without overwriting existing enrichment results.*

### 2. List Companies
- **All companies:** `GET http://localhost:8000/companies`
- **Filter by status:** `GET http://localhost:8000/companies?status=0`
```bash
curl http://localhost:8000/companies
```

### 3. Get Single Company
```bash
curl "http://localhost:8000/companies/nutrimmun%20GmbH"
```

### 4. Video Endpoints (Tasks 1 & 2)
- `POST /upload`: Upload video and optional sidecar.
- `POST /process`: Trigger zoom processing on uploaded video.
- `GET /get_video_url?company_name=<name>`: Retrieve processed video URL.
- `GET /media/<filename>`: Static media streaming.

---

## CLI Enrichment Tool (`enrich_companies.py`)

Run the enrichment tool directly from the host or inside the container:

```bash
# Enrich all pending or non-zero companies
python enrich_companies.py

# Enrich one specific company
python enrich_companies.py --company "nutrimmun GmbH"

# Limit processing count
python enrich_companies.py --limit 5

# Re-process companies with a specific status (e.g. status 1)
python enrich_companies.py --status 1
```

Inside Docker:
```bash
docker compose exec web python /app/enrich_companies.py --company "nutrimmun GmbH"
```

---

## Testing

Run the full pytest suite locally:
```bash
python -m pytest
```
Output:
```
tests/test_enrich_companies.py ......... [  8%]
tests/test_ffmpeg_integration.py sssss   [ 13%]
tests/test_impressum.py ................ [ 42%]
tests/test_sidecar.py ............       [ 54%]
tests/test_web_service.py .............. [ 69%]
tests/test_zoom_calc.py ................ [100%]
====================== 102 passed, 5 skipped ======================
```

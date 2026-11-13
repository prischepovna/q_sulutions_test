# Video web service in Docker (Apache + mod_wsgi + PostgreSQL) + Camtasia Zoom

Flask video web service with Camtasia-style zoom effect post-processing, running in two containers managed by Docker Compose:

- **web** — Apache with mod_wsgi serving the Flask app, with ffmpeg installed for post-processing (host port 8000 -> container port 80)
- **db** — PostgreSQL 16 (replaces SQLite)

Data survives restarts thanks to two named volumes: `db_data` (PostgreSQL data) and `uploads` (uploaded videos and sidecars).

---

## Features

- **Browser Recording with Zoom Capture:** Playwright records actions with a custom SVG cursor, click ripples, and on-screen callouts.
- **Zoom Events:**
  - **F5 hotkey** toggles zoom at the current cursor position (first press = zoom-in, second press = zoom-out).
  - **Programmatic hook:** `window.__zoomAt(x, y)` can be called directly by automation scenarios.
  - **Visual indicator:** A pulsating colored ring shows active zoom state.
  - **Sidecar JSON:** If zoom events are captured, writes `<video>.zoom.json` alongside the video.
- **FFmpeg Post-Processing (`apply_zoom.py`):**
  - Uses ffmpeg's `zoompan` filter.
  - Smooth transitions using smoothstep easing ($3t^2 - 2t^3$).
  - Precise mouse coordinate clamping to avoid crop overflow.
  - Supports multiple in/out pairs, open-ended zooms (holds to video end), and fallback copying when no events exist.
  - `--dry-run` to preview ffmpeg command; `--ffmpeg` to specify custom binary path.
- **Docker Integration:**
  - Automatic post-processing when uploading video with its sidecar.
  - Dedicated `/process` and `/jobs/<company_name>/process` endpoints.
  - Processed video URL stored in PostgreSQL (`processed_video_url`).

---

## Project structure

```
Dockerfile              Apache + mod_wsgi + Flask + ffmpeg image
docker-compose.yml      services web and db, volumes, healthcheck
apply_zoom.py           Camtasia-style zoom post-processing via ffmpeg zoompan
web_service.py          Flask app (PostgreSQL via psycopg2, /upload, /process)
video_client.py         Client helper for upload, process, and url query
capture_video.py        Recording runner reading input.csv and uploading to server
qscript.py              Playwright automation + zoom event capture
app.wsgi                WSGI entry point for mod_wsgi
apache/videoapp.conf    Apache VirtualHost + WSGI config
docker/entrypoint.sh    DB initialization + Apache startup
requirements.txt        server dependencies (flask, psycopg2-binary, mod_wsgi)
requirements-client.txt client dependencies (requests, playwright, pytest)
tests/                  pytest suite (zoom calculations, sidecar parsing, endpoints)
```

---

## Run

Requires Docker with Docker Compose.

```bash
cp .env.example .env     # optional: change DB credentials
docker compose up --build
```

The service is available at http://localhost:8000.

Stop (data is kept):
```bash
docker compose down
```

Stop and delete all data (database and uploaded videos):
```bash
docker compose down -v
```

---

## API

### 1. Upload a video (with optional zoom sidecar)
```bash
curl -F "file=@video/AcmeCorp.webm" \
     -F "sidecar=@video/AcmeCorp.zoom.json" \
     -F "company_name=AcmeCorp" \
     http://localhost:8000/upload
```
*If a sidecar is provided, zoom post-processing is executed automatically and `processed_video_url` is returned.*

### 2. Trigger zoom processing manually
```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{"company_name": "AcmeCorp"}' \
     http://localhost:8000/process
```
*(Also available as `POST /jobs/AcmeCorp/process`)*

### 3. Get video URL
```bash
curl "http://localhost:8000/get_video_url?company_name=AcmeCorp"
```
Response:
```json
{
  "company_name": "AcmeCorp",
  "video_url": "http://localhost:8000/media/AcmeCorp.webm",
  "processed_video_url": "http://localhost:8000/media/AcmeCorp_zoomed.webm"
}
```

---

## Standalone Post-Processing (`apply_zoom.py`)

You can run zoom post-processing directly on the host or inside a container:

```bash
# Render zoomed video
python apply_zoom.py --video video/AcmeCorp.webm

# Preview ffmpeg command without encoding
python apply_zoom.py --video video/AcmeCorp.webm --dry-run

# Specify custom ffmpeg binary or sidecar
python apply_zoom.py --video video/AcmeCorp.webm --sidecar video/custom.zoom.json --ffmpeg /path/to/ffmpeg
```

---

## Client (Runs on Host)

```bash
pip install -r requirements-client.txt
playwright install chromium

# Record video with zoom capture, upload to server, and preview
python capture_video.py --server http://localhost:8000 --view-seconds 5
```

---

## Testing

Run unit tests locally (no ffmpeg or database required):

```bash
pytest tests/ -v
```

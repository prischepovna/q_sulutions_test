# Video web service in Docker (Apache + mod_wsgi + PostgreSQL)

Flask video web service from Test Task 2, reworked to run in two containers
managed by Docker Compose:

- **web** - Apache with mod_wsgi serving the Flask app (host port 8000 -> container port 80)
- **db** - PostgreSQL 16 (replaces SQLite)

Data survives restarts thanks to two named volumes: `db_data` (PostgreSQL data)
and `uploads` (uploaded videos). The DB connection is configured only through
environment variables, and `web` starts after `db` passes its healthcheck.

## Project structure

```
Dockerfile              Apache + mod_wsgi + Flask image
docker-compose.yml      services web and db, volumes, healthcheck
web_service.py          Flask app (PostgreSQL via psycopg2)
app.wsgi                WSGI entry point for mod_wsgi
apache/videoapp.conf    Apache VirtualHost + WSGI config
docker/entrypoint.sh    creates the table, then starts Apache
requirements.txt        server dependencies (flask, psycopg2-binary, mod_wsgi)
requirements-client.txt client dependencies (requests, playwright), run on the host
```

## Run

Requires Docker with Docker Compose.

```bash
cp .env.example .env     # optional: change the DB password
docker compose up --build
```

The service is available at http://localhost:8000. Without a `.env` file the
defaults from `docker-compose.yml` are used.

Stop (data is kept):

```bash
docker compose down
```

Stop and delete all data (database and uploaded videos):

```bash
docker compose down -v
```

## API

Upload a video:

```bash
curl -F "file=@video/AcmeCorp.webm" -F "company_name=AcmeCorp" http://localhost:8000/upload
```

Get the video URL:

```bash
curl "http://localhost:8000/get_video_url?company_name=AcmeCorp"
```

The returned URL (`http://localhost:8000/media/AcmeCorp.webm`) can be opened in a browser.

On Windows PowerShell use `curl.exe` instead of `curl`.

## Configuration

| Variable      | Default      | Description       |
|---------------|--------------|-------------------|
| `DB_NAME`     | `videos`     | database name     |
| `DB_USER`     | `video_user` | database user     |
| `DB_PASSWORD` | `video_pass` | database password |

`DB_HOST=db` and `DB_PORT=5432` are set in `docker-compose.yml`.
In production use `.env` / Docker secrets and never commit real passwords.

## Check persistence

1. Upload a video (see above).
2. `docker compose down`
3. `docker compose up`
4. `GET /get_video_url?company_name=AcmeCorp` still returns the URL and the video still opens.

## Debugging

```bash
docker compose logs -f web
docker compose exec web curl http://localhost/get_video_url?company_name=AcmeCorp
docker compose exec db psql -U video_user -d videos -c "SELECT * FROM videos;"
```

## Client (runs on the host, not in Docker)

```bash
pip install -r requirements-client.txt
playwright install chromium
python capture_video.py --server http://localhost:8000
```
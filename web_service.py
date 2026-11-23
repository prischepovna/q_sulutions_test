from __future__ import annotations

import csv
import io
import os
import sys
import time
import subprocess
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory, g

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SCHEMA_FALLBACK_SQL = '''
    CREATE TABLE IF NOT EXISTS videos (
        id SERIAL PRIMARY KEY,
        company_name TEXT NOT NULL UNIQUE,
        video_url TEXT NOT NULL,
        file_path TEXT NOT NULL,
        processed_video_url TEXT,
        sidecar_path TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_video_url TEXT;
    ALTER TABLE videos ADD COLUMN IF NOT EXISTS sidecar_path TEXT;

    CREATE TABLE IF NOT EXISTS companies (
        id SERIAL PRIMARY KEY,
        company_name TEXT NOT NULL UNIQUE,
        language TEXT,
        country TEXT,
        postcode TEXT,
        city TEXT,
        street TEXT,
        house_no TEXT,
        web TEXT,
        status INTEGER,
        impressum_url TEXT,
        legal_name TEXT,
        postal_address TEXT,
        handelsregister TEXT,
        vat_number TEXT,
        phone TEXT,
        email TEXT,
        responsible_person TEXT,
        raw_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
    CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);
'''

SCHEMA_FILE = os.path.join(BASE_DIR, 'schema.sql')
if os.path.exists(SCHEMA_FILE):
    with open(SCHEMA_FILE, 'r', encoding='utf-8') as _f:
        SCHEMA_SQL = _f.read()
else:
    SCHEMA_SQL = SCHEMA_FALLBACK_SQL


def _db_params():
    """Параметры подключения берутся из переменных окружения."""
    return {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432'),
        'dbname': os.environ.get('DB_NAME') or os.environ.get('пDB_NAME', 'videos'),
        'user': os.environ.get('DB_USER', 'video_user'),
        'password': os.environ.get('DB_PASSWORD', 'video_pass'),
    }


def connect(retries=1, delay=2.0):
    """Новое подключение к PostgreSQL с повторными попытками."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(
                cursor_factory=RealDictCursor,
                connect_timeout=5,
                **_db_params(),
            )
        except psycopg2.OperationalError as e:
            last_error = e
            if attempt < retries:
                print(f'[db] not ready (attempt {attempt}/{retries}), retry in {delay}s', flush=True)
                time.sleep(delay)
    raise last_error


def get_db():
    # psycopg2-соединения не потокобезопасны: одно соединение на запрос.
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect(retries=3, delay=1.0)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.errorhandler(psycopg2.OperationalError)
def handle_db_unavailable(e):
    return jsonify({'error': 'Database is unavailable'}), 503


def init_db(retries=30, delay=2.0):
    conn = connect(retries=retries, delay=delay)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
    finally:
        conn.close()


def run_zoom_processing(video_path: str, sidecar_path: str | None = None) -> str | None:
    """Run apply_zoom.py on the given video and return the processed file path if created."""
    script_path = os.path.join(BASE_DIR, 'apply_zoom.py')
    cmd = [sys.executable, script_path, '--video', video_path]
    if sidecar_path and os.path.exists(sidecar_path):
        cmd.extend(['--sidecar', sidecar_path])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"[zoom] apply_zoom output:\n{res.stdout}", flush=True)
    except subprocess.CalledProcessError as err:
        print(f"[zoom] apply_zoom failed: {err}\nStderr: {err.stderr}", flush=True)
        return None

    stem = Path(video_path).stem
    suffix = Path(video_path).suffix
    expected_out = os.path.join(os.path.dirname(video_path), f"{stem}_zoomed{suffix}")
    if os.path.exists(expected_out):
        return expected_out
    return None


@app.route('/upload', methods=['POST'])
def upload_video():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    company_name = request.form.get('company_name')

    if not company_name or file.filename == '':
        return jsonify({'error': 'Company name and file are required'}), 400

    clean_name = company_name.replace('/', '_').replace(' ', '_')
    filename = f"{clean_name}.webm"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    video_url = f"{request.host_url.rstrip('/')}/media/{filename}"

    # Handle optional sidecar file
    sidecar_path = None
    if 'sidecar' in request.files:
        sidecar_file = request.files['sidecar']
        if sidecar_file.filename != '':
            sidecar_filename = f"{clean_name}.zoom.json"
            sidecar_path = os.path.join(app.config['UPLOAD_FOLDER'], sidecar_filename)
            sidecar_file.save(sidecar_path)

    # Check for sidecar on disk if not provided in upload
    if not sidecar_path:
        default_sidecar = os.path.join(app.config['UPLOAD_FOLDER'], f"{clean_name}.zoom.json")
        if os.path.exists(default_sidecar):
            sidecar_path = default_sidecar

    processed_video_url = None
    if sidecar_path and os.path.exists(sidecar_path):
        processed_file = run_zoom_processing(file_path, sidecar_path)
        if processed_file:
            processed_video_url = f"{request.host_url.rstrip('/')}/media/{os.path.basename(processed_file)}"

    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            INSERT INTO videos (company_name, video_url, file_path, processed_video_url, sidecar_path, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (company_name) DO UPDATE SET
                video_url = EXCLUDED.video_url,
                file_path = EXCLUDED.file_path,
                processed_video_url = COALESCE(EXCLUDED.processed_video_url, videos.processed_video_url),
                sidecar_path = COALESCE(EXCLUDED.sidecar_path, videos.sidecar_path),
                updated_at = NOW();
        ''', (company_name, video_url, file_path, processed_video_url, sidecar_path))
    db.commit()

    return jsonify({
        'company_name': company_name,
        'video_url': video_url,
        'processed_video_url': processed_video_url
    }), 200


@app.route('/process', methods=['POST'])
@app.route('/jobs/<company_name>/process', methods=['POST'])
def process_video_endpoint(company_name=None):
    if not company_name:
        if request.is_json:
            company_name = request.json.get('company_name') or request.json.get('id')
        else:
            company_name = request.form.get('company_name') or request.form.get('id') or request.args.get('company_name') or request.args.get('id')

    if not company_name:
        return jsonify({'error': 'company_name or id is required'}), 400

    db = get_db()
    with db.cursor() as cur:
        if str(company_name).isdigit():
            cur.execute(
                'SELECT company_name, video_url, file_path, sidecar_path, processed_video_url FROM videos WHERE id = %s OR company_name = %s',
                (int(company_name), str(company_name)),
            )
        else:
            cur.execute(
                'SELECT company_name, video_url, file_path, sidecar_path, processed_video_url FROM videos WHERE company_name = %s',
                (str(company_name),),
            )
        row = cur.fetchone()

    if not row:
        return jsonify({'error': 'Company not found'}), 404

    file_path = row['file_path']
    sidecar_path = row['sidecar_path']

    if not sidecar_path:
        default_sidecar = os.path.join(app.config['UPLOAD_FOLDER'], f"{Path(file_path).stem}.zoom.json")
        if os.path.exists(default_sidecar):
            sidecar_path = default_sidecar

    processed_file = run_zoom_processing(file_path, sidecar_path)
    if not processed_file:
        return jsonify({
            'error': 'Zoom processing failed or no sidecar found',
            'company_name': company_name,
            'video_url': row['video_url']
        }), 500

    processed_video_url = f"{request.host_url.rstrip('/')}/media/{os.path.basename(processed_file)}"

    with db.cursor() as cur:
        cur.execute(
            'UPDATE videos SET processed_video_url = %s, sidecar_path = %s, updated_at = NOW() WHERE company_name = %s',
            (processed_video_url, sidecar_path, company_name),
        )
    db.commit()

    return jsonify({
        'company_name': company_name,
        'video_url': row['video_url'],
        'processed_video_url': processed_video_url,
        'status': 'success'
    }), 200


@app.route('/get_video_url', methods=['GET'])
def get_video_url():
    company_name = request.args.get('company_name')
    if not company_name:
        return jsonify({'error': 'company_name parameter is required'}), 400

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            'SELECT company_name, video_url, processed_video_url FROM videos WHERE company_name = %s',
            (company_name,),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({'error': 'Company not found'}), 404

    return jsonify({
        'company_name': row['company_name'],
        'video_url': row['video_url'],
        'processed_video_url': row.get('processed_video_url')
    }), 200


@app.route('/media/<path:filename>', methods=['GET'])
def serve_media(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


def _serialize_company(row: dict) -> dict:
    """Format row dictionary into JSON-serializable structure with ISO timestamps."""
    item = dict(row)
    for dt_col in ('created_at', 'updated_at'):
        val = item.get(dt_col)
        if val and hasattr(val, 'isoformat'):
            item[dt_col] = val.isoformat()
    return item


@app.route('/upload_companies', methods=['GET', 'POST'])
def upload_companies():
    if request.method == 'GET':
        return '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Upload Companies CSV</title>
</head>
<body>
  <h2>Upload Companies CSV</h2>
  <form action="/upload_companies" method="post" enctype="multipart/form-data">
    <p><input type="file" name="file" accept=".csv" required></p>
    <p><button type="submit">Upload</button></p>
  </form>
  <p><a href="/companies">View all companies</a></p>
</body>
</html>''', 200, {'Content-Type': 'text/html; charset=utf-8'}

    if 'file' not in request.files:
        return jsonify({'error': 'No file part in request'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        content = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            content = file.read().decode('latin-1')
        except Exception as e:
            return jsonify({'error': f'Could not decode file: {e}'}), 400

    reader = csv.DictReader(io.StringIO(content), delimiter=';', quotechar='"')
    if not reader.fieldnames:
        return jsonify({'error': 'Empty or invalid CSV file'}), 400

    def get_val(r: dict, *aliases: str) -> str | None:
        for alias in aliases:
            for k in r:
                if k and k.strip().lower() == alias.lower():
                    v = (r[k] or '').strip()
                    return v if v else None
        return None

    db = get_db()
    imported = 0
    updated = 0

    with db.cursor() as cur:
        for r in reader:
            company_name = get_val(r, 'Company Name', 'company_name', 'name')
            if not company_name:
                continue

            language = get_val(r, 'Language', 'language')
            country = get_val(r, 'Country', 'country')
            postcode = get_val(r, 'Postcode', 'postcode', 'zip')
            city = get_val(r, 'City', 'city')
            street = get_val(r, 'Street', 'street')
            house_no = get_val(r, 'HouseNo', 'house_no', 'house_number')
            web = get_val(r, 'Web', 'web', 'website', 'url')

            cur.execute('''
                INSERT INTO companies (
                    company_name, language, country, postcode, city, street, house_no, web
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_name) DO UPDATE SET
                    language = COALESCE(EXCLUDED.language, companies.language),
                    country = COALESCE(EXCLUDED.country, companies.country),
                    postcode = COALESCE(EXCLUDED.postcode, companies.postcode),
                    city = COALESCE(EXCLUDED.city, companies.city),
                    street = COALESCE(EXCLUDED.street, companies.street),
                    house_no = COALESCE(EXCLUDED.house_no, companies.house_no),
                    web = COALESCE(EXCLUDED.web, companies.web),
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted;
            ''', (company_name, language, country, postcode, city, street, house_no, web))

            res = cur.fetchone()
            if res and res.get('inserted'):
                imported += 1
            else:
                updated += 1

    db.commit()
    return jsonify({
        'status': 'ok',
        'imported': imported,
        'updated': updated,
        'total_rows': imported + updated,
    }), 200


@app.route('/companies', methods=['GET'])
def list_companies():
    status_param = request.args.get('status')
    status_val = None
    filter_null = False

    if status_param is not None:
        trimmed = status_param.strip().lower()
        if trimmed in ('null', 'none', 'pending'):
            filter_null = True
        else:
            try:
                status_val = int(status_param)
            except ValueError:
                return jsonify({'error': 'Invalid status parameter'}), 400

    db = get_db()

    query = '''
        SELECT id, company_name, language, country, postcode, city, street, house_no,
               web, status, impressum_url, legal_name, postal_address, handelsregister,
               vat_number, phone, email, responsible_person, raw_json, created_at, updated_at
        FROM companies
    '''
    params = []

    if filter_null:
        query += ' WHERE status IS NULL'
    elif status_val is not None:
        query += ' WHERE status = %s'
        params.append(status_val)

    query += ' ORDER BY id ASC'

    with db.cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    return jsonify([_serialize_company(r) for r in rows]), 200


@app.route('/companies/<path:company_name>', methods=['GET'])
def get_company(company_name):
    db = get_db()
    with db.cursor() as cur:
        cur.execute('''
            SELECT id, company_name, language, country, postcode, city, street, house_no,
                   web, status, impressum_url, legal_name, postal_address, handelsregister,
                   vat_number, phone, email, responsible_person, raw_json, created_at, updated_at
            FROM companies
            WHERE company_name = %s
        ''', (company_name,))
        row = cur.fetchone()

    if not row:
        return jsonify({'error': 'Company not found'}), 404

    return jsonify(_serialize_company(row)), 200


if __name__ == '__main__':
    # Локальный запуск без Docker (нужны те же DB_* переменные окружения).
    init_db()

    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 8000))
    app.run(host=host, port=port, debug=False)

import os
import sys
import time
import subprocess
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory, g

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SCHEMA_SQL = '''
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
'''


def _db_params():
    """Параметры подключения берутся только из переменных окружения."""
    return {
        'host': os.environ['DB_HOST'],
        'port': os.environ.get('DB_PORT', '5432'),
        'dbname': os.environ['DB_NAME'],
        'user': os.environ['DB_USER'],
        'password': os.environ['DB_PASSWORD'],
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
            company_name = request.json.get('company_name')
        else:
            company_name = request.form.get('company_name') or request.args.get('company_name')

    if not company_name:
        return jsonify({'error': 'company_name is required'}), 400

    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            'SELECT company_name, video_url, file_path, sidecar_path, processed_video_url FROM videos WHERE company_name = %s',
            (company_name,),
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


if __name__ == '__main__':
    # Локальный запуск без Docker (нужны те же DB_* переменные окружения).
    init_db()

    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 8000))
    app.run(host=host, port=port, debug=False)

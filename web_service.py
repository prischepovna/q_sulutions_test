import hashlib
import os
import sqlite3
from urllib.parse import quote

from flask import Flask, request, jsonify, send_from_directory, g
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_NAME = os.path.join(BASE_DIR, 'videos.db')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_NAME, timeout=30.0)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL;')
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                video_url TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        ''')
        conn.commit()


init_db()


def make_filename(company_name: str) -> str:
    safe = secure_filename(company_name.replace(' ', '_'))
    if not safe:
        safe = 'video_' + hashlib.sha1(company_name.encode('utf-8')).hexdigest()[:10]
    return f"{safe}.webm"


@app.route('/upload', methods=['POST'])
def upload_video():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    company_name = (request.form.get('company_name') or '').strip()

    if not company_name or file.filename == '':
        return jsonify({'error': 'Company name and file are required'}), 400

    filename = make_filename(company_name)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    video_url = f"{request.host_url.rstrip('/')}/media/{quote(filename)}"

    db = get_db()
    db.execute('''
        INSERT INTO videos (company_name, video_url, file_path, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(company_name) DO UPDATE SET
            video_url = excluded.video_url,
            file_path = excluded.file_path,
            updated_at = datetime('now');
    ''', (company_name, video_url, file_path))
    db.commit()

    return jsonify({'company_name': company_name, 'video_url': video_url}), 200


@app.route('/get_video_url', methods=['GET'])
def get_video_url():
    company_name = request.args.get('company_name')
    if not company_name:
        return jsonify({'error': 'company_name parameter is required'}), 400

    row = get_db().execute(
        'SELECT company_name, video_url FROM videos WHERE company_name = ?',
        (company_name,)
    ).fetchone()

    if not row:
        return jsonify({'error': 'Company not found'}), 404

    return jsonify({'company_name': row['company_name'], 'video_url': row['video_url']}), 200


@app.route('/media/<path:filename>', methods=['GET'])
def serve_media(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/videos', methods=['GET'])
def list_videos():
    rows = get_db().execute(
        'SELECT id, company_name, video_url, file_path, created_at, updated_at '
        'FROM videos ORDER BY id'
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200


if __name__ == '__main__':
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 8000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host=host, port=port, debug=debug)
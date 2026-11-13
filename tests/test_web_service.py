
import io
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

flask = pytest.importorskip("flask")

if 'psycopg2' not in sys.modules:
    mock_psycopg2 = MagicMock()
    mock_psycopg2.OperationalError = Exception
    sys.modules['psycopg2'] = mock_psycopg2
    sys.modules['psycopg2.extras'] = MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import web_service


@pytest.fixture
def client(tmp_path):
    web_service.app.config['TESTING'] = True
    web_service.app.config['UPLOAD_FOLDER'] = str(tmp_path)

    with web_service.app.test_client() as client:
        yield client


def test_upload_missing_file(client):
    res = client.post('/upload', data={'company_name': 'AcmeCorp'})
    assert res.status_code == 400
    assert 'No file part' in res.get_json()['error']


def test_upload_missing_company(client):
    data = {'file': (io.BytesIO(b'video content'), 'test.webm')}
    res = client.post('/upload', data=data, content_type='multipart/form-data')
    assert res.status_code == 400
    assert 'Company name and file are required' in res.get_json()['error']


@patch('web_service.get_db')
@patch('web_service.run_zoom_processing')
def test_upload_success_with_sidecar(mock_run_zoom, mock_get_db, client, tmp_path):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur

    mock_run_zoom.return_value = str(tmp_path / "AcmeCorp_zoomed.webm")

    data = {
        'company_name': 'AcmeCorp',
        'file': (io.BytesIO(b'video data'), 'AcmeCorp.webm'),
        'sidecar': (io.BytesIO(json.dumps({"events": []}).encode('utf-8')), 'AcmeCorp.zoom.json'),
    }

    res = client.post('/upload', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['company_name'] == 'AcmeCorp'
    assert 'AcmeCorp.webm' in json_data['video_url']
    assert 'AcmeCorp_zoomed.webm' in json_data['processed_video_url']
    assert mock_cur.execute.called


@patch('web_service.get_db')
def test_get_video_url_missing_param(mock_get_db, client):
    res = client.get('/get_video_url')
    assert res.status_code == 400
    assert 'company_name parameter is required' in res.get_json()['error']


@patch('web_service.get_db')
def test_get_video_url_not_found(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = None

    res = client.get('/get_video_url?company_name=NonExistent')
    assert res.status_code == 404
    assert 'Company not found' in res.get_json()['error']


@patch('web_service.get_db')
def test_get_video_url_success(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        'company_name': 'AcmeCorp',
        'video_url': 'http://localhost/media/AcmeCorp.webm',
        'processed_video_url': 'http://localhost/media/AcmeCorp_zoomed.webm',
    }

    res = client.get('/get_video_url?company_name=AcmeCorp')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['company_name'] == 'AcmeCorp'
    assert json_data['video_url'] == 'http://localhost/media/AcmeCorp.webm'
    assert json_data['processed_video_url'] == 'http://localhost/media/AcmeCorp_zoomed.webm'


@patch('web_service.get_db')
@patch('web_service.run_zoom_processing')
def test_process_endpoint_success(mock_run_zoom, mock_get_db, client, tmp_path):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        'company_name': 'AcmeCorp',
        'video_url': 'http://localhost/media/AcmeCorp.webm',
        'file_path': str(tmp_path / 'AcmeCorp.webm'),
        'sidecar_path': str(tmp_path / 'AcmeCorp.zoom.json'),
        'processed_video_url': None,
    }

    mock_run_zoom.return_value = str(tmp_path / 'AcmeCorp_zoomed.webm')

    res = client.post('/process', json={'company_name': 'AcmeCorp'})
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['status'] == 'success'
    assert 'AcmeCorp_zoomed.webm' in json_data['processed_video_url']

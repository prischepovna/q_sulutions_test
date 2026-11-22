
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


def test_get_upload_companies_form(client):
    res = client.get('/upload_companies')
    assert res.status_code == 200
    assert b'<form' in res.data
    assert b'name="file"' in res.data
    assert b'Upload Companies CSV' in res.data
    assert b'href="/companies"' in res.data


def test_post_upload_companies_no_file(client):
    res = client.post('/upload_companies')
    assert res.status_code == 400
    assert 'No file part' in res.get_json()['error']


def test_post_upload_companies_empty_filename(client):
    data = {'file': (io.BytesIO(b''), '')}
    res = client.post('/upload_companies', data=data, content_type='multipart/form-data')
    assert res.status_code == 400
    assert 'No file selected' in res.get_json()['error']


@patch('web_service.get_db')
def test_post_upload_companies_success(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    # Row 1 inserted (True), Row 2 updated (False)
    mock_cur.fetchone.side_effect = [{'inserted': True}, {'inserted': False}]

    csv_data = (
        "URL;Company Name;Language;Country;Postcode;City;Street;HouseNo;Web\n"
        "http://nutrimmun.de;nutrimmun GmbH;DE;DE;48153;Münster;Ludgeriplatz;2;http://nutrimmun.de\n"
        "http://barolo.com;Barolo GbR;DE;DE;10115;Berlin;Muster;1;http://barolo.com\n"
    ).encode('utf-8')

    data = {'file': (io.BytesIO(csv_data), 'companies.csv')}
    res = client.post('/upload_companies', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    json_res = res.get_json()
    assert json_res['status'] == 'ok'
    assert json_res['imported'] == 1
    assert json_res['updated'] == 1
    assert json_res['total_rows'] == 2
    assert mock_cur.execute.call_count == 2
    # Verify ON CONFLICT query was executed
    first_query = mock_cur.execute.call_args_list[0][0][0]
    assert 'ON CONFLICT (company_name) DO UPDATE' in first_query


@patch('web_service.get_db')
def test_list_companies_success(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [
        {
            'id': 1,
            'company_name': 'nutrimmun GmbH',
            'status': 0,
            'web': 'http://nutrimmun.de',
            'city': 'Münster',
            'created_at': None,
            'updated_at': None,
        },
        {
            'id': 2,
            'company_name': 'Barolo & Champagne GbR',
            'status': 3,
            'web': 'http://baroloandchampagne.com',
            'city': 'Berlin',
            'created_at': None,
            'updated_at': None,
        },
    ]

    res = client.get('/companies')
    assert res.status_code == 200
    rows = res.get_json()
    assert len(rows) == 2
    assert rows[0]['company_name'] == 'nutrimmun GmbH'


@patch('web_service.get_db')
def test_list_companies_with_status_filter(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [
        {'id': 1, 'company_name': 'nutrimmun GmbH', 'status': 0, 'created_at': None, 'updated_at': None}
    ]

    res = client.get('/companies?status=0')
    assert res.status_code == 200
    rows = res.get_json()
    assert len(rows) == 1
    assert rows[0]['status'] == 0
    query = mock_cur.execute.call_args[0][0]
    assert 'WHERE status = %s' in query


def test_list_companies_invalid_status_filter(client):
    res = client.get('/companies?status=invalid')
    assert res.status_code == 400
    assert 'Invalid status parameter' in res.get_json()['error']


@patch('web_service.get_db')
def test_get_single_company_success(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        'id': 1,
        'company_name': 'nutrimmun GmbH',
        'status': 0,
        'web': 'http://nutrimmun.de',
        'vat_number': 'DE126116348',
        'created_at': None,
        'updated_at': None,
    }

    res = client.get('/companies/nutrimmun%20GmbH')
    assert res.status_code == 200
    data = res.get_json()
    assert data['company_name'] == 'nutrimmun GmbH'
    assert data['vat_number'] == 'DE126116348'


@patch('web_service.get_db')
def test_get_single_company_not_found(mock_get_db, client):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_cur = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = None

    res = client.get('/companies/NonExistentCorp')
    assert res.status_code == 404
    assert 'Company not found' in res.get_json()['error']


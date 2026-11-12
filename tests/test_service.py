"""API/CLI contract tests with synthetic worker results, not platform acceptance."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import downloader as d
from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'DOWNLOADS_DIR', tmp_path)
    with TestClient(main.app) as client:
        yield client


def test_api_errors_and_input_validation(client):
    with patch('app.main.get_info', side_effect=d.DownloadError('timeout')):
        response = client.post('/api/parse', json={'text': 'https://youtu.be/abc'})
        assert response.status_code == 504
        assert response.json()['code'] == 'timeout'
        assert isinstance(response.json()['detail'], str)
    assert client.post('/api/download', json={'text': 'https://youtu.be/abc', 'confirmed': False}).status_code == 400
    assert client.post('/api/download', json={'text': 'https://youtu.be/abc', 'quality': 'invalid', 'confirmed': True}).status_code == 422
    assert client.post('/api/parse', json={'text': 'x' * 8193}).status_code == 422


def test_busy_is_retryable(client):
    with patch('app.main.get_info', side_effect=d.DownloadError('busy')):
        response = client.post('/api/parse', json={'text': 'https://youtu.be/abc'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '5'


def test_existing_owner_pages_frontend_can_preflight(client):
    response = client.options('/api/parse', headers={
        'Origin': 'https://yuyantan02-cmyk.github.io',
        'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'https://yuyantan02-cmyk.github.io'


def test_file_is_signed_typed_and_not_cross_origin(client, tmp_path):
    (tmp_path / 'a.json').write_text('{}')
    assert client.get('/files/a.json').status_code == 403
    token = d.file_token('a.json')
    response = client.get('/files/a.json', params={'token': token}, headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert 'access-control-allow-origin' not in response.headers
    assert response.headers['cache-control'] == 'private, no-store'
    assert client.get('/files/a.json', params={'token': d.file_token('b.json')}).status_code == 403
    assert not d.valid_file_token('a.json', d.file_token('a.json', int(time.time()) - 1))


def test_signed_symlink_cannot_escape(client, tmp_path):
    outside = tmp_path.parent / 'outside.json'
    outside.write_text('{}')
    (tmp_path / 'escape.json').symlink_to(outside)
    assert client.get('/files/escape.json', params={'token': d.file_token('escape.json')}).status_code == 400


def test_api_preserves_old_keys_and_returns_signed_sidecar(client):
    result = {'file': 'a.mp4', 'bytes': 123, 'metadata_file': 'a.json', 'platform': {'key': 'youtube'},
              'info': {'title': 'Synthetic', 'uploader': 'Author'}, 'watermark_note': '未验证'}
    with patch('app.main.download', return_value=result):
        body = client.post('/api/download', json={'text': 'https://youtu.be/abc', 'confirmed': True}).json()
    assert {'file', 'bytes', 'metadata_file', 'platform', 'title', 'uploader', 'download_url', 'watermark_note'} <= body.keys()
    assert '?token=' in body['download_url'] and '?token=' in body['metadata_url']
    assert body['watermark_status'] == 'unverified'
    assert len(client.get('/api/platforms').json()) == 11


def test_download_tasks_never_delete_previous_results(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'DOWNLOADS_DIR', tmp_path)
    old = tmp_path / 'successful.mp4'
    old.write_bytes(b'old success')

    def worker(mode, url, quality, directory):
        (directory / 'video.mp4').write_bytes(b'synthetic media')
        return {'path': 'video.mp4', 'info': {'title': 'Same title', 'watermark_status': 'unverified'}}

    with patch('app.downloader._run_worker', side_effect=worker):
        first = d.download('https://youtu.be/abc', True)
        second = d.download('https://youtu.be/abc', True)
    assert first['path'] != second['path']
    assert old.read_bytes() == b'old success'
    assert list((tmp_path / '.tasks').iterdir()) == []
    with patch('app.downloader._run_worker', side_effect=d.DownloadError('network_error')):
        with pytest.raises(d.DownloadError):
            d.download('https://youtu.be/abc', True)
    assert Path(first['path']).is_file()
    assert list((tmp_path / '.tasks').iterdir()) == []


def test_cleanup_only_expires_owned_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'DOWNLOADS_DIR', tmp_path)
    expired = tmp_path / ('old_' + 'a' * 24 + '.mp4')
    expired.write_bytes(b'old')
    expired.with_suffix('.json').write_text(json.dumps({'managed_by': 'social-video-downloader', 'file': expired.name, 'expires_at': 1}))
    legacy = tmp_path / 'old-user-file.mp4'
    legacy.write_bytes(b'keep')
    os.utime(legacy, (1, 1))
    current = tmp_path / 'current.mp4'
    current.write_bytes(b'new')
    d.cleanup_downloads()
    assert not expired.exists() and current.exists() and legacy.exists()


def test_source_tokens_are_not_persisted():
    url = 'https://www.xiaohongshu.com/explore/abc?xsec_token=secret&xsec_source=pc_share'
    assert 'secret' not in d.source_url(url)
    assert 'xsec_source=pc_share' in d.source_url(url)


def test_cli_confirm_precedes_metadata_request(monkeypatch):
    import cli
    monkeypatch.setattr(sys, 'argv', ['cli.py', 'https://youtu.be/abc'])
    with patch('cli.get_info') as get_info:
        assert cli.main() == 1
        get_info.assert_not_called()


def test_worker_blocks_loopback_in_a_real_child():
    code = '''from app.network import install_socket_guard, open_public
install_socket_guard()
try:
    open_public('http://127.0.0.1/')
except Exception:
    print('BLOCKED')
else:
    raise AssertionError('loopback reached')
'''
    result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True, timeout=10, check=True)
    assert result.stdout.strip() == 'BLOCKED'


def test_worker_admission_limit():
    d._TASK_SLOT.acquire()
    try:
        with pytest.raises(d.DownloadError) as error:
            d._run_worker('info', 'https://youtu.be/abc')
        assert error.value.code == 'busy'
    finally:
        d._TASK_SLOT.release()


def test_worker_import_is_independent_of_launch_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = f'''import sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
from app import downloader as d
d.DOWNLOADS_DIR = Path({str(tmp_path)!r}) / 'downloads'
try:
    d._run_worker('info', 'https://example.com/not-supported')
except d.DownloadError as error:
    print(error.code)
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            text=True, capture_output=True, timeout=15, check=True)
    assert result.stdout.strip() == 'unsupported'

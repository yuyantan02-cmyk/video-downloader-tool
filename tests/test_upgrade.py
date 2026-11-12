"""Synthetic regression/security fixtures; these are NOT real platform downloads."""
import json
import socket
from unittest.mock import patch

import pytest

from app.platforms import detect_platform


@pytest.mark.parametrize('url', [
    'http://127.0.0.1/kuaishou.com/',
    'https://evil.example/youtube.com/watch?v=x',
    'https://youtube.com.evil.example/watch?v=x',
    'https://youtube.com@evil.example/watch?v=x',
    'https://www.youtube.com:8080/watch?v=x',
])
def test_platform_host_is_a_boundary(url):
    assert detect_platform(url) is None


@pytest.mark.parametrize(('url', 'key'), [
    ('https://v.douyin.com/abc/', 'douyin'),
    ('https://www.facebook.com/watch/?v=123', 'facebook'),
    ('https://youtu.be/abc', 'youtube'),
    ('https://www.threads.com/@name/post/ABC', 'threads'),
    ('https://b23.tv/abc', 'bilibili'),
    ('https://xhslink.cn/a/abc', 'xiaohongshu'),
    ('https://weixin.qq.com/sph/abc', 'wechat'),
    ('https://vm.tiktok.com/abc', 'tiktok'),
    ('https://x.com/a/status/123', 'x'),
    ('https://www.instagram.com/reel/abc/', 'instagram'),
    ('https://v.kuaishou.com/abc', 'kuaishou'),
])
def test_all_platform_routes(url, key):
    assert detect_platform(url)['key'] == key


def test_dns_rejects_any_private_answer():
    from app.network import public_addresses
    with patch('app.network.socket.getaddrinfo', return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443)),
    ]):
        with pytest.raises(ValueError):
            public_addresses('example.com', 443)


def test_errors_are_classified_and_redacted():
    from app.downloader import DownloadError, explain_failure
    for message, code in [('Fresh cookies are needed', 'verification_required'),
                          ('login required', 'login_required'),
                          ('HTTP Error 404', 'unavailable'),
                          ('Unsupported URL', 'unsupported'),
                          ('connection timed out', 'network_error')]:
        assert explain_failure(message).code == code
    assert 'secret' not in str(DownloadError('network_error', 'https://x.test/?token=secret'))
    assert explain_failure('Unsupported URL: https://example.com/?redirect=login').code == 'unsupported'


def test_wechat_is_explicitly_blocked():
    from app.downloader import DownloadError, get_info
    with pytest.raises(DownloadError) as error:
        get_info('https://weixin.qq.com/sph/abc')
    assert error.value.code == 'official_export_required'


def test_image_and_protected_metadata_are_rejected():
    from app.worker import validate_info
    from app.downloader import DownloadError
    for info in [{'id': 'a', 'formats': []},
                 {'id': 'a', 'has_drm': True},
                 {'id': 'a', 'availability': 'private'},
                 {'id': 'a', 'age_limit': 18}]:
        with pytest.raises(DownloadError):
            validate_info(info)


def test_threads_uses_only_requested_post_videos():
    from app.extractors import threads_info
    page = json.dumps({'items': [
        {'code': 'OTHER', 'video_versions': [{'url': 'https://cdn.example/other.mp4'}]},
        {'code': 'ABC', 'caption': {'text': 'Title'}, 'user': {'username': 'author'},
         'carousel_media': [{'image_versions2': {'candidates': []}},
                            {'id': 'v1', 'video_versions': [{'url': 'https://cdn.example/video.mp4', 'width': 720, 'height': 1280}]}]},
    ]})
    info = threads_info('<script type="application/json">' + page + '</script>', 'ABC')
    assert info['video_count'] == 1
    assert info['formats'][0]['url'] == 'https://cdn.example/video.mp4'
    assert info['uploader'] == 'author'


def test_confirmation_stops_network():
    from app.downloader import download
    with patch('app.downloader._run_worker') as run:
        with pytest.raises(ValueError):
            download('https://youtu.be/abc', False)
        run.assert_not_called()

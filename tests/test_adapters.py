"""Synthetic public-page and redirect fixtures only."""
import json
from unittest.mock import Mock, patch

import pytest
from yt_dlp.utils import ExtractorError
from yt_dlp import YoutubeDL

from app.extractors import PublicDouyinIE, PublicXiaohongshuIE, threads_info
from app.kuaishou import extract_photo_id
from app.worker import normalize_url


def test_short_xhs_link_keeps_required_query():
    destination = 'https://www.xiaohongshu.com/explore/abc?xsec_token=secret&xsec_source=pc_share'
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.geturl.return_value = destination
    with patch('app.worker.open_public', return_value=response):
        assert normalize_url('https://xhslink.cn/a/abc') == destination


def test_short_link_cannot_change_platform():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.geturl.return_value = 'https://www.youtube.com/watch?v=abc'
    with patch('app.worker.open_public', return_value=response), pytest.raises(RuntimeError):
        normalize_url('https://b23.tv/abc')


def test_douyin_public_hydration_reuses_original_video_parser():
    extractor = PublicDouyinIE()
    item = {'aweme_id': '123456', 'video': {'play_addr': {'url_list': ['https://cdn.example/v.mp4']}}}
    page = 'window._ROUTER_DATA = ' + json.dumps({'loaderData': {'videoInfoRes': {'item_list': [item]}}})
    with patch.object(extractor, '_download_webpage', return_value=page), patch.object(extractor, '_parse_aweme_video_app', return_value={'id': '123456'}) as parse:
        assert extractor._real_extract('https://www.douyin.com/video/123456')['id'] == '123456'
        parse.assert_called_once_with(item)


def test_xhs_image_note_has_explicit_error():
    extractor = PublicXiaohongshuIE(YoutubeDL({"quiet": True}))
    with patch('yt_dlp.extractor.xiaohongshu.XiaoHongShuIE._real_extract', return_value={'formats': []}):
        with pytest.raises(ExtractorError, match='NO_VIDEO'):
            extractor._real_extract('https://www.xiaohongshu.com/explore/abc')


def test_xhs_verification_page_is_not_an_image_note():
    extractor = PublicXiaohongshuIE(YoutubeDL({"quiet": True}))
    with patch('yt_dlp.extractor.common.InfoExtractor._download_webpage', return_value='<html>安全验证</html>'):
        with pytest.raises(ExtractorError, match='VERIFICATION_REQUIRED'):
            extractor._download_webpage('https://www.xiaohongshu.com/explore/abc', 'abc')


def test_xhs_image_type_is_checked_before_media_extraction():
    extractor = PublicXiaohongshuIE(YoutubeDL({"quiet": True}))
    page = 'window.__INITIAL_STATE__=' + json.dumps({'note': {'noteDetailMap': {'abc': {'note': {'type': 'normal'}}}}})
    with patch('yt_dlp.extractor.common.InfoExtractor._download_webpage', return_value=page):
        with pytest.raises(ExtractorError, match='NO_VIDEO'):
            extractor._download_webpage('https://www.xiaohongshu.com/explore/abc', 'abc')


def test_kuaishou_redirect_stops_without_progress():
    url = 'https://v.kuaishou.com/abc'
    with patch('app.kuaishou._http_get', return_value=(url, '')) as get:
        assert extract_photo_id(url) is None
        assert get.call_count == 1


def test_threads_image_post_does_not_pick_recommendations():
    payload = [{'code': 'ABC', 'image_versions2': {}}, {'code': 'OTHER', 'video_versions': [{'url': 'https://cdn.example/video.mp4'}]}]
    with pytest.raises(ExtractorError, match='NO_VIDEO'):
        threads_info('<script type="application/json">' + json.dumps(payload) + '</script>', 'ABC')


def test_threads_multi_video_selection_is_explicit():
    payload = {'code': 'ABC', 'carousel_media': [{'video_versions': [{'url': 'https://cdn.example/a.mp4'}]}, {'video_versions': [{'url': 'https://cdn.example/b.mp4'}]}]}
    info = threads_info('<script type="application/json">' + json.dumps(payload) + '</script>', 'ABC')
    assert info['video_count'] == 2 and '第一段' in info['selection_note']

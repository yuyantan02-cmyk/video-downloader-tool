"""Public-page adapters; fixtures prove parsing, not live platform availability."""
import html
import json
import re
from urllib.parse import unquote

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.extractor.xiaohongshu import XiaoHongShuIE
from yt_dlp.utils import ExtractorError, js_to_json


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def threads_info(page, post_id):
    posts = []
    for script in re.findall(r'<script\b[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(html.unescape(script))
        except (ValueError, RecursionError):
            continue
        posts.extend(node for node in objects(data) if node.get('code') == post_id or node.get('shortcode') == post_id)
    for post in posts:
        videos = [item for item in (post.get('carousel_media') or [post]) if item.get('video_versions')]
        if not videos:
            continue
        video = videos[0]
        formats = [{'url': f['url'], 'width': f.get('width'), 'height': f.get('height'),
                    'ext': 'mp4', 'format_id': str(index)}
                   for index, f in enumerate(video['video_versions']) if f.get('url')]
        caption = post.get('caption') or {}
        return {'id': post_id, 'title': caption.get('text') or f'Threads {post_id}',
                'uploader': (post.get('user') or {}).get('username'), 'formats': formats,
                'duration': video.get('video_duration'),
                'thumbnail': next((f.get('url') for f in (video.get('image_versions2') or {}).get('candidates', []) if f.get('url')), None),
                'video_count': len(videos),
                'selection_note': '多媒体帖子下载第一段视频，跳过图片。' if len(videos) > 1 else ''}
    if posts:
        raise ExtractorError('NO_VIDEO: 这个 Threads 帖子没有视频', expected=True)
    if re.search(r'captcha|login_required|checkpoint|challenge_required', page, re.I):
        raise ExtractorError('VERIFICATION_REQUIRED: Threads 要求登录或访问验证', expected=True)
    raise ExtractorError('UNSUPPORTED: 未找到属于当前帖子的公开媒体数据', expected=True)


class PublicThreadsIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?threads\.(?:net|com)/@[^/]+/post/(?P<id>[^/?#]+)'

    def _real_extract(self, url):
        post_id = self._match_id(url)
        return threads_info(self._download_webpage(url, post_id), post_id)


class PublicDouyinIE(DouyinIE):
    def _real_extract(self, url):
        video_id = self._match_id(url)
        page = self._download_webpage(f'https://www.iesdouyin.com/share/video/{video_id}/', video_id, fatal=False) or ''
        payloads = []
        for pattern, encoded in [(r'window\._ROUTER_DATA\s*=\s*', False),
                                 (r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>\s*', True)]:
            match = re.search(pattern, page)
            if match:
                try:
                    payloads.append(json.JSONDecoder().raw_decode(unquote(page[match.end():]) if encoded else page[match.end():])[0])
                except (ValueError, RecursionError):
                    pass
        for payload in payloads:
            for item in objects(payload):
                if str(item.get('aweme_id')) == video_id and item.get('video'):
                    if item.get('is_private') or (item.get('status') or {}).get('is_private'):
                        raise ExtractorError('PRIVATE: 视频不可公开访问', expected=True)
                    return self._parse_aweme_video_app(item)
        # No verification-cookie generation or rewriting of watermarked URLs.
        return super()._real_extract(url)


class PublicXiaohongshuIE(XiaoHongShuIE):
    def _download_webpage(self, *args, **kwargs):
        page = super()._download_webpage(*args, **kwargs)
        if '__INITIAL_STATE__' not in page and re.search(r'captcha|安全验证|登录后查看|当前笔记暂时无法浏览', page, re.I):
            raise ExtractorError('VERIFICATION_REQUIRED: 小红书返回访问验证页', expected=True)
        state = self._search_json(r'window\.__INITIAL_STATE__\s*=', page, 'initial state', args[1],
                                  transform_source=js_to_json, default={})
        notes = (state.get('note') or {}).get('noteDetailMap') or {}
        note = (notes.get(args[1]) or {}).get('note') or {}
        if note.get('type') in ('normal', 'image'):
            raise ExtractorError('NO_VIDEO: 这是图片笔记，不是视频笔记', expected=True)
        return page

    def _real_extract(self, url):
        result = super()._real_extract(url)
        if not result.get('formats'):
            raise ExtractorError('NO_VIDEO: 笔记没有可公开获取的视频流，可能是图片笔记', expected=True)
        return result

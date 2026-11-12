"""One bounded media task per child. No inherited yt-dlp CLI config or plugins."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

# The Python API otherwise discovers user-installed extractor/postprocessor plugins.
os.environ['YTDLP_NO_PLUGINS'] = '1'

from yt_dlp import YoutubeDL
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.external import FFmpegFD
from yt_dlp.networking import Request
from yt_dlp.networking._urllib import UrllibRH

from .downloader import DownloadError, explain_failure, source_url
from .extractors import PublicDouyinIE, PublicThreadsIE, PublicXiaohongshuIE
from .network import install_socket_guard, open_public, validate_url
from .platforms import detect_platform


def normalize_url(url):
    platform = detect_platform(url)
    if not platform:
        raise DownloadError('unsupported')
    key = platform['key']
    parts = urlsplit(url)
    short_hosts = {'v.douyin.com', 'b23.tv', 'xhslink.com', 'www.xhslink.com', 'xhslink.cn', 'www.xhslink.cn'}
    if parts.hostname in short_hosts:
        with open_public(url, timeout=20) as response:
            url = response.geturl()
        resolved = detect_platform(url)
        if not resolved or resolved['key'] != key:
            raise DownloadError('unsupported')
        parts = urlsplit(url)
    if re.search(r'/(?:login|signin)(?:/|$)', parts.path):
        raise DownloadError('login_required')
    if re.search(r'/(?:captcha|checkpoint|challenge)(?:/|$)', parts.path):
        raise DownloadError('verification_required')
    if key == 'xiaohongshu' and parts.hostname in ('xiaohongshu.com', 'www.xiaohongshu.com'):
        url = urlunsplit(('https', 'www.xiaohongshu.com', parts.path, parts.query, ''))
    if key == 'douyin':
        match = re.search(r'/(?:video|share/video)/(\d+)', parts.path)
        video_id = match.group(1) if match else parse_qs(parts.query).get('modal_id', [None])[0]
        if video_id and video_id.isdigit():
            url = f'https://www.douyin.com/video/{video_id}'
    return url


def validate_info(info):
    if info.get('has_drm') or info.get('is_paid') or info.get('age_limit', 0) and info['age_limit'] > 0:
        raise DownloadError('restricted')
    if info.get('is_private'):
        raise DownloadError('private')
    if info.get('availability') == 'needs_auth':
        raise DownloadError('login_required')
    if info.get('availability') in ('private', 'needs_auth', 'premium_only', 'subscriber_only'):
        raise DownloadError('private' if info['availability'] == 'private' else 'restricted')
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
        raise DownloadError('unsupported')
    if not info.get('formats') and not info.get('url'):
        raise DownloadError('no_video')
    allowed = []
    for fmt in info.get('formats') or [info]:
        if fmt.get('has_drm'):
            continue
        if fmt.get('protocol', 'https') not in ('http', 'https', 'm3u8', 'm3u8_native', 'http_dash_segments'):
            continue
        validate_url(fmt['url'])
        allowed.append(fmt)
    if not allowed:
        raise DownloadError('restricted')
    if 'formats' in info:
        info['formats'] = allowed


class SafeYoutubeDL(YoutubeDL):
    def build_request_director(self, handlers, preferences=None):
        # Keep every media connection in Python's guarded sockets, including redirects.
        return super().build_request_director([UrllibRH])

    def urlopen(self, request):
        validate_url(request.url if isinstance(request, Request) else request)
        return super().urlopen(request)

    def process_ie_result(self, result, download=True, extra_info=None):
        if result.get('_type', 'video') == 'video':
            validate_info(result)
        elif result.get('_type') in ('playlist', 'multi_video'):
            raise DownloadError('unsupported')
        return super().process_ie_result(result, download, extra_info)

    def process_info(self, info):
        validate_info(info)
        for fmt in info.get('requested_formats') or [info]:
            downloader = get_suitable_downloader(fmt.copy(), self.params)
            if not downloader or downloader.__name__ not in ('HttpFD', 'HlsFD', 'DashSegmentsFD'):
                raise DownloadError('unsupported')
        return super().process_info(info)


def public_info(info):
    formats = []
    for fmt in info.get('formats') or []:
        if fmt.get('vcodec') == 'none':
            continue
        formats.append({key: fmt.get(key) for key in (
            'format_id', 'ext', 'protocol', 'width', 'height', 'fps', 'filesize', 'tbr', 'vcodec', 'acodec')})
    formats.sort(key=lambda f: (f.get('height') or 0, f.get('tbr') or 0), reverse=True)
    thumbnail = info.get('thumbnail')
    # Do not expose a credential-bearing URL to the browser or the provenance sidecar.
    if thumbnail and source_url(thumbnail) != thumbnail:
        thumbnail = None
    return {**{key: info.get(key) for key in ('id', 'title', 'uploader', 'uploader_id', 'duration', 'width', 'height', 'ext', 'video_count', 'selection_note')},
            'webpage_url': source_url(info.get('webpage_url') or ''), 'formats': formats[:12],
            'thumbnail': thumbnail, 'description': (info.get('description') or '')[:500],
            'watermark_status': 'unverified', 'watermark_label': '未验证'}


def probe_media(path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
        audio = next((stream for stream in data['streams'] if stream['codec_type'] == 'audio'), None)
        duration = float(data.get('format', {}).get('duration') or video.get('duration') or 0)
        if video.get('width', 0) <= 0 or video.get('height', 0) <= 0 or duration <= 0:
            raise ValueError('invalid video')
        return {'width': video['width'], 'height': video['height'], 'duration': duration,
                'vcodec': video.get('codec_name'), 'acodec': audio.get('codec_name') if audio else None,
                'has_audio': audio is not None, 'ext': path.suffix[1:]}
    except FileNotFoundError as error:
        raise DownloadError('dependency_missing') from error
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration) as error:
        raise DownloadError('invalid_media') from error


def run_task(task):
    install_socket_guard()
    def refuse_external_network(*args, **kwargs):
        raise DownloadError('unsupported')
    # HlsFD can otherwise silently fall back to a network-enabled FFmpegFD.
    FFmpegFD.real_download = refuse_external_network
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):
            os.environ.pop(key)
    url = normalize_url(task['url'])
    platform = detect_platform(url)
    if not platform:
        raise DownloadError('unsupported')
    if platform['key'] == 'wechat':
        raise DownloadError('official_export_required')
    mode = task['mode']
    if mode == 'download' and (not shutil.which('ffmpeg') or not shutil.which('ffprobe')):
        raise DownloadError('dependency_missing')
    directory = Path(task['directory']) if mode == 'download' else None
    cap = {'1080p': 1080, '720p': 720}.get(task['quality'])
    selector = f'bv*[height<={cap}]+ba/b[height<={cap}]' if cap else 'bv*+ba/b'
    outputs = []
    options = {'quiet': True, 'noprogress': True, 'no_warnings': True, 'noplaylist': True, 'proxy': '',
               'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2,
               'skip_unavailable_fragments': False, 'concurrent_fragment_downloads': 1,
               'max_filesize': task['max_bytes'], 'ratelimit': 10 * 1024 * 1024,
               'format': selector, 'merge_output_format': 'mp4/mkv',
               'external_downloader': 'native', 'hls_prefer_native': True,
               'postprocessor_args': {'ffmpeg_i': ['-protocol_whitelist', 'file,pipe']},
               'cachedir': False, 'usenetrc': False, 'cookiefile': None,
               'remote_components': set(), 'js_runtimes': {'deno': {}},
               'outtmpl': str(directory / 'video.%(ext)s') if directory else '%(id)s.%(ext)s',
               'post_hooks': [outputs.append]}
    with SafeYoutubeDL(options, auto_init=False) as ydl:
        for extractor in (PublicDouyinIE, PublicThreadsIE, PublicXiaohongshuIE):
            ydl.add_info_extractor(extractor())
        ydl.add_default_info_extractors()
        if platform['key'] == 'kuaishou':
            from .kuaishou import resolve, MOBILE_UA
            ks = resolve(url)
            info = {'id': ks['photo_id'], 'title': ks['title'], 'webpage_url': url,
                    'formats': [{'format_id': 'direct', 'url': ks['video_url'], 'ext': 'mp4', 'protocol': 'https'}],
                    'http_headers': {'User-Agent': MOBILE_UA,
                                     'Referer': f"https://v.m.chenzhongtech.com/fw/photo/{ks['photo_id']}"}}
            # Dimensions are unknown until probing; never claim a cap can be enforced.
            if cap:
                raise DownloadError('unsupported')
            info = ydl.process_ie_result(info, download=False)
        else:
            info = ydl.extract_info(url, download=False)
        validate_info(info)
        result = {'info': public_info(info)}
        if mode == 'info':
            return result
        expected_audio = any(f.get('acodec') not in (None, 'none') for f in info.get('formats', []))
        expected_duration = info.get('duration')
        ydl.process_ie_result(info, download=True)
        if len(outputs) != 1:
            raise DownloadError('invalid_media')
        path = Path(outputs[0]).resolve()
        if path.parent != directory.resolve() or not path.is_file() or not 0 < path.stat().st_size <= task['max_bytes']:
            raise DownloadError('invalid_media')
        measured = probe_media(path)
        if expected_audio and not measured['has_audio']:
            raise DownloadError('invalid_media')
        if cap and measured['height'] > cap:
            raise DownloadError('invalid_media')
        if expected_duration and abs(measured['duration'] - expected_duration) > max(2, expected_duration * 0.02):
            raise DownloadError('invalid_media')
        result['info'].update(measured)
        result['path'] = path.name
        return result


def main():
    try:
        task = json.load(sys.stdin)
        result = run_task(task)
    except DownloadError as error:
        result = {'error': error.code}
    except Exception as error:
        result = {'error': explain_failure(error).code}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

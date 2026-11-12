"""Shared, bounded download lifecycle for the existing API and CLI."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .platforms import detect_platform, extract_url

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / 'downloads'
MAX_BYTES = int(os.getenv('MAX_DOWNLOAD_BYTES', str(512 * 1024 * 1024)))
FILE_TTL = int(os.getenv('DOWNLOAD_TTL_SECONDS', '3600'))
DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT_SECONDS', '600'))
PARSE_TIMEOUT = int(os.getenv('PARSE_TIMEOUT_SECONDS', '120'))
_TASK_SLOT = threading.BoundedSemaphore(1)
_FILE_KEY = secrets.token_bytes(32)
MAX_WORKER_MEMORY = int(os.getenv('MAX_WORKER_MEMORY_MB', '320')) * 1024 * 1024
WATERMARK_LABELS = {'verified_clean': '已验证无水印', 'verified_watermarked': '已验证带水印', 'unverified': '未验证'}

_MESSAGES = {
    'verification_required': '平台要求访问验证；本工具不会生成验证凭证或绕过验证。',
    'login_required': '平台要求登录；请使用平台官方允许的保存或导出方式。',
    'private': '内容不是可公开访问的视频，拒绝下载。',
    'restricted': '内容有年龄、付费或 DRM 限制，拒绝下载。',
    'unavailable': '视频不存在、已删除或当前不可访问。',
    'unsupported': '当前解析器暂不支持这个链接或页面结构。',
    'network_error': '服务器连接平台失败或超时；这不代表链接错误或视频私密。',
    'no_video': '没有可用的视频流；可能是图片帖子或平台未提供视频。',
    'timeout': '平台响应或下载超过服务时间上限，请稍后重试。',
    'busy': '服务器正在处理另一个任务，请稍后重试。',
    'limit': '任务超过文件大小、临时空间或日志上限。',
    'invalid_media': '下载结果未通过媒体完整性检查，未提供下载文件。',
    'dependency_missing': '服务器缺少必要的视频处理依赖，请联系维护者。',
    'unsafe_url': '链接或媒体跳转指向不允许的地址，已拒绝访问。',
    'official_export_required': '微信视频号尚无本项目已确认可用的通用授权下载接口；请在官方客户端或视频号助手检查本人作品可用的导出功能。',
}


class DownloadError(RuntimeError):
    def __init__(self, code, detail=None):
        self.code = code
        # Never return upstream URLs, cookies, signed CDN links or stderr.
        super().__init__(_MESSAGES.get(code, '解析或下载失败，请稍后重试。'))


def explain_failure(message):
    text = re.sub(r'https?://[^\s\x22\x27<>]+', '', str(message).lower())
    groups = [
        ('unsafe_url', ('内网', '拒绝访问', '不允许的媒体地址', '只允许 http', '不允许访问本机')),
        ('restricted', ('drm', 'premium', 'paywall', 'members-only', 'age-restricted', 'age restricted', 'age_limit')),
        ('private', ('private', 'not public')),
        ('verification_required', ('fresh cookies', 'captcha', 'verification', 'not a bot', 'challenge', 'checkpoint', '429')),
        ('login_required', ('login', 'log in', 'sign in', 'registered users', 'cookies')),
        ('unavailable', ('404', '410', 'unavailable', 'deleted', 'not found')),
        ('no_video', ('no_video', 'no video formats', 'no formats')),
        ('unsupported', ('unsupported', 'unable to extract', 'cannot parse', 'no suitable extractor')),
        ('network_error', ('timeout', 'timed out', 'connection', 'network', '403', '567', 'http error', 'urlerror', 'ssl')),
    ]
    for code, markers in groups:
        if any(marker in text for marker in markers):
            return DownloadError(code)
    return DownloadError('unsupported')


def source_url(url):
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not re.search(r'token|sig|pkey|auth|cookie|credential', k, re.I)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def _safe_filename(name: str, max_len: int = 80) -> str:
    # "#" must be stripped too: it starts a URL fragment, so a filename
    # containing it can never be requested intact by a browser.
    # Emoji are stripped as well: they are 4 bytes each in UTF-8 and
    # break some tools (ffmpeg fixup, URL encoding) when they appear
    # in a filename.
    name = _EMOJI_RE.sub("", name or "video")
    name = re.sub(r'[\\/:*?"<>|#]+', "_", name).strip()
    name = re.sub(r"\s+", "_", name)
    # Collapse runs of dots ("..." from truncated titles) so the
    # resulting filename never contains "..".
    name = re.sub(r"\.{2,}", "_", name)
    name = name[:max_len]
    # Byte cap: keep the name itself <= 90 UTF-8 bytes, so the suffixes
    # yt-dlp appends for fragmented downloads
    # (".<format>.mp4.part-FragNN", ".part", ".ytdl") stay well under
    # the 255-byte per-component filesystem limit even for Chinese titles.
    while len(name.encode("utf-8")) > 90 and len(name) > 1:
        name = name[:-1]
    return name.strip("_").strip(".") or "video"



def parse_url(raw_text):
    url = extract_url(raw_text or '')
    if not url:
        raise ValueError('没有找到有效的视频链接，请粘贴完整的分享链接。')
    platform = detect_platform(url)
    if not platform:
        raise ValueError('暂不支持这个平台或链接格式，请使用视频的完整分享链接。')
    return {'url': url, 'platform': platform}


def cleanup_downloads():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for sidecar in DOWNLOADS_DIR.glob('*.json'):
        try:
            if sidecar.is_symlink() or sidecar.stat().st_size > 65536:
                continue
            meta = json.loads(sidecar.read_text(encoding='utf-8'))
            filename = meta.get('file', '')
            if (meta.get('managed_by') == 'social-video-downloader' and meta.get('expires_at')
                    and meta['expires_at'] < time.time()
                    and re.fullmatch(r'.+_[a-f0-9]{24}\.(mp4|mkv|webm)', filename)
                    and sidecar.stem == Path(filename).stem):
                (DOWNLOADS_DIR / filename).unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    tasks = DOWNLOADS_DIR / '.tasks'
    if tasks.exists():
        for path in tasks.iterdir():
            try:
                if not path.is_symlink() and path.is_dir() and path.stat().st_mtime < time.time() - DOWNLOAD_TIMEOUT - 60:
                    shutil.rmtree(path)
            except OSError:
                continue


def _run_worker(mode, url, quality='best', directory=None):
    if not _TASK_SLOT.acquire(blocking=False):
        raise DownloadError('busy')
    try:
        cleanup_downloads()
        payload = {'mode': mode, 'url': url, 'quality': quality,
                   'directory': str(directory) if directory else None, 'max_bytes': MAX_BYTES}
        timeout = PARSE_TIMEOUT if mode == 'info' else DOWNLOAD_TIMEOUT
        # shortcut: one worker/instance; use shared admission control before scaling replicas.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen([sys.executable, '-m', 'app.worker'], stdin=subprocess.PIPE,
                                    stdout=out, stderr=err, cwd=Path(__file__).resolve().parent.parent,
                                    start_new_session=os.name != 'nt')
            try:
                proc.stdin.write(json.dumps(payload).encode())
                proc.stdin.close()
                deadline = time.monotonic() + timeout
                while True:
                    if time.monotonic() >= deadline:
                        raise DownloadError('timeout')
                    if out.tell() + err.tell() > 8 * 1024 * 1024:
                        raise DownloadError('limit')
                    if os.name == 'posix' and Path('/proc').exists():
                        memory = 0
                        for stat in Path('/proc').glob('[0-9]*/stat'):
                            try:
                                fields = stat.read_text().rsplit(') ', 1)[1].split()
                                if int(fields[2]) == proc.pid:
                                    memory += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
                            except (OSError, ValueError, IndexError):
                                continue
                        if memory > MAX_WORKER_MEMORY:
                            raise DownloadError('limit')
                    if directory and sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file()) > MAX_BYTES:
                        raise DownloadError('limit')
                    try:
                        proc.wait(timeout=0.25)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                out.seek(0)
                result = json.loads(out.read(8 * 1024 * 1024))
                if proc.returncode or result.get('error'):
                    raise DownloadError(result.get('error', 'unsupported'))
                return result
            finally:
                if proc.poll() is None:
                    if os.name != 'nt':
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                proc.wait()
    except (json.JSONDecodeError, OSError) as error:
        raise DownloadError('dependency_missing' if isinstance(error, FileNotFoundError) else 'network_error') from error
    finally:
        _TASK_SLOT.release()


def get_info(url):
    parsed = parse_url(url)
    if parsed['platform']['key'] == 'wechat':
        raise DownloadError('official_export_required')
    return _run_worker('info', parsed['url'])['info']


def file_token(filename, expires=None):
    expires = int(time.time()) + FILE_TTL if expires is None else expires
    signature = hmac.new(_FILE_KEY, f'{expires}:{filename}'.encode(), hashlib.sha256).hexdigest()
    return f'{expires}.{signature}'


def valid_file_token(filename, token):
    try:
        expires = int(token.split('.', 1)[0])
        return int(time.time()) < expires <= int(time.time()) + FILE_TTL + 1 and hmac.compare_digest(token, file_token(filename, expires))
    except (ValueError, AttributeError):
        return False


def download(url, confirmed, quality='best', keep_file=False):
    if not confirmed:
        raise ValueError('请先确认这是本人上传、已授权或平台明确允许下载的内容。')
    if quality not in ('best', '1080p', '720p'):
        raise ValueError('不支持的画质，请选择 best、1080p 或 720p。')
    parsed = parse_url(url)
    if parsed['platform']['key'] == 'wechat':
        raise DownloadError('official_export_required')
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(DOWNLOADS_DIR).free < MAX_BYTES * 2:
        raise DownloadError('limit')
    tasks = DOWNLOADS_DIR / '.tasks'
    tasks.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tasks) as tmp:
        task = Path(tmp)
        result = _run_worker('download', parsed['url'], quality, task)
        info = result['info']
        origin = (task / result['path']).resolve()
        if origin.parent != task.resolve() or origin.suffix not in ('.mp4', '.mkv', '.webm') or not origin.is_file() or not 0 < origin.stat().st_size <= MAX_BYTES:
            raise DownloadError('invalid_media')
        base = _safe_filename(info.get('title') or 'video', 30) + '_' + secrets.token_hex(12)
        final = DOWNLOADS_DIR / (base + origin.suffix)
        sidecar = final.with_suffix('.json')
        metadata = {**info, 'source_url': source_url(parsed['url']), 'platform': parsed['platform'],
                    'file': final.name, 'bytes': origin.stat().st_size, 'requested_quality': quality,
                    'managed_by': 'social-video-downloader',
                    'expires_at': None if keep_file else int(time.time()) + FILE_TTL,
                    'note': '仅限本人、授权或平台明确允许下载内容；原生视频流不等于已验证无水印。'}
        try:
            origin.replace(final)
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            final.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            raise DownloadError('limit')
        return {'file': final.name, 'path': str(final), 'bytes': final.stat().st_size,
                'metadata_file': sidecar.name, 'platform': parsed['platform'], 'info': info,
                'watermark_note': '水印状态：未验证。本工具不去除水印或版权标识。'}

"""FastAPI service: paste a link -> parse -> download -> return the file.

No login, no cookies, no account data. Downloads go to ./downloads/
which is git-ignored and never committed.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import asyncio
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError, version
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import downloader
from .downloader import DownloadError, download, get_info, parse_url, file_token, valid_file_token
from .platforms import HOSTS, PLATFORMS

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

@asynccontextmanager
async def lifespan(app):
    downloader.cleanup_downloads()
    async def cleanup_loop():
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(downloader.cleanup_downloads)
    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="Social Video Downloader", version="0.1.0", lifespan=lifespan)

# Same-origin Render UI works without CORS. Explicit origins allow a separate Pages UI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv('ALLOWED_ORIGINS', 'https://yuyantan02-cmyk.github.io').split(',') if origin.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8192)


class DownloadRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8192)
    quality: Literal['best', '1080p', '720p'] = "best"
    confirmed: bool = False


@app.get("/health")
def health():
    try:
        from yt_dlp.version import __version__ as ytdlp_version
    except Exception:
        ytdlp_version = None
    dependencies = {name: bool(shutil.which(name)) for name in ('ffmpeg', 'ffprobe', 'deno')}
    try:
        dependencies['ejs'] = version('yt-dlp-ejs')
    except PackageNotFoundError:
        dependencies['ejs'] = None
    return {"ok": True, "version": "0.1.0", "yt_dlp": ytdlp_version,
            'revision': os.getenv('RENDER_GIT_COMMIT'),
            'ready': bool(ytdlp_version) and all(dependencies.values()), 'dependencies': dependencies,
            'limits': {'concurrent_tasks': 1, 'max_bytes': downloader.MAX_BYTES,
                       'parse_timeout_seconds': downloader.PARSE_TIMEOUT,
                       'download_timeout_seconds': downloader.DOWNLOAD_TIMEOUT,
                       'file_ttl_seconds': downloader.FILE_TTL}}


@app.get('/api/platforms')
def platforms():
    return [{'key': key, 'name': name, 'hosts': HOSTS[key],
             'notes': ('需要官方授权导出，暂不提供通用下载。' if key == 'wechat' else
                       '公开可访问内容可尝试解析；真实可用性与水印需逐条验证。'),
             'status': 'official_export_required' if key == 'wechat' else 'not_verified'}
            for key, name, _, _ in PLATFORMS]


@app.exception_handler(DownloadError)
async def download_error(request, error):
    status = {'busy': 429, 'limit': 413, 'timeout': 504, 'dependency_missing': 503, 'unsafe_url': 400}.get(error.code, 502)
    content = {'detail': str(error), 'code': error.code}
    if error.code == 'official_export_required':
        content['official_url'] = 'https://channels.weixin.qq.com/'
    return JSONResponse(status_code=status, content=content,
                        headers={'Retry-After': '5'} if error.code == 'busy' else None)


@app.post("/api/parse")
def api_parse(req: ParseRequest):
    try:
        parsed = parse_url(req.text)
        info = get_info(parsed["url"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DownloadError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"platform": parsed["platform"], "url": downloader.source_url(parsed["url"]), "info": info}


@app.post("/api/download")
def api_download(req: DownloadRequest):
    try:
        result = download(req.text, confirmed=req.confirmed, quality=req.quality)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DownloadError:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "file": result["file"],
        "bytes": result["bytes"],
        "metadata_file": result["metadata_file"],
        "platform": result["platform"],
        "title": result["info"].get("title"),
        "uploader": result["info"].get("uploader"),
        "download_url": f"/files/{quote(result['file'])}?token={file_token(result['file'])}",
        "metadata_url": f"/files/{quote(result['metadata_file'])}?token={file_token(result['metadata_file'])}",
        "watermark_note": result["watermark_note"],
        "watermark_status": result['info'].get('watermark_status', 'unverified'),
        "watermark_label": result['info'].get('watermark_label', '未验证'),
        "info": result['info'],
    }


@app.get("/files/{filename}")
def serve_file(filename: str, token: str = ''):
    # Only serve files from the local downloads dir, no path traversal.
    # NOTE: do NOT reject on the substring ".." — legitimate video titles
    # often end with "..." (ellipsis), e.g. "标题....mp4". Block only
    # actual traversal: "/" or "\" separators, NUL, or "." / ".." as a
    # whole name, and verify the resolved path stays inside downloads/.
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not valid_file_token(filename, token):
        raise HTTPException(status_code=403, detail='下载链接已过期或无效，请重新下载。')
    downloader.cleanup_downloads()
    downloads_dir = downloader.DOWNLOADS_DIR.resolve()
    path = (downloads_dir / filename).resolve()
    if path.parent != downloads_dir:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    mime = {'.mp4': 'video/mp4', '.mkv': 'video/x-matroska', '.webm': 'video/webm', '.json': 'application/json'}
    if path.suffix not in mime:
        raise HTTPException(status_code=404, detail='文件不存在')
    return FileResponse(path, filename=filename, media_type=mime[path.suffix],
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

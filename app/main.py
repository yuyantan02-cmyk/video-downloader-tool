"""FastAPI service: paste a link -> parse -> download -> return the file.

No login, no cookies, no account data. Downloads go to ./downloads/
which is git-ignored and never committed.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .downloader import download, get_info, parse_url

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Social Video Downloader", version="0.1.0")

# GitHub Pages (https://<user>.github.io/...) is a different origin from the
# Render backend, so browsers block fetch() without CORS. Allow cross-origin
# calls to the public, no-login API endpoints; no cookies/credentials are used.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ParseRequest(BaseModel):
    text: str


class DownloadRequest(BaseModel):
    text: str
    quality: str = "best"
    confirmed: bool = False


@app.get("/health")
def health():
    return {"ok": True, "version": "0.1.0"}


@app.post("/api/parse")
def api_parse(req: ParseRequest):
    try:
        parsed = parse_url(req.text)
        info = get_info(parsed["url"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"platform": parsed["platform"], "url": parsed["url"], "info": info}


@app.post("/api/download")
def api_download(req: DownloadRequest):
    try:
        result = download(req.text, confirmed=req.confirmed, quality=req.quality)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "file": result["file"],
        "bytes": result["bytes"],
        "metadata_file": result["metadata_file"],
        "platform": result["platform"],
        "title": result["info"].get("title"),
        "uploader": result["info"].get("uploader"),
        "download_url": f"/files/{result['file']}",
        "watermark_note": result["watermark_note"],
    }


@app.get("/files/{filename}")
def serve_file(filename: str):
    # Only serve files from the local downloads dir, no path traversal.
    # NOTE: do NOT reject on the substring ".." — legitimate video titles
    # often end with "..." (ellipsis), e.g. "标题....mp4". Block only
    # actual traversal: "/" or "\" separators, NUL, or "." / ".." as a
    # whole name, and verify the resolved path stays inside downloads/.
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    downloads_dir = (BASE_DIR.parent / "downloads").resolve()
    path = (downloads_dir / filename).resolve()
    if path.parent != downloads_dir:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=filename, media_type="video/mp4")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

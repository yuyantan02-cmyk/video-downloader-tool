"""Download engine built on yt-dlp.

Compliance model (see COMPLIANCE.md):
- Only the URL the user pastes is fetched. No account login, no cookies,
  no credential storage, no scraping of profiles / followers / comments.
- No watermark is painted over or AI-inpainted. We ask yt-dlp for the
  best available source stream; when the platform supplies a clean
  (no-watermark) source, that is what is returned. When the watermark
  is baked into the upload itself, the file is returned as-is and the
  fact is reported — we do not attempt to remove it.
- Author / title / source URL are always saved alongside the video so
  attribution is preserved.
- Private, login-walled, age-restricted and DRM-protected items are
  refused with a clear error. Use the platform's official export for
  your own content in those cases.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .platforms import detect_platform, extract_url

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "downloads"


def _yt_dlp_cmd() -> list[str]:
    """Return a working yt-dlp invocation.

    Prefers the `yt-dlp` binary on PATH, otherwise runs the installed
    Python package with the current interpreter (works inside a venv
    where the binary is not on PATH).
    """
    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]
    return [sys.executable, "-m", "yt_dlp"]


def _safe_filename(name: str, max_len: int = 80) -> str:
    # "#" must be stripped too: it starts a URL fragment, so a filename
    # containing it can never be requested intact by a browser.
    name = re.sub(r'[\\/:*?"<>|#]+', "_", name or "video").strip()
    name = re.sub(r"\s+", "_", name)
    # Collapse runs of dots ("..." from truncated titles) so the
    # resulting filename never contains "..".
    name = re.sub(r"\.{2,}", "_", name)
    return name[:max_len].strip("_").strip(".") or "video"


def parse_url(raw_text: str) -> dict:
    """Validate a pasted link and return platform + clean URL.

    Raises ValueError with a user-facing message on bad input.
    """
    url = extract_url(raw_text or "")
    if not url:
        raise ValueError("没有找到有效的视频链接，请粘贴完整的分享链接。")
    platform = detect_platform(url)
    if platform is None:
        raise ValueError("暂不支持这个链接的平台。MVP 支持：YouTube、TikTok、Instagram、Facebook、X、Threads、抖音、小红书、微信视频号（仅提示）、Bilibili、快手。")
    return {"url": url, "platform": platform}


def get_info(url: str) -> dict:
    """Fetch metadata + formats with yt-dlp without downloading.

    Uses --dump-single-json so we never fetch media we do not need.
    """
    cmd = _yt_dlp_cmd() + [
        "--no-playlist",
        "--no-warnings",
        "--dump-single-json",
        "--no-download",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        msg = (result.stderr or "").strip().splitlines()
        tail = msg[-1] if msg else "解析失败"
        # Do not leak cookie / auth hints; normalise login-walled cases.
        lowered = tail.lower()
        if any(k in lowered for k in ("login", "log in", "sign in", "private", "age", "cookies")):
            raise RuntimeError("这个视频需要登录 / 是私密内容，工具不会用账号去取。请用你本人在平台官方的导出功能。")
        raise RuntimeError(f"解析失败：{tail}")

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"解析结果无法识别：{e}")

    formats = []
    for f in info.get("formats") or []:
        # Only list formats that actually carry video.
        if f.get("vcodec") in (None, "none"):
            continue
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "width": f.get("width"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "tbr": f.get("tbr"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "note": f.get("format_note") or "",
        })
    # Best-first by height then bitrate.
    formats.sort(key=lambda x: ((x["height"] or 0), (x["tbr"] or 0)), reverse=True)

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "uploader_id": info.get("uploader_id") or info.get("channel_id"),
        "webpage_url": info.get("webpage_url") or url,
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "ext": info.get("ext"),
        "formats": formats[:12],
        "thumbnail": info.get("thumbnail"),
        "description": (info.get("description") or "")[:500],
    }


def download(url: str, confirmed: bool, quality: str = "best") -> dict:
    """Download the best clean source stream for a URL.

    ``confirmed`` must be True: the caller must have shown the user
    the compliance checkbox and received their confirmation that this
    is their own upload, authorised material, or public downloadable
    content. Without it the download is refused.
    """
    if not confirmed:
        raise ValueError("请先确认：这是你本人上传的内容，或已获得权利人授权，或属于可公开下载的内容，然后再下载。")

    parsed = parse_url(url)
    clean_url = parsed["url"]
    platform = parsed["platform"]
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    info = get_info(clean_url)

    # Format selector: best video + best audio, merged to mp4.
    # TikTok: --no-watermark asks yt-dlp for the clean source when available.
    if quality == "1080p":
        fmt = "bv*[height<=1080]+ba/b[height<=1080]"
    elif quality == "720p":
        fmt = "bv*[height<=720]+ba/b[height<=720]"
    else:
        fmt = "bv*+ba/b"

    base = _safe_filename(f"{info.get('title') or 'video'}_{info.get('id') or 'noid'}")
    out_tpl = str(DOWNLOADS_DIR / f"{base}.%(ext)s")

    cmd = _yt_dlp_cmd() + [
        "--no-playlist",
        "--no-warnings",
        "--no-overwrites",
        "--merge-output-format", "mp4",
        "-f", fmt,
        "--sleep-requests", "1",
        "--limit-rate", "10M",
        "-o", out_tpl,
    ]
    if platform["key"] == "tiktok":
        cmd.append("--no-watermark")
    cmd.append(clean_url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        last = tail[-1] if tail else "下载失败"
        if any(k in last.lower() for k in ("login", "private", "age", "cookies")):
            raise RuntimeError("这个视频需要登录 / 是私密内容，工具不会用账号去取。请用你本人在平台官方的导出功能。")
        raise RuntimeError(f"下载失败：{last}")

    # Find the finished file (yt-dlp writes .mp4 after merging).
    candidates = sorted(DOWNLOADS_DIR.glob(f"{base}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    video_file = None
    for cand in candidates:
        if cand.suffix.lower() in (".mp4", ".mkv", ".webm") and cand.stat().st_size > 0:
            video_file = cand
            break
    if video_file is None:
        raise RuntimeError("下载已完成但没有找到视频文件。")

    # Save attribution metadata next to the video. Never strip it.
    meta = {
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id"),
        "source_url": info.get("webpage_url") or clean_url,
        "platform": platform,
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "file": video_file.name,
        "bytes": video_file.stat().st_size,
        "note": "仅限本人 / 授权 / 可公开下载内容使用，保留作者信息，勿二次分发。",
    }
    meta_path = video_file.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "file": video_file.name,
        "path": str(video_file),
        "bytes": video_file.stat().st_size,
        "metadata_file": meta_path.name,
        "info": info,
        "platform": platform,
        "watermark_note": "本工具只取平台提供的干净源流，不做涂抹 / AI 去水印。如果水印已烧进原片，文件会保留原样。",
    }

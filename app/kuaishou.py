"""Kuaishou resolver (no login, no cookies).

yt-dlp 2026.10.26 ships no Kuaishou extractor at all ("Unsupported URL"),
so Kuaishou links cannot go through yt-dlp. The mobile share page does,
however, embed direct MP4 URLs in its HTML when fetched with a mobile
User-Agent, no login needed:

  v.kuaishou.com/<short>  --302-->  v.m.chenzhongtech.com/fw/photo/<photoId>
  https://v.m.chenzhongtech.com/fw/photo/<photoId>  (mobile UA)
      -> HTML contains https://v*.kwaicdn.com/...mp4?pkey=...&tt=v6UltraV5
         (and v6HighV5 / b variants)

The URLs are signed (pkey) and short-lived, so they must be downloaded
immediately after resolving, which is exactly what download() does.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

_MOBILE_PAGE = "https://v.m.chenzhongtech.com/fw/photo/{photo_id}"

# Best-first quality markers in the signed URL's tt= parameter.
_QUALITY_ORDER = ("v6UltraV5", "v6HighV5", "v6SuperV5", "v6V5", "b")


def _http_get(url: str, timeout: int = 30) -> tuple[str, str]:
    """GET url, return (final_url, body_text). Follows redirects."""
    req = urllib.request.Request(url, headers={
        "User-Agent": MOBILE_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return resp.geturl(), body


def extract_photo_id(url: str) -> str | None:
    """Get the photoId from any Kuaishou link shape, following redirects."""
    url = (url or "").strip()
    m = re.search(r"/short-video/([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/fw/photo/([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]photoId=([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)
    # Short links (v.kuaishou.com/..., /f/...) redirect to the photo page.
    try:
        final_url, _ = _http_get(url, timeout=20)
    except Exception:
        return None
    return extract_photo_id(final_url)


def _pick_video_url(html: str) -> str | None:
    """Pick the best direct MP4 URL embedded in the mobile photo page."""
    urls = re.findall(r"https://[^\s\"'\\<>]+?\.mp4[^\s\"'\\<>]*", html)
    # Dedupe, keeping order.
    seen: set[str] = set()
    uniq = []
    for u in urls:
        u = u.replace("&amp;", "&")
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        return None

    def quality_key(u: str) -> int:
        tt = re.search(r"[?&]tt=([^&]+)", u)
        marker = tt.group(1) if tt else ""
        for i, q in enumerate(_QUALITY_ORDER):
            if marker == q:
                return i
        return len(_QUALITY_ORDER)

    # Prefer signed CDN URLs (with pkey) over the bare manifest URLs.
    signed = [u for u in uniq if "pkey=" in u] or uniq
    return sorted(signed, key=quality_key)[0]


def _page_title(html: str, photo_id: str) -> str:
    m = re.search(r'"caption"\s*:\s*"([^"\\]{1,120})', html)
    if m:
        return m.group(1)
    m = re.search(r"<title>([^<]{1,120})</title>", html)
    if m and m.group(1).strip() and "快手" not in m.group(1):
        return m.group(1).strip()
    return f"快手视频 {photo_id}"


def resolve(url: str) -> dict:
    """Resolve a Kuaishou link to a direct MP4 URL.

    Returns {"photo_id", "title", "video_url"}.
    Raises ValueError with a user-facing message on failure.
    """
    photo_id = extract_photo_id(url)
    if not photo_id:
        raise ValueError("没能从这个快手链接里找到作品 ID，请确认链接完整（v.kuaishou.com 短链或 short-video 链接）。")
    try:
        _, html = _http_get(_MOBILE_PAGE.format(photo_id=photo_id), timeout=30)
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError(f"打不开快手作品页（{e}），请稍后重试，或确认作品没有被删除。")
    video_url = _pick_video_url(html)
    if not video_url:
        raise ValueError("快手页面里没有找到视频直链，可能是作品已删除，或是图文/直播内容。")
    return {
        "photo_id": photo_id,
        "title": _page_title(html, photo_id),
        "video_url": video_url,
    }

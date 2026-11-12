"""Platform detection for social video links.

Only URL-pattern routing. No account access, no credential handling,
no private-content bypass. If yt-dlp cannot fetch a URL without login,
the downloader returns a clear error instead of trying cookies.
"""
from __future__ import annotations

import re

# (platform key, display name, URL patterns, notes)
PLATFORMS = [
    ("youtube", "YouTube", [
        r"youtube\.com/(watch|shorts|live|embed)",
        r"youtu\.be/",
    ], "Best quality via bv*+ba, merged with ffmpeg."),
    ("tiktok", "TikTok", [
        r"tiktok\.com/@[^/]+/video/\d+",
        r"tiktok\.com/t/",
        r"vt\.tiktok\.com/",
        r"vm\.tiktok\.com/",
    ], "Prefers the clean source stream when the platform provides one."),
    ("instagram", "Instagram", [
        r"instagram\.com/(reel|reels|p|stories)/",
        r"instagr\.am/",
    ], "Public posts/reels only. Login-walled content is refused."),
    ("facebook", "Facebook", [
        r"facebook\.com/.*/(videos|reel|watch)",
        r"fb\.watch/",
        r"fb\.com/",
    ], "Public videos only."),
    ("x", "X", [
        r"(twitter|x)\.com/[^/]+/status/\d+",
        r"t\.co/",
    ], "Public posts only."),
    ("threads", "Threads", [
        r"threads\.net/@[^/]+/post/",
        r"threads\.com/@[^/]+/post/",
    ], "Public posts only."),
    ("douyin", "抖音", [
        r"douyin\.com/video/\d+",
        r"v\.douyin\.com/",
        r"iesdouyin\.com/",
    ], "MVP: via yt-dlp only. Dedicated extractor is a Phase 2 item."),
    ("xiaohongshu", "小红书", [
        r"xiaohongshu\.com/",
        r"xhslink\.com/",
        r"xhslink\.cn/",
    ], "MVP: via yt-dlp only. Dedicated extractor is a Phase 2 item."),
    ("wechat", "微信视频号", [
        r"weixin\.qq\.com/sph/",
        r"channels\.weixin\.qq\.com/",
    ], "Requires the owner's own login in the official client. MVP does not fetch it; use official export."),
    ("bilibili", "Bilibili", [
        r"bilibili\.com/video/",
        r"b23\.tv/",
    ], "Public videos only."),
    ("kuaishou", "快手", [
        r"kuaishou\.com/",
        r"v\.kuaishou\.com/",
    ], "MVP: via yt-dlp only."),
]

_GENERIC_PATTERNS = [
    r"https?://\S+",
]


def detect_platform(url: str) -> dict | None:
    """Return platform info for a URL, or None if unknown."""
    url = (url or "").strip()
    for key, name, patterns, notes in PLATFORMS:
        for pat in patterns:
            if re.search(pat, url, re.IGNORECASE):
                return {"key": key, "name": name, "notes": notes}
    return None


def extract_url(text: str) -> str | None:
    """Extract the first http(s) URL from pasted share text."""
    if not text:
        return None
    m = re.search(r"https?://[^\s\"'<>）】]+", text.strip())
    if not m:
        return None
    # Strip trailing punctuation that is often part of share text.
    return m.group(0).rstrip(".,;!?)")

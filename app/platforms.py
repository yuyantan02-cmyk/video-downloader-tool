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
        r"facebook\.com/share/",
        r"fb\.watch/",
        r"fb\.com/",
    ], "Public videos only; Facebook often requires login to view video details from a server IP."),
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
    ], "抖音要浏览器验证 cookie 才能拿到视频地址，工具不登录、不存 cookie，所以取不到；请用抖音 App 官方保存/导出。"),
    ("xiaohongshu", "小红书", [
        r"xiaohongshu\.com/",
        r"xhslink\.com/",
        r"xhslink\.cn/",
    ], "有 yt-dlp 提取器，但小红书常对服务器 IP 回“笔记暂时无法浏览”，要登录/验证；带 xsec_token 的完整分享链接成功率更高。"),
    ("wechat", "微信视频号", [
        r"weixin\.qq\.com/sph/",
        r"channels\.weixin\.qq\.com/",
    ], "要登录后的 token 才能拿到视频地址，工具不登录所以取不到；请用微信 / 视频号助手官方导出。"),
    ("bilibili", "Bilibili", [
        r"bilibili\.com/video/",
        r"b23\.tv/",
    ], "Public videos only."),
    ("kuaishou", "快手", [
        r"kuaishou\.com/",
        r"v\.kuaishou\.com/",
    ], "专用解析：手机分享页里直接给无水印 MP4 直链，不用登录。"),
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

"""Platform detection for social video links.

Only URL-pattern routing. No account access, no credential handling,
no private-content bypass. If yt-dlp cannot fetch a URL without login,
the downloader returns a clear error instead of trying cookies.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

HOSTS = {
    'youtube': ('youtube.com', 'youtu.be'),
    'tiktok': ('tiktok.com',), 'instagram': ('instagram.com', 'instagr.am'),
    'facebook': ('facebook.com', 'fb.watch', 'fb.com'),
    'x': ('twitter.com', 'x.com', 't.co'), 'threads': ('threads.net', 'threads.com'),
    'douyin': ('douyin.com', 'iesdouyin.com'),
    'xiaohongshu': ('xiaohongshu.com', 'xhslink.com', 'xhslink.cn'),
    'wechat': ('weixin.qq.com',), 'bilibili': ('bilibili.com', 'b23.tv'),
    'kuaishou': ('kuaishou.com', 'chenzhongtech.com'),
}

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
        r"facebook\.com/(watch|reel|videos)/?",
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
        r"douyin\.com/\?[^\s]*modal_id=\d+",
    ], "尝试公开分享页与 yt-dlp；遇到访问验证即停止，需真实链接验收。"),
    ("xiaohongshu", "小红书", [
        r"xiaohongshu\.com/",
        r"xhslink\.com/",
        r"xhslink\.cn/",
    ], "保留分享链接必要参数；仅视频笔记，访问验证或图片笔记会明确报错。"),
    ("wechat", "微信视频号", [
        r"weixin\.qq\.com/sph/",
        r"channels\.weixin\.qq\.com/",
    ], "尚未确认通用授权下载接口；请在官方客户端或视频号助手检查本人作品的导出方式。"),
    ("bilibili", "Bilibili", [
        r"bilibili\.com/video/",
        r"b23\.tv/",
    ], "Public videos only."),
    ("kuaishou", "快手", [
        r"kuaishou\.com/",
        r"v\.kuaishou\.com/",
        r"chenzhongtech\.com/fw/photo/",
    ], "手机公开分享页直链；仅最高档，水印未验证，作者与画质可能未知。"),
]

def detect_platform(url: str) -> dict | None:
    """Return platform info for a URL, or None if unknown."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower().rstrip('.')
        if parts.scheme not in ('http', 'https') or parts.username is not None or parts.password is not None:
            return None
        if parts.port not in (None, 80 if parts.scheme == 'http' else 443):
            return None
    except ValueError:
        return None
    for key, name, patterns, notes in PLATFORMS:
        if not any(host == domain or host.endswith('.' + domain) for domain in HOSTS[key]):
            continue
        for pat in patterns:
            if re.search(pat, host + parts.path + ('?' + parts.query if parts.query else ''), re.IGNORECASE):
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
    return m.group(0).rstrip(".,;!?)。，；！、）】")

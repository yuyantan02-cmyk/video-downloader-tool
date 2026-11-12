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
import urllib.request
from pathlib import Path

from .platforms import detect_platform, extract_url

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "downloads"

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _resolve_redirect(url: str, timeout: int = 20) -> str:
    """Follow a short link to its final URL (best-effort, no login).

    Used for xhslink.com share links, which yt-dlp's Xiaohongshu
    extractor does not match directly: it only matches
    www.xiaohongshu.com/explore/<id>. On any failure the original
    URL is returned unchanged.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.geturl()
        except Exception:
            return url


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
    # xhslink.com short links: resolve to the www.xiaohongshu.com/explore/<id>
    # page so yt-dlp's Xiaohongshu extractor matches it (and so any
    # xsec_token in the share link is carried to the real page).
    if platform["key"] == "xiaohongshu" and "xhslink.com" in url:
        url = _resolve_redirect(url)
        platform = detect_platform(url) or platform
    return {"url": url, "platform": platform}


DOUYIN_COOKIE_MSG = (
    "抖音现在要浏览器先跑验证才能拿到视频地址：它先发一段验证用的 JS，"
    "只有真浏览器跑完、拿到验证 cookie 之后，接口才给视频地址。"
    "yt-dlp 也明确提示需要 fresh cookies，而且做不了这步验证。"
    "工具按不登录、不存 cookie 的规矩取不到——不是这条视频私密，也不是链接错了。"
    "请用抖音 App 官方的办法：自己发的去创作者中心导出原视频，"
    "别人发的公开视频点分享 → 保存本地（作者允许下载的才有这个选项）。"
)

WECHAT_MSG = (
    "微信视频号要登录后的 token 才能拿到视频地址，工具不登录所以取不到。"
    "自己发的视频请用微信 App / 视频号助手里的官方导出；"
    "别人发的公开视频，请在微信里直接保存（作者允许保存的才有这个选项）。"
)

XIAOHONGSHU_MSG = (
    "小红书这条笔记现在打不开：服务器回的是“当前笔记暂时无法浏览”，"
    "从服务器 IP 看要登录/验证才能看笔记详情，工具按不登录、不存 cookie "
    "的规矩取不到。不是链接错了。请试试用 App 里复制的、带 xsec_token 的"
    "完整分享链接再粘贴一次，或直接在小红书 App 里保存这条视频。"
)


YOUTUBE_BOT_MSG = (
    "YouTube 判定这次请求是机器人，要求登录验证，工具不登录所以取不到。"
    "换个时间再试一次；自己的视频请用 YouTube Studio 导出。"
)

FACEBOOK_MSG = (
    "Facebook 这条视频在服务器上打不开：Facebook 要求登录账号才能看视频详情，"
    "哪怕是公开视频也一样，工具不登录所以取不到。请用 Facebook App 里官方的"
    "保存/下载（自己的视频在 Facebook 里有下载选项）。"
)


def _explain_failure(url: str, tail: str) -> str:
    """Turn yt-dlp's last error line into a message the user can act on."""
    lowered = tail.lower()
    platform = detect_platform(url)
    key = platform.get("key") if platform else None
    if key == "douyin" and "cookies" in lowered:
        return DOUYIN_COOKIE_MSG
    if key == "wechat":
        return WECHAT_MSG
    if key == "xiaohongshu" and ("no video formats" in lowered or "404" in lowered):
        return XIAOHONGSHU_MSG
    if key == "bilibili" and "567" in lowered:
        return "B站的下载链接偶尔会被它的 CDN 拒绝（HTTP 567），不是这条视频的问题，重新点一次下载一般就好了。"
    if key == "youtube" and "not a bot" in lowered:
        return YOUTUBE_BOT_MSG
    if key == "facebook" and ("registered users" in lowered or "cannot parse data" in lowered):
        return FACEBOOK_MSG
    if any(k in lowered for k in ("login", "log in", "sign in", "private", "age", "cookies")):
        return "这个视频需要登录 / 是私密内容，工具不会用账号去取。请用你本人在平台官方的导出功能。"
    return f"解析失败：{tail}"


def get_info(url: str) -> dict:
    """Fetch metadata + formats with yt-dlp without downloading.

    Uses --dump-single-json so we never fetch media we do not need.
    Kuaishou has no yt-dlp extractor, so it uses the dedicated
    no-login resolver in app/kuaishou.py. WeChat Channels has no
    no-login route at all, so it fails fast with a clear message
    instead of wasting a yt-dlp call.
    """
    platform = detect_platform(url)
    key = platform.get("key") if platform else None
    if key == "wechat":
        raise RuntimeError(WECHAT_MSG)
    if key == "kuaishou":
        from .kuaishou import resolve as resolve_kuaishou

        ks = resolve_kuaishou(url)
        return {
            "id": ks["photo_id"],
            "title": ks["title"],
            "uploader": None,
            "uploader_id": None,
            "webpage_url": url,
            "duration": None,
            "width": None,
            "height": None,
            "ext": "mp4",
            "formats": [{
                "format_id": "direct",
                "ext": "mp4",
                "protocol": "https",
                "width": None,
                "height": None,
                "fps": None,
                "filesize": None,
                "tbr": None,
                "vcodec": None,
                "acodec": None,
                "note": "快手直链（无水印源）",
            }],
            "thumbnail": None,
            "description": "",
        }

    cmd = _yt_dlp_cmd() + [
        "--no-playlist",
        "--no-warnings",
        "--dump-single-json",
        "--no-download",
        url,
    ]
    # One retry: Bilibili / X sometimes fail a first fetch with a bare
    # read timeout and succeed immediately on the second attempt.
    result = None
    android_client = False
    for _attempt in range(2):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            break
        tail = ((result.stderr or "").strip().splitlines() or [""])[-1].lower()
        if "timed out" not in tail and "timeout" not in tail:
            break
    assert result is not None
    # YouTube bot check: the web player client gets "Sign in to confirm
    # you're not a bot" from datacenter IPs. The Android player client
    # is not subject to that web check and usually returns the video.
    # Only used as a fallback, so normal videos keep the web client
    # (best quality).
    if result.returncode != 0 and key == "youtube":
        tail0 = ((result.stderr or "").strip().splitlines() or [""])[-1].lower()
        if "not a bot" in tail0:
            android_cmd = cmd + ["--extractor-args", "youtube:player_client=android"]
            result = subprocess.run(android_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                android_client = True
    if result.returncode != 0:
        msg = (result.stderr or "").strip().splitlines()
        tail = msg[-1] if msg else "解析失败"
        raise RuntimeError(_explain_failure(url, tail))

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"解析结果无法识别：{e}")

    formats = []
    for f in info.get("formats") or []:
        # Audio-only formats have no video (height None). Combined
        # direct files (e.g. X/Twitter http-25128) have vcodec/acodec
        # unknown (None) but a height, and must be kept: they are the
        # single-file alternative to a fragmented HLS stream.
        if f.get("vcodec") in (None, "none") and f.get("height") is None:
            continue
        formats.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "protocol": f.get("protocol"),
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
        # Internal: the YouTube Android player client was needed to pass
        # the bot check; download() must use the same client.
        "_android_client": android_client,
    }


def _finish_download(info: dict, platform: dict, clean_url: str, base: str) -> dict:
    """Find the finished file, write the attribution sidecar, return the result."""
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


def _download_kuaishou_file(clean_url: str, info: dict, base: str) -> None:
    """Download a Kuaishou video from its resolved direct MP4 URL.

    The signed URL is short-lived, so it is resolved fresh here,
    immediately before downloading.
    """
    from .kuaishou import MOBILE_UA, resolve as resolve_kuaishou

    ks = resolve_kuaishou(clean_url)
    dest = DOWNLOADS_DIR / f"{base}.mp4"
    req = urllib.request.Request(ks["video_url"], headers={
        "User-Agent": MOBILE_UA,
        "Referer": f"https://v.m.chenzhongtech.com/fw/photo/{ks['photo_id']}",
    })
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as e:
        try:
            dest.unlink()
        except OSError:
            pass
        raise RuntimeError(f"下载失败：{e}")
    if dest.stat().st_size == 0:
        dest.unlink()
        raise RuntimeError("下载失败：快手返回了空文件。")


def _build_download_cmd(info: dict, platform: dict, quality: str, base: str, clean_url: str) -> list[str]:
    """Pick the format and build the yt-dlp download command.

    Separated out so the retry loop can rebuild it after re-running
    get_info() — e.g. when the YouTube Android player client was only
    detected as needed on the second extraction.
    """
    # Format choice.
    # First try a direct combined https file at the requested quality:
    # X/Twitter offers http-25128, a single 4K MP4, alongside
    # hls-15468, ~54 HLS fragments whose signed segment URLs can
    # expire mid-download and abort near the last fragment
    # ("...part-Frag54" not found). A single file has no fragments
    # to expire. Only use it when it reaches the requested height;
    # otherwise (e.g. YouTube, where combined files top out at 360p)
    # fall back to best video + best audio, merged to mp4.
    cap = {"1080p": 1080, "720p": 720}.get(quality)
    formats = info.get("formats") or []
    max_h = max((f.get("height") or 0) for f in formats) if formats else 0
    target_h = cap if cap is not None else max_h
    direct = None
    for f in formats:
        if f.get("protocol") not in ("https", "http"):
            continue
        if (f.get("height") or 0) != target_h:
            continue
        if f.get("acodec") == "none":
            continue  # video-only, not a combined file
        direct = f
        break
    if direct is not None:
        fmt = direct["format_id"]
    elif quality == "1080p":
        fmt = "bv*[height<=1080]+ba/b[height<=1080]"
    elif quality == "720p":
        fmt = "bv*[height<=720]+ba/b[height<=720]"
    else:
        fmt = "bv*+ba/b"

    # Short on-disk name: 30 chars of title + full video id. The title
    # stays in full in the .json sidecar and in the page, so nothing
    # about attribution is lost; the file itself just stops being a
    # 215-byte name that yt-dlp then extends with fragment suffixes.
    out_tpl = str(DOWNLOADS_DIR / f"{base}.%(ext)s")

    cmd = _yt_dlp_cmd() + [
        "--no-playlist",
        "--no-warnings",
        "--no-overwrites",
        "--merge-output-format", "mp4",
        "-f", fmt,
        # No --sleep-requests: for HLS that adds 1s per fragment
        # (~54s for a 4-minute video), which is exactly the window in
        # which signed segment URLs expire. Keep the rate limit only.
        "--limit-rate", "10M",
        "--fragment-retries", "10",
        "--retries", "10",
        "--hls-prefer-native",
        "-o", out_tpl,
    ]
    # TikTok: yt-dlp's extractor already prefers the non-watermarked
    # source (preference -1 vs -2 for watermarked). There is no
    # --no-watermark option in yt-dlp; passing it aborts every TikTok
    # download with "no such option", so nothing is added here.
    # YouTube: when the web player client hit the bot check, get_info()
    # fell back to the Android player client; the download must use
    # the same client or it hits the same wall.
    if info.get("_android_client"):
        cmd += ["--extractor-args", "youtube:player_client=android"]
    cmd.append(clean_url)
    return cmd


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

    # Kuaishou has no yt-dlp extractor: download its resolved direct
    # MP4 straight to disk, then share the normal finish step below.
    base = f"{_safe_filename(info.get('title') or 'video', max_len=30)}_{info.get('id') or 'noid'}"
    if platform["key"] == "kuaishou":
        _download_kuaishou_file(clean_url, info, base)
        return _finish_download(info, platform, clean_url, base)

    # Format choice + command (rebuilt on retry after re-extraction).
    cmd = _build_download_cmd(info, platform, quality, base, clean_url)

    result = None
    last_error = "下载失败"
    # Two retries with a fresh manifest: HLS segment URLs are short-lived,
    # so a transient fragment failure is often fixed by re-extracting
    # and starting over from clean partial files. Bilibili's CDN also
    # intermittently rejects with HTTP 567 and succeeds on a fresh try.
    for attempt in range(3):
        if attempt:
            for stale in DOWNLOADS_DIR.glob(f"{base}.*"):
                try:
                    stale.unlink()
                except OSError:
                    pass
            info = get_info(clean_url)
            cmd = _build_download_cmd(info, platform, quality, base, clean_url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            break
        tail = (result.stderr or "").strip().splitlines()
        last_error = tail[-1] if tail else "下载失败"
    if result is None or result.returncode != 0:
        raise RuntimeError(_explain_failure(clean_url, last_error))

    return _finish_download(info, platform, clean_url, base)

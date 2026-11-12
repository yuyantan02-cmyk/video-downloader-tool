#!/usr/bin/env python3
"""CLI: python cli.py "<link>" [--quality best|1080p|720p] --confirm

--confirm is required. It means: this is your own upload, authorised
material, or public downloadable content. Without it nothing downloads.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.downloader import download, get_info, parse_url


def main() -> int:
    p = argparse.ArgumentParser(description="社交视频下载器（仅限本人 / 授权 / 可公开下载内容）")
    p.add_argument("link", help="视频分享链接或整段分享文案")
    p.add_argument("--quality", default="best", choices=["best", "1080p", "720p"])
    p.add_argument("--confirm", action="store_true", help="确认合规：本人上传 / 已授权 / 可公开下载")
    p.add_argument("--info-only", action="store_true", help="只解析不下载")
    args = p.parse_args()

    try:
        parsed = parse_url(args.link)
        print(f"平台：{parsed['platform']['name']}  {parsed['platform']['notes']}")
        info = get_info(parsed["url"])
        print(f"标题：{info.get('title')}")
        print(f"作者：{info.get('uploader')}  时长：{info.get('duration')}s  画质：{info.get('width')}x{info.get('height')}")
        for f in info.get("formats", [])[:5]:
            print(f"  - {f['format_id']} {f['width']}x{f['height']} fps={f['fps']} ext={f['ext']}")
        if args.info_only:
            return 0
        result = download(args.link, confirmed=args.confirm, quality=args.quality)
        print(f"已下载：{result['path']}  ({result['bytes']} bytes)")
        print(f"元数据：{result['metadata_file']}")
        print(result["watermark_note"])
        return 0
    except (ValueError, RuntimeError) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

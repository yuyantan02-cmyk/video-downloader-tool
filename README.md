# 社交视频下载器 Social Video Downloader

粘贴一个社交平台的视频链接，下载平台提供的最高画质源流。

> **定位：** 仅用于你本人上传的内容、已获得权利人授权的内容，或可公开下载的内容。详见 [COMPLIANCE.md](COMPLIANCE.md)。
>
> 工具只取平台提供的干净源流，不涂抹、不做 AI 去水印。私密 / 需登录 / DRM 保护的视频会直接拒绝。

## 支持的平台（MVP）

| 平台 | 状态 |
|---|---|
| YouTube、TikTok、X、Instagram、Facebook、Threads | yt-dlp 核心，效果最稳 |
| 抖音、小红书、快手、Bilibili | MVP 走 yt-dlp，专用解析器是第二阶段 |
| 微信视频号 | 需要本人在官方客户端登录，MVP 不直接取，请用官方导出 |

国内平台接口变化快，专用解析器见 `docs/roadmap.md`（计划中）。

## 快速开始

需要 Python 3.10+ 和 ffmpeg。

```bash
git clone https://github.com/<你的用户名>/social-video-downloader.git
cd social-video-downloader
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 网页版
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000

# 命令行版（只解析不下载）
python cli.py "https://www.youtube.com/watch?v=..." --info-only

# 命令行版（下载，必须加 --confirm）
python cli.py "https://www.youtube.com/watch?v=..." --confirm --quality best
```

下载的文件在 `downloads/`，旁边会有一个同名 `.json`，保存标题、作者、原链接。

## Docker

```bash
docker compose up --build
# 打开 http://127.0.0.1:8000
```

## 项目结构

```
app/
  main.py        # FastAPI：解析 / 下载 / 文件回传
  downloader.py  # yt-dlp 封装：最高画质 bv*+ba，TikTok 用 --no-watermark 取干净流
  platforms.py   # 平台识别（只按 URL 正则，不碰账号）
  static/index.html  # 简单网页：粘贴链接、选画质、勾选确认
cli.py           # 命令行入口
tests/           # 平台识别的单元测试（不联网）
COMPLIANCE.md    # 合规说明，必读
```

## 常见问题

- **画质只有 720p？** 先看解析结果里的格式列表。YouTube 高清是视频流 + 音频流分开的，工具已用 `bv*+ba` 合并；如果平台本身最高就是 720p，那就是平台给的上限。
- **提示需要登录？** 说明是私密 / 需登录内容，工具不会用账号去取，请用官方导出。
- **水印还在？** 说明水印已烧进原片，或平台这次没给干净流。工具不会涂抹去水印，会如实返回原样。
- **解析突然失效？** 平台改接口了，先升级：`pip install -U yt-dlp`，不行就等专用解析器更新。

## License

MIT，见 LICENSE。

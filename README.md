# Social Video Downloader

现有 FastAPI + yt-dlp + Web/CLI 项目的七平台适配升级分支。保留网页布局、解析与下载接口及 Render Docker 架构。

**当前是待真实下载验收的开发版本，不宣称七个平台全部可下载。** 用户选择自行完成授权样例验收；自动化合成测试不能替代真实平台成功。详见 [验收矩阵与阶段报告](docs/acceptance.md)。

## 平台范围

| 平台 | 实现路径 | 已知边界 | 真实下载验收 |
|---|---|---|---|
| 抖音 | 标准/短链/分享文案；公开页面 hydration + yt-dlp Douyin | 验证页会停止，不生成验证 Cookie | BLOCKED（本次样例需验证） |
| Facebook | yt-dlp；补 watch/reel 等识别及错误分类 | 登录、验证、不可访问、解析器、网络分别报错 | PASS（单个授权样例；公开 DNS 测试进程） |
| YouTube | yt-dlp + 匹配的 EJS/Deno；分离音视频用 FFmpeg 无损合并 | 不切换客户端规避拒绝，不处理付费/私密/DRM | PASS（单个授权样例；公开 DNS 测试进程） |
| Threads | 当前帖子公开 JSON 中的视频版本，跳过图片 | 多视频帖子只保存第一段，显示视频数和说明；不取推荐帖视频 | NOT TESTED |
| Bilibili | BV、b23.tv 短链 + yt-dlp + FFmpeg | 不绕过会员画质/付费；CDN 错误分类，有限重试 | NOT TESTED |
| 小红书 | xhslink.com/.cn 跳转、必要查询参数、yt-dlp 笔记解析 | 区分图片笔记与访问验证；不导入登录态 | BLOCKED（本次样例跳转登录） |
| 微信视频号 | 识别后返回 official_export_required | 未取得通用授权下载接口依据，不伪造解析成功 | BLOCKED |
| TikTok、X、Instagram | 保留 yt-dlp 路径 | 仍需真实回归验收 | NOT TESTED |
| 快手 | 保留手机分享页解析，媒体交给统一安全下载流程 | 直链分辨率未知时仅支持 best，作者可能未知 | NOT TESTED |

所有未逐文件检查的视频都显示水印状态 **未验证**。不做 AI、裁剪、模糊或覆盖去水印；原生视频地址不等于已验证无水印。文件下载后用 ffprobe 测量分辨率、编码、时长和音频流；是否完整播放仍需验收。

## 使用

公网用户直接使用已部署的网站，无需安装 Python。**开发分支尚未部署，当前生产网站不会自动获得本分支修改。**

本地开发使用 Python 3.12（最低 3.11）、FFmpeg 和 ffprobe：

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

依赖中包含固定版本 yt-dlp、匹配的 EJS、Deno 和 HLS 所需的加密库；不允许远程临时拉取执行组件。Docker 已安装 FFmpeg/ffprobe，无需公网用户手动安装。

```sh
python cli.py 'https://www.youtube.com/watch?v=YOUR_VIDEO' --info-only
python cli.py 'https://www.youtube.com/watch?v=YOUR_VIDEO' --confirm --quality best
```

CLI 本人主动保存的文件与出处保留在 downloads，不参与 Web 文件的过期删除；旧版已有文件也不会被自动删除。

## API 兼容与限制

保留 `GET /health`、`POST /api/parse`、`POST /api/download`、`GET /files/{filename}`，保留原有请求/成功字段。新增 `/api/platforms`、结构化错误 `code`、封面、水印状态、实测媒体信息、`metadata_url`。

**文件访问安全变化：** `/files/{filename}` 现在需要返回链接中的 token。客户端必须直接使用 `download_url`，不能丢弃查询参数再拼文件名。旧文件无访问令牌时不公开回传。默认有效一小时；重启后旧链接失效。

- 每实例单 Uvicorn worker，同时一个解析/下载任务；繁忙返回 429。
- 解析上限 120 秒，下载上限 600 秒；网页等待略长于服务端上限。
- 每任务临时文件总量与最终文件各限 512 MiB（合并时输入输出都会计入临时空间），10 MiB/s，分片串行。
- Linux 上监测子进程组 RSS，默认 320 MiB 上限；轮询检查是资源保护，不是操作系统级隔离。
- Web 文件默认一小时过期，服务每分钟清理本版本带管理标记的过期文件；失败只清理本任务临时目录。
- DNS 与每次连接拒绝本机、内网、保留地址，连接使用已检查的数值 IP；重定向同样受约束。媒体网络下载只允许 Python 原生下载器，禁止静默回退到联网 FFmpeg。FFmpeg 仅处理本地文件。
- 不导入用户 yt-dlp 配置、账号 Cookie 或插件，不持久保存登录态；不返回上游签名媒体地址或原始错误日志。
- 默认同源及本仓库所有者的 `https://yuyantan02-cmyk.github.io` 来源。其他独立静态前端需在 `ALLOWED_ORIGINS` 填写明确来源，以逗号分隔；不使用通配符。

## Render / Docker

继续使用仓库 `Dockerfile`、`render.yaml` 和 `docker-compose.yml`。镜像以非 root 用户运行，单 worker，关闭含文件凭证的访问日志；Compose 默认只绑定本机。

```sh
docker compose up --build
```

Compose 使用命名卷承接非 root 用户的临时下载，避免宿主目录 UID 不匹配；原宿主 `downloads/` 不会删除或迁移。网页仍使用保存链接，CLI 仍保存到本机 `downloads/`。

Render 新建测试服务或 Blueprint 时选择本开发分支，**不要直接把生产服务改到此分支**。本次交付不合并 main、不部署生产。健康接口 `ready` 检查 FFmpeg/ffprobe/Deno/EJS 是否可用；它不证明平台可下载。Render 默认临时磁盘，重启、重新部署、休眠可能丢失尚未保存到用户设备的文件；免费实例有内存/带宽/休眠限制，不承诺长期零成本商用。

可配置：`MAX_DOWNLOAD_BYTES`、`MAX_WORKER_MEMORY_MB`、`PARSE_TIMEOUT_SECONDS`、`DOWNLOAD_TIMEOUT_SECONDS`、`DOWNLOAD_TTL_SECONDS`、`ALLOWED_ORIGINS`。这些是服务保护参数，调大前应核实实例资源。

## 测试

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

测试包括原有链接测试、安全/重定向/权限/超时/API/CLI/平台页面合成夹具，以及真实本地合成媒体的 FFmpeg 合并和 ffprobe 检查。运行媒体测试需要 ffmpeg/ffprobe。GitHub Actions 另构建镜像并检查容器依赖及健康；不执行未授权的平台视频下载。

## 使用与许可

仅用于本人上传、获得授权或平台明确允许下载的内容。可公开访问不等于获准下载或商用。见 [COMPLIANCE.md](COMPLIANCE.md)。代码许可为 MIT，不授予任何平台内容或自动化访问许可。

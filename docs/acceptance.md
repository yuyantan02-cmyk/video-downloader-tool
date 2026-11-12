# 七平台开发交付与真实验收矩阵

日期：2026-11-12。基线：`dbdb50f`；开发分支：`codex/seven-platform-adapters`。

用户最初选择自行测试，随后提供并明确授权了小红书、YouTube、抖音、Facebook、视频号五条样例。本次只对这些授权样例进行真实检查；不随意选择其他视频。生产 Render 只提交了小红书只读解析请求，未提交媒体下载。下表的真实结果与合成测试分别记录。

## 状态定义

- PASS：有权下载的真实视频已经成功取得，媒体可播放并核验相关项目。
- FAIL：实际执行真实测试，结果不满足要求，并有错误或文件证据。
- BLOCKED：平台授权/访问或测试环境限制导致不能完成该项。
- NOT TESTED：未执行真实测试。

## 六阶段记录

1. **基线：** 修改产品代码前建立开发分支；原有 5 项测试通过。旧版全部目标平台没有可恢复的授权样例成功记录，不能把 README 声明当作成功证据。
2. **抖音/小红书/Facebook：** 已做公开页面适配、短链/参数、图文区分与错误分类代码和合成夹具。抖音不生成验证 Cookie，小红书保留必要查询参数。真实结果见下方逐条记录。
3. **YouTube/Threads/Bilibili：** 复用 yt-dlp；补匹配的 EJS/Deno；只用 Python 原生媒体下载与本地 FFmpeg 合并；Threads 提取当前帖子视频并明确多媒体选择。真实结果见下方逐条记录。
4. **微信视频号：** 研究官方打开视频接口与官方助手入口。官方打开接口不是通用下载 API；没有取得任意分享链接可合法下载的授权接口依据。保留 `official_export_required`，不虚构适配成功。
5. **回归：** Web/CLI、公用安全流程、11 平台路由、平台页面合成夹具及本地合成媒体测试。合成媒体使用实际 FFmpeg/ffprobe；这不是任何平台的真实 PASS。
6. **Render：** 保留现有 Docker/Blueprint 架构，新增单进程限额、依赖健康信息、RSS 监测、清理、非 root 运行与 CI 镜像检查。生产健康接口只读检查成功，仍返回旧版三字段，不能证明新代码已部署。没有合并 main 或部署生产；新分支 Render 媒体验收尚未执行。

## 每个平台的原状、修改和限制

| 平台 | 原有实现 / 可确认的代码问题 | 本次修改与主要文件 | 测试链接类别（待用户填写实际链接） | 本地真实视频 | Render 新分支真实视频 | 水印 / 未解决限制 |
|---|---|---|---|---|---|---|
| 抖音 | 原 yt-dlp Douyin 只依赖 detail API，失败提示 fresh cookies；没有公开分享页适配。不能确认某个真实链接必然失败 | `extractors.py` 公开 hydration → 复用原 Douyin 视频解析；`worker.py` 安全短链/标准化；`platforms.py` 文案识别 | 标准、v.douyin 短链、中文分享文案 | BLOCKED：该授权样例要求访问验证 | NOT TESTED | 未验证；不生成验证凭证 |
| Facebook | 缺根路径 watch/reel 识别；错误可能把网络或解析问题笼统归为登录 | `platforms.py` 增补；`downloader.py` 错误分类；`worker.py` 保留原 yt-dlp | watch?v、reel、share/v、fb.watch | PASS：该授权样例取得媒体并完整解码 | NOT TESTED | 未验证；只证明该样例，不保证全平台 |
| YouTube | 原有 yt-dlp+合并；缺 EJS/JS运行时，对任何失败尝试客户端切换；输出未实际核验 | `requirements.txt`、`worker.py`、`Dockerfile`；保留格式选择、无损合并，增加 ffprobe，移除广泛客户端切换 | watch、Shorts、分享文案；有分离音视频的授权样例 | PASS：该授权样例取得媒体并完整解码 | NOT TESTED | 未验证；当前可获取最高档不等于上传原片 |
| Threads | 原来只有域名/帖子识别；固定 yt-dlp 版本未找到 Threads 专用提取器 | `extractors.py` 新增当前帖子 JSON 视频提取；跳过图片与推荐；多视频显示数量，仅下载第一段 | .net/.com 标准帖子、纯图片、多媒体 | NOT TESTED | NOT TESTED | 未验证；页面结构变动/登录验证仍可能阻塞；不批量下载所有片段 |
| Bilibili | yt-dlp 原有流程；b23 由底层处理，CDN失败重试会清理共享前缀文件 | `worker.py` 先安全解析 b23、保留 yt-dlp/FFmpeg；`downloader.py` 任务隔离和保护原文件 | BV、b23.tv、中文分享文案；分离流样例 | NOT TESTED | NOT TESTED | 未验证；不获取会员/付费限制画质；具体 CDN 错误需真实日志代码 |
| 小红书 | 仅 xhslink.com 判断跳转，未覆盖 .cn；未明确区分图文和访问验证 | `worker.py` .com/.cn 跳转并保留必要参数；`extractors.py` 复用原解析器、图文/验证分支 | explore、discovery/item、xhslink.com/.cn、含必要参数的中文分享文案 | BLOCKED：该授权短链跳转至登录页 | NOT TESTED | 未验证；不导入账号登录态 |
| 微信视频号 | 识别后主动拒绝，没有实际媒体获取 | `main.py`/`downloader.py` 明确错误码和官方入口，`COMPLIANCE.md` 记录研究边界 | sph 分享链、官方助手本人作品；若以后有正式授权接口需另行接入 | BLOCKED | BLOCKED | 无媒体可验证；未取得本项目可用的通用授权接口 |

共享改动也涉及 `network.py`、`main.py`、`cli.py`、现有网页及部署配置。原 TikTok/X/Instagram 保留 yt-dlp 路径，快手保留公开分享页解析并使用同一下载与探测流程。四个平台的**真实下载回归都是 NOT TESTED**；路由/安全/合成夹具测试不能作为真实回归通过。

## 用户逐条验收表（复制一份用于每条视频、每种环境）

测试环境应填写：本地或独立 Render 测试服务、系统/浏览器、时间、分支提交、`/health` 结果。原生产地址尚未更新，不能直接用它验证新分支。

| 项目 | 状态（默认 NOT TESTED） | 证据 / 备注 |
|---|---|---|
| 本人/授权/平台明确允许下载的依据 | NOT TESTED | 不在公开 issue 粘贴 Cookie、分享 token、签名地址或账号资料 |
| 标准链接识别 | NOT TESTED | |
| 短链接及中文分享文案识别 | NOT TESTED | |
| 标题、作者、封面、真实画质信息 | NOT TESTED | 作者未知时应明确显示未知 |
| 获得实际媒体文件，非 JSON/HTML 错误页 | NOT TESTED | 文件大小、格式 |
| 开头/中间/结尾正常播放 | NOT TESTED | 播放器与时间点 |
| 音频开头/中间/结尾完整、与画面对齐 | NOT TESTED | 有音频流不等于完整听验 |
| 原宽高比、实际分辨率、无虚假放大 | NOT TESTED | 和原平台可用版本对照 |
| 时长与格式正确 | NOT TESTED | 下载后信息与原视频对照 |
| 原生水印状态 | NOT TESTED | 人工查看后记已验证无水印/已验证带水印/未验证；UI未检测时必须仍为未验证 |
| 出处 JSON 可保存且无敏感签名参数 | NOT TESTED | |
| Render 同一链接可执行 | NOT TESTED | 单独记录；不能从本地推断 |
| 无权限/图片/删除/验证/网络的失败提示准确 | NOT TESTED | HTTP 状态与 code；别粘贴原始带令牌 URL |
| 原 TikTok/X/Instagram/快手无回归 | NOT TESTED | 各用一条授权样例；快手 best 档 |

## 如何测试新分支而不影响生产

1. 查看 PR 与自动化检查；新建独立 Render **测试服务**，指向开发分支，按原 Docker 架构构建。不要把现有生产服务切到本分支。
2. 打开测试服务网站。`/health` 应有 `ready=true` 与新 `limits` 字段；如平台提供 `RENDER_GIT_COMMIT`，`revision` 应等于测试提交。
3. 粘贴本人/授权视频，先解析，核对封面与格式，再确认并下载。直接使用返回的保存链接，不丢弃 token 查询参数。
4. 逐项填写表格；分别记录本地和 Render。如果网络出错，保留错误 code、发生时间、测试区域和健康信息；没有真实请求证据时不能笼统判定“Render IP 被封”。
5. 将有问题的平台、链接类别、脱敏错误码和现象反馈。只有真实通过的项目可改为 PASS。

## 诊断代码

`verification_required` 访问验证；`login_required` 登录；`private` 私密；`restricted` 付费/年龄/DRM；`unavailable` 删除/不可访问；`unsupported` 解析器或媒体协议不支持；`no_video` 没有视频流；`network_error` 服务器网络/HTTP/CDN；`unsafe_url` 地址被安全策略拒绝；`timeout` 服务时间上限；`busy` 单任务繁忙；`limit` 大小/磁盘/内存等资源上限；`invalid_media` 文件媒体检查失败；`dependency_missing` 缺处理依赖；`official_export_required` 视频号需官方授权途径。

某些上游错误文本不足以区分删除、地区限制与访问验证；错误分类是诊断起点，不是对平台状态的绝对认定。

## 尚未完成的发布验收

YouTube、Facebook 各一条授权样例取得真实媒体并完整解码；其余结果见表。没有执行新代码的 Render 媒体下载、目标手机验收、完整人工听验、逐帧水印核验、生产压力测试或商业授权审查。完整七平台端到端验收尚未完成。

官方参考：
- yt-dlp EJS：https://github.com/yt-dlp/yt-dlp/wiki/EJS
- 视频号打开接口：https://developers.weixin.qq.com/miniprogram/dev/api/open-api/channels/wx.openChannelsActivity.html （本次已读取页面；用途是打开视频，不是文件下载）
- 官方助手：https://channels.weixin.qq.com/
- Render 限制：https://render.com/docs/free

## 本次授权样例的真实证据

本机系统 DNS 被代理映射到 198.18.* 保留网段，新分支默认安全策略正确阻止请求。因此以下成功测试使用**仓库外独立测试子进程中的公开 DNS（DNS-over-HTTPS）**，没有修改系统 DNS，也没有关闭本项目的公共地址/连接检查。运行的是本分支 `worker.run_task` 下载引擎，不是浏览器绕过、第三方下载 API 或模拟媒体；该实验不证明默认本机 API 在假 IP 代理环境可用，也不证明 Render 可用。

| 样例 | 实际结果 | 输出与校验 | 水印/人工验收 |
|---|---|---|---|
| YouTube Shorts `hjocn0LwnSM` | PASS：下载及完整解码 | 720×960，34.581s，MKV，AV1+Opus，3,580,450 bytes；ffprobe 有音频流，FFmpeg 全片解码退出 0 | 未验证；未做完整听验/手机播放 |
| Facebook share/r `1FjSn7TWF2` | PASS：下载及完整解码 | 1080×1920，36.409s，MP4，AV1+AAC，4,551,066 bytes；ffprobe 有音频流，FFmpeg 全片解码退出 0 | 未验证；未做完整听验/手机播放 |
| 小红书 `xhslink.cn/o/2SXdtViq8TA` | BLOCKED：公开 DNS 下跳转到 /login | 新版明确 login_required；当前生产旧版不处理 .cn 跳转，返回 Unsupported URL。已修正 URL 内 login 字样污染错误分类的问题 | 没有取得视频，无法验证 |
| 抖音 `v.douyin.com/ut1Av6Pt1WU` | BLOCKED：verification_required | 尝试公开分享页与原 yt-dlp，未取得无需验证的可用视频；不生成验证 Cookie | 没有取得视频，无法验证 |
| 视频号 `weixin.qq.com/sph/Ao58kYhs8e` | BLOCKED：official_export_required | 应用有明确阻止路径；不把模拟识别或官方打开接口当作成功下载 | 没有取得视频，无法验证 |

Threads、Bilibili 尚无用户授权样例，真实视频测试仍为 NOT TESTED。所有成功结果仅对应本次样例，不代表平台全面支持，也不能自动改成「已验证无水印」。

## 自动化与页面检查记录

原有 5 项测试保留；当前扩展到 52 项（待最终 CI 核验），覆盖 URL/DNS/连接安全、短链、错误脱敏与分类、媒体限制、API/CLI兼容、文件凭证、清理/并发/不同工作目录、平台合成页面和真实合成音视频。合成检查单独计数，不写入真实平台 PASS。

浏览器在本地打开现有界面，检测到服务连接成功、七目标及原平台仍在列表、下载确认门槛存在，视频号解析显示明确受限原因。独立代码审查发现的 CLI 工作目录及原 GitHub Pages 来源兼容问题均已修复并补回归测试。

# Roadmap

## Phase 1 — MVP（已完成）
- yt-dlp 核心 + FastAPI + 网页 + CLI
- 平台识别：YouTube、TikTok、X、Instagram、Facebook、Threads、抖音、小红书、快手、Bilibili
- 最高画质 bv*+ba，ffmpeg 合并，TikTok 用 --no-watermark 取干净流
- 合规确认、元数据保存、私密内容拒绝

## Phase 2 — 国内平台专用解析器（计划中）
- 抖音：移动端分享页解析，取无水印 play_addr
- 小红书：短链解析 + 图集原图
- 快手、B站：补齐专用提取器
- 失败时回退到 yt-dlp，再失败时回退到第三方解析 API（需用户自己配 key，不内置）

## Phase 3 — 视频号与批量
- 微信视频号：只在用户本人在官方客户端完成登录导出的前提下处理，不在工具内保存登录态
- 批量队列、下载进度、封面 / BGM 提取（仅限授权内容）

## Phase 4 — 维护
- 每周检查 yt-dlp 更新，平台改接口时只升级提取器
- 自动化测试：平台识别单测 + 一个公开测试视频的端到端测试

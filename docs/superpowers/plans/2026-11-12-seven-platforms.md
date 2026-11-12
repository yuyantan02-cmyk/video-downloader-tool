# Seven platform upgrade implementation plan

**Goal:** Extend the existing service without changing its UI layout, endpoint names or single-video workflow. Real downloads are accepted only after the owner tests authorized samples.

**Architecture:** Keep FastAPI, the existing page, CLI, Render Docker deployment and yt-dlp. Use platform-specific yt-dlp extractors only where needed, and run extraction/downloads in a bounded child process with public-network-only Python networking. Existing JSON response keys remain; diagnostic, watermark and file-token fields are additive. Multi-video Threads posts explicitly select the first video and report the video count.

**Scope:** `platforms.py` (host validation), `downloader.py` (shared lifecycle), `main.py`/`cli.py` (existing callers), `kuaishou.py` (redirect regression), new `network.py`, `extractors.py`, `worker.py`, existing HTML, dependencies/Docker/Render, tests and acceptance documentation. No unrelated project modules, authentication sessions, paid/private/DRM bypass, AI watermark removal, main merge or production deployment.

## Review focus
- DNS rebinding and redirects must not turn a permitted share link into a private-network request.
- A retry must never remove another task's successful output.
- Missing audio, image notes, empty formats and unavailable quality must not become false success.
- Platform verification, login, unavailable content, unsupported parsing and network errors must remain distinguishable without leaking tokens.
- Local tests and production health checks must not be labeled real platform downloads.

## Phase 1 — baseline and shared safety
- [x] Create `codex/seven-platform-adapters` before code changes; existing 5 tests pass on Python 3.12.
- [ ] Add failing tests for host validation, safe DNS/connect, structured errors, task cleanup, confirmation, token access and output integrity.
- [ ] Implement public-network checks, one-process task admission, isolated child workers, bounded temporary downloads and signed file links; keep API shapes.

## Phase 2 — Douyin, Xiaohongshu, Facebook
- [ ] Test and implement safe short-link canonicalization while preserving necessary query parameters.
- [ ] Add public-page Douyin hydration extraction using the installed Douyin parser; retain the official extractor fallback without generating verification credentials.
- [ ] Reuse Xiaohongshu's installed parser, explicitly reject image notes and report challenges. Retain Facebook's extractor and classify failures.

## Phase 3 — YouTube, Threads, Bilibili
- [ ] Keep default yt-dlp YouTube/Bilibili format selection, native network download and local lossless FFmpeg merging; validate restrictions before media requests.
- [ ] Add a Threads public-page extractor that selects only videos belonging to the requested post.
- [ ] Probe final media with ffprobe and return measured resolution, codecs, duration and audio state; unknown watermark remains unverified.

## Phase 4 — WeChat Channels
- [ ] Verify official export/access documentation. If no general authorized API is established, expose `official_export_required` with official source links; do not fabricate a download adapter.

## Phase 5 — regression
- [ ] Test seven target platforms and TikTok/X/Instagram/Kuaishou routing, API/CLI compatibility, timeout and security cases with explicitly synthetic fixtures.
- [ ] Retain the page layout; synchronize platform data, show cover/metadata/watermark, align timeout and provide video/sidecar links.

## Phase 6 — Render and handoff
- [ ] Pin a compatible Python/yt-dlp/EJS/JS-runtime stack, install FFmpeg/ffprobe, define health and resource checks and add CI.
- [ ] Record live read-only health diagnostics. No production mutations; real local/Render video acceptance remains NOT TESTED per owner's choice to test personally.
- [ ] Run tests, inspect full diff, commit, push development branch and open PR. Do not merge or deploy.

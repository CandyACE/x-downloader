# xdl — X Media Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.2.0-green.svg)](CHANGELOG.md)

> 通过浏览器 Cookie 登录 X（Twitter），下载用户图片/视频，或自己账号的喜欢列表媒体。  
> **无需开发者账号，无需 API Key。**

[English](README.md) | 中文

---

## 目录

- [功能](#功能)
- [环境要求](#环境要求)
- [安装](#安装)
- [获取 Cookie](#获取-cookie)
- [配置](#配置)
- [使用方法](#使用方法)
- [存储模式对比](#存储模式对比)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [代理](#代理)
- [参与贡献](#参与贡献)
- [注意事项](#注意事项)
- [License](#license)

---

## 功能

| 功能 | 说明 |
|------|------|
| 🖼️ **用户媒体** | 下载任意用户的全部推文图片、GIF、视频；`--media-only` 可直接查询 Media 标签页 |
| ❤️ **喜欢列表** | 下载自己点赞推文的媒体（按原作者分文件夹保存） |
| 🐦 **单条推文** | 通过推文 ID 或 URL 下载单条推文的媒体 |
| 🔍 **类型过滤** | `--image-only` / `--video-only` 只下载图片（含 GIF）或视频 |
| 📦 **两种存储模式** | `folder`（文件夹树）或 `sqlite`（单一 `.db` 文件） |
| 🌐 **内置画廊** | `xdl serve` 启动本地 HTTP 服务器，可视化浏览已下载媒体 |
| 🔄 **增量 & 断点续传** | 第二次运行只下载新内容；Ctrl+C 后自动从中断处继续 |
| ⚡ **并发下载** | 异步多线程，默认 5 并发 |
| 📁 **归档导入** | 从 X 数据归档（`like.js`）批量导入喜欢列表 |
| 🎞️ **视频缩略图** | 调用 ffmpeg 自动生成 MP4 预览图 |

---

## 环境要求

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html)（可选，用于视频缩略图）

---

## 安装

```bash
git clone https://github.com/yourusername/x-downloader.git
cd x-downloader

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -e .
```

> **可选依赖**：视频缩略图需要系统已安装 [ffmpeg](https://ffmpeg.org/download.html)，  
> SOCKS5 代理需要 `httpx[socks]`（已包含在依赖中）。

---

## 获取 Cookie

> Cookie 是登录凭证，**切勿分享或提交到代码仓库**。

1. 在浏览器打开 [x.com](https://x.com) 并登录
2. 按 **F12** → **Application** → **Cookies** → `https://x.com`
3. 复制以下两项的 **Value**：

   | Cookie 名 | 说明 |
   |-----------|------|
   | `auth_token` | 登录凭证（约 40 个十六进制字符） |
   | `ct0` | CSRF 令牌（约 32 个字符） |

---

## 配置

### 方式 A：`.env` 文件（推荐）

在项目根目录创建 `.env`（已被 `.gitignore` 忽略）：

```env
X_AUTH_TOKEN=你的auth_token
X_CT0=你的ct0

# 可选
X_OUTPUT_DIR=./downloads
X_CONCURRENCY=5
X_PROXY=http://127.0.0.1:7890
```

### 方式 B：命令行

```bash
xdl config --auth-token "..." --ct0 "..."
xdl config --auth-token "..." --ct0 "..." --proxy "http://127.0.0.1:7890"
```

配置保存到 `~/.x-downloader/config.json`。

> **优先级**：环境变量 > `.env` > `~/.x-downloader/config.json`

### 方式 C：浏览器自动抓取（实验性）

```bash
xdl config --login
```

会自动打开 Chrome/Edge，登录后自动提取 Cookie。

---

## 使用方法

### 下载用户媒体

```bash
# 下载 @username 的全部媒体（增量模式，仅下载新内容）
xdl user username

# 指定保存目录（folder 模式）
xdl user username --output D:\pictures

# 使用 SQLite 单文件模式，指定数据库路径
xdl user username --mode sqlite --db D:\gallery.db

# 只扫描最近 100 条推文
xdl user username --limit 100

# 强制全量重扫（忽略增量记录，从头重新扫描）
xdl user username --full

# 只查询 Media 标签页（推荐：服务端过滤，跳过纯文字推文，分页更快）
xdl user username --media-only

# Media 标签页 + SQLite 模式组合（推荐搭配）
xdl user username --media-only --db D:\gallery.db

# 只下载图片和 GIF（跳过视频）
xdl user username --image-only

# 只下载视频（跳过图片和 GIF）
xdl user username --video-only

# 调慢翻页速度以降低被限流风险（单位：秒）
xdl user username --scan-delay 2.0

# 调试模式（打印 API 请求详情）
xdl user username --debug
```

> **`--media-only` 说明**：调用 X 的 `UserMedia` GraphQL 接口（即个人主页"媒体"标签页所用接口），
> 服务端直接过滤纯文字推文，翻页效率更高（每页约 10 条内容，均为带媒体的推文）。  
> ⚠️ 该接口**不包含转推中的媒体**，如需转推媒体请使用普通模式（不加 `--media-only`）。  
> 两种模式的断点续传状态**相互独立**，可对同一用户分别运行两种模式。

保存路径（folder 模式）：`downloads/username_用户ID/推文ID_序号.jpg`

### 下载喜欢列表

```bash
# 下载自己全部点赞媒体（自动检测账号）
xdl likes

# 如果自动检测账号失败，用 --me 指定用户名
xdl likes --me your_username

# 指定保存目录 / 限制数量 / 指定数据库
xdl likes --output D:\pictures --limit 500
xdl likes --db D:\gallery.db

# 只下载图片和 GIF（跳过视频）
xdl likes --image-only

# 只下载视频
xdl likes --video-only
```

### 下载单条推文

```bash
# 通过推文 ID 下载
xdl tweet 1234567890

# 通过推文 URL 下载
xdl tweet https://x.com/user/status/1234567890

# 下载到指定 SQLite 数据库
xdl tweet 1234567890 --single --db D:\gallery.db
```

### 内置画廊服务器

```bash
# 浏览 SQLite 模式的画廊数据库
xdl serve gallery.db

# 指定端口
xdl serve gallery.db --port 8080
```

浏览器会自动打开 `http://localhost:<port>`，支持右键菜单删除媒体。

### 其他命令

```bash
# 诊断凭证与 API 连通性
xdl doctor

# 查看统计信息
xdl stats gallery.db

# 预生成视频缩略图（需要 ffmpeg）
xdl thumbs gallery.db

# 从 X 数据归档导入喜欢列表
xdl import-archive /path/to/archive --db gallery.db

# folder 模式 ↔ sqlite 模式互转
xdl convert ./downloads gallery.db
```

---

## 存储模式对比

| | folder 模式 | sqlite 模式 |
|-|------------|------------|
| 存储形式 | 文件夹树 | 单一 `.db` 文件 |
| 可直接访问 | ✅ 直接用图片查看器打开 | ❌ 需要 `xdl serve` |
| 画廊功能 | 基础 HTML 画廊 | 完整交互式画廊 |
| 便携性 | 需要整个目录 | 单文件 |
| 搜索/删除 | ❌ | ✅ 画廊内支持 |

---

## 项目结构

```
x-downloader/
├── xdl/                        ← Python 包
│   ├── __init__.py
│   ├── cli.py                  ← CLI 入口（薄包装层，注册所有子命令）
│   ├── _helpers.py             ← 共享工具函数、常量、KVStore 协议
│   ├── commands/               ← 子命令实现（每命令一文件）
│   │   ├── config.py           ←   xdl config（含 CDP 浏览器登录）
│   │   ├── user.py             ←   xdl user
│   │   ├── likes.py            ←   xdl likes
│   │   ├── tweet.py            ←   xdl tweet
│   │   ├── doctor.py           ←   xdl doctor
│   │   ├── gallery_cmd.py      ←   xdl gallery
│   │   ├── serve_cmd.py        ←   xdl serve
│   │   ├── convert.py          ←   xdl convert
│   │   ├── stats.py            ←   xdl stats
│   │   ├── thumbs.py           ←   xdl thumbs
│   │   └── archive.py          ←   xdl import-archive
│   ├── auth.py                 ← 请求头 / Cookie 认证
│   ├── client.py               ← X GraphQL API 客户端
│   ├── config.py               ← 配置加载与保存
│   ├── db.py                   ← folder 模式下载历史 DB（含 KVStore 协议）
│   ├── downloader.py           ← 异步并发下载引擎（含指数退避重试）
│   ├── gallery.py              ← HTML 画廊生成器
│   ├── media_parser.py         ← 推文媒体解析
│   ├── serve.py                ← 内置 HTTP 画廊服务器
│   ├── store.py                ← SQLite 媒体存储
│   ├── thumb.py                ← ffmpeg 视频缩略图提取
│   ├── archive.py              ← X 数据归档解析
│   └── _fetch_ids.py           ← 内部工具：从 X JS 提取 Query ID
├── downloads/                  ← 默认下载目录（gitignored）
├── .env                        ← 凭证（gitignored）
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 常见问题

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| `401 Unauthorized` | Cookie 过期 | 重新从浏览器复制 auth_token、ct0 |
| `403 Forbidden` | Cookie 无效 | 确认从 `x.com`（非 `twitter.com`）复制 |
| `503 Service Unavailable` | X 服务器临时故障 | 等待 30 秒后重试，已自动重试最多 8 次 |
| 自动检测账号失败 | settings.json 接口不可用 | 使用 `xdl likes --me your_username` |
| GraphQL 请求失败 | Query ID 已更新 | 见下方"更新 Query ID" |
| `--media-only` 无内容 | 用户 Media 标签页为空或接口限流 | 检查用户是否有媒体；改用普通模式 |

### 更新 GraphQL Query ID

当 X 更新前端导致 API 请求失败时：

1. 运行 `python -m xdl._fetch_ids` 自动扫描最新 ID（需代理）
2. 或手动从 DevTools → Network 过滤 `UserTweets` / `UserMedia` 请求，复制 URL 中的 ID
3. 也可参考 [fa0311/TwitterInternalAPIDocument](https://github.com/fa0311/TwitterInternalAPIDocument)（每日自动更新）

然后在 `~/.x-downloader/config.json` 更新 `query_ids` 字段。

---

## 代理

```env
# HTTP/HTTPS 代理（如 Clash）
X_PROXY=http://127.0.0.1:7890

# SOCKS5 代理
X_PROXY=socks5://127.0.0.1:1080

# 带认证的代理
X_PROXY=socks5://user:password@127.0.0.1:1080
```

---

## 参与贡献

欢迎贡献代码、报告问题！

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交改动：`git commit -m 'Add some feature'`
4. 推送到分支：`git push origin feature/your-feature`
5. 提交 Pull Request

---

## 注意事项

- Cookie 会随时间过期（通常数周到数月）
- 请合理控制并发（`X_CONCURRENCY`），避免触发限流
- 429 / 5xx 错误自动指数退避重试（最多 3 次），并遵守 `Retry-After` 响应头
- 仅供个人学习使用，请遵守 [X 服务条款](https://twitter.com/en/tos)

---

## License

MIT — 详见 [LICENSE](LICENSE)

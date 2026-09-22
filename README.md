# 小红书文字提取（macOS）

桌面自用版本的代码备份：支持小红书正文、图片 OCR，以及完整视频/本地音频转写。

## 来源

本项目基于 [8334224/xiaohongshu-notes-ocr-macos](https://github.com/8334224/xiaohongshu-notes-ocr-macos)，本机基线提交为 `3c7e814`。在此基础上加入专用浏览器手动登录、短链接兼容和 MLX Whisper 视频转写等本地修改。原说明保留在 [未命名文件夹/README.md](未命名文件夹/README.md)。本备份不替上游授予额外许可。

## 目录

- `小红书文字提取.command`：双击启动入口。
- `未命名文件夹/`：当前源代码、依赖清单及测试；保留桌面原有目录结构。
- [完整视频转写说明.md](完整视频转写说明.md)：视频和音频提取步骤。

## 首次准备

在下载后的仓库根目录打开终端。需要 macOS、Python 3；视频转写使用 Apple Silicon 和 FFmpeg。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r 未命名文件夹/requirements.txt
.venv/bin/python -m pip install -r 未命名文件夹/requirements-video.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m playwright install chromium
chmod +x 小红书文字提取.command
```

视频转写还需要系统可用的 `ffmpeg` 和 `ffprobe`（使用 Homebrew 时可执行 `brew install ffmpeg`）。随后双击启动入口，选择视频或图文模式，按提示手动登录。首次转写需下载模型。

本仓库不包含本机 Python 环境、浏览器、模型、登录 Cookie、临时视频、个人提取结果或运行报告，换电脑后需重新安装依赖和登录。网页变化可能影响提取；本次上传只整理代码，未重新验证在线提取功能。

仅处理自己有权访问和使用的内容，遵守平台规则及内容版权。不要提交 `.login-browser` 或其他登录数据。

#!/bin/zsh
set -u
XHS_ENTRY_DIR="${0:A:h}"
if [[ -d "$XHS_ENTRY_DIR/.venv" ]]; then
  XHS_TOOL_DIR="$XHS_ENTRY_DIR"
elif [[ -d "$XHS_ENTRY_DIR/xiaohongshu-notes-ocr-macos/.venv" ]]; then
  XHS_TOOL_DIR="$XHS_ENTRY_DIR/xiaohongshu-notes-ocr-macos"
elif [[ -d "$XHS_ENTRY_DIR/../.venv" ]]; then
  XHS_TOOL_DIR="${XHS_ENTRY_DIR:h}"
else
  printf '未找到工具目录，请把本启动器和 xiaohongshu-notes-ocr-macos 文件夹放在一起。\n' >&2
  exit 1
fi
if [[ -f "$XHS_TOOL_DIR/login_extract.py" ]]; then
  XHS_SOURCE_DIR="$XHS_TOOL_DIR"
elif [[ -f "$XHS_TOOL_DIR/未命名文件夹/login_extract.py" ]]; then
  XHS_SOURCE_DIR="$XHS_TOOL_DIR/未命名文件夹"
else
  printf '找不到程序文件，请不要单独移动程序文件。\n' >&2
  exit 1
fi
if [[ ! -x "$XHS_TOOL_DIR/.venv/bin/python" ]]; then
  printf '未找到工具的 Python 环境：%s\n' "$XHS_TOOL_DIR/.venv/bin/python" >&2
  exit 1
fi
XHS_NOTES_DIR="$XHS_TOOL_DIR"
export PLAYWRIGHT_BROWSERS_PATH="$XHS_TOOL_DIR/.browsers"
cd "$XHS_TOOL_DIR" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
printf '小红书文字提取（完整视频转写／图文识别）\n结果保存到：%s\n\n' "$XHS_NOTES_DIR"
printf '1. 完整视频讲话转文字（默认）\n2. 图文笔记：正文＋图片文字\n选择 1 或 2，直接回车选视频：'
IFS= read -r XHS_MODE
XHS_ARGS=()
case "$XHS_MODE" in
  1|'') XHS_ARGS=(--video) ;;
  2) ;;
  *) printf '选项无效，未开始提取。\n'; exit 1 ;;
esac
printf '\n请粘贴小红书分享链接；视频模式也可以把本地视频／音频文件拖进来，再按回车：\n'
IFS= read -r XHS_SHARE_TEXT
if [[ -z "$XHS_SHARE_TEXT" ]]; then
  printf '没有输入链接，未运行。\n'
  exit 0
fi
export XHS_URL="$XHS_SHARE_TEXT"
"$XHS_TOOL_DIR/.venv/bin/python" "$XHS_SOURCE_DIR/login_extract.py" "${XHS_ARGS[@]}"
XHS_RESULT=$?
unset XHS_URL
if [[ "$XHS_RESULT" -eq 0 ]]; then
  printf '\n流程已结束。若完成提取，Markdown 保存在：%s，可用 Typora 打开。\n' "$XHS_NOTES_DIR"
else
  printf '\n提取未完成。若遇到登录或访问限制，请保留错误信息，不要反复重试。\n'
fi
printf '\n按回车关闭窗口。'
IFS= read -r XHS_CLOSE_INPUT
exit "$XHS_RESULT"

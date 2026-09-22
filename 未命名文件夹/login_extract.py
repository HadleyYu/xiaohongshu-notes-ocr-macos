"""User-operated login in an isolated local browser profile, then extraction.

No everyday Chrome profile is read. The user opens this entry point and logs in
manually. Browser automation only starts after the user's terminal confirmation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import build_opener, ProxyHandler

from utils import AppError
from xhs_url_validator import _extract_url_from_text

ROOT = Path(__file__).resolve().parent
if not (ROOT / '.venv').is_dir() and (ROOT.parent / '.venv').is_dir():
    ROOT = ROOT.parent
PROFILE = ROOT / '.login-browser'


def share_url(text: str) -> str:
    url = _extract_url_from_text(text)
    host = urlparse(url).hostname or ''
    if not any(host == h or host.endswith('.' + h)
               for h in ('xiaohongshu.com', 'xhslink.com', 'xhslink.cn')):
        raise AppError('请输入小红书笔记链接或分享文案。')
    return url


def running_endpoint(profile: Path) -> str | None:
    """Attach only to the loopback endpoint recorded by this private profile."""
    try:
        lines = (profile / 'DevToolsActivePort').read_text().splitlines()
        port = int(lines[0])
        if not 1 <= port <= 65535 or not lines[1].startswith('/devtools/browser/'):
            return None
        endpoint = f'http://127.0.0.1:{port}'
        # Never send the browser-control request through a configured proxy.
        with build_opener(ProxyHandler({})).open(endpoint + '/json/version', timeout=1) as response:
            data = json.loads(response.read(65536))
        websocket = urlparse(data.get('webSocketDebuggerUrl', ''))
        if (websocket.hostname not in ('127.0.0.1', 'localhost')
                or websocket.port != port or websocket.path != lines[1]):
            return None
        return endpoint
    except (OSError, ValueError, IndexError, KeyError):
        return None


def open_login_browser(url: str) -> str:
    PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
    PROFILE.chmod(0o700)
    existing = running_endpoint(PROFILE)
    if existing:
        print('已找到本工具的专用浏览器，将复用其登录状态。')
        return existing

    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.browsers')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        binary = Path(pw.chromium.executable_path)
    if not binary.is_file():
        raise AppError('未找到本工具的独立浏览器，请重新检查安装。')
    args = [str(binary), f'--user-data-dir={PROFILE}',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
            '--no-first-run', '--no-default-browser-check', url]
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    for _ in range(60):
        endpoint = running_endpoint(PROFILE)
        if endpoint:
            return endpoint
        if process.poll() is not None:
            raise AppError('专用浏览器未能启动；请关闭本工具的旧浏览器窗口后重试。')
        time.sleep(0.5)
    raise AppError('专用浏览器启动超时，尚未开始提取。')


def main() -> int:
    parser = argparse.ArgumentParser(description='手动登录专用浏览器后提取小红书正文和图片文字。')
    parser.add_argument('--login-only', action='store_true')
    parser.add_argument('--video', action='store_true', help='完整视频语音转写，不提取封面')
    args = parser.parse_args()
    try:
        text = os.environ.get('XHS_URL', '').strip()
        if not args.login_only and not text:
            text = input('请粘贴分享链接：').strip()
        if args.video:
            from video_transcribe import local_media_path, transcribe_media
            local = local_media_path(text)
            if local:
                transcribe_media(local, ROOT, title=local.stem)
                return 0
        url = 'https://www.xiaohongshu.com' if args.login_only else share_url(text)
        print('\n需要使用本工具的专用浏览器登录，不是日常 Chrome。')
        print(f'登录状态仅保存在本机：{PROFILE}')
        print('浏览器控制接口仅绑定本机回环地址；不读取或复制日常浏览器的 Cookie。')
        consent = input('按回车同意打开并在本机保存登录状态；输入 q 取消：').strip()
        if consent.lower() == 'q':
            return 0
        endpoint = open_login_browser(url)
        print('\n请在弹出的浏览器窗口中自行扫码或登录，验证码也由你手动完成。')
        print('登录后请保留窗口；若已经登录，可以直接继续。')
        answer = input('确认登录完成后回到这里按回车继续；输入 q 取消：').strip()
        if answer.lower() == 'q' or args.login_only:
            return 0

        # Both URL resolution and content extraction use this exact session.
        os.environ['XHS_CHROME_CDP_URL'] = endpoint
        os.environ['XHS_URL'] = text
        if args.video:
            from video_transcribe import run_video
            run_video(url, endpoint, ROOT)
            return 0
        from main import run_from_clipboard_flow
        run_from_clipboard_flow(ROOT, use_local_chrome=True, chrome_cdp_url=endpoint)
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\n已取消，没有继续提取。')
        return 130
    except AppError as exc:
        print(f'错误：{exc}')
        return 1
    except Exception as exc:
        # Browser/network exceptions may contain signed URLs; do not echo them.
        print(f'流程未完成（{type(exc).__name__}）。请确认专用浏览器仍打开；视频模式也可直接拖入本地视频。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

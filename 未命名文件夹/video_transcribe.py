"""Full-video ASR. User-run browser access; offline transcription and Markdown.

No cover OCR, no account-cookie export, no external transcription service.
Only target-note stream URLs are used, never recommendation video streams.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

from utils import AppError

MODEL = 'mlx-community/whisper-large-v3-turbo-q4'
MODEL_REVISION = '660c343bbf4e52ac257f0b7d952e5388e6f93bef'
MODEL_SIZE = 463664664
MODEL_FILE = 'weights.npz'
MEDIA_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.mp3', '.m4a', '.wav', '.aac', '.flac', '.aiff'}
MAX_BYTES = 2 * 1024**3


def local_media_path(text: str) -> Path | None:
    text = text.strip()
    if re.search(r'https?://', text):
        return None
    plain = Path(text).expanduser()
    if plain.is_file():
        candidate = plain
    else:
        try:
            words = shlex.split(text)
        except ValueError:
            words = []
        candidate = Path(words[0]).expanduser() if len(words) == 1 else plain
    if not candidate.is_file():
        if text.startswith(('/', "'/", '"/')):
            raise AppError('找不到拖入的文件，请重新拖入一个视频或音频文件。')
        return None
    if candidate.suffix.lower() not in MEDIA_EXTENSIONS:
        raise AppError('该文件不是支持的视频或音频格式。')
    return candidate.resolve()


def media_url_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
        host = p.hostname or ''
        return (p.scheme in ('http', 'https') and not p.username and not p.password
                and p.port in (None, 80, 443)
                and any(host == d or host.endswith('.' + d)
                        for d in ('xhscdn.com', 'xiaohongshu.com')))
    except ValueError:
        return False


def stream_candidates(note: dict) -> list[tuple[str, float | None]]:
    """Follow known stream fields of this note only; do not scan the whole page."""
    found = []
    streams = ((note.get('video') or {}).get('media') or {}).get('stream') or {}
    for entries in streams.values():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            duration = item.get('duration')
            seconds = float(duration) / 1000 if isinstance(duration, (int, float)) and duration > 0 else None
            urls = [item.get('masterUrl')]
            backups = item.get('backupUrls')
            if isinstance(backups, list):
                urls.extend(backups)
            for url in urls:
                if isinstance(url, str) and media_url_allowed(url) and url not in [x[0] for x in found]:
                    found.append((url, seconds))
    return found


def clean_source(url: str) -> str:
    p = urlparse(url)
    # Do not retain login/share tokens in the finished note.
    return f'{p.scheme}://{p.netloc}{p.path}' if p.scheme in ('http', 'https') else ''


def tool_path(name: str) -> str:
    result = shutil.which(name)
    if result:
        return result
    path = Path('/opt/homebrew/bin') / name
    if path.is_file():
        return str(path)
    raise AppError(f'缺少 {name}，无法读取完整视频声音。')


def inspect_media(path: Path, expected: float | None = None) -> float:
    result = subprocess.run([tool_path('ffprobe'), '-v', 'error', '-show_streams',
                             '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AppError('下载到的内容不是有效视频／音频；没有把封面当成完整视频。可尝试拖入已保存的视频。')
    data = json.loads(result.stdout)
    if not any(s.get('codec_type') == 'audio' for s in data.get('streams', [])):
        raise AppError('这个文件没有音轨，无法语音转写；画面字幕识别需要另外处理。')
    duration = float(data.get('format', {}).get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise AppError('无法确认文件时长，未开始转写。')
    if expected and math.isfinite(expected) and abs(duration - expected) > max(2, expected * .02):
        raise AppError(f'下载时长 {duration:.1f} 秒与网页标注 {expected:.1f} 秒不符，可能不是完整视频。请拖入完整文件。')
    return duration


class MediaRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not media_url_allowed(newurl):
            raise AppError('视频跳转到了非小红书媒体域名，已停止下载。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_video(url: str, target: Path) -> None:
    if not media_url_allowed(url):
        raise AppError('未取得可信的视频地址，未下载。')
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.xiaohongshu.com/'})
    try:
        with build_opener(MediaRedirect()).open(request, timeout=40) as response:
            if response.status != 200:
                raise AppError('服务器没有返回完整视频，已停止。')
            length = int(response.headers.get('Content-Length', '0'))
            if length > MAX_BYTES:
                raise AppError('视频超过 2 GB，请先保存到本机后拖入，避免反复下载。')
            total = 0
            last_print = time.monotonic()
            with target.open('wb') as output:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_BYTES:
                        raise AppError('视频超过 2 GB，已停止下载。')
                    output.write(block)
                    if time.monotonic() - last_print > 3:
                        print(f'已下载 {total / 1024**2:.1f} MB', flush=True)
                        last_print = time.monotonic()
            if not total or (length and total != length):
                raise AppError('视频下载不完整，未开始转写。')
    except AppError:
        raise
    except Exception as exc:
        # Exception messages can contain signed media URLs; do not print them.
        raise AppError(f'视频下载失败（{type(exc).__name__}）。可先保存视频，再拖入本工具；不会绕过访问限制。') from exc


def get_video(url: str, endpoint: str) -> dict:
    from playwright.sync_api import sync_playwright
    p = urlparse(endpoint)
    if p.scheme != 'http' or p.hostname not in ('127.0.0.1', 'localhost') or p.username or p.password:
        raise AppError('浏览器接口必须是本机回环地址。')
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(endpoint)
        page = None
        try:
            if not browser.contexts:
                raise AppError('专用浏览器没有可用窗口，请重新运行。')
            page = browser.contexts[0].new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            print('\n已打开目标笔记。请确认视频可播放；必要时手动点播放。')
            if input('确认后按回车读取完整视频；输入 q 取消：').strip().lower() == 'q':
                raise AppError('已取消视频提取。')
            target = re.search(r'/(?:explore|discovery/item)/([a-fA-F0-9]+)', page.url)
            host = urlparse(page.url).hostname or ''
            if not target or not (host == 'xiaohongshu.com' or host.endswith('.xiaohongshu.com')):
                raise AppError('当前页面不是可访问的笔记，可能仍需登录。请完成登录，或拖入本地视频。')
            data = page.evaluate('''(id) => {
                const state = window.__INITIAL_STATE__;
                const raw = state?.note?.noteDetailMap?.[id]?.note;
                const note = raw ? JSON.parse(JSON.stringify(raw)) : {};
                const videos = [...document.querySelectorAll('video')];
                // Only accept a DOM fallback when exactly one video is present.
                const v = videos.length === 1 ? videos[0] : null;
                return {note, src: v ? (v.currentSrc || v.src) : '',
                    duration: v && Number.isFinite(v.duration) ? v.duration : null,
                    title: document.querySelector('meta[property="og:title"]')?.content || document.title};
            }''', target.group(1))
            note = data.get('note') or {}
            if str(note.get('type') or note.get('noteType') or '').lower() in ('normal', 'image'):
                raise AppError('这条笔记的类型是图文，请重新运行并选择图文模式；不读取推荐视频。')
            candidates = stream_candidates(note)
            if not candidates and media_url_allowed(data.get('src') or ''):
                candidates = [(data['src'], data.get('duration'))]
            if not candidates:
                raise AppError('没有取得这条笔记的完整视频地址（也可能是图文笔记）。不会改用封面冒充转写；请拖入已保存的视频，或选择图文模式。')
            return {'url': candidates[0][0], 'expected': candidates[0][1] or data.get('duration'),
                    'title': note.get('title') or data.get('title') or '小红书视频',
                    'description': note.get('desc') or '',
                    'author': (note.get('user') or {}).get('nickname') or '',
                    'source': clean_source(page.url)}
        finally:
            if page is not None:
                page.close()
            browser.close()  # Disconnect this client; keep the user's browser.


def timestamp(seconds: float) -> str:
    value = max(0, round(seconds))
    return f'{value // 3600:02d}:{value // 60 % 60:02d}:{value % 60:02d}'


def write_markdown(output_dir: Path, result: dict, title: str, duration: float,
                   source: str = '', author: str = '', description: str = '') -> Path:
    segments = [s for s in result.get('segments', []) if str(s.get('text', '')).strip()]
    if not segments:
        raise AppError('没有识别到可用讲话，未生成空白的“成功”文稿。可能无讲话、声音过小或识别失败。')
    heading = ' '.join(str(title).split()) or '视频转写'
    filename = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '_', heading)[:70].strip('. ') or '视频转写'
    content = [f'# {heading} — 视频语音转写', '',
               f'- 文件时长：{timestamp(duration)}（整段音轨已送入识别，非封面 OCR）',
               '- 说明：自动语音识别，可能有错字、漏词；不等同于人工逐字稿。不包含未被念出的画面文字。']
    if source:
        content.append(f'- 来源：{clean_source(source)}')
    if author:
        content.append(f'- 作者：{author}')
    if description:
        content.extend(['', '## 发布者配文（不是视频逐字稿）', '', description])
    content.extend(['', '## 视频讲话（按时间顺序）', ''])
    for segment in segments:
        start, end = float(segment.get('start', 0)), float(segment.get('end', 0))
        content.extend([f'**[{timestamp(start)}–{timestamp(end)}]** {segment["text"].strip()}', ''])
    output_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10000):
        suffix = '' if index == 1 else f'_{index}'
        destination = output_dir / f'{filename}_视频全文{suffix}.md'
        try:
            with destination.open('x', encoding='utf-8') as stream:
                stream.write('\n'.join(content))
            return destination
        except FileExistsError:
            continue
    raise AppError('同名输出文件过多，请整理输出目录。')


def transcribe_media(media: Path, root: Path, *, title: str, source: str = '',
                     author: str = '', description: str = '', expected: float | None = None) -> Path:
    duration = inspect_media(media, expected)
    print(f'文件时长：{timestamp(duration)}。开始整段语音识别，不是封面 OCR。', flush=True)
    os.environ['HF_HOME'] = str(root / '.models')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    os.environ['PATH'] = str(Path(tool_path('ffmpeg')).parent) + os.pathsep + os.environ.get('PATH', '')
    try:
        import mlx_whisper
    except ImportError as exc:
        raise AppError('语音识别组件尚未安装完整，请先完成本工具的依赖安装；图文模式不受影响。') from exc
    try:
        model_path = ensure_model(root)
        print('模型已就绪，正在本机识别整段声音……', flush=True)
        result = mlx_whisper.transcribe(str(media), path_or_hf_repo=str(model_path),
                                       language='zh', task='transcribe', verbose=False,
                                       condition_on_previous_text=False)
    except Exception as exc:
        raise AppError(f'本地语音识别未完成（{type(exc).__name__}）。请检查模型下载网络和可用内存；音频未上传。') from exc
    destination = write_markdown(root, result, title, duration, source, author, description)
    print(f'\n视频语音转写完成：{destination}', flush=True)
    return destination


def ensure_model(root: Path) -> Path:
    """Pin model revision, reuse it fully offline, show first-download progress."""
    model_cache = root / '.models' / 'hub'
    repo_cache = model_cache / ('models--' + MODEL.replace('/', '--'))
    snapshot = repo_cache / 'snapshots' / MODEL_REVISION
    weights = snapshot / MODEL_FILE
    if (snapshot / 'config.json').is_file() and weights.is_file() and weights.stat().st_size == MODEL_SIZE:
        return snapshot
    print('首次下载约 464 MB 语音模型；之后无需重复下载，音频不会上传。', flush=True)
    stopped = threading.Event()

    def progress():
        while not stopped.wait(15):
            sizes = []
            for path in (repo_cache / 'blobs').glob('*'):
                try:
                    sizes.append(path.stat().st_size)
                except OSError:
                    pass
            downloaded = min(max(sizes, default=0), MODEL_SIZE)
            print(f'模型下载：{downloaded / 1024**2:.0f} / {MODEL_SIZE / 1024**2:.0f} MB。请保持网络连接。', flush=True)

    worker = threading.Thread(target=progress, daemon=True)
    worker.start()
    try:
        from huggingface_hub import snapshot_download
        return Path(snapshot_download(MODEL, revision=MODEL_REVISION, cache_dir=model_cache,
                                      allow_patterns=['config.json', MODEL_FILE]))
    finally:
        stopped.set()
        worker.join(timeout=1)


def run_video(url: str, endpoint: str, root: Path) -> None:
    data = get_video(url, endpoint)
    work_parent = root / '.video-work'
    work_parent.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='run-', dir=work_parent))
    media = work / 'video.mp4'
    try:
        print('正在下载完整视频（不会下载封面代替）……', flush=True)
        download_video(data['url'], media)
        transcribe_media(media, root, title=data['title'], source=data['source'],
                         author=data['author'], description=data['description'], expected=data['expected'])
    except Exception:
        print(f'尚未完成。下载文件保留在：{media}\n若文件完整，可下次直接拖入重试，不必重复登录下载。')
        raise
    else:
        shutil.rmtree(work)  # Only this invocation's private temporary directory.

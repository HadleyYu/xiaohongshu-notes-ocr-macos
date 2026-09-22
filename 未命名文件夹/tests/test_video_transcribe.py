"""Offline tests: never attach a browser, download media or load an ASR model."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import video_transcribe as v
from utils import AppError


@pytest.mark.parametrize('url,good', [
    ('https://sns-video-bd.xhscdn.com/test.mp4', True),
    ('http://sns-video.xhscdn.com/test', True),
    ('https://xhscdn.com.attacker.org/video', False),
    ('https://user:secret@xhscdn.com/video', False),
    ('http://127.0.0.1/test', False), ('file:///tmp/video', False),
    ('blob:https://www.xiaohongshu.com/1', False),
    ('https://xhscdn.com:bad/test', False),
])
def test_media_allowlist(url, good):
    assert v.media_url_allowed(url) is good


def test_only_target_stream_fields():
    note = {'video': {'media': {'stream': {'h264': [
        {'masterUrl': 'https://sns-video.xhscdn.com/whole.mp4', 'duration': 65000,
         'backupUrls': ['https://sns-video.xhscdn.com/whole.mp4', 'https://evil.example/video']}]}}},
        'imageList': [{'urlDefault': 'https://sns-webpic.xhscdn.com/cover'}],
        'recommendation': {'masterUrl': 'https://sns-video.xhscdn.com/wrong.mp4'}}
    assert v.stream_candidates(note) == [('https://sns-video.xhscdn.com/whole.mp4', 65)]


def test_local_paths_with_spaces(tmp_path):
    media = tmp_path / '中文 视频.mp4'
    media.touch()
    for text in (str(media), repr(str(media)), str(media).replace(' ', r'\ ')):
        assert v.local_media_path(text) == media
    assert v.local_media_path('分享 https://xhslink.cn/o/abc') is None
    assert v.local_media_path('很长的分享文案' * 100 + ' https://xhslink.cn/o/abc') is None


def test_bad_local_inputs(tmp_path):
    with pytest.raises(AppError):
        v.local_media_path('/not-existing/video.mp4')
    image = tmp_path / 'cover.png'
    image.touch()
    with pytest.raises(AppError):
        v.local_media_path(str(image))


def probe(monkeypatch, duration, audio=True):
    monkeypatch.setattr(v, 'tool_path', lambda name: name)
    result = {'format': {'duration': duration}, 'streams': [{'codec_type': 'audio' if audio else 'video'}]}
    monkeypatch.setattr(v.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=json.dumps(result)))


def test_full_duration_check(monkeypatch):
    probe(monkeypatch, 120)
    assert v.inspect_media(Path('v'), 120) == 120
    with pytest.raises(AppError, match='不是完整视频'):
        v.inspect_media(Path('v'), 300)


def test_cover_or_silent_video_rejected(monkeypatch):
    probe(monkeypatch, 100, audio=False)
    with pytest.raises(AppError, match='没有音轨'):
        v.inspect_media(Path('v'))


def test_markdown_keeps_later_speech_and_does_not_overwrite(tmp_path):
    result = {'segments': [{'start': 1, 'end': 4, 'text': '开始。'},
                           {'start': 100, 'end': 105, 'text': '结尾不能丢。'}]}
    a = v.write_markdown(tmp_path, result, '../标题', 120,
                         'https://www.xiaohongshu.com/explore/abc?xsec_token=secret')
    b = v.write_markdown(tmp_path, result, '../标题', 120)
    text = a.read_text()
    assert a.parent == tmp_path and a != b
    assert '[00:01:40–00:01:45]' in text and '结尾不能丢' in text
    assert 'secret' not in text and '00:02:00' in text


def test_no_speech_not_success(tmp_path):
    with pytest.raises(AppError, match='没有识别到'):
        v.write_markdown(tmp_path, {'segments': []}, '标题', 10)
    assert not list(tmp_path.glob('*.md'))


def test_whole_media_sent_to_asr(tmp_path, monkeypatch):
    monkeypatch.setattr(v, 'inspect_media', lambda *a: 300)
    monkeypatch.setattr(v, 'ensure_model', lambda root: tmp_path / 'model')
    monkeypatch.setattr(v, 'tool_path', lambda name: '/opt/homebrew/bin/' + name)
    asr = MagicMock(return_value={'segments': [{'start': 299, 'end': 300, 'text': '最后一句'}]})
    monkeypatch.setitem(sys.modules, 'mlx_whisper', SimpleNamespace(transcribe=asr))
    out = v.transcribe_media(tmp_path / 'whole.mp4', tmp_path, title='测试')
    assert asr.call_args.args == (str(tmp_path / 'whole.mp4'),)
    assert 'clip_timestamps' not in asr.call_args.kwargs
    assert '最后一句' in out.read_text()


def test_video_login_route(monkeypatch, tmp_path):
    import login_extract as login
    monkeypatch.setattr(sys, 'argv', ['login_extract.py', '--video'])
    monkeypatch.setenv('XHS_URL', 'https://xhslink.cn/o/test')
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    monkeypatch.setattr(login, 'open_login_browser', lambda url: 'http://127.0.0.1:12345')
    run = MagicMock()
    monkeypatch.setattr(v, 'run_video', run)
    assert login.main() == 0
    run.assert_called_once_with('https://xhslink.cn/o/test', 'http://127.0.0.1:12345', login.ROOT)


def test_local_route_needs_no_browser(monkeypatch, tmp_path):
    import login_extract as login
    media = tmp_path / '视频.mp4'
    media.touch()
    monkeypatch.setattr(sys, 'argv', ['login_extract.py', '--video'])
    monkeypatch.setenv('XHS_URL', str(media))
    start, asr = MagicMock(), MagicMock()
    monkeypatch.setattr(login, 'open_login_browser', start)
    monkeypatch.setattr(v, 'transcribe_media', asr)
    assert login.main() == 0
    start.assert_not_called()
    asr.assert_called_once()


def test_failed_run_retains_download(tmp_path, monkeypatch):
    monkeypatch.setattr(v, 'get_video', lambda *a: dict(url='url', title='标题', source='',
                                                      author='', description='', expected=None))
    monkeypatch.setattr(v, 'download_video', lambda url, path: path.write_bytes(b'video'))
    monkeypatch.setattr(v, 'transcribe_media', MagicMock(side_effect=AppError('识别失败')))
    with pytest.raises(AppError):
        v.run_video('link', 'endpoint', tmp_path)
    assert len(list((tmp_path / '.video-work').glob('run-*/video.mp4'))) == 1


def test_external_endpoint_rejected():
    with pytest.raises(AppError, match='本机回环'):
        v.get_video('https://xhslink.cn/o/test', 'http://evil.example:9222')


def browser_stub(monkeypatch, data, url='https://www.xiaohongshu.com/explore/a123?xsec_token=secret'):
    page = MagicMock(url=url)
    page.evaluate.return_value = data
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock(contexts=[context])
    pw = MagicMock()
    pw.chromium.connect_over_cdp.return_value = browser
    factory = MagicMock()
    factory.return_value.__enter__.return_value = pw
    monkeypatch.setattr('playwright.sync_api.sync_playwright', factory)
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    return page, browser


def test_browser_dom_video_fallback(monkeypatch):
    page, browser = browser_stub(monkeypatch, {'note': {}, 'src': 'https://sns-video.xhscdn.com/whole',
                                              'duration': 120, 'title': '视频标题'})
    data = v.get_video('https://xhslink.cn/o/test', 'http://127.0.0.1:12345')
    assert data['expected'] == 120 and data['title'] == '视频标题'
    assert data['source'] == 'https://www.xiaohongshu.com/explore/a123'
    assert page.evaluate.call_args.args[1] == 'a123'
    page.close.assert_called_once()
    browser.close.assert_called_once()


def test_no_fallback_to_cover(monkeypatch):
    page, browser = browser_stub(monkeypatch, {'note': {'imageList': [{'url': 'https://sns-webpic.xhscdn.com/cover'}]},
                                              'src': '', 'duration': None})
    with pytest.raises(AppError, match='不会改用封面'):
        v.get_video('https://xhslink.cn/o/test', 'http://127.0.0.1:12345')
    page.close.assert_called_once()


def test_image_note_does_not_use_recommended_video(monkeypatch):
    browser_stub(monkeypatch, {'note': {'type': 'normal'},
                              'src': 'https://sns-video.xhscdn.com/recommended'})
    with pytest.raises(AppError, match='不读取推荐视频'):
        v.get_video('https://xhslink.cn/o/test', 'http://127.0.0.1:12345')


def test_cached_model_works_offline(tmp_path, monkeypatch):
    snapshot = tmp_path / '.models/hub' / ('models--' + v.MODEL.replace('/', '--')) / 'snapshots' / v.MODEL_REVISION
    snapshot.mkdir(parents=True)
    (snapshot / 'config.json').write_text('{}')
    (snapshot / v.MODEL_FILE).write_bytes(b'weights')
    monkeypatch.setattr(v, 'MODEL_SIZE', 7)
    download = MagicMock(side_effect=AssertionError('Network access was attempted'))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=download))
    assert v.ensure_model(tmp_path) == snapshot
    download.assert_not_called()


def test_login_page_not_retried(monkeypatch):
    page, browser = browser_stub(monkeypatch, {}, url='https://www.xiaohongshu.com/login')
    with pytest.raises(AppError, match='仍需登录'):
        v.get_video('https://xhslink.cn/o/test', 'http://127.0.0.1:12345')
    page.goto.assert_called_once()
    page.evaluate.assert_not_called()


def test_download_rejects_partial_response(tmp_path, monkeypatch):
    response = MagicMock(status=206)
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr(v, 'build_opener', lambda *a: opener)
    with pytest.raises(AppError, match='完整视频'):
        v.download_video('https://sns-video.xhscdn.com/test', tmp_path / 'video.mp4')
    assert not (tmp_path / 'video.mp4').exists()


def test_download_truncation(tmp_path, monkeypatch):
    response = MagicMock(status=200, headers={'Content-Length': '100'})
    response.read.side_effect = [b'short', b'']
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr(v, 'build_opener', lambda *a: opener)
    with pytest.raises(AppError, match='不完整'):
        v.download_video('https://sns-video.xhscdn.com/test', tmp_path / 'video.mp4')


def test_success_cleans_only_own_download(tmp_path, monkeypatch):
    retained = tmp_path / '.video-work' / 'previous-run'
    retained.mkdir(parents=True)
    (retained / 'video.mp4').write_bytes(b'previous')
    monkeypatch.setattr(v, 'get_video', lambda *a: dict(url='url', title='标题', source='',
                                                      author='', description='', expected=None))
    monkeypatch.setattr(v, 'download_video', lambda url, path: path.write_bytes(b'video'))
    monkeypatch.setattr(v, 'transcribe_media', MagicMock())
    v.run_video('link', 'endpoint', tmp_path)
    assert list((tmp_path / '.video-work').iterdir()) == [retained]

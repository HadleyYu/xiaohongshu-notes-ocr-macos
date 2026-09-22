"""Offline tests; no account data, browser startup or real network requests."""
import json
from unittest.mock import MagicMock

import pytest
import login_extract as login
import xhs_url_validator as urls
from utils import AppError


@pytest.fixture(autouse=True)
def isolated_endpoint_env(monkeypatch):
    monkeypatch.delenv('XHS_CHROME_CDP_URL', raising=False)


def test_no_implicit_browser_attachment(monkeypatch):
    monkeypatch.delenv('XHS_CHROME_CDP_URL', raising=False)
    assert urls._resolve_short_url_via_browser('https://xhslink.cn/o/test') is None


@pytest.mark.parametrize('endpoint', ['http://example.com:9222', 'https://127.0.0.1:9222',
                                       'http://user:pass@127.0.0.1:9222'])
def test_external_browser_endpoints_rejected(monkeypatch, endpoint):
    monkeypatch.setenv('XHS_CHROME_CDP_URL', endpoint)
    with pytest.raises(AppError, match='本机回环'):
        urls._resolve_short_url_via_browser('https://xhslink.cn/o/test')


def test_resolver_uses_explicit_session(monkeypatch):
    monkeypatch.setenv('XHS_CHROME_CDP_URL', 'http://127.0.0.1:43210')
    context = MagicMock()
    context.new_page.return_value.url = 'https://www.xiaohongshu.com/explore/abc'
    browser = MagicMock(contexts=[context])
    pw = MagicMock()
    pw.chromium.connect_over_cdp.return_value = browser
    factory = MagicMock()
    factory.return_value.__enter__.return_value = pw
    monkeypatch.setattr('playwright.sync_api.sync_playwright', factory)
    assert urls._resolve_short_url_via_browser('https://xhslink.cn/o/test').endswith('/abc')
    pw.chromium.connect_over_cdp.assert_called_once_with('http://127.0.0.1:43210')
    context.new_page.return_value.close.assert_called_once()


@pytest.mark.parametrize('websocket,valid', [
    ('ws://127.0.0.1:43210/devtools/browser/test-id', True),
    ('ws://127.0.0.1:43210/devtools/browser/other-id', False),
    ('ws://example.com:43210/devtools/browser/test-id', False),
])
def test_endpoint_belongs_to_private_profile(tmp_path, monkeypatch, websocket, valid):
    (tmp_path / 'DevToolsActivePort').write_text('43210\n/devtools/browser/test-id\n')
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {'webSocketDebuggerUrl': websocket}).encode()
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr(login, 'build_opener', lambda *args: opener)
    assert (login.running_endpoint(tmp_path) is not None) == valid


def test_confirmation_then_shared_session(monkeypatch):
    monkeypatch.setattr('sys.argv', ['login_extract.py'])
    monkeypatch.setenv('XHS_URL', 'https://xhslink.cn/o/test')
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    monkeypatch.setattr(login, 'open_login_browser', lambda url: 'http://127.0.0.1:43210')
    run = MagicMock()
    monkeypatch.setattr('main.run_from_clipboard_flow', run)
    assert login.main() == 0
    assert login.os.environ['XHS_CHROME_CDP_URL'] == 'http://127.0.0.1:43210'
    run.assert_called_once_with(login.ROOT, use_local_chrome=True, chrome_cdp_url='http://127.0.0.1:43210')


def test_cancel_opens_nothing(monkeypatch):
    monkeypatch.setattr('sys.argv', ['login_extract.py'])
    monkeypatch.setenv('XHS_URL', 'https://xhslink.cn/o/test')
    monkeypatch.setattr('builtins.input', lambda prompt: 'q')
    start = MagicMock()
    monkeypatch.setattr(login, 'open_login_browser', start)
    assert login.main() == 0
    start.assert_not_called()

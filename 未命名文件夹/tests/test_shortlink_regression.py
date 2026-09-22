"""Share-link regression tests; no live network or browser access."""
from unittest.mock import MagicMock
import pytest
import xhs_url_validator as urls
from utils import AppError

SHORT = 'https://xhslink.cn/o/2jlnsN1y3LH'
NOTE = 'https://www.xiaohongshu.com/discovery/item/abc123?xsec_token=test&xsec_source=app_share&foo=bar'


@pytest.fixture(autouse=True)
def no_real_browser_or_network(monkeypatch):
    monkeypatch.setattr(urls, '_resolve_short_url_via_browser', lambda url: None)
    response = MagicMock()
    response.__enter__.return_value.geturl.return_value = NOTE
    request = MagicMock(return_value=response)
    monkeypatch.setattr(urls, 'urlopen', request)
    return request


@pytest.mark.parametrize('share', [
    SHORT,
    f'科研IDEA怎么来的【直播切片】 科研的IDEA可以有两种... {SHORT} 直达【小红书】看看这篇分享~',
    f'科研IDEA怎么来的【直播切片】 [{SHORT}]({SHORT}) 直达【小红书】看看这篇分享~',
    f'[查看笔记]({SHORT})',
    f'<{SHORT}>',
    f'链接：{SHORT}。',
])
def test_cn_share_formats(share, no_real_browser_or_network):
    parsed = urls.parse_xhs_url(share)
    assert parsed.extracted_url == SHORT
    assert parsed.share_link_host == 'xhslink.cn'
    assert parsed.note_id == 'abc123'
    assert parsed.xsec_token == 'test'
    assert parsed.xsec_source == 'app_share'
    assert 'foo=bar' in parsed.canonical_url
    assert '/explore/abc123?' in parsed.canonical_url
    assert no_real_browser_or_network.call_args.args[0].full_url == SHORT


def test_existing_com_still_supported():
    assert urls.parse_xhs_url('https://xhslink.com/o/example').share_link_host == 'xhslink.com'


@pytest.mark.parametrize('bad', [
    'https://xhslink.cn.evil.example/o/example',
    'https://notxhslink.cn/o/example',
    'https://example.com/o/example',
])
def test_lookalike_domains_rejected(bad, no_real_browser_or_network):
    with pytest.raises(AppError, match='不是支持的小红书'):
        urls.parse_xhs_url(bad)
    no_real_browser_or_network.assert_not_called()


def test_non_xhs_redirect_rejected(no_real_browser_or_network):
    no_real_browser_or_network.return_value.__enter__.return_value.geturl.return_value = 'https://example.com/note'
    with pytest.raises(AppError, match='不是支持的小红书'):
        urls.parse_xhs_url(SHORT)


def test_network_failure_is_not_invalid_format(no_real_browser_or_network):
    no_real_browser_or_network.side_effect = OSError('network down')
    with pytest.raises(AppError, match='短链解析失败'):
        urls.parse_xhs_url(SHORT)


def test_login_redirect_has_actionable_error(no_real_browser_or_network):
    no_real_browser_or_network.return_value.__enter__.return_value.geturl.return_value = (
        'https://www.xiaohongshu.com/login?redirectPath=%2Fexplore%2Fabc123'
    )
    with pytest.raises(AppError, match='要求登录后查看'):
        urls.parse_xhs_url(SHORT)

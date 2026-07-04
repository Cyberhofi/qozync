"""Credential extraction from a synthetic web-player bundle.

The secret assembly is: seed + info + extras, drop the last 44 chars, base64-
decode. We craft a single-timezone bundle whose fragments decode to "abc".
"""

import base64

from app.qobuz import bundle

# base64("abc") == "YWJj"; make info+extras exactly 44 chars so that
# (seed+info+extras)[:-44] == "YWJj".
_SEED = base64.b64encode(b"abc").decode()  # "YWJj"
_INFO = "A" * 22
_EXTRAS = "B" * 22

_BUNDLE = (
    'foo production:{api:{appId:"123456789",appSecret:"x"}} bar '
    f'a.initialSeed("{_SEED}",window.utimezone.berlin) baz '
    f'name:"Europe/Berlin",info:"{_INFO}",extras:"{_EXTRAS}" qux'
)


def test_extract_app_id():
    assert bundle.extract_app_id(_BUNDLE) == "123456789"


def test_extract_secrets_decodes_fragments():
    assert bundle.extract_secrets(_BUNDLE) == ["abc"]


def test_bundle_url_regex():
    html = '<html><script src="/resources/7.1.3-b012/bundle.js"></script></html>'
    m = bundle._BUNDLE_URL_RE.search(html)
    assert m and m.group(1) == "/resources/7.1.3-b012/bundle.js"

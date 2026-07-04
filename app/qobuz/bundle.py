"""Extract the Qobuz ``app_id`` and candidate ``app_secret`` values.

Qobuz doesn't hand these out to end users, but the public web player ships them
inside its JavaScript bundle. The app id is embedded verbatim; the secrets are
assembled from per-timezone "seed" fragments plus "info"/"extras" fragments and
base64-decoded — the long-standing community algorithm reproduced here.

Extraction can break whenever Qobuz reshapes their bundle, so callers should
treat failure as non-fatal and fall back to values entered in Settings.
"""

from __future__ import annotations

import base64
import re
from collections import OrderedDict
from dataclasses import dataclass

import httpx

PLAY_BASE = "https://play.qobuz.com"
LOGIN_PAGE = f"{PLAY_BASE}/login"

_BUNDLE_URL_RE = re.compile(r'<script src="(/resources/[^"]+/bundle\.js)"')
_APP_ID_RE = re.compile(r'production:\{api:\{appId:"(\d+)"')
_APP_ID_FALLBACK_RE = re.compile(r'app(?:_i|I)d:"(\d{9,})"')
_SEED_TZ_RE = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)


@dataclass
class BundleCredentials:
    app_id: str
    secrets: list[str]  # candidate secrets; the working one is chosen by validation


class BundleError(RuntimeError):
    pass


def fetch_bundle(client: httpx.Client | None = None) -> str:
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        login_html = client.get(LOGIN_PAGE).text
        m = _BUNDLE_URL_RE.search(login_html)
        if not m:
            raise BundleError("could not locate bundle.js on the Qobuz login page")
        return client.get(f"{PLAY_BASE}{m.group(1)}").text
    finally:
        if own:
            client.close()


def extract_app_id(bundle: str) -> str:
    m = _APP_ID_RE.search(bundle) or _APP_ID_FALLBACK_RE.search(bundle)
    if not m:
        raise BundleError("could not find app_id in bundle")
    return m.group(1)


def extract_secrets(bundle: str) -> list[str]:
    """Reassemble the candidate app secrets from the bundle.

    Each timezone contributes a seed and (usually) an info/extras pair; the
    three are concatenated, the trailing 44 chars dropped, and the result
    base64-decoded into a 32-char secret. One timezone has no info/extras and
    yields an empty string, which we discard.
    """
    seed_matches = list(_SEED_TZ_RE.finditer(bundle))
    if not seed_matches:
        raise BundleError("could not find timezone seeds in bundle")

    secrets: "OrderedDict[str, list[str]]" = OrderedDict()
    for match in seed_matches:
        secrets[match.group("timezone")] = [match.group("seed")]

    # Rotate so timezone order matches the info/extras declaration order.
    keypairs = list(secrets.items())
    if len(keypairs) > 1:
        secrets.move_to_end(keypairs[1][0], last=False)

    info_extras_re = re.compile(
        r'name:"\w+/(?P<timezone>'
        + "|".join(tz.capitalize() for tz in secrets)
        + r')",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
    )
    for match in info_extras_re.finditer(bundle):
        tz = match.group("timezone").lower()
        if tz in secrets:
            secrets[tz] += [match.group("info"), match.group("extras")]

    out: list[str] = []
    for parts in secrets.values():
        joined = "".join(parts)
        if len(joined) <= 44:
            continue
        try:
            decoded = base64.standard_b64decode(joined[:-44]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded:
            out.append(decoded)
    if not out:
        raise BundleError("no secrets could be decoded from bundle")
    return out


def fetch_credentials(client: httpx.Client | None = None) -> BundleCredentials:
    bundle = fetch_bundle(client)
    return BundleCredentials(app_id=extract_app_id(bundle), secrets=extract_secrets(bundle))

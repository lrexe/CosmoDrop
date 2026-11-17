"""Картинки NFT-подарков: берём с публичного CDN Telegram/Fragment и кладём в дисковый кэш."""
import os
import re
import tempfile
import threading
import time
import urllib.request

SLUG_RE = re.compile(r"^[a-z0-9]{2,40}-\d{1,7}$")
# ext -> (суффикс на CDN, content-type, лимит в байтах)
EXTS = {"jpg": (".medium.jpg", "image/jpeg", 1024 * 1024),
        "webp": (".webp", "image/webp", 1024 * 1024),
        "json": (".lottie.json", "application/json", 600 * 1024)}
NEG_TTL = 600          # секунд помним, что CDN ответил «нет»
TIMEOUT = 6

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "instance", "gift_cache")

_neg = {}
_lock = threading.Lock()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редиректы не выполняем: 3xx от CDN — это промах (иначе можно уйти на внутренний адрес)."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _cdn_base():
    return os.getenv("GIFT_CDN_BASE", "https://nft.fragment.com/gift").rstrip("/")


def _fetch(slug, ext):
    suffix, ctype, limit = EXTS[ext]
    req = urllib.request.Request(f"{_cdn_base()}/{slug}{suffix}",
                                 headers={"User-Agent": "vloody-giftart"})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            return None
        if resp.headers.get_content_type() != ctype:
            return None
        data = resp.read(limit + 1)
    if not data or len(data) > limit:
        return None
    return data


def get_art(slug, ext):
    """(байты, content-type) или None. Сначала диск, потом CDN."""
    if not isinstance(slug, str) or not isinstance(ext, str):
        return None
    if ext not in EXTS or not SLUG_RE.match(slug):
        return None
    ctype = EXTS[ext][1]
    path = os.path.join(CACHE_DIR, f"{slug}.{ext}")
    try:
        with open(path, "rb") as f:
            return f.read(), ctype
    except OSError:
        pass
    key = (slug, ext)
    with _lock:
        until = _neg.get(key, 0)
    if until > time.monotonic():
        return None
    try:
        data = _fetch(slug, ext)
    except Exception:
        data = None
    if data is None:
        with _lock:
            _neg[key] = time.monotonic() + NEG_TTL
        return None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass                      # кэш не записался — всё равно отдаём байты
    return data, ctype

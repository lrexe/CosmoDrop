"""Картинки NFT-подарков: берём с публичного CDN Telegram/Fragment и кладём в дисковый кэш."""
import json
import os
import re
import tempfile
import threading
import time
import urllib.parse
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


def _write_cache(path, data):
    """Атомарная запись в кэш: временный файл + os.replace."""
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
    _write_cache(path, data)
    return data, ctype


# ------------------------------------------------------------------ обычные подарки (за Stars)
CATALOG_TTL = 6 * 3600     # каталог живёт в памяти 6 часов
CATALOG_FAIL_TTL = 60      # при ошибке API не долбим Telegram чаще раза в минуту
REGULAR_LIMIT = 200 * 1024
GID_RE = re.compile(r"^\d{1,20}$")

_cat = {"at": 0.0, "items": None, "ttl": CATALOG_TTL}


def _api_base():
    return os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")


def _token():
    return (os.getenv("BOT_TOKEN", "").strip() or os.getenv("RELAY_BOT_TOKEN", "").strip())


def _api_json(token, method, query=""):
    req = urllib.request.Request(f"{_api_base()}/bot{token}/{method}{query}",
                                 headers={"User-Agent": "vloody-giftart"})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            return None
        data = json.loads(resp.read(1024 * 1024 + 1))
    return data.get("result") if isinstance(data, dict) and data.get("ok") else None


def _load_catalog(token):
    res = _api_json(token, "getAvailableGifts")
    items = []
    for g in (res or {}).get("gifts", []):
        gid, stars = str(g.get("id", "")), g.get("star_count")
        if not GID_RE.match(gid) or not isinstance(stars, int) or isinstance(stars, bool):
            continue
        sticker = g.get("sticker") or {}
        thumb = (sticker.get("thumbnail") or {}).get("file_id")
        items.append({"id": gid, "stars": stars, "emoji": str(sticker.get("emoji") or ""),
                      "_thumb": thumb if isinstance(thumb, str) else None})
    return items


def _catalog_full():
    """Каталог вместе со служебным _thumb (наружу не отдаётся)."""
    with _lock:
        if _cat["items"] is not None and time.monotonic() - _cat["at"] < _cat["ttl"]:
            return _cat["items"]
    token = _token()
    if not token:
        return []
    try:
        items, ttl = _load_catalog(token), CATALOG_TTL
        if not items:
            ttl = CATALOG_FAIL_TTL
    except Exception:
        items, ttl = [], CATALOG_FAIL_TTL
    with _lock:
        _cat.update(at=time.monotonic(), items=items, ttl=ttl)
    return items


def regular_catalog():
    """[{"id": str, "stars": int, "emoji": str}] из getAvailableGifts; без токена или при ошибке — []."""
    return [{"id": g["id"], "stars": g["stars"], "emoji": g["emoji"]} for g in _catalog_full()]


def _fetch_regular(token, thumb):
    info = _api_json(token, "getFile", "?" + urllib.parse.urlencode({"file_id": thumb}))
    path = (info or {}).get("file_path")
    # путь от Telegram — только компонент URL; берём лишь простой путь к .webp
    if not isinstance(path, str) or not path.endswith(".webp") or path.startswith("/") \
            or ".." in path.split("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
        return None
    req = urllib.request.Request(f"{_api_base()}/file/bot{token}/{path}",
                                 headers={"User-Agent": "vloody-giftart"})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            return None
        data = resp.read(REGULAR_LIMIT + 1)
    if not data or len(data) > REGULAR_LIMIT or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    return data


def get_regular_art(gid):
    """(байты, 'image/webp') для подарка из каталога или None. id сверяется с каталогом ДО любой загрузки."""
    gid = str(gid)
    entry = next((g for g in _catalog_full() if g["id"] == gid), None)
    if entry is None:
        return None
    ctype = "image/webp"
    # имя файла строится только из совпавшего id каталога
    path = os.path.join(CACHE_DIR, f"regular-{entry['id']}.webp")
    try:
        with open(path, "rb") as f:
            return f.read(), ctype
    except OSError:
        pass
    key = ("regular", entry["id"])
    with _lock:
        until = _neg.get(key, 0)
    if until > time.monotonic() or not entry["_thumb"]:
        return None
    try:
        data = _fetch_regular(_token(), entry["_thumb"])
    except Exception:
        data = None
    if data is None:
        with _lock:
            _neg[key] = time.monotonic() + NEG_TTL
        return None
    _write_cache(path, data)
    return data, ctype

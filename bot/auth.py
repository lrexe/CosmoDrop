"""
CosmoDrop — авторизация и защита API.

Кто делает запрос, определяет ТОЛЬКО сервер:
  * боевой режим (задан BOT_TOKEN): личность берётся из подписанного Telegram
    `initData` (заголовок X-Telegram-Init-Data), подпись проверяется HMAC-SHA256;
  * демо-режим (BOT_TOKEN не задан или DEMO_MODE=1): все запросы без initData
    выполняются от имени одного демо-пользователя DEMO_TELEGRAM_ID.

`telegram_id` из тела/параметров запроса больше ни на что не влияет.
"""

import hashlib
import hmac
import json
import os
import re
import time
from collections import defaultdict, deque
from urllib.parse import parse_qsl

from flask import g, jsonify, request

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DEMO_MODE = os.getenv("DEMO_MODE", "").strip() == "1" or not BOT_TOKEN
DEMO_TELEGRAM_ID = int(os.getenv("DEMO_TELEGRAM_ID", "111222333"))
INIT_DATA_MAX_AGE = int(os.getenv("INIT_DATA_MAX_AGE", str(24 * 3600)))   # секунд
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

INIT_DATA_HEADER = "X-Telegram-Init-Data"

# лимит запросов на одного пользователя (или IP, если личность не установлена)
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "40"))
RATE_WINDOW = 5.0                                                         # секунд
_hits = defaultdict(deque)


# ------------------------------------------------------------- initData
def verify_init_data(init_data, bot_token=None, max_age=None):
    """Проверяет подпись Telegram WebApp initData. Возвращает dict user или None."""
    bot_token = bot_token if bot_token is not None else BOT_TOKEN
    max_age = INIT_DATA_MAX_AGE if max_age is None else max_age
    if not init_data or not bot_token or len(init_data) > 4096:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None

    received = pairs.pop("hash", "")
    if not received:
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        if max_age and time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None                                  # подпись устарела
        user = json.loads(pairs.get("user", ""))
        user["id"] = int(user["id"])
    except (ValueError, TypeError, KeyError):
        return None
    user["start_param"] = pairs.get("start_param")
    return user


def current_identity():
    """Личность текущего запроса: dict(telegram_id, username, first_name, photo_url, demo) или None."""
    if "cd_identity" in g:
        return g.cd_identity
    ident = None
    user = verify_init_data(request.headers.get(INIT_DATA_HEADER, ""))
    if user:
        ident = {
            "telegram_id": user["id"],
            "username": user.get("username"),
            "first_name": user.get("first_name") or user.get("username"),
            "photo_url": user.get("photo_url"),
            "demo": False,
        }
    elif DEMO_MODE:
        ident = {"telegram_id": DEMO_TELEGRAM_ID, "username": None,
                 "first_name": None, "photo_url": None, "demo": True}
    g.cd_identity = ident
    return ident


# ------------------------------------------------------------- санитайзинг
_UNSAFE = re.compile(r"[<>&\"'`\x00-\x1f\x7f]")


def clean_text(value, limit=64):
    """Имя/юзернейм попадают в HTML на клиенте — вырезаем всё, что может стать разметкой."""
    if not isinstance(value, str):
        return None
    value = _UNSAFE.sub("", value).strip()[:limit]
    return value or None


def clean_photo_url(value):
    if not isinstance(value, str) or len(value) > 255:
        return None
    if not re.fullmatch(r"https://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+", value):
        return None
    return value


# ------------------------------------------------------------- хуки приложения
PUBLIC_PATHS = {"/api/telegram_payment"}          # у вебхука своя проверка секрета
# служебные API (бот-хранитель подарков, админка) авторизуются своим секретом
SERVICE_PREFIXES = ("/api/relay/", "/api/admin/")
RELAY_SECRET = os.getenv("RELAY_SECRET", "").strip()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "").strip()


def service_auth(secret, header):
    """True, если запрос несёт верный служебный секрет (и он вообще настроен)."""
    got = request.headers.get(header, "")
    return bool(secret) and hmac.compare_digest(got, secret)


def _rate_limited(key):
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    if len(_hits) > 20000:                         # не даём словарю расти бесконечно
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
            _hits.pop(k, None)
    return False


def init_security(app):
    @app.before_request
    def guard_api():
        if not request.path.startswith("/api/") or request.path in PUBLIC_PATHS:
            return None
        if request.path.startswith(SERVICE_PREFIXES):
            if _rate_limited(f"svc:{request.remote_addr}"):
                return jsonify({"error": "Too many requests"}), 429
            return None
        ident = current_identity()
        key = ident["telegram_id"] if ident else f"ip:{request.remote_addr}"
        if _rate_limited(key):
            return jsonify({"error": "Слишком много запросов, подожди пару секунд"}), 429
        if ident is None:
            return jsonify({"error": "Открой приложение через Telegram"}), 401
        return None

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

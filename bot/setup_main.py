"""
Vloody — подключение основного бота и Mini App.

Что делает:
  1. проверяет токен основного бота (BOT_TOKEN в .env);
  2. дописывает в .env недостающие секреты (SECRET_KEY, TELEGRAM_WEBHOOK_SECRET, ADMIN_SECRET)
     и адрес приложения (PUBLIC_URL, BOT_USERNAME);
  3. ставит вебхук на <адрес>/api/telegram_payment — через него идут /start и оплата звёздами;
  4. делает кнопку меню бота кнопкой запуска Mini App.

Запуск:  python -m bot.setup_main https://твой-адрес
Проверка без изменений:  python -m bot.setup_main --status

После запуска ПЕРЕЗАПУСТИ сервер: с BOT_TOKEN он переходит в боевой режим
(вход только из Telegram, демо-пополнение и демо-подарки выключены).
"""

import json
import os
import secrets
import sys
import urllib.error
import urllib.request

from bot.envfile import ENV_PATH, load_env

API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")


def tg(token, method, **params):
    req = urllib.request.Request(f"{API_BASE}/bot{token}/{method}", data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        res = json.loads(e.read() or b"{}")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"Нет связи с Telegram: {e}")
    if not res.get("ok"):
        raise SystemExit(f"Telegram отклонил {method}: {res.get('description')}")
    return res["result"]


def set_env(values, path=None):
    """Обновляет/добавляет KEY=VALUE в .env, не трогая остальное. Значения не печатает."""
    path = path or ENV_PATH
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    left = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in left and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={left.pop(key)}"
    lines += [f"{k}={v}" for k, v in left.items()]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.environ.update(values)


def status(token):
    me = tg(token, "getMe")
    wh = tg(token, "getWebhookInfo")
    print(f"Бот: @{me['username']} ({me.get('first_name')})")
    print(f"Вебхук: {wh.get('url') or 'не задан'}")
    if wh.get("last_error_message"):
        print(f"  последняя ошибка доставки: {wh['last_error_message']}")
    print(f"  ждут доставки: {wh.get('pending_update_count', 0)}")
    return me


def main(argv):
    load_env()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("В .env нет BOT_TOKEN — токена основного бота от @BotFather.")
    if token == os.getenv("RELAY_BOT_TOKEN", "").strip():
        raise SystemExit("BOT_TOKEN совпадает с токеном бота-хранителя. Основной бот должен быть отдельным.")

    if "--status" in argv or not argv:
        status(token)
        if not argv:
            print("\nЧтобы подключить: python -m bot.setup_main https://твой-адрес")
        return

    url = argv[0].strip().rstrip("/")
    if not url.startswith("https://") or len(url) < 12:
        raise SystemExit("Нужен публичный адрес, начинающийся с https:// — Telegram не работает с http.")

    me = tg(token, "getMe")
    fresh = {k: secrets.token_urlsafe(32)
             for k in ("SECRET_KEY", "TELEGRAM_WEBHOOK_SECRET", "ADMIN_SECRET") if not os.getenv(k)}
    set_env({**fresh, "PUBLIC_URL": url, "BOT_USERNAME": me["username"]})

    tg(token, "setWebhook", url=url + "/api/telegram_payment",
       secret_token=os.environ["TELEGRAM_WEBHOOK_SECRET"],
       allowed_updates=["message", "pre_checkout_query"], drop_pending_updates=True)
    tg(token, "setChatMenuButton", menu_button={"type": "web_app", "text": "Vloody", "web_app": {"url": url + "/"}})
    from bot.vloody import BOT_COMMANDS, BOT_SHORT_DESC, BOT_LONG_DESC
    tg(token, "setMyCommands", commands=BOT_COMMANDS)
    tg(token, "setMyShortDescription", short_description=BOT_SHORT_DESC)
    tg(token, "setMyDescription", description=BOT_LONG_DESC)

    print(f"Готово: @{me['username']} подключён к {url}")
    if fresh:
        print("В .env добавлены новые секреты: " + ", ".join(fresh)
              + ("\n  ADMIN_SECRET — пароль для /admin, посмотри его в файле .env" if "ADMIN_SECRET" in fresh else ""))
    print("\nДальше:\n  1. Перезапусти сервер — он перейдёт в боевой режим.\n"
          f"  2. Открой @{me['username']} в Telegram и нажми /start или кнопку меню.\n"
          "  3. В @BotFather: Bot Settings → Configure Mini App → включи и укажи тот же адрес —\n"
          "     тогда заработают реферальные ссылки вида t.me/бот?startapp=код.")


if __name__ == "__main__":
    main(sys.argv[1:])

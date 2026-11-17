"""
Vloody — бот-хранитель подарков (эскроу).

Как это устроено в Telegram
---------------------------
Бот сам подарки получать не умеет. Подарки принимает обычный аккаунт с Telegram
Business (аккаунт-хранитель, например @VloodyRelay), а этот бот подключён к нему
как бизнес-бот с правами «просмотр подарков» и «передача подарков». От имени
аккаунта бот:

  1. видит уникальные (NFT) подарки, которые игроки передали хранителю, и сообщает
     о них серверу Vloody -> подарок появляется в инвентаре отправителя;
  2. забирает с сервера заявки на вывод и передаёт подарки победителям/владельцам;
  3. если передать не получилось — возвращает подарок в инвентарь и плату владельцу.

Запуск:  python -m bot.relay
Переменные окружения:
  RELAY_BOT_TOKEN   токен ОТДЕЛЬНОГО бота (не основного — у того вебхук оплаты)
  RELAY_SECRET      тот же секрет, что у сервера Vloody
  VLOODY_URL        адрес сервера, по умолчанию http://127.0.0.1:5000
  RELAY_STATE       файл состояния, по умолчанию instance/relay_state.json
  RELAY_SYNC_SEC    период сверки, по умолчанию 15

Используется только стандартная библиотека.
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger("relay")

MAX_ATTEMPTS = 5            # после стольких неудач подарок возвращается в инвентарь
STARS_ERRORS = ("BALANCE_TOO_LOW", "not enough", "STARS")

# эмодзи для популярных коллекций — чисто косметика в интерфейсе
GIFT_EMOJI = {
    "plush pepe": "🐸", "evil eye": "👁", "vintage cigar": "🚬", "jelly bunny": "🐰",
    "durov's cap": "🎩", "astral shard": "💎", "spring basket": "🥚", "witch hat": "🧙",
    "toy bear": "🧸", "lol pop": "🍭", "signet ring": "💍", "voodoo doll": "🪆",
    "scared cat": "🙀", "berry box": "🍓", "jester hat": "🤡", "homemade cake": "🎂",
    "diamond ring": "💍", "loot bag": "💰", "love potion": "🧪", "magic potion": "⚗️",
    "desk calendar": "📅", "eternal rose": "🌹", "crystal ball": "🔮", "skull flower": "💀",
}


class ApiError(Exception):
    pass


class Relay:
    def __init__(self, token, secret, backend="http://127.0.0.1:5000",
                 state_path="instance/relay_state.json",
                 api_base="https://api.telegram.org"):
        self.token, self.secret = token, secret
        self.backend = backend.rstrip("/")
        self.api_base = api_base.rstrip("/")
        self.state_path = state_path
        self.state = {"offset": 0, "connection_id": None, "owner_id": None,
                      "started_at": int(time.time()), "seen": [], "attempts": {}, "skipped": []}
        self._load()

    # ------------------------------------------------------------ состояние
    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                self.state.update(json.load(f))
        except (OSError, ValueError):
            pass

    def _save(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------ HTTP
    def _http(self, url, payload=None, headers=None, timeout=35):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            raise ApiError(body.get("description") or body.get("error") or f"HTTP {e.code}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(str(e))

    def tg(self, method, **params):
        res = self._http(f"{self.api_base}/bot{self.token}/{method}", params)
        if not res.get("ok"):
            raise ApiError(res.get("description") or "Telegram API error")
        return res["result"]

    def api(self, path, payload=None):
        return self._http(self.backend + path, payload, {"X-Relay-Secret": self.secret}, timeout=15)

    def notify(self, chat_id, text):
        """Сообщение игроку — по возможности: он мог не открывать диалог с ботом."""
        try:
            self.tg("sendMessage", chat_id=chat_id, text=text)
        except ApiError:
            pass

    # ------------------------------------------------------------ обновления
    def poll_updates(self, timeout=20):
        """Ловит подключение бизнес-аккаунта и ускоряет сверку при новом подарке."""
        updates = self.tg("getUpdates", offset=self.state["offset"], timeout=timeout,
                          allowed_updates=["message", "business_connection", "business_message"])
        fresh_gift = False
        for u in updates:
            self.state["offset"] = u["update_id"] + 1
            conn = u.get("business_connection")
            if conn:
                self._on_connection(conn)
            bm = u.get("business_message")
            if bm and (bm.get("unique_gift") or bm.get("gift")):
                fresh_gift = True
            msg = u.get("message")
            if msg and (msg.get("text") or "").startswith("/start"):
                self.notify(msg["chat"]["id"],
                            "Я храню подарки для розыгрышей Vloody.\n\n"
                            "Чтобы внести подарок, передай уникальный (NFT) подарок аккаунту-хранителю — "
                            "через минуту он появится в твоём инвентаре в приложении.")
        if updates:
            self._save()
        return fresh_gift

    def _on_connection(self, conn):
        rights = conn.get("rights") or {}
        if not conn.get("is_enabled"):
            if conn.get("id") == self.state["connection_id"]:
                log.error("Бизнес-аккаунт ОТКЛЮЧИЛ бота — приём и выдача подарков остановлены")
                self.state["connection_id"] = None
            return
        self.state["connection_id"] = conn["id"]
        self.state["owner_id"] = (conn.get("user") or {}).get("id")
        log.info("Подключён бизнес-аккаунт %s (connection %s)", self.state["owner_id"], conn["id"])
        for right, why in (("can_view_gifts_and_stars", "видеть подарки"),
                           ("can_transfer_and_upgrade_gifts", "передавать подарки"),
                           ("can_transfer_stars", "платить звёздами за передачу")):
            if not rights.get(right):
                log.warning("У бота нет права %s — он не сможет %s", right, why)

    # ------------------------------------------------------------ подарки аккаунта
    def owned_gifts(self):
        """Все уникальные подарки на аккаунте-хранителе: {owned_gift_id: OwnedGift}."""
        out, offset = {}, ""
        for _ in range(200):
            page = self.tg("getBusinessAccountGifts", business_connection_id=self.state["connection_id"],
                           offset=offset, limit=100)
            for g in page.get("gifts", []):
                if g.get("type") == "unique" and g.get("owned_gift_id"):
                    out[g["owned_gift_id"]] = g
            offset = page.get("next_offset") or ""
            if not offset:
                break
        return out

    @staticmethod
    def gift_title(owned):
        gift = owned.get("gift") or {}
        base = gift.get("base_name") or gift.get("name") or "Gift"
        number = gift.get("number")
        return (f"{base} #{number}" if number else base), GIFT_EMOJI.get(base.lower(), "🎁")

    def sync_deposits(self, owned):
        """Сообщает серверу о подарках, пришедших после запуска хранителя."""
        seen, credited = set(self.state["seen"]), 0
        for gid, g in owned.items():
            if gid in seen:
                continue
            sender = g.get("sender_user") or {}
            reason = None
            if (g.get("send_date") or 0) < self.state["started_at"]:
                reason = "получен до запуска хранителя"      # личные подарки владельца не трогаем
            elif not sender.get("id") or sender.get("is_bot"):
                reason = "отправитель скрыт — некому зачислить"
            elif sender["id"] == self.state["owner_id"]:
                reason = "отправитель — сам аккаунт-хранитель"
            if reason:
                if gid not in self.state["skipped"]:
                    self.state["skipped"].append(gid)
                    log.warning("Подарок %s пропущен: %s", gid, reason)
                continue

            name, emoji = self.gift_title(g)
            try:
                res = self.api("/api/relay/gift-deposit", {
                    "telegram_id": sender["id"], "name": name, "emoji": emoji, "tg_gift_id": gid,
                    "transfer_star_count": g.get("transfer_star_count") or 0})
            except ApiError as e:
                log.error("Сервер не принял подарок %s: %s", gid, e)
                continue
            seen.add(gid)
            if res.get("status") == "credited":
                credited += 1
                log.info("Зачислен «%s» игроку %s", name, sender["id"])
                self.notify(sender["id"], f"✅ Подарок «{name}» принят на хранение.\n"
                                          "Он уже в твоём инвентаре в Vloody — можно создавать розыгрыш.")
        self.state["seen"] = sorted(seen)
        return credited

    def process_withdrawals(self, owned):
        """Передаёт подарки по заявкам на вывод."""
        delivered = 0
        for item in self.api("/api/relay/withdrawals").get("items", []):
            gid, key = item.get("tg_gift_id"), str(item["gift_id"])
            g = owned.get(gid)
            if not g:
                self._fail(item, "подарка нет на аккаунте-хранителе", permanent=True)
                continue
            if g.get("can_be_transferred") is False:
                self._fail(item, "этот подарок нельзя передавать", permanent=True)
                continue
            if (g.get("next_transfer_date") or 0) > time.time():
                continue                                   # у Telegram пауза на передачу — ждём
            params = {"business_connection_id": self.state["connection_id"], "owned_gift_id": gid,
                      "new_owner_chat_id": item["telegram_id"]}
            if g.get("transfer_star_count"):
                params["star_count"] = g["transfer_star_count"]
            try:
                self.tg("transferGift", **params)
            except ApiError as e:
                if any(s.lower() in str(e).lower() for s in STARS_ERRORS):
                    log.error("На аккаунте-хранителе не хватает звёзд на передачу «%s» — пополни баланс",
                              item["name"])
                    continue                               # вина не игрока: не считаем попыткой
                self._fail(item, str(e))
                continue
            try:
                self.api("/api/relay/gift-delivered", {"gift_id": item["gift_id"]})
            except ApiError as e:
                # подарок уже ушёл; сервер узнает об этом при следующем проходе (подарка не будет в owned)
                log.error("Подарок %s передан, но сервер не подтвердил: %s", gid, e)
                self.state.setdefault("delivered_unconfirmed", []).append(item["gift_id"])
                continue
            delivered += 1
            self.state["attempts"].pop(key, None)
            if gid in self.state["seen"]:
                self.state["seen"].remove(gid)
            log.info("Передан «%s» игроку %s", item["name"], item["telegram_id"])
            self.notify(item["telegram_id"], f"🎁 Подарок «{item['name']}» отправлен тебе в Telegram.")
        self._confirm_pending()
        return delivered

    def _confirm_pending(self):
        pending = self.state.get("delivered_unconfirmed") or []
        for gift_id in list(pending):
            try:
                self.api("/api/relay/gift-delivered", {"gift_id": gift_id})
                pending.remove(gift_id)
            except ApiError as e:
                if "not found" in str(e).lower():
                    pending.remove(gift_id)
        self.state["delivered_unconfirmed"] = pending

    def _fail(self, item, reason, permanent=False):
        key = str(item["gift_id"])
        if key in [str(x) for x in self.state.get("delivered_unconfirmed") or []]:
            return                                         # подарок уже передан, ждём подтверждения сервера
        n = self.state["attempts"].get(key, 0) + 1
        self.state["attempts"][key] = n
        log.warning("Не удалось передать «%s» (попытка %s): %s", item["name"], n, reason)
        if not permanent and n < MAX_ATTEMPTS:
            return
        try:
            self.api("/api/relay/gift-failed", {"gift_id": item["gift_id"], "reason": reason[:200]})
            self.state["attempts"].pop(key, None)
            self.notify(item["telegram_id"],
                        f"⚠️ Не получилось отправить «{item['name']}»: {reason}.\n"
                        "Подарок вернулся в инвентарь, плата за передачу возвращена.")
        except ApiError as e:
            log.error("Сервер не принял отказ по подарку %s: %s", item["gift_id"], e)

    # ------------------------------------------------------------ цикл
    def sync(self):
        """Один проход: приём новых подарков и выдача по заявкам."""
        if not self.state["connection_id"]:
            return None
        owned = self.owned_gifts()
        result = (self.sync_deposits(owned), self.process_withdrawals(owned))
        self._save()
        return result

    def check_stars(self):
        try:
            bal = self.tg("getBusinessAccountStarBalance",
                          business_connection_id=self.state["connection_id"])
            log.info("Звёзд на аккаунте-хранителе: %s", bal.get("amount"))
        except ApiError as e:
            log.warning("Не удалось узнать баланс звёзд хранителя: %s", e)

    def run(self, sync_every=15):
        me = self.tg("getMe")
        log.info("Бот-хранитель @%s запущен, сервер %s", me.get("username"), self.backend)
        if not self.state["connection_id"]:
            log.warning("Бизнес-аккаунт ещё не подключён. Открой в Telegram: Настройки → "
                        "Telegram для бизнеса → Чат-боты → укажи @%s и выдай права на подарки.",
                        me.get("username"))
        else:
            self.check_stars()
        last = 0.0
        while True:
            try:
                fresh = self.poll_updates(timeout=min(20, sync_every))
                if fresh or time.time() - last >= sync_every:
                    self.sync()
                    last = time.time()
            except ApiError as e:
                log.error("Ошибка: %s", e)
                time.sleep(5)
            except KeyboardInterrupt:
                self._save()
                log.info("Остановлен")
                return


def main():
    from bot.envfile import load_env
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    token = os.getenv("RELAY_BOT_TOKEN", "").strip()
    secret = os.getenv("RELAY_SECRET", "").strip()
    if not token or not secret:
        raise SystemExit("Задайте RELAY_BOT_TOKEN (токен отдельного бота) и RELAY_SECRET")
    if token == os.getenv("BOT_TOKEN", "").strip():
        raise SystemExit("RELAY_BOT_TOKEN должен быть токеном ОТДЕЛЬНОГО бота: основной бот "
                         "получает оплату через вебхук и не может одновременно опрашиваться.")
    Relay(token, secret,
          backend=os.getenv("VLOODY_URL", "http://127.0.0.1:5000"),
          state_path=os.getenv("RELAY_STATE", "instance/relay_state.json"),
          api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org"),
          ).run(sync_every=int(os.getenv("RELAY_SYNC_SEC", "15")))


if __name__ == "__main__":
    main()

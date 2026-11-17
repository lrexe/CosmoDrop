"""Проверка бота-хранителя на ИМИТАЦИИ Telegram Bot API (настоящий Telegram не участвует)."""
import hashlib, hmac, json, logging, os, sys, tempfile, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RELAY_SECRET="relay-s", RATE_LIMIT="100000")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from werkzeug.serving import make_server                      # noqa: E402
from app import app                                            # noqa: E402
from models import db, User, GiftItem, Pool, PoolEntry, LedgerTx  # noqa: E402
from bot.relay import Relay                                    # noqa: E402

logging.basicConfig(level=logging.CRITICAL)
OWNER, ALICE, BOB = 990000200, 990000201, 990000202
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


# ------------------------------------------------------------ имитация Telegram
class FakeTG:
    def __init__(self):
        self.updates, self.gifts, self.transfers, self.messages = [], {}, [], []
        self.transfer_error = None

    def call(self, method, p):
        if method == "getMe":
            return {"username": "VloodyRelayBot"}
        if method == "getUpdates":
            out = [u for u in self.updates if u["update_id"] >= p.get("offset", 0)]
            return out
        if method == "getBusinessAccountGifts":
            assert p["business_connection_id"] == "conn-1"
            return {"total_count": len(self.gifts), "gifts": list(self.gifts.values()), "next_offset": ""}
        if method == "transferGift":
            if self.transfer_error:
                raise ValueError(self.transfer_error)
            self.transfers.append(p)
            self.gifts.pop(p["owned_gift_id"])
            return True
        if method == "sendMessage":
            self.messages.append((p["chat_id"], p["text"]))
            return {"message_id": 1}
        if method == "getBusinessAccountStarBalance":
            return {"amount": 500}
        raise ValueError("unknown method " + method)


fake = FakeTG()


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        try:
            res, code = {"ok": True, "result": fake.call(method, body)}, 200
        except ValueError as e:
            res, code = {"ok": False, "description": str(e)}, 400
        raw = json.dumps(res).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


tg_srv = HTTPServer(("127.0.0.1", 5078), H)
api_srv = make_server("127.0.0.1", 5077, app, threaded=True)
for s in (tg_srv, api_srv):
    threading.Thread(target=s.serve_forever, daemon=True).start()

state_file = os.path.join(tempfile.mkdtemp(), "relay_state.json")
relay = Relay("777:RELAY-TEST", "relay-s", backend="http://127.0.0.1:5077",
              state_path=state_file, api_base="http://127.0.0.1:5078")
T0 = relay.state["started_at"]


def unique(gid, sender, base, number, fee=25, date=None, **extra):
    g = {"type": "unique", "owned_gift_id": gid, "send_date": date or T0 + 5,
         "gift": {"base_name": base, "name": base.replace(" ", "") + "-" + str(number), "number": number},
         "can_be_transferred": True, "transfer_star_count": fee}
    if sender:
        g["sender_user"] = {"id": sender, "is_bot": False, "first_name": "U"}
    g.update(extra)
    return g


def hdr(tid, name):
    f = {"auth_date": str(int(time.time())), "user": json.dumps({"id": tid, "first_name": name, "username": name})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    sec = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(f)}


c = app.test_client()
A, B = hdr(ALICE, "alice"), hdr(BOB, "bob")
inv = lambda h: c.get("/api/inventory/gifts", headers=h).get_json()["gifts"]
bal = lambda h: c.get("/api/profile", headers=h).get_json()["balance"]

# ---------- 1. подключение бизнес-аккаунта
check("без подключённого аккаунта хранитель ничего не делает", relay.sync() is None)
fake.updates.append({"update_id": 1, "business_connection": {
    "id": "conn-1", "user": {"id": OWNER}, "is_enabled": True,
    "rights": {"can_view_gifts_and_stars": True, "can_transfer_and_upgrade_gifts": True, "can_transfer_stars": True}}})
relay.poll_updates(timeout=0)
check("подключение бизнес-аккаунта сохранено", relay.state["connection_id"] == "conn-1" and relay.state["owner_id"] == OWNER)

# ---------- 2. приём подарков
fake.gifts = {
    "old": unique("old", ALICE, "Toy Bear", 1, date=T0 - 86400),          # личный подарок владельца
    "anon": unique("anon", None, "Lol Pop", 2),                           # скрытый отправитель
    "self": unique("self", OWNER, "Loot Bag", 3),
    "plain": {"type": "regular", "owned_gift_id": "plain", "send_date": T0 + 5,
              "sender_user": {"id": ALICE}, "gift": {"id": "x"}},         # обычный, не NFT
    "g-pepe": unique("g-pepe", ALICE, "Plush Pepe", 1337, fee=25),
}
c.get("/api/profile", headers=A); c.get("/api/profile", headers=B)
res = relay.sync()
a_inv = inv(A)
check("NFT-подарок зачислен отправителю", res[0] == 1 and len(a_inv) == 1 and a_inv[0]["name"] == "Plush Pepe #1337", a_inv)
check("запомнена плата Telegram за передачу", a_inv[0]["transfer_fee"] == 25)
check("настоящая картинка подарка: image", a_inv[0]["image"] == "/gift-art/plushpepe-1337.jpg", a_inv[0].get("image"))
check("настоящая анимация подарка: anim", a_inv[0]["anim"] == "/gift-art/plushpepe-1337.json", a_inv[0].get("anim"))
check("игрок получил уведомление", any(m[0] == ALICE and "принят" in m[1] for m in fake.messages))
with app.app_context():
    n = GiftItem.query.filter(GiftItem.tg_gift_id.in_(["old", "anon", "self", "plain"])).count()
check("старые, анонимные, свои и обычные подарки не зачислены", n == 0, n)
res = relay.sync()
check("повторная сверка не создаёт дублей", res[0] == 0 and len(inv(A)) == 1)

relay2 = Relay("777:RELAY-TEST", "relay-s", backend="http://127.0.0.1:5077",
               state_path=state_file, api_base="http://127.0.0.1:5078")
check("состояние переживает перезапуск", relay2.state["connection_id"] == "conn-1" and "g-pepe" in relay2.state["seen"])

junk = unique("g-junk", ALICE, "Toy Bear", 5)
junk["gift"]["name"] = "../x"
nameless = unique("g-nameless", ALICE, "Lol Pop", 6)
del nameless["gift"]["name"]
fake.gifts["g-junk"], fake.gifts["g-nameless"] = junk, nameless
res = relay.sync()
by_name = {g["name"]: g for g in inv(A)}
check("подарок с мусорным gift.name зачислен без картинки",
      res[0] == 2 and by_name["Toy Bear #5"]["image"] is None and by_name["Toy Bear #5"]["anim"] is None, by_name.get("Toy Bear #5"))
check("подарок без gift.name зачислен без картинки", by_name["Lol Pop #6"]["image"] is None)
with app.app_context():
    check("в БД мусорный slug не сохранён",
          all(g.slug is None for g in GiftItem.query.filter(GiftItem.tg_gift_id.in_(["g-junk", "g-nameless"]))))

# ---------- 3. розыгрыш и выдача победителю
with app.app_context():
    for tid in (ALICE, BOB):
        User.query.filter_by(telegram_id=tid).first().stars_balance = 1000
    db.session.commit()
gift_id = a_inv[0]["id"]
pool = c.post("/api/pools", headers=A, json={"mode": "wheel", "gift_id": gift_id, "min_stake": 5, "duration_min": 15}).get_json()
check("раунд отдаёт image/anim подарка", pool.get("image") == "/gift-art/plushpepe-1337.jpg"
      and pool.get("anim") == "/gift-art/plushpepe-1337.json", (pool.get("image"), pool.get("anim")))
c.post(f"/api/pools/{pool['id']}/stake", headers=B, json={"amount": 100})
with app.app_context():
    db.session.get(Pool, pool["id"]).ends_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
done = c.get(f"/api/pools/{pool['id']}", headers=B).get_json()
check("раунд разыгран, подарок у победителя", done["winner"]["is_me"] and inv(B)[0]["id"] == gift_id)

with app.app_context():
    User.query.filter_by(telegram_id=BOB).first().stars_balance = 10
    db.session.commit()
r = c.post(f"/api/inventory/gifts/{gift_id}/withdraw", headers=B)
check("вывод без звёзд на плату Telegram -> отказ", r.status_code == 400, r.status_code)
with app.app_context():
    User.query.filter_by(telegram_id=BOB).first().stars_balance = 900
    db.session.commit()
r = c.post(f"/api/inventory/gifts/{gift_id}/withdraw", headers=B).get_json()
check("плата за передачу списана с игрока, не с платформы", r["fee"] == 25 and bal(B) == 875, r)

fake.gifts["g-pepe"]["next_transfer_date"] = int(time.time()) + 3600
res = relay.sync()
check("пока у Telegram пауза на передачу — ждём", res[1] == 0 and not fake.transfers and inv(B)[0]["status"] == "withdraw_requested")
fake.gifts["g-pepe"].pop("next_transfer_date")
res = relay.sync()
t = fake.transfers[-1] if fake.transfers else {}
check("подарок передан победителю в Telegram",
      res[1] == 1 and t.get("new_owner_chat_id") == BOB and t.get("owned_gift_id") == "g-pepe" and t.get("star_count") == 25, t)
check("сервер пометил подарок выданным", inv(B) == [])
check("победитель получил уведомление", any(m[0] == BOB and "отправлен" in m[1] for m in fake.messages))
res = relay.sync()
check("повторно подарок не передаётся", len(fake.transfers) == 1)

# ---------- 4. сбои
fake.gifts["g-eye"] = unique("g-eye", ALICE, "Evil Eye", 88, fee=30)
relay.sync()
eye = next(g for g in inv(A) if g["name"] == "Evil Eye #88")
a0 = bal(A)
c.post(f"/api/inventory/gifts/{eye['id']}/withdraw", headers=A)
fake.transfer_error = "Bad Request: BALANCE_TOO_LOW"
for _ in range(7):
    relay.sync()
st = next(g for g in inv(A) if g["id"] == eye["id"])["status"]
check("нет звёзд у хранителя: заявка ждёт, игрок не наказан", st == "withdraw_requested" and bal(A) == a0 - 30, st)

fake.transfer_error = "Bad Request: USER_PRIVACY_RESTRICTED"
for _ in range(4):
    relay.sync()
st = next(g for g in inv(A) if g["id"] == eye["id"])["status"]
check("после 4 неудач заявка ещё в работе", st == "withdraw_requested", st)
relay.sync()
st = next(g for g in inv(A) if g["id"] == eye["id"])["status"]
check("после 5 неудач подарок вернулся в инвентарь", st == "held", st)
check("плата за передачу возвращена игроку", bal(A) == a0, (bal(A), a0))
check("игрок уведомлён о неудаче", any(m[0] == ALICE and "Не получилось" in m[1] for m in fake.messages))

fake.transfer_error = None
c.post(f"/api/inventory/gifts/{eye['id']}/withdraw", headers=A)
del fake.gifts["g-eye"]                                    # подарок пропал с аккаунта-хранителя
relay.sync()
st = next(g for g in inv(A) if g["id"] == eye["id"])["status"]
check("подарка нет у хранителя: заявка отклонена с возвратом", st == "held" and bal(A) == a0, st)

# ---------- 5. отключение
fake.updates.append({"update_id": 2, "business_connection": {"id": "conn-1", "user": {"id": OWNER}, "is_enabled": False}})
relay.poll_updates(timeout=0)
check("после отключения бизнес-аккаунта хранитель останавливается", relay.sync() is None)

r = c.post("/api/relay/gift-failed", json={"gift_id": eye["id"]})
check("служебный API без секрета -> 403", r.status_code == 403, r.status_code)

# ---------- уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_([ALICE, BOB])).all()
    uids = [u.id for u in users]
    pids = [p.id for p in Pool.query.filter(Pool.organizer_id.in_(uids)).all()]
    PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).delete(synchronize_session=False)
    Pool.query.filter(Pool.id.in_(pids)).delete(synchronize_session=False)
    GiftItem.query.filter(GiftItem.owner_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.title.like(f"%#{pool['id']}")).delete(synchronize_session=False)  # noqa: E711
    LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.kind == "gift_fee").delete(synchronize_session=False)  # noqa: E711
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()
tg_srv.shutdown(); api_srv.shutdown()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

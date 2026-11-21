"""Проверка подключения основного бота на ИМИТАЦИИ Telegram Bot API."""
import contextlib, hashlib, hmac, io, json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="", RATE_LIMIT="100000",
                  TELEGRAM_WEBHOOK_SECRET="hook-s", PUBLIC_URL="https://vloody.example.com",
                  TELEGRAM_API_BASE="http://127.0.0.1:5081")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
import bot.vloody as V                                         # noqa: E402
import bot.setup_main as SM                                    # noqa: E402
from models import db, User                                    # noqa: E402

ok = True
calls = []


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        calls.append((method, body))
        result = {"getMe": {"username": "VloodyGamesBot", "first_name": "Vloody"},
                  "getWebhookInfo": {"url": "", "pending_update_count": 0}}.get(method, True)
        raw = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 5081), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def run(argv):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            SM.main(argv)
        return 0, out.getvalue()
    except SystemExit as e:
        return 1, str(e)


# ---------- скрипт подключения
env_path = os.path.join(tempfile.mkdtemp(), ".env")
open(env_path, "w", encoding="utf-8").write("# комментарий\nRELAY_BOT_TOKEN=777:RELAY\nPUBLIC_URL=https://old.example.com\n")
SM.ENV_PATH = env_path
# SM.main() подгружает настоящий .env разработчика (load_env с setdefault) и тогда не создаёт
# секреты, которые там уже есть, — тест зависел от содержимого чужого .env. Изолируем его.
SM.load_env = lambda *a, **k: True
saved ={k: os.environ.pop(k) for k in ("SECRET_KEY", "TELEGRAM_WEBHOOK_SECRET") if k in os.environ}
os.environ.pop("ADMIN_SECRET", None)

code, msg = run(["http://vloody.example.com"])
check("адрес без https отклонён, Telegram не тронут", code == 1 and "https" in msg and not calls, msg)
code, msg = run(["https://vloody.example.com/"])
check("подключение прошло", code == 0 and "@VloodyGamesBot" in msg, msg[:80])
by = {m: b for m, b in calls}
env = dict(l.split("=", 1) for l in open(env_path, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
check("вебхук поставлен на адрес оплаты с секретом",
      by["setWebhook"]["url"] == "https://vloody.example.com/api/telegram_payment"
      and by["setWebhook"]["secret_token"] == env["TELEGRAM_WEBHOOK_SECRET"] and len(env["TELEGRAM_WEBHOOK_SECRET"]) > 30)
check("вебхук получает события о правах бота в каналах",
      by["setWebhook"]["allowed_updates"] == ["message", "pre_checkout_query", "my_chat_member"],
      by["setWebhook"].get("allowed_updates"))
check("кнопка меню открывает Mini App",
      by["setChatMenuButton"]["menu_button"] == {"type": "web_app", "text": "Vloody", "web_app": {"url": "https://vloody.example.com/"}})
check(".env: секреты созданы, адрес обновлён, чужие строки целы",
      all(len(env.get(k, "")) > 30 for k in ("SECRET_KEY", "ADMIN_SECRET")) and env["PUBLIC_URL"] == "https://vloody.example.com"
      and env["RELAY_BOT_TOKEN"] == "777:RELAY" and env["BOT_USERNAME"] == "VloodyGamesBot"
      and open(env_path, encoding="utf-8").read().startswith("# комментарий"))
check("секреты не выводятся на экран", env["ADMIN_SECRET"] not in msg and env["SECRET_KEY"] not in msg)
before = dict(env)
run(["https://vloody2.example.com"])
env = dict(l.split("=", 1) for l in open(env_path, encoding="utf-8").read().splitlines() if "=" in l and not l.startswith("#"))
check("повторный запуск не меняет секреты, только адрес",
      all(env[k] == before[k] for k in ("SECRET_KEY", "ADMIN_SECRET", "TELEGRAM_WEBHOOK_SECRET")) and env["PUBLIC_URL"] == "https://vloody2.example.com")
os.environ["RELAY_BOT_TOKEN"] = os.environ["BOT_TOKEN"]
code, msg = run(["https://vloody.example.com"])
check("один токен на оба бота отклонён", code == 1 and "отдельным" in msg, msg)
os.environ["RELAY_BOT_TOKEN"] = "777:RELAY"
os.environ.update(saved)

os.environ["PUBLIC_URL"] = "https://vloody.example.com"   # скрипт подключения менял адрес в окружении

# ---------- /start через вебхук
sent = []
V.tg_api = lambda method, payload, **kw: sent.append((method, payload)) or {"ok": True, "result": True}
c = app.test_client()
HOOK = {"X-Telegram-Bot-Api-Secret-Token": "hook-s"}
start = lambda text, chat="private": {"message": {"text": text, "chat": {"id": 555, "type": chat}, "from": {"id": 555}}}

r = c.post("/api/telegram_payment", json=start("/start"))
check("вебхук без секрета Telegram -> 403", r.status_code == 403 and not sent, r.status_code)
c.post("/api/telegram_payment", headers=HOOK, json=start("/start"))
m, p = sent[-1]
btn = p["reply_markup"]["inline_keyboard"][0][0]
check("/start: приветствие с кнопкой Mini App", m == "sendMessage" and p["chat_id"] == 555 and "Vloody" in p["text"]
      and btn["web_app"]["url"] == "https://vloody.example.com/", btn)
c.post("/api/telegram_payment", headers=HOOK, json=start("/start CDABC12"))
check("/start с кодом: код передаётся в приложение",
      sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://vloody.example.com/?startapp=CDABC12")
check("/start с реферальным кодом — обычное приветствие",
      "Добро пожаловать" in sent[-1][1]["text"]
      and sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "🎡 Открыть Vloody", sent[-1][1])
c.post("/api/telegram_payment", headers=HOOK, json=start("/start pool_42"))
m, p = sent[-1]
btn = p["reply_markup"]["inline_keyboard"][0][0]
check("/start pool_42 (кнопка из канала): ответ про раунд и кнопка «Открыть раунд»",
      m == "sendMessage" and "Открой раунд по кнопке ниже" in p["text"] and btn["text"] == "🎯 Открыть раунд"
      and btn["web_app"]["url"] == "https://vloody.example.com/?startapp=pool_42", p)
os.environ["PUBLIC_URL"] = ""
n = len(sent)
r = c.post("/api/telegram_payment", headers=HOOK, json=start("/start pool_42"))
os.environ["PUBLIC_URL"] = "https://vloody.example.com"
check("без PUBLIC_URL бот не молчит: «временно недоступно», без кнопки Mini App",
      len(sent) == n + 1 and sent[-1][0] == "sendMessage" and "временно недоступно" in sent[-1][1]["text"]
      and "reply_markup" not in sent[-1][1], sent[n:])
c.post("/api/telegram_payment", headers=HOOK, json=start('/start x&admin=1"><script>'))
check("подозрительный параметр отброшен",
      sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://vloody.example.com/")
c.post("/api/telegram_payment", headers=HOOK, json=start("/help"))
check("/help и /fair отвечают справкой с кнопкой приложения",
      "VLD" in sent[-1][1]["text"] and sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["web_app"])
c.post("/api/telegram_payment", headers=HOOK, json=start("/fair"))
check("/fair объясняет честность", "хэш" in sent[-1][1]["text"])
import bot.relay_texts as RT
check("бот-хранитель: тексты для новичков называют аккаунт и шаги",
      "@keeper" in RT.reply_for("start", "keeper") and "инвентаре" in RT.reply_for("deposit", "keeper")
      and RT.reply_for("nope", "keeper") is None and len(RT.reply_for("help", None)) > 800)
n = len(sent)
c.post("/api/telegram_payment", headers=HOOK, json=start("/start", chat="group"))
c.post("/api/telegram_payment", headers=HOOK, json=start("привет"))
check("в группах и на обычный текст бот не отвечает", len(sent) == n)

# ---------- вход из Telegram и реферальный код
def hdr(tid, name):
    f = {"auth_date": str(int(time.time())), "user": json.dumps({"id": tid, "first_name": name, "username": name})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    sec = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(f)}


check("главная страница открывается без подписи", c.get("/").status_code == 200)
check("в боевом режиме браузер без Telegram не получает данные", c.get("/api/profile").status_code == 401)
A, B = hdr(990000501, "main_a"), hdr(990000502, "main_b")
pa = c.get("/api/profile", headers=A).get_json()
check("из Telegram — свой аккаунт, не демо", pa["telegram_id"] == 990000501 and pa["demo"] is False and pa["balance"] == 0, pa.get("telegram_id"))
c.get("/api/profile", headers=B)
r = c.post("/api/referral/bind", headers=B, json={"code": pa["referral"]["code"]}).get_json()
check("реферальный код из ссылки привязывает друга",
      r["bound"] and c.get("/api/profile", headers=A).get_json()["referral"]["invited"] == 1, r)
r = c.post("/api/referral/bind", headers=A, json={"code": pa["referral"]["code"]}).get_json()
check("свой код привязать нельзя", r["bound"] is False)
check("демо-пополнение в боевом режиме идёт через счёт, а не начисляет",
      c.get("/api/profile", headers=A).get_json()["balance"] == 0)

with app.app_context():
    User.query.filter(User.telegram_id.in_([990000501, 990000502])).delete(synchronize_session=False)
    db.session.commit()

# ---------- бот публикует раунды в канале
from datetime import datetime, timedelta                       # noqa: E402
from models import Channel, GiftItem, Pool, PoolEntry, LedgerTx  # noqa: E402

TIDS = [990000950, 990000951, 990000952]
CH, CH2 = -1009900009500, -1009900009501


def wipe():
    with app.app_context():
        ids = [u.id for u in User.query.filter(User.telegram_id.in_(TIDS)).all()]
        if ids:
            pools = Pool.query.filter(Pool.organizer_id.in_(ids)).all()
            refs = [V.pool_ref(p, w) for p in pools for w in ("fee", "commission")]
            PoolEntry.query.filter(PoolEntry.pool_id.in_([p.id for p in pools] or [0])).delete(synchronize_session=False)
            PoolEntry.query.filter(PoolEntry.user_id.in_(ids)).delete(synchronize_session=False)
            for p in pools:
                db.session.delete(p)
            db.session.flush()
            if refs:
                LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_(refs)).delete(synchronize_session=False)  # noqa: E711
            LedgerTx.query.filter(LedgerTx.user_id.in_(ids)).delete(synchronize_session=False)
            GiftItem.query.filter(GiftItem.owner_id.in_(ids)).delete(synchronize_session=False)
        Channel.query.filter(Channel.chat_id.in_([CH, CH2, -1009900009502])).delete(synchronize_session=False)
        User.query.filter(User.telegram_id.in_(TIDS)).delete(synchronize_session=False)
        db.session.commit()


wipe()
os.environ["BOT_USERNAME"] = "Cosmos67Drop_Bot"
member_status, tg_down = {}, [False]


def fake_tg(method, payload, **kw):
    sent.append((method, payload))
    if method == "getChatMember":
        return {"ok": True, "result": {"status": member_status.get(payload["user_id"], "member")}}
    if tg_down[0]:
        raise RuntimeError("telegram down")
    return {"ok": True, "result": {"message_id": 1}}


V.tg_api = fake_tg
OA, OB, OC = hdr(990000950, "chan_a"), hdr(990000951, "chan_b"), hdr(990000952, "chan_c")
for h in (OA, OB, OC):
    c.get("/api/profile", headers=h)


def mcm(chat_id, status, by=990000950, chat_type="channel", **rights):
    return {"my_chat_member": {"chat": {"id": chat_id, "type": chat_type, "title": "Канал Vloody",
                                        "username": "vloody_test_ch"},
                               "from": {"id": by}, "date": 0,
                               "old_chat_member": {"status": "left", "user": {"id": 1, "is_bot": True}},
                               "new_chat_member": {"status": status, "user": {"id": 1, "is_bot": True}, **rights}}}


c.post("/api/telegram_payment", headers=HOOK, json=mcm(CH, "administrator", can_post_messages=True))
with app.app_context():
    ch = Channel.query.filter_by(chat_id=CH).first()
    check("бота сделали админом канала -> канал записан активным",
          ch is not None and ch.active and ch.added_by_tg == 990000950 and ch.owner_id is None
          and ch.title == "Канал Vloody" and ch.username == "vloody_test_ch", ch and ch.active)
    ch_id = ch.id if ch else 0
c.post("/api/telegram_payment", headers=HOOK, json=mcm(-1009900009502, "administrator", chat_type="group"))
with app.app_context():
    check("группы (не каналы) не записываются", Channel.query.filter_by(chat_id=-1009900009502).first() is None)

r = c.get("/api/channels", headers=OA).get_json()
check("GET /api/channels: канал ещё не привязан, но предложен добавившему",
      r["items"] == [] and [x["chat_id"] for x in r["pending"]] == [CH], r)
check("чужому пользователю канал не предлагается", c.get("/api/channels", headers=OB).get_json()["pending"] == [])

member_status[990000951] = "member"
r = c.post("/api/channels/link", headers=OB, json={"chat_id": CH})
check("привязать канал не-админ не может -> 403", r.status_code == 403, r.status_code)
r = c.post("/api/channels/link", headers=OA, json={"chat_id": -1009900009999})
check("неизвестный канал -> 404", r.status_code == 404, r.status_code)
member_status[990000950] = "creator"
r = c.post("/api/channels/link", headers=OA, json={"chat_id": CH})
j = r.get_json()
check("создатель канала привязывает его -> 200",
      r.status_code == 200 and j["channel"]["chat_id"] == CH and j["channel"]["active"] is True
      and set(j["channel"]) >= {"id", "chat_id", "title", "username", "active"}, j)
check("проверка прав ушла в Telegram с моим id",
      any(m == "getChatMember" and p["chat_id"] == CH and p["user_id"] == 990000950 for m, p in sent))
r = c.get("/api/channels", headers=OA).get_json()
check("канал виден в моём списке, из «ожидающих» ушёл",
      [x["id"] for x in r["items"]] == [ch_id] and r["pending"] == [], r)
check("в чужом списке канала нет", c.get("/api/channels", headers=OB).get_json()["items"] == [])

with app.app_context():
    ua, ub, uc = (User.query.filter_by(telegram_id=t).first() for t in TIDS)
    ua.vdt_balance, ub.stars_balance, uc.stars_balance = 1000, 500, 500
    gifts = []
    for owner, slug in ((ua, "plushpepe-1337"), (ua, None), (ua, None), (ub, None)):
        g = GiftItem(owner_id=owner.id, name="Plush Pepe #1337", emoji="🐸", slug=slug, status="held")
        db.session.add(g)
        gifts.append(g)
    db.session.commit()
    g_slug, g_plain, g_plain2, g_b = (g.id for g in gifts)

new_pool = lambda h, gid, **kw: c.post("/api/pools", headers=h, json={"mode": "wheel", "currency": "VLD", "min_stake": 5,
                                                                      "gift_id": gid, "duration_min": 15, **kw})
r = new_pool(OB, g_b, channel_id=ch_id)
check("чужой канал в раунде -> 400", r.status_code == 400 and "Канал не найден" in r.get_json()["error"], r.get_json())
r = new_pool(OA, g_slug, channel_id=999999999)
check("несуществующий канал -> 400", r.status_code == 400 and "бот в нём не админ" in r.get_json()["error"])

n = len(sent)
r = new_pool(OA, g_slug, channel_id=ch_id)
p1 = r.get_json()
posts = [(m, p) for m, p in sent[n:] if m in ("sendMessage", "sendPhoto")]
m, p = posts[-1] if posts else (None, {})
btn = (p.get("reply_markup") or {}).get("inline_keyboard", [[{}]])[0][0]
body = p.get("caption") or p.get("text") or ""
check("раунд с каналом -> пост с картинкой подарка и кнопкой участия",
      r.status_code == 200 and len(posts) == 1 and m == "sendPhoto" and p["chat_id"] == CH
      and p["photo"] == "https://vloody.example.com/gift-art/plushpepe-1337.jpg"
      and btn.get("text") == "🎯 Участвовать"
      and btn.get("url") == f"https://t.me/Cosmos67Drop_Bot?start=pool_{p1['id']}", (m, p))
check("в посте: подарок, режим, валюта, ставка, срок; без разметки",
      "Plush Pepe #1337" in body and "Колесо" in body and "5 VLD" in body and "UTC" in body
      and "parse_mode" not in p, body)

n = len(sent)
tg_down[0] = True
r = new_pool(OA, g_plain, channel_id=ch_id)
tg_down[0] = False
p2 = r.get_json()
with app.app_context():
    check("Telegram недоступен -> раунд всё равно создан", r.status_code == 200
          and db.session.get(Pool, p2["id"]).status == "live", r.status_code)
check("без картинки — обычное сообщение", any(m == "sendMessage" and q["chat_id"] == CH for m, q in sent[n:]))

# ставки двух игроков в первом раунде, затем время выходит -> итог в канале
c.post(f"/api/pools/{p1['id']}/stake", headers=OB, json={"amount": 10})
c.post(f"/api/pools/{p1['id']}/stake", headers=OC, json={"amount": 15})
with app.app_context():
    for pid in (p1["id"], p2["id"]):
        db.session.get(Pool, pid).ends_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
n = len(sent)
c.get("/api/pools", headers=OA)
results = [q for m, q in sent[n:] if m == "sendMessage" and q["chat_id"] == CH]
with app.app_context():
    fin = db.session.get(Pool, p1["id"])
    wname = V.display_name(fin.winner)
won = [q["text"] for q in results if "Победитель" in q["text"]]
check("раунд завершён -> в канале итог: победитель и банк",
      fin.status == "finished" and len(won) == 1 and wname in won[0] and "25 VLD" in won[0], [q["text"] for q in results])
check("раунд без игроков -> в канале «Раунд отменён — ставки возвращены»",
      sum("Раунд отменён — ставки возвращены" in q["text"] for q in results) == 1, len(results))
n = len(sent)
c.get("/api/pools", headers=OA)
check("итог публикуется один раз", not [1 for m, q in sent[n:] if q.get("chat_id") == CH])

# ошибка Telegram при публикации итога не ломает расчёт
r = new_pool(OA, g_plain2, channel_id=ch_id)
p3 = r.get_json()
with app.app_context():
    db.session.get(Pool, p3["id"]).ends_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
tg_down[0] = True
r = c.get("/api/pools", headers=OA)
tg_down[0] = False
with app.app_context():
    check("Telegram упал при итоге -> раунд всё равно отменён и сохранён",
          r.status_code == 200 and db.session.get(Pool, p3["id"]).status == "cancelled")

# бота убрали из канала -> канал неактивен, раунд в него не создать
c.post("/api/telegram_payment", headers=HOOK, json=mcm(CH, "left"))
with app.app_context():
    check("бота убрали -> канал неактивен", Channel.query.filter_by(chat_id=CH).first().active is False)
    gx = GiftItem(owner_id=db.session.get(Pool, p3["id"]).organizer_id, name="X", emoji="🎁", status="held")
    db.session.add(gx)
    db.session.commit()
    gx_id = gx.id
r = new_pool(OA, gx_id, channel_id=ch_id)
check("неактивный канал -> 400", r.status_code == 400 and "Канал не найден" in r.get_json()["error"])
r = c.post("/api/channels/link", headers=OA, json={"chat_id": CH})
check("неактивный канал не привязать -> 404", r.status_code == 404, r.status_code)

# бот снова админ (добавил другой человек) — перепривязать может только проверенный админ
c.post("/api/telegram_payment", headers=HOOK, json=mcm(CH, "administrator", by=990000951, can_post_messages=True))
member_status[990000951] = "administrator"
r = c.post("/api/channels/link", headers=OB, json={"chat_id": CH})
check("канал переходит к последнему проверенному админу",
      r.status_code == 200 and c.get("/api/channels", headers=OA).get_json()["items"] == []
      and [x["chat_id"] for x in c.get("/api/channels", headers=OB).get_json()["items"]] == [CH])
c.post("/api/telegram_payment", headers=HOOK, json=mcm(CH, "administrator", can_post_messages=False))
with app.app_context():
    check("бот админ без права публикации -> канал неактивен", Channel.query.filter_by(chat_id=CH).first().active is False)
wipe()
srv.shutdown()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

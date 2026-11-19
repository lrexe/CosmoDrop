"""Сквозная проверка Vloody в боевом режиме: эскроу, три режима, выплаты, сходимость денег."""
import hashlib, hmac, json, os, sys, time
from datetime import datetime, timedelta
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:TEST-TOKEN-not-real", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RELAY_SECRET="relay-s", ADMIN_SECRET="admin-s", RATE_LIMIT="100000")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, GiftItem, Pool, PoolEntry, LedgerTx, PayoutRequest  # noqa: E402
from bot.vloody import pool_ref, payout_ref                  # noqa: E402

IDS = {"org": 990000101, "bob": 990000102, "cat": 990000103, "dan": 990000104}
START = 10000
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail if not cond or detail != "" else "")


def hdr(who):
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": IDS[who], "first_name": who.title(), "username": who})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


c = app.test_client()
get = lambda who, url: c.get(url, headers=hdr(who))
post = lambda who, url, body=None: c.post(url, headers=hdr(who), json=body or {})
RELAY = {"X-Relay-Secret": "relay-s"}
ADMIN = {"X-Admin-Secret": "admin-s"}


def bal(who):
    return get(who, "/api/profile").get_json()["balance"]


def expire(pool_id):
    with app.app_context():
        p = db.session.get(Pool, pool_id)
        p.ends_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()


def deposit_gift(who, name, tg_id, slug=None):
    body = {"telegram_id": IDS[who], "name": name, "emoji": "🐸", "tg_gift_id": tg_id}
    if slug:
        body["slug"] = slug
    r = c.post("/api/relay/gift-deposit", headers=RELAY, json=body)
    return r.get_json()["gift"]["id"]


# ---------- подготовка
for who in IDS:
    get(who, "/api/profile")
with app.app_context():
    for tid in IDS.values():
        User.query.filter_by(telegram_id=tid).first().stars_balance = START
    User.query.filter_by(telegram_id=IDS["org"]).first().vdt_balance = 1000   # сбор 0.1 VDT за каждый раунд
    cat = User.query.filter_by(telegram_id=IDS["cat"]).first()
    cat.referred_by = IDS["dan"]                         # dan пригласил cat
    db.session.commit()
    rev0 = db.session.query(db.func.coalesce(db.func.sum(LedgerTx.amount), 0)).filter(
        LedgerTx.user_id == None, LedgerTx.currency == "VLD").scalar()   # noqa: E711

# ---------- эскроу
r = post("org", "/api/pools", {"mode": "wheel", "gift_id": 999999, "min_stake": 5, "duration_min": 15})
check("раунд без подарка в эскроу -> отказ", r.status_code == 400, r.status_code)
r = c.post("/api/relay/gift-deposit", json={"telegram_id": IDS["org"], "name": "X", "tg_gift_id": "g0"})
check("зачисление подарка без секрета хранителя -> 403", r.status_code == 403, r.status_code)
r = post("org", "/api/demo/gift")
check("демо-подарок в боевом режиме -> 403", r.status_code == 403, r.status_code)

g1 = deposit_gift("org", "Plush Pepe #1", "tg-g1")
r = c.post("/api/relay/gift-deposit", headers=RELAY,
           json={"telegram_id": IDS["org"], "name": "Plush Pepe #1", "tg_gift_id": "tg-g1"})
check("повторное зачисление того же подарка -> duplicate", r.get_json().get("status") == "duplicate")
r = post("bob", "/api/pools", {"mode": "wheel", "gift_id": g1, "min_stake": 5, "duration_min": 15})
check("раунд с чужим подарком -> отказ", r.status_code == 400, r.status_code)

# ---------- колесо
r = post("org", "/api/pools", {"mode": "wheel", "gift_id": g1, "min_stake": 5, "duration_min": 15})
wheel = r.get_json()
check("колесо создано из подарка в эскроу", r.status_code == 200 and wheel["status"] == "live")
r = post("org", "/api/pools", {"mode": "wheel", "gift_id": g1, "min_stake": 5, "duration_min": 15})
check("один подарок нельзя разыграть дважды", r.status_code == 400, r.status_code)
r = post("org", f"/api/inventory/gifts/{g1}/withdraw")
check("подарок в раунде нельзя вывести", r.status_code == 400, r.status_code)
r = post("org", f"/api/pools/{wheel['id']}/stake", {"amount": 100})
check("организатор не может ставить в своём раунде", r.status_code == 400, r.status_code)
r = post("bob", f"/api/pools/{wheel['id']}/stake", {"amount": 3})
check("ставка ниже минимума -> отказ", r.status_code == 400, r.status_code)
r = post("bob", f"/api/pools/{wheel['id']}/stake", {"amount": START + 1})
check("ставка больше баланса -> отказ", r.status_code == 400, r.status_code)
post("bob", f"/api/pools/{wheel['id']}/stake", {"amount": 300})
post("cat", f"/api/pools/{wheel['id']}/stake", {"amount": 700})
r = post("org", f"/api/pools/{wheel['id']}/cancel")
check("отмена раунда со ставками -> отказ", r.status_code == 400, r.status_code)
live = get("bob", f"/api/pools/{wheel['id']}").get_json()
check("seed скрыт до завершения", "seed" not in live["fair"] and live["fair"]["seed_hash"])
check("шанс = доля в банке", live["my_chance"] == 30.0, live["my_chance"])

expire(wheel["id"])
done = get("bob", f"/api/pools/{wheel['id']}").get_json()
check("колесо завершилось по таймеру", done["status"] == "finished" and done["winner"])
f = done["fair"]
check("seed соответствует опубликованному хешу",
      hashlib.sha256(bytes.fromhex(f["seed"])).hexdigest() == f["seed_hash"])
ticket = int(hmac.new(bytes.fromhex(f["seed"]), f"{wheel['id']}:1000:2".encode(), hashlib.sha256).hexdigest(), 16) % 1000
exp_winner = "@bob" if ticket < 300 else "@cat"
check("победителя можно пересчитать по seed", f["result"]["ticket"] == ticket and done["winner"]["name"] == exp_winner,
      (ticket, done["winner"]["name"]))
check("организатор получил 95.5% банка (комиссия 4.5%)", bal("org") == START + 955, bal("org"))
check("реферер получил 1% ставок друга из комиссии", bal("dan") == START + 7, bal("dan"))
win_who = "bob" if exp_winner == "@bob" else "cat"
gifts = get(win_who, "/api/inventory/gifts").get_json()["gifts"]
check("подарок в инвентаре победителя", any(g["id"] == g1 and g["status"] == "held" and g["source"] == "win" for g in gifts))
check("у организатора подарка больше нет", not get("org", "/api/inventory/gifts").get_json()["gifts"])
r = post("bob", f"/api/pools/{wheel['id']}/stake", {"amount": 50})
check("ставка в завершённый раунд -> отказ", r.status_code == 400, r.status_code)

# ---------- отмена пустого раунда
g2 = deposit_gift("org", "Evil Eye #2", "tg-g2")
p = post("org", "/api/pools", {"mode": "wheel", "gift_id": g2, "min_stake": 5, "duration_min": 15}).get_json()
expire(p["id"])
st = get("org", f"/api/pools/{p['id']}").get_json()["status"]
g = get("org", "/api/inventory/gifts").get_json()["gifts"][0]
check("раунд без ставок отменён, подарок вернулся", st == "cancelled" and g["status"] == "held", (st, g))

# ---------- сейф
r = post("org", "/api/pools", {"mode": "vault", "gift_id": g2, "min_stake": 10, "vault_max": 25})
vault = r.get_json()
check("сейф создан, число не раскрыто", r.status_code == 200 and "secret" not in vault and "secret" not in json.dumps(vault["fair"]))
b0 = bal("bob")
post("bob", f"/api/pools/{vault['id']}/vault", {"number": 1})
r = post("cat", f"/api/pools/{vault['id']}/vault", {"number": 1})
first_hit = get("bob", f"/api/pools/{vault['id']}").get_json()["status"] == "finished"
if not first_hit:
    check("занятое число нельзя взять повторно", r.status_code == 400, r.status_code)
tries, res = 1, None
for n in range(2, 26):
    if get("bob", f"/api/pools/{vault['id']}").get_json()["status"] != "live":
        break
    res = post("bob", f"/api/pools/{vault['id']}/vault", {"number": n}).get_json()
    tries += 1
    if res.get("hit"):
        break
v = get("cat", f"/api/pools/{vault['id']}").get_json()
check("сейф вскрыт, раунд завершён", v["status"] == "finished" and v["winner"]["name"] == "@bob", v["status"])
check("хеш сейфа совпадает с раскрытым числом",
      hashlib.sha256(f"{v['secret']}:{v['fair']['seed']}".encode()).hexdigest() == v["fair"]["seed_hash"])
check("с игрока списано ровно попытки × ставка", b0 - bal("bob") == tries * 10, (b0 - bal("bob"), tries))

# ---------- аукцион
g3 = deposit_gift("org", "Jelly Rabbit #3", "tg-g3", slug="jellybunny-42")
auc = post("org", "/api/pools", {"mode": "auction", "gift_id": g3, "min_stake": 20, "duration_min": 15}).get_json()
post("bob", f"/api/pools/{auc['id']}/bid", {"amount": 200})
post("cat", f"/api/pools/{auc['id']}/bid", {"amount": 150})
post("cat", f"/api/pools/{auc['id']}/bid", {"amount": 50})          # cat догнал bob: 200 = 200, но позже
seen = get("dan", f"/api/pools/{auc['id']}").get_json()
check("аукцион слепой: банк и ставки скрыты", seen["bank"] is None and seen["participants"] is None and "bids" not in seen)
check("игрок видит только свою ставку", get("cat", f"/api/pools/{auc['id']}").get_json()["my_total"] == 200)
expire(auc["id"])
a = get("dan", f"/api/pools/{auc['id']}").get_json()
check("при равенстве побеждает достигший суммы раньше", a["winner"]["name"] == "@bob", a["winner"])
check("после раскрытия видны все ставки", a["bank"] == 400 and len(a["bids"]) == 2)

# ---------- лента победителей: настоящая картинка подарка
wins = {w["pool_id"]: w for w in get("dan", "/api/winners").get_json()["items"]}
wa, ww = wins.get(auc["id"], {}), wins.get(wheel["id"], {})
check("победители: у подарка со slug есть картинка и анимация",
      wa.get("image") == "/gift-art/jellybunny-42.jpg" and wa.get("anim") == "/gift-art/jellybunny-42.json", wa)
check("победители: у подарка без slug image = None", "image" in ww and ww["image"] is None and ww.get("anim") is None, ww)
check("победители: прежние ключи на месте",
      all(k in wa for k in ("pool_id", "title", "emoji", "winner", "ts", "bank")) and wa.get("title") == "Jelly Rabbit #3", wa)

# ---------- перевод
b_b, b_d = bal("bob"), bal("dan")
r = post("bob", "/api/transfer", {"to_telegram_id": IDS["dan"], "amount": 100})
check("перевод ниже минимума -> отказ", r.status_code == 400, r.status_code)
r = post("bob", "/api/transfer", {"to_telegram_id": IDS["bob"], "amount": 200})
check("перевод самому себе -> отказ", r.status_code == 400, r.status_code)
r = post("bob", "/api/transfer", {"to_telegram_id": IDS["dan"], "amount": 200})
check("перевод: списано 200, получено 180", bal("bob") == b_b - 200 and bal("dan") == b_d + 180, r.get_json())

# ---------- вывод
b_c = bal("cat")
r = post("cat", "/api/payout", {"amount": 50, "destination": "@cat"})
check("вывод ниже минимума -> отказ", r.status_code == 400, r.status_code)
r1 = post("cat", "/api/payout", {"amount": 500, "destination": "@cat"}).get_json()
check("заявка: списано 500, комиссия 13.5% (67), к выплате 433", bal("cat") == b_c - 500 and r1["request"]["net"] == 433
      and r1["request"]["commission"] == 67 and r1["request"]["currency"] == "VLD", r1)
r = c.post(f"/api/admin/payouts/{r1['request']['id']}", json={"action": "paid"})
check("обработка вывода без секрета админа -> 403", r.status_code == 403, r.status_code)
c.post(f"/api/admin/payouts/{r1['request']['id']}", headers=ADMIN, json={"action": "reject"})
check("отклонённая заявка возвращена полностью", bal("cat") == b_c, bal("cat"))
r2 = post("cat", "/api/payout", {"amount": 500, "destination": "@cat"}).get_json()
c.post(f"/api/admin/payouts/{r2['request']['id']}", headers=ADMIN, json={"action": "paid"})
r = c.post(f"/api/admin/payouts/{r2['request']['id']}", headers=ADMIN, json={"action": "reject"})
check("выплаченную заявку нельзя отклонить повторно", r.status_code == 404, r.status_code)

# ---------- сходимость: ни одна звезда не появилась из воздуха
with app.app_context():
    users = User.query.filter(User.telegram_id.in_(IDS.values())).all()
    balances = sum(u.stars_balance for u in users)
    rev = db.session.query(db.func.coalesce(db.func.sum(LedgerTx.amount), 0)).filter(
        LedgerTx.user_id == None, LedgerTx.currency == "VLD").scalar() - rev0   # noqa: E711
    org = next(u for u in users if u.telegram_id == IDS["org"])
    check("за 4 раунда списано 4 × 0.1 VDT, VLD сбор не тронул", org.vdt_balance == 1000 - 4 * 100, org.vdt_balance)
    paid_out = 433                                       # ушло игроку наружу по заявке r2
    total = balances + rev + paid_out
    check("деньги сходятся: балансы + доход платформы + выплаты = внесённому",
          total == START * len(IDS), (balances, rev, paid_out, total))
    check("платформа в плюсе и ничего не доплачивала", rev > 0, rev)
    print(f"     доход платформы за прогон: {rev} ⭐ (комиссии раундов, перевода и вывода)")

    # уборка; проводки платформы — только этого прогона, по точным ключам
    uids = [u.id for u in users]
    pools = Pool.query.filter(Pool.organizer_id.in_(uids)).all()
    pids = [p.id for p in pools]
    plat_refs = [pool_ref(p, w) for p in pools for w in ("fee", "commission")]
    plat_refs += [x.ref.rsplit(":", 1)[0] + ":fee" for x in LedgerTx.query.filter(
        LedgerTx.user_id.in_(uids), LedgerTx.kind == "transfer_out").all() if x.ref]
    plat_refs += [payout_ref(q, "fee") for q in PayoutRequest.query.filter(PayoutRequest.user_id.in_(uids)).all()]
    plat_q = LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_(plat_refs))  # noqa: E711
    found = plat_q.count()
    plat_q.delete(synchronize_session=False)
    # 4 сбора за запуск + 3 комиссии раундов (колесо, сейф, аукцион) + перевод + выплата r2
    check("уборка: все 9 проводок платформы этого прогона найдены по ключу", found == 9, found)
    PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).delete(synchronize_session=False)
    Pool.query.filter(Pool.id.in_(pids)).delete(synchronize_session=False)
    GiftItem.query.filter(GiftItem.tg_gift_id.in_(["tg-g1", "tg-g2", "tg-g3"])).delete(synchronize_session=False)
    PayoutRequest.query.filter(PayoutRequest.user_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

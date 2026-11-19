"""Фаза 1: две валюты (VLD и VDT), раздельный учёт; раунды в валюте, комиссия 4.5%, сбор 0.1 VDT, 6 часов."""
import hashlib, hmac, json, os, sys, time
from datetime import datetime, timedelta
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:TEST-TOKEN-not-real", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RELAY_SECRET="relay-s", ADMIN_SECRET="admin-s", RATE_LIMIT="100000")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, LedgerTx, GiftItem, Pool, PoolEntry  # noqa: E402
from bot import vloody                                         # noqa: E402

IDS = {"ann": 990000901, "org": 990000910, "p1": 990000911, "p2": 990000912}
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
prof = c.get("/api/profile", headers=hdr("ann"))
check("profile 200", prof.status_code == 200, prof.status_code)
b = prof.get_json().get("balances")
check("profile.balances = {VLD:int, VDT:int}",
      isinstance(b, dict) and set(b) == {"VLD", "VDT"} and all(isinstance(v, int) for v in b.values()), b)
check("profile.balance == balances.VLD", prof.get_json()["balance"] == (b or {}).get("VLD"))

with app.app_context():
    u = User.query.filter_by(telegram_id=IDS["ann"]).first()
    uid = u.id
    u.stars_balance, u.vdt_balance = 500, 0
    db.session.commit()

    check("CURRENCIES", vloody.CURRENCIES == ("VLD", "VDT"))
    vloody.move_vdt(u, 1500, "t", "t")
    db.session.commit()
    last = LedgerTx.query.filter_by(user_id=uid).order_by(LedgerTx.id.desc()).first()
    check("move_vdt меняет vdt_balance", u.vdt_balance == 1500, u.vdt_balance)
    check("move_vdt: проводка в VDT", last.currency == "VDT" and last.amount == 1500, last.currency)
    check("move_vdt не трогает VLD", u.stars_balance == 500, u.stars_balance)

    vloody.move_vld(u, -100, "t", "t")
    db.session.commit()
    last = LedgerTx.query.filter_by(user_id=uid).order_by(LedgerTx.id.desc()).first()
    check("move_vld: проводка в VLD, VDT цел", last.currency == "VLD" and u.stars_balance == 400
          and u.vdt_balance == 1500)
    check("move — алиас move_vld", vloody.move is vloody.move_vld)

    check("mover('VDT') is move_vdt", vloody.mover("VDT") is vloody.move_vdt)
    check("mover('VLD') is move_vld", vloody.mover("VLD") is vloody.move_vld)
    try:
        vloody.mover("vld"); bad = False
    except ValueError:
        bad = True
    check("mover('vld') -> ValueError", bad)

    for fn, msg in ((vloody.move_vld, "Недостаточно VLD"), (vloody.move_vdt, "Недостаточно VDT")):
        try:
            fn(u, -10 ** 9, "t", "t"); got = None
        except ValueError as e:
            got = str(e)
        check(f"overdraft -> {msg}", got == msg, got)
    check("после овердрафта балансы не изменились", u.stars_balance == 400 and u.vdt_balance == 1500)

    check("balance_of", vloody.balance_of(u, "VLD") == 400 and vloody.balance_of(u, "VDT") == 1500)
    check("fmt_cur", vloody.fmt_cur(12, "VLD") == "12 VLD" and vloody.fmt_cur(1250, "VDT") == "1.25 VDT"
          and vloody.fmt_cur(1000, "VDT") == "1 VDT" and vloody.fmt_cur(1, "VDT") == "0.001 VDT",
          (vloody.fmt_cur(1250, "VDT"), vloody.fmt_cur(1000, "VDT")))

    vloody.move_vdt(None, 7, "fee", "платформа")
    db.session.commit()
    last = LedgerTx.query.order_by(LedgerTx.id.desc()).first()
    check("move_vdt(None) — доход платформы в VDT", last.user_id is None and last.currency == "VDT")

    # уборка
    LedgerTx.query.filter(db.or_(LedgerTx.user_id == uid, LedgerTx.id == last.id)).delete(synchronize_session=False)
    User.query.filter_by(id=uid).delete(synchronize_session=False)
    db.session.commit()


# ================================================================== задача 2: раунды в валюте
RELAY = {"X-Relay-Secret": "relay-s"}
ADMIN = {"X-Admin-Secret": "admin-s"}
get = lambda who, url: c.get(url, headers=hdr(who))
post = lambda who, url, body=None: c.post(url, headers=hdr(who), json=body or {})
_gift_n = [0]


def gift(who="org"):
    _gift_n[0] += 1
    r = c.post("/api/relay/gift-deposit", headers=RELAY,
               json={"telegram_id": IDS[who], "name": f"P1 Gift #{_gift_n[0]}", "tg_gift_id": f"p1t2-{_gift_n[0]}"})
    return r.get_json()["gift"]["id"]


def setbal(who, vld=None, vdt=None):
    with app.app_context():
        x = User.query.filter_by(telegram_id=IDS[who]).first()
        if vld is not None:
            x.stars_balance = vld
        if vdt is not None:
            x.vdt_balance = vdt
        db.session.commit()


def bals(who):
    with app.app_context():
        x = User.query.filter_by(telegram_id=IDS[who]).first()
        return x.stars_balance, x.vdt_balance


def expire(pid):
    with app.app_context():
        db.session.get(Pool, pid).ends_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()


def platform(pid):
    """Проводки платформы по раунду: [(kind, currency, amount)]."""
    with app.app_context():
        prefix = vloody.pool_ref(db.session.get(Pool, pid), "")
        rows = LedgerTx.query.filter(LedgerTx.user_id == None,                  # noqa: E711
                                     LedgerTx.ref.like(prefix + "%")).order_by(LedgerTx.id).all()
        return [(r.kind, r.currency, r.amount) for r in rows]


for who in ("org", "p1", "p2"):
    get(who, "/api/profile")
setbal("org", vld=0, vdt=50)
setbal("p1", vld=500, vdt=10000)
setbal("p2", vld=500, vdt=10000)

check("константы", vloody.DURATIONS_MIN == (15, 30, 60, 180, 360) and vloody.ROUND_LIFE == timedelta(hours=6)
      and vloody.CREATE_FEE_VDT == 100 and vloody.COMMISSION_RATE == 0.045)

# ---------- сбор за запуск
g = gift()
r = post("org", "/api/pools", {"mode": "wheel", "gift_id": g, "min_stake": 5, "duration_min": 15})
check("без 0.1 VDT раунд не создаётся", r.status_code == 400
      and r.get_json().get("error") == "Нужно 0.1 VDT на запуск раунда — пополни баланс TON", (r.status_code, r.get_json()))
check("после отказа VDT не списан, подарок свободен", bals("org")[1] == 50
      and get("org", "/api/inventory/gifts").get_json()["gifts"][0]["status"] == "held")

setbal("org", vdt=10000)
r = post("org", "/api/pools", {"mode": "wheel", "gift_id": g, "min_stake": 10, "duration_min": 15,
                               "currency": "VDT"})
w = r.get_json()
check("VDT-колесо создано", r.status_code == 200 and w["currency"] == "VDT" and w["create_fee"] == 100, r.get_json())
check("сбор 100 милли-VDT списан", bals("org") == (0, 9900), bals("org"))
check("платформа получила +100 VDT create_fee", platform(w["id"]) == [("create_fee", "VDT", 100)], platform(w["id"]))
with app.app_context():
    org_id = User.query.filter_by(telegram_id=IDS["org"]).first().id
    row = LedgerTx.query.filter_by(user_id=org_id, kind="create_fee").first()
    check("у организатора проводка −100 VDT create_fee", row and row.amount == -100 and row.currency == "VDT")

# ---------- ставки идут в валюте раунда, а не из тела запроса
r = post("p1", f"/api/pools/{w['id']}/stake", {"amount": 50, "currency": "VLD"})
check("ставка {currency: VLD} в VDT-раунде списывает VDT", r.status_code == 200 and bals("p1") == (500, 9950), bals("p1"))
r = post("p1", f"/api/pools/{w['id']}/stake", {"amount": 100001})
check("VDT-ставка выше 100 VDT -> отказ", r.status_code == 400, r.status_code)
r = post("p1", f"/api/pools/{w['id']}/stake", {"amount": 9})
check("VDT-ставка ниже минимума -> отказ", r.status_code == 400, r.status_code)
post("p1", f"/api/pools/{w['id']}/stake", {"amount": 950})
post("p2", f"/api/pools/{w['id']}/stake", {"amount": 3000})
check("банк 4000 милли-VDT", get("p1", f"/api/pools/{w['id']}").get_json()["bank"] == 4000)

# ---------- двойной расчёт: устаревший объект не платит второй раз
expire(w["id"])
with app.app_context():
    p = db.session.get(Pool, w["id"])
    db.session.execute(db.update(Pool).where(Pool.id == w["id"]).values(status="finished"),
                       execution_options={"synchronize_session": False})
    vloody.settle(p)                    # объект в памяти ещё «live», в БД — уже нет
    db.session.commit()
check("settle перечитывает статус под блокировкой", bals("org") == (0, 9900) and platform(w["id"]) == [("create_fee", "VDT", 100)],
      (bals("org"), platform(w["id"])))
with app.app_context():
    db.session.execute(db.update(Pool).where(Pool.id == w["id"]).values(status="live"),
                       execution_options={"synchronize_session": False})
    db.session.commit()
    vloody.settle_due()
    vloody.settle(db.session.get(Pool, w["id"]))          # повторный расчёт
    vloody.settle_due()
    db.session.commit()
check("организатор получил 4000 − 4.5% = 3820 милли-VDT", bals("org") == (0, 9900 + 3820), bals("org"))
check("платформа +180 VDT комиссии, ровно один раз",
      platform(w["id"]) == [("create_fee", "VDT", 100), ("commission", "VDT", 180)], platform(w["id"]))
check("VLD ни у кого не изменились", bals("p1")[0] == 500 and bals("p2")[0] == 500 and bals("org")[0] == 0)
d = get("p1", f"/api/pools/{w['id']}").get_json()
check("раунд завершён, победитель есть", d["status"] == "finished" and d["winner"] and d.get("cancel_reason") is None, d["status"])

# ---------- колесо с одним участником -> отмена с возвратом
g2 = gift()
org_vdt = bals("org")[1]
w2 = post("org", "/api/pools", {"mode": "wheel", "gift_id": g2, "min_stake": 5, "duration_min": 30}).get_json()
check("раунд без currency — VLD", w2.get("currency") == "VLD", w2.get("currency"))
post("p1", f"/api/pools/{w2['id']}/stake", {"amount": 100})
post("p1", f"/api/pools/{w2['id']}/stake", {"amount": 20})
check("ставки списаны в VLD", bals("p1")[0] == 380)
expire(w2["id"])
d = get("org", f"/api/pools/{w2['id']}").get_json()
check("один участник -> отменён, причина no_players", d["status"] == "cancelled" and d.get("cancel_reason") == "no_players", d)
check("участнику вернули всё", bals("p1")[0] == 500, bals("p1"))
check("сбор не возвращён", bals("org")[1] == org_vdt - 100, (bals("org"), org_vdt))
check("организатор не получил VLD", bals("org")[0] == 0)
gs = {x["id"]: x for x in get("org", "/api/inventory/gifts").get_json()["gifts"]}
check("подарок вернулся организатору (held)", gs.get(g2, {}).get("status") == "held", gs.get(g2))
check("платформа по отмене: только сбор", platform(w2["id"]) == [("create_fee", "VDT", 100)], platform(w2["id"]))
with app.app_context():
    p1_id = User.query.filter_by(telegram_id=IDS["p1"]).first().id
    refunds = LedgerTx.query.filter_by(user_id=p1_id, kind="refund", currency="VLD").all()
    check("возвраты — проводки refund в VLD", sorted(x.amount for x in refunds) == [20, 100], [x.amount for x in refunds])
check("причина отмены переживает перезагрузку", get("p2", f"/api/pools/{w2['id']}").get_json().get("cancel_reason") == "no_players")

# ---------- сейф: цена билета, 6 часов, не вскрыт -> отмена
g3 = gift()
for bad_stake in (0, 10001):
    r = post("org", "/api/pools", {"mode": "vault", "gift_id": g3, "min_stake": bad_stake, "vault_max": 25})
    check(f"сейф min_stake={bad_stake} -> отказ", r.status_code == 400, r.status_code)
for bad_stake in (9, 100001):
    r = post("org", "/api/pools", {"mode": "vault", "gift_id": g3, "min_stake": bad_stake, "vault_max": 25,
                                   "currency": "VDT"})
    check(f"VDT-сейф min_stake={bad_stake} -> отказ", r.status_code == 400, r.status_code)
r = post("org", "/api/pools", {"mode": "vault", "gift_id": g3, "min_stake": 5, "vault_max": 25, "currency": "TON"})
check("неизвестная валюта -> отказ", r.status_code == 400, r.status_code)
check("отказы не списали сбор", bals("org")[1] == org_vdt - 100)
r = post("org", "/api/pools", {"mode": "vault", "gift_id": g3, "min_stake": 37, "vault_max": 25})
v = r.get_json()
check("сейф с ценой 37 VLD создан", r.status_code == 200 and v["min_stake"] == 37, r.get_json())
check("сейф живёт 6 часов", v["ends_ts"] and abs(v["ends_ts"] - v["created_ts"] - 6 * 3600) <= 5,
      (v.get("ends_ts"), v.get("created_ts")))
with app.app_context():
    secret = json.loads(db.session.get(Pool, v["id"]).cfg)["secret"]
miss = 1 if secret != 1 else 2
r = post("p1", f"/api/pools/{v['id']}/vault", {"number": miss, "currency": "VDT"})
check("попытка в сейфе списала 37 VLD", r.status_code == 200 and not r.get_json()["hit"] and bals("p1") == (463, 9000), bals("p1"))
expire(v["id"])
d = get("p1", f"/api/pools/{v['id']}").get_json()
check("не вскрыт -> отменён, причина not_cracked", d["status"] == "cancelled" and d.get("cancel_reason") == "not_cracked", d)
check("попытка в сейфе возвращена", bals("p1") == (500, 9000), bals("p1"))

# ---------- длительность
g4 = gift()
r = post("org", "/api/pools", {"mode": "auction", "gift_id": g4, "min_stake": 10, "duration_min": 1440})
check("1440 минут -> отказ", r.status_code == 400, r.status_code)
r = post("org", "/api/pools", {"mode": "auction", "gift_id": g4, "min_stake": 10, "duration_min": 360,
                               "currency": "VDT"})
a = r.get_json()
check("360 минут -> ок", r.status_code == 200 and a["ends_ts"] - a["created_ts"] in range(360 * 60 - 5, 360 * 60 + 6))

# ---------- аварийная отмена VDT-раунда админом возвращает VDT
post("p2", f"/api/pools/{a['id']}/bid", {"amount": 500})
check("ставка в VDT-аукционе списала VDT", bals("p2") == (500, 6500), bals("p2"))
r = c.post(f"/api/admin/pools/{a['id']}/refund", headers=ADMIN)
check("админ-отмена: возвращено 500", r.status_code == 200 and r.get_json().get("refunded") == 500, r.get_json())
check("возврат в VDT, VLD не тронут", bals("p2") == (500, 7000), bals("p2"))

# ---------- отмена организатором пустого раунда
g5 = gift()
org_vdt = bals("org")[1]
e = post("org", "/api/pools", {"mode": "wheel", "gift_id": g5, "min_stake": 5, "duration_min": 15}).get_json()
r = post("org", f"/api/pools/{e['id']}/cancel")
d = get("org", f"/api/pools/{e['id']}").get_json()
check("организатор отменил пустой раунд", r.status_code == 200 and d["status"] == "cancelled"
      and d.get("cancel_reason") == "organizer", d)
check("сбор при отмене организатором не возвращён", bals("org")[1] == org_vdt - 100, bals("org"))

# ---------- уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_([IDS[k] for k in ("org", "p1", "p2")])).all()
    uids = [x.id for x in users]
    pools = Pool.query.filter(Pool.organizer_id.in_(uids)).all()
    pids = [p.id for p in pools]
    for p in pools:                         # проводки платформы — только по ключу именно этих раундов
        LedgerTx.query.filter(LedgerTx.user_id == None,                         # noqa: E711
                              LedgerTx.ref.like(vloody.pool_ref(p, "") + "%")).delete(synchronize_session=False)
    PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).delete(synchronize_session=False)
    Pool.query.filter(Pool.id.in_(pids)).delete(synchronize_session=False)
    GiftItem.query.filter(GiftItem.owner_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

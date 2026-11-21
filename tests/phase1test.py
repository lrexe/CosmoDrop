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


# ================================================================== задача 3: кошелёк в двух валютах
import io, secrets                                              # noqa: E402
from models import PayoutRequest, TonDeposit                    # noqa: E402

IDS.update({"vlt3_alice": 990000930, "vlt3_bob": 990000931, "vlt3_ban": 990000932,
            "vlt3_new": 990000933, "vlt3_old": 990000934, "vlt3_stale": 990000935, "vlt3_dup": 990000936})
T3 = ("vlt3_alice", "vlt3_bob", "vlt3_ban", "vlt3_new", "vlt3_old", "vlt3_stale", "vlt3_dup")
plat_refs = []                       # ключи проводок платформы, созданных этим блоком


def uid_of(who):
    with app.app_context():
        return User.query.filter_by(telegram_id=IDS[who]).first().id


def plat_row(ref):
    with app.app_context():
        r = LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref == ref).first()  # noqa: E711
        return (r.kind, r.currency, r.amount) if r else None


for who in T3:
    get(who, "/api/profile")

# ---------- константы и профиль
lim = get("vlt3_alice", "/api/profile").get_json()
L, R = lim["limits"], lim["rates"]
check("limits: новые ключи", all(L.get(k) == v for k, v in {
    "payout_min_vld": 275, "payout_fee_vld": 0.135, "payout_min_vdt": 2500, "payout_fee_vdt": 0.115,
    "transfer_min_vld": 150, "transfer_min_vdt": 1500, "transfer_fee": 0.10, "commission": 0.045,
    "create_fee_vdt": 100}.items()), L)
check("limits: старые ключи для текущего UI", L.get("transfer_min") == 150 and L.get("payout_min") == 275
      and L.get("payout_fee") == 0.135 and L.get("payout_fee_ton") == 0.115 and L.get("transfer_fee") == 0.10, L)
check("rates.stars_to_vld = 1", R.get("stars_to_vld") == 1, R)

# ---------- TON-депозит: 2.5 TON -> 2500 милли-VDT, VLD не трогает, одна транзакция — один раз
setbal("vlt3_alice", vld=0, vdt=0)
tx_hash = "t3-" + secrets.token_hex(8)
with app.app_context():
    dep = TonDeposit(user_id=uid_of("vlt3_alice"), comment="vl" + secrets.token_hex(6), created_at=datetime.utcnow())
    db.session.add(dep); db.session.commit()
    comment, dep_id = dep.comment, dep.id
fake_chain = {"result": [{"transaction_id": {"hash": tx_hash}, "in_msg": {
    "source": "UQsender", "value": str(2_500_000_000), "message": comment}}]}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_urlopen, _wallet, _every = vloody.urllib.request.urlopen, vloody.TON_WALLET, vloody.TON_SCAN_EVERY
vloody.urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(fake_chain).encode())
vloody.TON_WALLET, vloody.TON_SCAN_EVERY = "UQ" + "T" * 46, 0
try:
    with app.app_context():
        n1 = vloody.scan_ton_deposits(force=True)
        n2 = vloody.scan_ton_deposits(force=True)
finally:
    vloody.urllib.request.urlopen, vloody.TON_WALLET, vloody.TON_SCAN_EVERY = _urlopen, _wallet, _every
check("TON 2.5 -> 2500 милли-VDT и 0 VLD", bals("vlt3_alice") == (0, 2500), bals("vlt3_alice"))
check("та же транзакция при повторной сверке не зачислена", n1 == 1 and n2 == 0, (n1, n2))
with app.app_context():
    rows = LedgerTx.query.filter_by(user_id=uid_of("vlt3_alice"), kind="deposit").all()
    d = db.session.get(TonDeposit, dep_id)
    check("проводка депозита: VDT, ref ton:<hash>", [(x.currency, x.amount, x.ref) for x in rows]
          == [("VDT", 2500, f"ton:{tx_hash}")], [(x.currency, x.amount, x.ref) for x in rows])
    check("TonDeposit.vld хранит зачисленные милли-VDT", d.status == "credited" and d.vld == 2500, (d.status, d.vld))
    try:                             # прямой повтор зачисления той же транзакции упирается в уникальный ref
        vloody._credit_ton(TonDeposit(user_id=uid_of("vlt3_alice"), comment="vl" + secrets.token_hex(6)),
                           2_500_000_000, tx_hash)
        db.session.commit(); dup = False
    except Exception:
        db.session.rollback(); dup = True
    check("прямое повторное зачисление того же хеша падает на уникальном ref", dup is True, dup)
    check("повторное зачисление того же хеша невозможно", bals("vlt3_alice") == (0, 2500), bals("vlt3_alice"))

# ---------- параллельная сверка: хеш уже зачислен другим процессом -> откат и пропуск, без 500
race_hash = "t3-race-" + secrets.token_hex(6)
with app.app_context():
    dep2 = TonDeposit(user_id=uid_of("vlt3_alice"), comment="vl" + secrets.token_hex(6), created_at=datetime.utcnow())
    db.session.add(dep2)
    # будто соседний процесс уже провёл ton:<hash>, а его TonDeposit мы ещё не видим
    db.session.add(LedgerTx(user_id=uid_of("vlt3_alice"), kind="deposit", amount=0, currency="VDT",
                            title="race", ref=f"ton:{race_hash}"))
    db.session.commit()
    comment2, dep2_id = dep2.comment, dep2.id
fake_chain = {"result": [{"transaction_id": {"hash": race_hash}, "in_msg": {
    "source": "UQsender", "value": str(1_000_000_000), "message": comment2}}]}
vloody.urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(fake_chain).encode())
vloody.TON_WALLET, vloody.TON_SCAN_EVERY = "UQ" + "T" * 46, 0
try:
    with app.app_context():
        try:
            n3, race_err = vloody.scan_ton_deposits(force=True), None
        except Exception as e:                                  # noqa: BLE001
            n3, race_err = None, repr(e)
        st2 = db.session.get(TonDeposit, dep2_id).status
finally:
    vloody.urllib.request.urlopen, vloody.TON_WALLET, vloody.TON_SCAN_EVERY = _urlopen, _wallet, _every
check("дубль хеша при сверке: откат, 0 зачислений, без исключения",
      race_err is None and n3 == 0 and st2 == "pending" and bals("vlt3_alice") == (0, 2500), (race_err, n3, st2, bals("vlt3_alice")))

# ---------- Stars: 100 XTR -> 100 VLD
charge = "t3-charge-" + secrets.token_hex(6)
upd = {"message": {"from": {"id": IDS["vlt3_alice"]}, "successful_payment": {
    "currency": "XTR", "total_amount": 100, "telegram_payment_charge_id": charge}}}
with app.app_context():
    r1 = vloody.handle_payment_update(upd)
    r2 = vloody.handle_payment_update(upd)
check("100 Stars -> 100 VLD, VDT не тронут", r1.get("amount") == 100 and bals("vlt3_alice") == (100, 2500), (r1, bals("vlt3_alice")))
check("повтор платежа не зачислен", r2.get("status") == "duplicate" and bals("vlt3_alice") == (100, 2500))

# ---------- транзакции различают валюту
items = get("vlt3_alice", "/api/transactions").get_json()["items"]
check("transactions: поле currency", {x.get("currency") for x in items} == {"VLD", "VDT"}, items[:2])

# ---------- вывод
TON_DEST = "UQ" + "C" * 46
setbal("vlt3_alice", vld=1000, vdt=0)
r = post("vlt3_alice", "/api/payout", {"currency": "VDT", "amount": 2500, "destination": TON_DEST})
check("вывод VDT при одном VLD -> 400", r.status_code == 400 and bals("vlt3_alice") == (1000, 0), (r.status_code, r.get_json()))
r = post("vlt3_alice", "/api/payout", {"currency": "BTC", "amount": 500, "destination": "@alice"})
check("неизвестная валюта вывода -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/payout", {"currency": "VLD", "amount": 274, "destination": "@alice"})
check("вывод 274 VLD -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/payout", {"currency": "VLD", "amount": 275, "destination": "@alice"})
q = (r.get_json() or {}).get("request") or {}
check("вывод 275 VLD -> к выплате 238", r.status_code == 200 and q.get("net") == 238 and q.get("commission") == 37
      and q.get("currency") == "VLD" and q.get("method") == "STARS" and bals("vlt3_alice") == (725, 0), (r.status_code, q))
r = post("vlt3_alice", "/api/payout", {"method": "STARS", "amount": 300, "destination": "@alice"})
q_legacy = (r.get_json() or {}).get("request") or {}
check("legacy method=STARS -> VLD", r.status_code == 200 and q_legacy.get("currency") == "VLD" and bals("vlt3_alice") == (425, 0))
c.post(f"/api/admin/payouts/{q.get('id', 0)}", headers=ADMIN, json={"action": "paid"})
with app.app_context():
    pr = db.session.get(PayoutRequest, q.get("id", 0))
    fee_ref = vloody.payout_ref(pr, "fee") if pr and hasattr(vloody, "payout_ref") else "missing"
plat_refs.append(fee_ref)
check("выплата VLD: комиссия 37 VLD платформе, баланс не тронут",
      plat_row(fee_ref) == ("commission", "VLD", 37) and bals("vlt3_alice") == (425, 0), plat_row(fee_ref))

setbal("vlt3_alice", vdt=5000)
r = post("vlt3_alice", "/api/payout", {"currency": "VDT", "amount": 2499, "destination": TON_DEST})
check("вывод 2499 милли-VDT -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/payout", {"currency": "VDT", "amount": 2500, "destination": "@alice"})
check("вывод VDT на не-TON адрес -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/payout", {"currency": "VDT", "amount": 2500, "destination": TON_DEST})
qv = (r.get_json() or {}).get("request") or {}
with app.app_context():
    prv = db.session.get(PayoutRequest, qv.get("id") or 0)
    nn = prv.net_nano if prv else None
check("вывод 2500 милли-VDT -> к выплате 2213, net_nano = 2213·10⁶",
      r.status_code == 200 and qv.get("net") == 2213 and qv.get("commission") == 287 and nn == 2213 * 10**6
      and qv.get("currency") == "VDT" and qv.get("method") == "TON" and bals("vlt3_alice") == (425, 2500), (r.status_code, qv, nn))
c.post(f"/api/admin/payouts/{qv.get('id', 0)}", headers=ADMIN, json={"action": "reject"})
check("отклонение VDT-вывода возвращает VDT", bals("vlt3_alice") == (425, 5000), bals("vlt3_alice"))
r = post("vlt3_alice", "/api/payout", {"method": "TON", "amount": 2500, "destination": TON_DEST})
ql = (r.get_json() or {}).get("request") or {}
check("legacy method=TON -> VDT", r.status_code == 200 and ql.get("currency") == "VDT" and bals("vlt3_alice") == (425, 2500), ql)
vloody.DEMO_MODE, _demo = True, vloody.DEMO_MODE
try:
    r = post("vlt3_alice", "/api/payout", {"currency": "VLD", "amount": 300, "destination": "@alice"})
finally:
    vloody.DEMO_MODE = _demo
check("демо-режим: вывод 403", r.status_code == 403, r.status_code)

# ---------- поиск по username
r = get("vlt3_alice", "/api/users/lookup?username=@VLT3_Bob")
j = r.get_json() or {}
check("lookup @VLT3_Bob -> bob, только публичные поля", r.status_code == 200 and j.get("username") == "vlt3_bob"
      and set(j) == {"name", "username", "photo", "is_me", "recipient_token"} and j.get("is_me") is False, j)
check("lookup не раскрывает telegram_id", str(IDS["vlt3_bob"]) not in r.get_data(as_text=True), r.get_data(as_text=True))
bob_token = j.get("recipient_token")
check("lookup себя -> is_me", get("vlt3_alice", "/api/users/lookup?username=vlt3_alice").get_json().get("is_me") is True)
check("lookup без @ тоже работает", get("vlt3_alice", "/api/users/lookup?username=vlt3_bob").status_code == 200)
check("lookup неизвестного -> 404", get("vlt3_alice", "/api/users/lookup?username=vlt3_nobody_x").status_code == 404)
for bad in ("", "@", "ab", "bad-name!", "x" * 33):
    rr = get("vlt3_alice", "/api/users/lookup?username=" + bad)
    check(f"lookup '{bad[:10]}' -> 400", rr.status_code == 400, rr.status_code)
with app.app_context():
    User.query.filter_by(telegram_id=IDS["vlt3_ban"]).first().is_banned = True
    db.session.commit()
check("lookup заблокированного -> 404", get("vlt3_alice", "/api/users/lookup?username=vlt3_ban").status_code == 404)
r = get("vlt3_alice", f"/api/users/lookup?telegram_id={IDS['vlt3_bob']}")
check("lookup по telegram_id больше не работает (нельзя перебирать id)", r.status_code == 400
      and "vlt3_bob" not in r.get_data(as_text=True), (r.status_code, r.get_json()))

# ---------- перевод по username
setbal("vlt3_alice", vld=1000, vdt=5000)
setbal("vlt3_bob", vld=0, vdt=0)
r = post("vlt3_alice", "/api/transfer", {"to_username": "@VLT3_BOB", "amount": 149, "currency": "VLD"})
check("перевод 149 VLD -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_username": "@VLT3_BOB", "amount": 150, "currency": "VLD"})
check("перевод 150 VLD @VLT3_BOB: −150 / +135", r.status_code == 200 and bals("vlt3_alice") == (850, 5000)
      and bals("vlt3_bob") == (135, 0), (r.status_code, r.get_json(), bals("vlt3_alice"), bals("vlt3_bob")))
with app.app_context():
    out = LedgerTx.query.filter_by(user_id=uid_of("vlt3_alice"), kind="transfer_out").order_by(LedgerTx.id.desc()).first()
    base = out.ref.rsplit(":", 1)[0] if out and out.ref else ""
plat_refs.append(base + ":fee")
check("комиссия перевода 15 VLD платформе", plat_row(base + ":fee") == ("commission", "VLD", 15), plat_row(base + ":fee"))
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 1499, "currency": "VDT"})
check("перевод 1499 милли-VDT -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_username": "Vlt3_Bob", "amount": 1500, "currency": "VDT"})
check("VDT-перевод двигает только VDT", r.status_code == 200 and bals("vlt3_alice") == (850, 3500)
      and bals("vlt3_bob") == (135, 1350), (bals("vlt3_alice"), bals("vlt3_bob")))
with app.app_context():
    out = LedgerTx.query.filter_by(user_id=uid_of("vlt3_alice"), kind="transfer_out").order_by(LedgerTx.id.desc()).first()
    inn = LedgerTx.query.filter_by(user_id=uid_of("vlt3_bob"), kind="transfer_in").order_by(LedgerTx.id.desc()).first()
    base = out.ref.rsplit(":", 1)[0] if out and out.ref else ""
    check("проводки перевода в VDT", out is not None and inn is not None and out.currency == "VDT" and inn.currency == "VDT" and inn.amount == 1350)
plat_refs.append(base + ":fee")
check("комиссия VDT-перевода 150 милли-VDT платформе", plat_row(base + ":fee") == ("commission", "VDT", 150), plat_row(base + ":fee"))
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 5000, "currency": "VDT"})
check("недостаточно VDT -> 400", r.status_code == 400 and (r.get_json() or {}).get("error") == "Недостаточно VDT", r.get_json())
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 5000, "currency": "VLD"})
check("недостаточно VLD -> 400", r.status_code == 400 and (r.get_json() or {}).get("error") == "Недостаточно VLD", r.get_json())
r = post("vlt3_alice", "/api/transfer", {"to_username": "@vlt3_alice", "amount": 200, "currency": "VLD"})
check("перевод себе -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_nobody_x", "amount": 200, "currency": "VLD"})
check("перевод неизвестному -> 404", r.status_code == 404, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_ban", "amount": 200, "currency": "VLD"})
check("перевод заблокированному -> 404", r.status_code == 404, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 200, "currency": "TON"})
check("перевод в неизвестной валюте -> 400", r.status_code == 400, r.status_code)
r = post("vlt3_alice", "/api/transfer", {"to_telegram_id": IDS["vlt3_bob"], "amount": 200})
check("перевод по telegram_id больше не принимается", r.status_code == 400 and bals("vlt3_alice") == (850, 3500)
      and bals("vlt3_bob") == (135, 1350), (r.status_code, bals("vlt3_alice"), bals("vlt3_bob")))

# ---------- получатель из предпросмотра: если имя ушло к другому — 409, деньги не двигаются
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 200, "recipient_token": bob_token})
with app.app_context():
    out = LedgerTx.query.filter_by(user_id=uid_of("vlt3_alice"), kind="transfer_out").order_by(LedgerTx.id.desc()).first()
    plat_refs.append(out.ref.rsplit(":", 1)[0] + ":fee" if out and out.ref else "")
check("перевод с recipient_token из предпросмотра -> 200 (без currency — VLD)", r.status_code == 200
      and bals("vlt3_alice") == (650, 3500) and bals("vlt3_bob") == (315, 1350), (r.status_code, r.get_json()))
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_dup", "amount": 200, "recipient_token": bob_token})
check("имя теперь у другого игрока -> 409 «Получатель изменился»", r.status_code == 409
      and (r.get_json() or {}).get("error") == "Получатель изменился — проверь ещё раз"
      and bals("vlt3_alice") == (650, 3500), (r.status_code, r.get_json()))
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_bob", "amount": 200, "recipient_token": "forged"})
check("поддельный recipient_token -> 409", r.status_code == 409 and bals("vlt3_alice") == (650, 3500), r.status_code)

# ---------- неоднозначный @username: не угадываем, а устаревшая запись чистится при входе владельца
with app.app_context():
    User.query.filter_by(telegram_id=IDS["vlt3_stale"]).first().username = "VLT3_DUP"   # устаревшее имя
    db.session.commit()
setbal("vlt3_alice", vld=1000, vdt=5000)
setbal("vlt3_dup", vld=0, vdt=0)
setbal("vlt3_stale", vld=0, vdt=0)
r = get("vlt3_alice", "/api/users/lookup?username=@vlt3_dup")
check("lookup неоднозначного имени -> 409", r.status_code == 409 and (r.get_json() or {}).get("error")
      == "Этот @username неоднозначен — попроси друга открыть Vloody, чтобы обновить профиль", (r.status_code, r.get_json()))
r = post("vlt3_alice", "/api/transfer", {"to_username": "vlt3_dup", "amount": 200, "currency": "VLD"})
check("перевод на неоднозначное имя -> 409, деньги не двигались", r.status_code == 409
      and bals("vlt3_alice") == (1000, 5000) and bals("vlt3_dup") == (0, 0) and bals("vlt3_stale") == (0, 0),
      (r.status_code, bals("vlt3_alice"), bals("vlt3_dup"), bals("vlt3_stale")))
get("vlt3_dup", "/api/profile")                                  # настоящий владелец заходит в приложение
with app.app_context():
    stale_name = User.query.filter_by(telegram_id=IDS["vlt3_stale"]).first().username
check("вход владельца снял имя с устаревшей записи", stale_name is None, stale_name)
r = get("vlt3_alice", "/api/users/lookup?username=@VLT3_DUP")
check("после этого lookup находит владельца", r.status_code == 200 and r.get_json()["username"] == "vlt3_dup", r.get_json())

# ---------- демо-бонус: 1000 VLD + NFT + 1 VDT, один раз; старым игрокам — только 1 VDT, один раз
vloody.DEMO_MODE = True
try:
    with app.app_context():
        nu = User.query.filter_by(telegram_id=IDS["vlt3_new"]).first()
        nu.stars_balance, nu.vdt_balance, nu.welcome_bonus = 0, 0, 0
        ou = User.query.filter_by(telegram_id=IDS["vlt3_old"]).first()
        ou.stars_balance, ou.vdt_balance, ou.welcome_bonus = 1000, 0, 1
        db.session.commit()
        g1 = vloody.grant_welcome(nu)
        g2 = vloody.grant_welcome(nu)
        o1 = vloody.grant_welcome(ou)
        o2 = vloody.grant_welcome(ou)
finally:
    vloody.DEMO_MODE = _demo
with app.app_context():
    n_gifts = GiftItem.query.filter_by(owner_id=uid_of("vlt3_new")).count()
    o_gifts = GiftItem.query.filter_by(owner_id=uid_of("vlt3_old")).count()
    vdt_bonus = LedgerTx.query.filter_by(user_id=uid_of("vlt3_new"), kind="bonus", currency="VDT").all()
check("новый игрок: 1000 VLD + 1000 милли-VDT + NFT", g1 and bals("vlt3_new") == (1000, 1000) and n_gifts == 1
      and [x.amount for x in vdt_bonus] == [1000], (bals("vlt3_new"), n_gifts))
check("повторно бонус не выдаётся", g2 is False and bals("vlt3_new") == (1000, 1000))
check("старый игрок получил только 1 VDT", o1 and bals("vlt3_old") == (1000, 1000) and o_gifts == 0, (bals("vlt3_old"), o_gifts))
check("старому игроку — тоже один раз", o2 is False and bals("vlt3_old") == (1000, 1000))

# ---------- уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_([IDS[k] for k in T3])).all()
    uids = [x.id for x in users]
    # комиссия каждого перевода этих игроков — даже если проверка выше упала и ref не попал в plat_refs
    plat_refs += [o.ref.rsplit(":", 1)[0] + ":fee" for o in LedgerTx.query.filter(
        LedgerTx.user_id.in_(uids), LedgerTx.kind == "transfer_out").all() if o.ref]
    LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_([x for x in plat_refs if x])).delete(  # noqa: E711
        synchronize_session=False)
    for model in (TonDeposit, PayoutRequest, GiftItem):
        col = model.owner_id if model is GiftItem else model.user_id
        model.query.filter(col.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()

# ================================================================== задача 6: аудит денежных путей
IDS.update({"a6_org": 990000970, "a6_p1": 990000971, "a6_p2": 990000972, "a6_ghost": 990000973,
            "a6_pay": 990000974})
T6 = ("a6_org", "a6_p1", "a6_p2", "a6_ghost", "a6_pay")
plat6 = []                           # ключи проводок платформы, созданных этим блоком


def clean6(extra_uids=()):
    """Убирает всё, что оставил блок 6 (в том числе после упавшего прогона): платформа — по точным ключам раундов."""
    with app.app_context():
        users = User.query.filter(User.telegram_id.in_([IDS[k] for k in T6])).all()
        uids = [x.id for x in users] + [u for u in extra_uids if u]
        pools = Pool.query.filter(Pool.organizer_id.in_(uids)).all()
        pids = [p.id for p in pools]
        refs = [vloody.pool_ref(p, w) for p in pools for w in ("fee", "commission", "orphan")] + plat6
        LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_([x for x in refs if x])).delete(  # noqa: E711
            synchronize_session=False)
        ghosts = [e.user_id for e in PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).all()]
        PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).delete(synchronize_session=False)
        Pool.query.filter(Pool.id.in_(pids)).delete(synchronize_session=False)
        GiftItem.query.filter(db.or_(GiftItem.owner_id.in_(uids), GiftItem.tg_gift_id.like("a6-%"))).delete(
            synchronize_session=False)
        for model in (TonDeposit, PayoutRequest):
            model.query.filter(model.user_id.in_(uids)).delete(synchronize_session=False)
        gone = [g for g in ghosts if not db.session.get(User, g)]       # удалённые тестом игроки
        LedgerTx.query.filter(LedgerTx.user_id.in_(uids + gone)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
        db.session.commit()


clean6()
ghost_id = None


def gift6(who="a6_org"):
    _gift_n[0] += 1
    r = c.post("/api/relay/gift-deposit", headers=RELAY,
               json={"telegram_id": IDS[who], "name": f"A6 Gift #{_gift_n[0]}", "tg_gift_id": f"a6-{_gift_n[0]}-{secrets.token_hex(3)}"})
    return r.get_json()["gift"]["id"]


def pool6(body):
    r = post("a6_org", "/api/pools", body)
    p = r.get_json()
    with app.app_context():
        plat6.append(vloody.pool_ref(db.session.get(Pool, p["id"]), "fee"))
        plat6.append(vloody.pool_ref(db.session.get(Pool, p["id"]), "commission"))
    return p


for who in T6:
    get(who, "/api/profile")
setbal("a6_org", vld=0, vdt=100000)
for who in ("a6_p1", "a6_p2", "a6_ghost"):
    setbal(who, vld=1000, vdt=10000)

# ---------- 1. ставивший игрок удалён: отмена раунда не роняет каждый запрос
w6 = pool6({"mode": "wheel", "gift_id": gift6(), "min_stake": 5, "duration_min": 15})
post("a6_p1", f"/api/pools/{w6['id']}/stake", {"amount": 40})
post("a6_ghost", f"/api/pools/{w6['id']}/stake", {"amount": 60})
with app.app_context():                 # строка игрока пропала (ручная чистка БД), ставка осталась
    ghost_id = uid_of("a6_ghost")
    LedgerTx.query.filter_by(user_id=ghost_id).delete(synchronize_session=False)
    User.query.filter_by(id=ghost_id).delete(synchronize_session=False)
    p6 = db.session.get(Pool, w6["id"])
    p6.ends_at = datetime.utcnow() - timedelta(seconds=1)
    # оставляем одного «живого» участника: раунд уйдёт в отмену с возвратом
    db.session.commit()
r = get("a6_p1", "/api/profile")
check("A6: удалённый игрок в отменяемом раунде не роняет запросы", r.status_code == 200, r.status_code)
d = get("a6_p1", f"/api/pools/{w6['id']}").get_json() or {}
# ghost и p1 — двое разных: раунд разыгрывается; победителем может оказаться удалённый игрок
check("A6: раунд с удалённым игроком всё равно завершён", d.get("status") in ("finished", "cancelled"), d.get("status"))
r = get("a6_p1", "/api/pools")
check("A6: список раундов с удалённым игроком отвечает 200", r.status_code == 200, r.status_code)
r = get("a6_p1", "/api/winners")
check("A6: лента победителей с удалённым игроком отвечает 200", r.status_code == 200, r.status_code)

w7 = pool6({"mode": "wheel", "gift_id": gift6(), "min_stake": 5, "duration_min": 15})
post("a6_p1", f"/api/pools/{w7['id']}/stake", {"amount": 25})
with app.app_context():
    db.session.add(PoolEntry(pool_id=w7["id"], user_id=ghost_id, amount=30, created_at=datetime.utcnow()))
    db.session.get(Pool, w7["id"]).ends_at = datetime.utcnow() - timedelta(seconds=1)
    # p1 — единственный настоящий участник, но записей двое: даже если розыгрыш — проверяем обе ветки ниже
    db.session.commit()
p1_before = bals("a6_p1")[0]
with app.app_context():
    try:
        vloody._refund_all(db.session.get(Pool, w7["id"]), "admin"); db.session.commit(); ref_err = None
    except Exception as e:                                       # noqa: BLE001
        db.session.rollback(); ref_err = repr(e)
check("A6: _refund_all пропускает отсутствующего игрока", ref_err is None, ref_err)
check("A6: остальным ставки вернулись", bals("a6_p1")[0] == p1_before + 25, (p1_before, bals("a6_p1")))

# ---------- 1b. организатор удалён: _finish не падает, деньги не исчезают
w8 = pool6({"mode": "wheel", "gift_id": gift6(), "min_stake": 5, "duration_min": 15})
post("a6_p1", f"/api/pools/{w8['id']}/stake", {"amount": 100})
post("a6_p2", f"/api/pools/{w8['id']}/stake", {"amount": 100})
with app.app_context():
    pl = db.session.get(Pool, w8["id"])
    real_org = pl.organizer_id
    pl.organizer_id = 10 ** 9                                   # организатора нет
    db.session.commit()
    try:
        vloody._finish(db.session.get(Pool, w8["id"]), uid_of("a6_p1"), {}); db.session.commit(); fin_err = None
    except Exception as e:                                       # noqa: BLE001
        db.session.rollback(); fin_err = repr(e)
    orphan = LedgerTx.query.filter(LedgerTx.user_id == None,                       # noqa: E711
                                   LedgerTx.ref == vloody.pool_ref(db.session.get(Pool, w8["id"]), "orphan")).first()
    orphan = orphan.amount if orphan else None
    plat6.append(vloody.pool_ref(db.session.get(Pool, w8["id"]), "orphan"))
    db.session.get(Pool, w8["id"]).organizer_id = real_org
    db.session.commit()
check("A6: _finish без организатора не падает", fin_err is None, fin_err)
check("A6: доля пропавшего организатора — на счёт платформы (orphan)", orphan == 191, orphan)

# ---------- 2. живой сейф без ends_at (старые данные) всё равно закрывается через 6 часов
v6 = pool6({"mode": "vault", "gift_id": gift6(), "min_stake": 10, "vault_max": 25})
with app.app_context():
    sec6 = json.loads(db.session.get(Pool, v6["id"]).cfg)["secret"]
post("a6_p2", f"/api/pools/{v6['id']}/vault", {"number": 1 if sec6 != 1 else 2})
with app.app_context():
    pv = db.session.get(Pool, v6["id"])
    pv.ends_at, pv.created_at = None, datetime.utcnow() - timedelta(hours=7)
    db.session.commit()
r = post("a6_p1", f"/api/pools/{v6['id']}/vault", {"number": 3 if sec6 != 3 else 4})
check("A6: в просроченный сейф без ends_at ставить нельзя", r.status_code == 400, r.status_code)
d = get("a6_p2", f"/api/pools/{v6['id']}").get_json()
check("A6: сейф без ends_at старше 6 часов отменён (not_cracked)", d["status"] == "cancelled"
      and d.get("cancel_reason") == "not_cracked", (d["status"], d.get("cancel_reason")))
with app.app_context():
    pv = db.session.get(Pool, v6["id"])
    pv.status, pv.ends_at = "live", None                      # имитация старой строки для мини-миграции
    db.session.commit()
    from models import ensure_columns
    ensure_columns()
    fixed = db.session.get(Pool, v6["id"])
    mig_ok = fixed.ends_at is not None and abs((fixed.ends_at - fixed.created_at) - timedelta(hours=6)) < timedelta(seconds=1)
    fixed.status = "cancelled"
    db.session.commit()
check("A6: мини-миграция ставит ends_at = created_at + 6ч живым раундам без срока", mig_ok)

# ---------- 3. отменённый раунд: банк показан возвращённым
d = get("a6_p2", f"/api/pools/{v6['id']}").get_json()
check("A6: у отменённого раунда bank = 0 и refunded = сумма возврата", d.get("bank") == 0 and d.get("refunded") == 10,
      (d.get("bank"), d.get("refunded")))
check("A6: ставки отменённого раунда видны для прозрачности", d.get("numbers") and len(d["numbers"]) == 1, d.get("numbers"))

# ---------- 4. Stars: pre_checkout_query проверяется, а не одобряется вслепую
sent6 = []
_tg_api = vloody.tg_api
vloody.tg_api = lambda method, payload, **kw: sent6.append((method, payload)) or {"ok": True, "result": True}


def pcq(from_id, payload, amount, currency="XTR"):
    sent6.clear()
    with app.app_context():
        vloody.handle_payment_update({"pre_checkout_query": {
            "id": "pcq-1", "from": {"id": from_id}, "currency": currency, "total_amount": amount,
            "invoice_payload": payload}})
    return sent6[-1][1] if sent6 else {}


try:
    me6 = IDS["a6_pay"]
    a = pcq(me6, f"topup:{me6}:100", 100)
    check("A6: pre_checkout верного счёта -> ok", a.get("ok") is True, a)
    a = pcq(me6, f"topup:{IDS['a6_p1']}:100", 100)
    check("A6: pre_checkout чужого счёта -> отказ", a.get("ok") is False and a.get("error_message"), a)
    a = pcq(me6, f"topup:{me6}:100", 1)
    check("A6: pre_checkout с другой суммой -> отказ", a.get("ok") is False, a)
    a = pcq(me6, f"topup:{me6}:100", 100, currency="USD")
    check("A6: pre_checkout не в XTR -> отказ", a.get("ok") is False, a)
    a = pcq(me6, "garbage", 100)
    check("A6: pre_checkout с мусорным payload -> отказ", a.get("ok") is False, a)
    a = pcq(990000999, "topup:990000999:100", 100)
    check("A6: pre_checkout незнакомого игрока -> отказ", a.get("ok") is False, a)
    with app.app_context():
        User.query.filter_by(telegram_id=me6).first().is_banned = True
        db.session.commit()
    a = pcq(me6, f"topup:{me6}:100", 100)
    check("A6: pre_checkout заблокированного -> отказ", a.get("ok") is False, a)
    with app.app_context():
        User.query.filter_by(telegram_id=me6).first().is_banned = False
        db.session.commit()
finally:
    vloody.tg_api = _tg_api

# successful_payment: платит from.id — ему и зачисляем фактически оплаченное, payload не переадресует деньги
setbal("a6_pay", vld=0, vdt=0)
setbal("a6_p1", vld=0, vdt=0)
upd6 = {"message": {"from": {"id": IDS["a6_pay"]}, "successful_payment": {
    "currency": "XTR", "total_amount": 70, "invoice_payload": f"topup:{IDS['a6_p1']}:9999",
    "telegram_payment_charge_id": "a6-charge-" + secrets.token_hex(6)}}}
with app.app_context():
    r6 = vloody.handle_payment_update(upd6)
check("A6: successful_payment зачисляет плательщику фактическую сумму", r6.get("amount") == 70
      and bals("a6_pay") == (70, 0) and bals("a6_p1") == (0, 0), (r6, bals("a6_pay"), bals("a6_p1")))
for bad_amt in (0, -5, "x"):
    bad = {"message": {"from": {"id": IDS["a6_pay"]}, "successful_payment": {
        "currency": "XTR", "total_amount": bad_amt, "telegram_payment_charge_id": "a6-bad-" + secrets.token_hex(6)}}}
    with app.app_context():
        try:
            rb, eb = vloody.handle_payment_update(bad), None
        except Exception as e:                                   # noqa: BLE001
            rb, eb = None, repr(e)
    check(f"A6: successful_payment total_amount={bad_amt!r} не зачисляется и не падает",
          eb is None and rb.get("status") != "credited" and bals("a6_pay") == (70, 0), (rb, eb, bals("a6_pay")))

# ---------- 5. TON: отражённые (bounced) сообщения и возвраты не зачисляются
setbal("a6_pay", vdt=0)
with app.app_context():
    deps = []
    for _ in range(2):
        dp = TonDeposit(user_id=uid_of("a6_pay"), comment="vl" + secrets.token_hex(6), created_at=datetime.utcnow())
        db.session.add(dp); db.session.commit()
        deps.append(dp.comment)
chain6 = {"result": [
    {"transaction_id": {"hash": "a6-bounced-" + secrets.token_hex(4)},
     "in_msg": {"source": "UQsender", "value": "3000000000", "message": deps[0], "bounced": True}, "out_msgs": []},
    {"transaction_id": {"hash": "a6-returned-" + secrets.token_hex(4)},
     "in_msg": {"source": "UQsender2", "value": "3000000000", "message": deps[1]},
     "out_msgs": [{"source": "UQwallet", "destination": "UQsender2", "value": "2990000000"}]}]}
vloody.urllib.request.urlopen = lambda *a, **k: _Resp(json.dumps(chain6).encode())
vloody.TON_WALLET, vloody.TON_SCAN_EVERY = "UQ" + "T" * 46, 0
try:
    with app.app_context():
        n6 = vloody.scan_ton_deposits(force=True)
finally:
    vloody.urllib.request.urlopen, vloody.TON_WALLET, vloody.TON_SCAN_EVERY = _urlopen, _wallet, _every
check("A6: bounced и возвращённые отправителю переводы не зачислены", n6 == 0 and bals("a6_pay")[1] == 0,
      (n6, bals("a6_pay")))

# ---------- 6. сейф: гонка за одно число упирается в уникальный индекс -> 400, а не 500, деньги целы
setbal("a6_p1", vld=1000, vdt=0)
setbal("a6_p2", vld=1000, vdt=0)
v9 = pool6({"mode": "vault", "gift_id": gift6(), "min_stake": 10, "vault_max": 25})
with app.app_context():
    sec9 = json.loads(db.session.get(Pool, v9["id"]).cfg)["secret"]
n9 = 1 if sec9 != 1 else 2
post("a6_p1", f"/api/pools/{v9['id']}/vault", {"number": n9})
_taken = getattr(vloody, "_number_taken", None)
vloody._number_taken = lambda pool, number: False       # проверка «прошла» у обоих — как при гонке
try:
    r = post("a6_p2", f"/api/pools/{v9['id']}/vault", {"number": n9})
finally:
    if _taken:
        vloody._number_taken = _taken
    else:
        del vloody._number_taken
check("A6: гонка за число сейфа -> 400 «уже занято», не 500", r.status_code == 400
      and (r.get_json() or {}).get("error") == "Это число уже занято", (r.status_code, r.get_json()))
check("A6: проигравший гонку ничего не потерял", bals("a6_p2")[0] == 1000, bals("a6_p2"))

# ---------- 7. публикация в канал: короткий таймаут, без повторной попытки после таймаута
seen_to = []


def _slow(req, timeout=None, **kw):
    seen_to.append((req.full_url.rsplit("/", 1)[-1], timeout))
    raise vloody.urllib.error.URLError(TimeoutError("timed out"))


vloody.urllib.request.urlopen = _slow
try:
    with app.app_context():
        okp = vloody._tg_post("sendPhoto", {"chat_id": -1, "photo": "x"})
finally:
    vloody.urllib.request.urlopen = _urlopen
check("A6: публикация в канал с таймаутом ≤ 4 c", seen_to and all(t is not None and t <= 4 for _, t in seen_to), seen_to)
check("A6: таймаут Telegram не роняет публикацию", okp is not True, okp)

# ---------- уборка блока 6
clean6()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

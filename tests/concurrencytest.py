"""Гонки за деньги: два параллельных запроса не должны ни задвоить возврат, ни «напечатать» VLD.

Каждый сценарий детерминирован: барьер держит оба потока в точке после проверки баланса/статуса,
пока второй не дойдёт до неё же, — ровно та гонка, которую раньше ловили на живом сервере.
"""
import hashlib, hmac, json, os, sys, threading, time
from datetime import datetime, timedelta
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:TEST-TOKEN-not-real", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RELAY_SECRET="relay-s", ADMIN_SECRET="admin-s", RATE_LIMIT="100000")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, LedgerTx, GiftItem, Pool, PoolEntry, PayoutRequest  # noqa: E402
from bot import vloody                                         # noqa: E402

IDS = {"snd": 990001001, "r1": 990001002, "r2": 990001003, "org": 990001010, "pl": 990001011}
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail if not cond or detail != "" else "")


def hdr(who):
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": IDS[who], "first_name": who.title(), "username": f"cc_{who}"})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


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


def uid(who):
    with app.app_context():
        return User.query.filter_by(telegram_id=IDS[who]).first().id


def race(fn_name, gate, calls):
    """Подменяет vloody.<fn_name>: потоки, для которых gate(*args) истинно, ждут друг друга на барьере."""
    orig = getattr(vloody, fn_name)
    barrier = threading.Barrier(len(calls), timeout=3)

    def patched(*a, **kw):
        if gate(*a, **kw):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:      # второй поток уже не придёт (исправленный код) — идём дальше
                pass
        return orig(*a, **kw)

    setattr(vloody, fn_name, patched)
    results = [None] * len(calls)

    def run(i, call):
        c = app.test_client()
        try:
            results[i] = call(c)
        except Exception as e:                        # noqa: BLE001
            results[i] = e

    threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
    finally:
        setattr(vloody, fn_name, orig)
    return results


boot = app.test_client()
for who in IDS:
    boot.get("/api/profile", headers=hdr(who))

# ================================================================== 1. два перевода всего баланса
setbal("snd", vld=1000, vdt=0)
setbal("r1", vld=0, vdt=0)
setbal("r2", vld=0, vdt=0)
# fee_floor зовётся после проверки баланса и до списания — оба потока «прошли» проверку
res = race("fee_floor", lambda amount, permille: amount == 1000, [
    lambda c: c.post("/api/transfer", headers=hdr("snd"), json={"to_username": "cc_r1", "amount": 1000}),
    lambda c: c.post("/api/transfer", headers=hdr("snd"), json={"to_username": "cc_r2", "amount": 1000}),
])
codes = sorted(getattr(r, "status_code", repr(r)) for r in res)
check("два перевода всего баланса: прошёл ровно один", codes == [200, 400], codes)
loser = next((r for r in res if getattr(r, "status_code", 0) == 400), None)
check("проигравший получил «Недостаточно VLD»", loser is not None
      and (loser.get_json() or {}).get("error") == "Недостаточно VLD", loser and loser.get_json())
s, r1, r2 = bals("snd")[0], bals("r1")[0], bals("r2")[0]
check("баланс отправителя не ушёл в минус и ровно 0", s == 0, s)
check("получено ровно 900 (одна сумма за вычетом 10%)", r1 + r2 == 900, (r1, r2))
with app.app_context():
    outs = LedgerTx.query.filter_by(user_id=uid("snd"), kind="transfer_out").all()
    check("одна проводка transfer_out", len(outs) == 1, len(outs))
    fee_refs = [o.ref[:-len(":out")] + ":fee" for o in outs if o.ref]

# ================================================================== 2. два вывода всего баланса
setbal("snd", vld=1000, vdt=0)
body = {"currency": "VLD", "amount": 1000, "destination": "@cc_snd"}
res = race("fee_floor", lambda amount, permille: amount == 1000, [
    lambda c: c.post("/api/payout", headers=hdr("snd"), json=body),
    lambda c: c.post("/api/payout", headers=hdr("snd"), json=body),
])
codes = sorted(getattr(r, "status_code", repr(r)) for r in res)
check("два вывода всего баланса: прошёл ровно один", codes == [200, 400], codes)
with app.app_context():
    n = PayoutRequest.query.filter_by(user_id=uid("snd")).count()
check("заявка на вывод ровно одна, баланс 0", n == 1 and bals("snd")[0] == 0, (n, bals("snd")))

# ================================================================== 3. два settle_due одного просроченного раунда
setbal("org", vld=0, vdt=10000)
setbal("pl", vld=500, vdt=0)
g = boot.post("/api/relay/gift-deposit", headers={"X-Relay-Secret": "relay-s"},
              json={"telegram_id": IDS["org"], "name": "CC Gift", "tg_gift_id": "cc-race-1"}).get_json()["gift"]["id"]
w = boot.post("/api/pools", headers=hdr("org"),
              json={"mode": "wheel", "gift_id": g, "min_stake": 10, "duration_min": 15}).get_json()
pid = w["id"]
boot.post(f"/api/pools/{pid}/stake", headers=hdr("pl"), json={"amount": 200})
check("ставка списана", bals("pl")[0] == 300, bals("pl"))
with app.app_context():
    db.session.get(Pool, pid).ends_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
posts = []
_queue = vloody._queue_result            # постановка итога в очередь публикации — по разу на отмену
vloody._queue_result = lambda pool: posts.append(pool.id)
try:
    # deadline() зовётся в settle после чтения статуса «live» — оба потока видят живой раунд
    res = race("deadline", lambda pool: pool.id == pid, [
        lambda c: c.get(f"/api/pools/{pid}", headers=hdr("pl")),
        lambda c: c.get(f"/api/pools/{pid}", headers=hdr("org")),
    ])
finally:
    vloody._queue_result = _queue
check("оба запроса ответили 200", [getattr(r, "status_code", repr(r)) for r in res] == [200, 200],
      [getattr(r, "status_code", repr(r)) for r in res])
with app.app_context():
    refunds = LedgerTx.query.filter_by(user_id=uid("pl"), kind="refund").all()
    st = db.session.get(Pool, pid).status
check("возврат ровно один", len(refunds) == 1, len(refunds))
check("баланс игрока восстановлен ровно до 500", bals("pl")[0] == 500, bals("pl"))
check("раунд отменён", st == "cancelled", st)
check("итог «отменён» в канал — ровно один", posts.count(pid) == 1, posts)

# ================================================================== 4. двойной клик аварийной отмены
g2 = boot.post("/api/relay/gift-deposit", headers={"X-Relay-Secret": "relay-s"},
               json={"telegram_id": IDS["org"], "name": "CC Gift 2", "tg_gift_id": "cc-race-2"}).get_json()["gift"]["id"]
w2 = boot.post("/api/pools", headers=hdr("org"),
               json={"mode": "wheel", "gift_id": g2, "min_stake": 10, "duration_min": 15}).get_json()
pid2 = w2["id"]
boot.post(f"/api/pools/{pid2}/stake", headers=hdr("pl"), json={"amount": 100})
ADMIN = {"X-Admin-Secret": "admin-s"}
res = race("_refund_all", lambda pool, reason: pool.id == pid2, [
    lambda c: c.post(f"/api/admin/pools/{pid2}/refund", headers=ADMIN),
    lambda c: c.post(f"/api/admin/pools/{pid2}/refund", headers=ADMIN),
])
codes = sorted(getattr(r, "status_code", repr(r)) for r in res)
check("аварийная отмена дважды: успешна ровно одна", codes.count(200) == 1, codes)
with app.app_context():
    n = LedgerTx.query.filter(LedgerTx.user_id == uid("pl"), LedgerTx.kind == "refund",
                              LedgerTx.title.like(f"%раунд #{pid2} %")).count()
check("возврат по аварийной отмене ровно один", n == 1 and bals("pl")[0] == 500, (n, bals("pl")))

# ================================================================== уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_(list(IDS.values()))).all()
    uids = [x.id for x in users]
    for p in Pool.query.filter(Pool.organizer_id.in_(uids)).all():
        LedgerTx.query.filter(LedgerTx.user_id == None,                         # noqa: E711
                              LedgerTx.ref.like(vloody.pool_ref(p, "") + "%")).delete(synchronize_session=False)
        PoolEntry.query.filter_by(pool_id=p.id).delete(synchronize_session=False)
        db.session.delete(p)
    if fee_refs:
        LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_(fee_refs)).delete(  # noqa: E711
            synchronize_session=False)
    GiftItem.query.filter(GiftItem.owner_id.in_(uids)).delete(synchronize_session=False)
    PayoutRequest.query.filter(PayoutRequest.user_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

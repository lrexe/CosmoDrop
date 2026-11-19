"""Фаза 1, задача 1: две валюты (VLD и VDT), раздельный учёт."""
import hashlib, hmac, json, os, sys, time
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:TEST-TOKEN-not-real", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RELAY_SECRET="relay-s", ADMIN_SECRET="admin-s", RATE_LIMIT="100000")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, LedgerTx                          # noqa: E402
from bot import vloody                                         # noqa: E402

IDS = {"ann": 990000901}
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

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

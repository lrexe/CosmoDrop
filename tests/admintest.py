"""Проверка админ-API в боевом режиме."""
import hashlib, hmac, json, os, sys, time
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="", RATE_LIMIT="100000",
                  ADMIN_SECRET="admin-s", RELAY_SECRET="relay-s")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
import bot.vloody as V                                         # noqa: E402
from models import db, User, GiftItem, Pool, PoolEntry, LedgerTx, PayoutRequest  # noqa: E402

ORG, P1, P2 = 990000401, 990000402, 990000403
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def hdr(tid, name):
    f = {"auth_date": str(int(time.time())), "user": json.dumps({"id": tid, "first_name": name, "username": name})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    sec = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(f)}


c = app.test_client()
O, A, B = hdr(ORG, "adm_org"), hdr(P1, "adm_p1"), hdr(P2, "adm_p2")
ADM = {"X-Admin-Secret": "admin-s"}
bal = lambda h: c.get("/api/profile", headers=h).get_json()["balance"]
aget = lambda path: c.get("/api/admin/" + path, headers=ADM)
apost = lambda path, body=None: c.post("/api/admin/" + path, headers=ADM, json=body or {})
for h in (O, A, B):
    bal(h)
with app.app_context():
    for tid in (P1, P2):
        User.query.filter_by(telegram_id=tid).first().stars_balance = 1000
    User.query.filter_by(telegram_id=ORG).first().vdt_balance = 1000      # сбор 0.1 VDT за запуск раунда
    db.session.commit()
    rev0 = V._sum(LedgerTx.amount, LedgerTx.user_id == None, LedgerTx.kind == "commission")  # noqa: E711

# ---------- доступ
check("страница /admin открывается и не индексируется",
      c.get("/admin").status_code == 200 and "noindex" in c.get("/admin").headers.get("X-Robots-Tag", ""))
check("страница /admin — настоящий шаблон: форма входа и vl-tokens.css (а не просто 200)",
      b'id="login"' in c.get("/admin").data and b"css/vl-tokens.css" in c.get("/admin").data)
check("страница не содержит секретов", b"admin-s" not in c.get("/admin").data)
paths = ["stats", "payouts", "pools", "users", f"users/{P1}", "gifts", "revenue"]
check("все разделы без секрета -> 403", all(c.get("/api/admin/" + p).status_code == 403 for p in paths))
V._admin_fails.clear()
check("слово «demo» в боевом режиме не подходит", c.get("/api/admin/stats", headers={"X-Admin-Secret": "demo"}).status_code == 403)
check("секрет игрока (initData) не даёт доступа", c.get("/api/admin/stats", headers=A).status_code == 403)
V._admin_fails.clear()
check("с секретом все разделы отвечают", all(aget(p).status_code == 200 for p in paths),
      [aget(p).status_code for p in paths])

# ---------- аварийная отмена раунда
g = c.post("/api/relay/gift-deposit", headers={"X-Relay-Secret": "relay-s"},
           json={"telegram_id": ORG, "name": "Admin Test Gift", "tg_gift_id": "adm-g1"}).get_json()["gift"]
pool = c.post("/api/pools", headers=O, json={"mode": "wheel", "gift_id": g["id"], "min_stake": 5, "duration_min": 60}).get_json()
c.post(f"/api/pools/{pool['id']}/stake", headers=A, json={"amount": 300})
c.post(f"/api/pools/{pool['id']}/stake", headers=B, json={"amount": 200})
c.post(f"/api/pools/{pool['id']}/stake", headers=A, json={"amount": 100})
row = next(p for p in aget("pools?status=live").get_json()["items"] if p["id"] == pool["id"])
check("раунд виден в админке с банком и участниками", row["bank"] == 600 and row["participants"] == 2 and row["entries"] == 3, row)
r = c.post(f"/api/admin/pools/{pool['id']}/refund", headers=A)
check("игрок не может отменить раунд через админ-API", r.status_code == 403, r.status_code)
V._admin_fails.clear()
r = apost(f"pools/{pool['id']}/refund").get_json()
check("отмена с возвратом: возвращено 600", r.get("refunded") == 600, r)
check("ставки вернулись игрокам полностью", bal(A) == 1000 and bal(B) == 1000, (bal(A), bal(B)))
gifts = c.get("/api/inventory/gifts", headers=O).get_json()["gifts"]
check("подарок вернулся организатору", gifts and gifts[0]["status"] == "held", gifts)
check("организатор ничего не получил", bal(O) == 0, bal(O))
with app.app_context():
    rev1 = V._sum(LedgerTx.amount, LedgerTx.user_id == None, LedgerTx.kind == "commission")  # noqa: E711
check("комиссия с отменённого раунда не взята", rev1 == rev0, (rev0, rev1))
check("повторная отмена -> 404", apost(f"pools/{pool['id']}/refund").status_code == 404)
st = c.get(f"/api/pools/{pool['id']}", headers=A).get_json()["status"]
check("раунд помечен отменённым", st == "cancelled", st)

# ---------- блокировка
r = apost(f"users/{P1}", {"action": "ban"}).get_json()
check("игрок заблокирован", r["banned"] is True)
pool2 = c.post("/api/pools", headers=O, json={"mode": "wheel", "gift_id": g["id"], "min_stake": 5, "duration_min": 60}).get_json()
codes = [c.post(f"/api/pools/{pool2['id']}/stake", headers=A, json={"amount": 50}).status_code,
         c.post("/api/transfer", headers=A, json={"to_username": "adm_p2", "amount": 200}).status_code,
         c.post("/api/payout", headers=A, json={"amount": 200, "destination": "@xyz", "method": "STARS"}).status_code]
check("заблокированный не может ставить, переводить и выводить", codes == [403, 403, 403] and bal(A) == 1000, codes)
r = c.post("/api/transfer", headers=B, json={"to_username": "adm_p1", "amount": 200})
check("заблокированному нельзя перевести", r.status_code == 404 and bal(B) == 1000, r.status_code)
apost(f"users/{P1}", {"action": "unban"})
r = c.post(f"/api/pools/{pool2['id']}/stake", headers=A, json={"amount": 50})
check("после разблокировки ставка проходит", r.status_code == 200 and bal(A) == 950, r.status_code)
check("неизвестное действие -> 400", apost(f"users/{P1}", {"action": "give_money"}).status_code == 400)

# ---------- поиск и карточка
items = aget(f"users?q={P1}").get_json()["items"]
check("поиск по Telegram ID", len(items) == 1 and items[0]["telegram_id"] == P1)
items = aget("users?q=@adm_p").get_json()["items"]
check("поиск по @username", {u["telegram_id"] for u in items} == {P1, P2}, [u["name"] for u in items])
card = aget(f"users/{P1}").get_json()
kinds = [x["kind"] for x in card["ledger"]]
check("в карточке игрока видна история: ставки и возврат", "refund" in kinds and "stake" in kinds and card["balance"] == 950, kinds)

# ---------- выводы и статистика
q = c.post("/api/payout", headers=B, json={"amount": 500, "destination": "@adm_p2", "method": "STARS"}).get_json()["request"]
s = aget("stats").get_json()
check("статистика видит заявку и банк живого раунда",
      s["counts"]["pending_payouts"] >= 1 and s["liabilities"]["pending_payouts"] >= 500
      and s["liabilities"]["locked_in_live_pools"] >= 50, s["liabilities"])
lst = aget("payouts?status=pending").get_json()["items"]
check("заявка в списке ожидающих с данными игрока", any(x["id"] == q["id"] and x["telegram_id"] == P2 for x in lst))
apost(f"payouts/{q['id']}", {"action": "paid"})
s2 = aget("stats").get_json()
check("после выплаты комиссия вывода 13.5% (67 из 500) попала в доход",
      s2["revenue"]["by_source"]["payouts"] - s["revenue"]["by_source"]["payouts"] == 67, s2["revenue"])
check("выплаченная заявка ушла из ожидающих", all(x["id"] != q["id"] for x in aget("payouts").get_json()["items"]))
check("и видна в выплаченных", any(x["id"] == q["id"] for x in aget("payouts?status=paid").get_json()["items"]))

# ---------- перебор секрета (в конце: блокирует IP)
V._admin_fails.clear()
codes = [c.get("/api/admin/stats", headers={"X-Admin-Secret": f"guess{i}"}).status_code for i in range(12)]
check("после 10 неверных попыток — блокировка", codes[:10] == [403] * 10 and codes[10:] == [429, 429], codes)
check("во время блокировки не пускает даже верный секрет", aget("stats").status_code == 429)
V._admin_fails.clear()
check("после снятия блокировки верный секрет работает", aget("stats").status_code == 200)

# ---------- уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_([ORG, P1, P2])).all()
    uids = [u.id for u in users]
    pools = Pool.query.filter(Pool.organizer_id.in_(uids)).all()
    pids = [p.id for p in pools]
    pool_refs = [V.pool_ref(p, w) for p in pools for w in ("fee", "commission")]
    found = LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_(pool_refs)).count()  # noqa: E711
    LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref.in_(pool_refs)).delete(synchronize_session=False)  # noqa: E711
    PoolEntry.query.filter(PoolEntry.pool_id.in_(pids)).delete(synchronize_session=False)
    Pool.query.filter(Pool.id.in_(pids)).delete(synchronize_session=False)
    GiftItem.query.filter(GiftItem.owner_id.in_(uids)).delete(synchronize_session=False)
    fee_ref = V.payout_ref(db.session.get(PayoutRequest, q["id"]), "fee")
    PayoutRequest.query.filter(PayoutRequest.user_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id.in_(uids)).delete(synchronize_session=False)
    LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.ref == fee_ref).delete(synchronize_session=False)  # noqa: E711
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()
check("уборка: сборы за запуск обоих раундов найдены по ключу и удалены", found == 2, found)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

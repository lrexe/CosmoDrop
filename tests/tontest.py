"""Проверка TON (-> VDT) и Stars (-> VLD) на ИМИТАЦИИ блокчейн-API (настоящая сеть TON не участвует)."""
import base64, hashlib, hmac, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

WALLET = "UQ" + "A" * 46
os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="", RATE_LIMIT="100000",
                  ADMIN_SECRET="admin-s", TELEGRAM_WEBHOOK_SECRET="hook-s",
                  TON_WALLET_ADDRESS=WALLET, TON_API_BASE="http://127.0.0.1:5079/api/v2")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
import bot.vloody as V                                         # noqa: E402
from models import db, User, LedgerTx, PayoutRequest, TonDeposit  # noqa: E402

V.TON_SCAN_EVERY = 0
ANN, BEN = 990000301, 990000302
ok = True
chain = {"txs": [], "down": False, "calls": 0}


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        chain["calls"] += 1
        q = parse_qs(urlparse(self.path).query)
        if chain["down"] or q.get("address") != [WALLET]:
            self.send_response(500); self.end_headers(); return
        raw = json.dumps({"ok": True, "result": chain["txs"]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 5079), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def tx(h, ton, comment, source="UQsender", as_data=False):
    msg = {"source": source, "destination": WALLET, "value": str(int(ton * 1e9))}
    if as_data:
        msg["msg_data"] = {"@type": "msg.dataText", "text": base64.b64encode(comment.encode()).decode()}
    else:
        msg["message"] = comment
    chain["txs"].insert(0, {"transaction_id": {"lt": "1", "hash": h}, "in_msg": msg, "out_msgs": []})


def hdr(tid, name):
    f = {"auth_date": str(int(time.time())), "user": json.dumps({"id": tid, "first_name": name, "username": name})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    sec = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(f)}


c = app.test_client()
A, B = hdr(ANN, "ann"), hdr(BEN, "ben")
prof = lambda h: c.get("/api/profile", headers=h).get_json()
bal = lambda h: prof(h)["balance"]
vdt = lambda h: prof(h)["balances"]["VDT"]          # милли-VDT
post = lambda h, url, body=None: c.post(url, headers=h, json=body or {})
ADMIN = {"X-Admin-Secret": "admin-s"}
bal(A); bal(B)

# ---------- депозит TON
r = post(A, "/api/wallet/ton/intent", {"amount_ton": 0.1})
check("депозит ниже минимума -> отказ", r.status_code == 400, r.status_code)
i1 = post(A, "/api/wallet/ton/intent", {"amount_ton": 2}).get_json()
check("выдан адрес платформы и уникальный комментарий",
      i1["address"] == WALLET and i1["comment"].startswith("vl") and i1["will_credit"] == 2000 and i1["currency"] == "VDT" and not i1["demo"], i1)
check("ссылка для кошелька содержит сумму и комментарий",
      i1["link"] == f"ton://transfer/{WALLET}?amount=2000000000&text={i1['comment']}", i1["link"])
r = post(A, "/api/wallet/ton/check", {"deposit_id": i1["deposit_id"]}).get_json()
check("пока перевода нет — ничего не зачислено", r["status"] == "pending" and vdt(A) == 0 and bal(A) == 0, r)
r = post(B, "/api/wallet/ton/check", {"deposit_id": i1["deposit_id"]})
check("чужое пополнение проверить нельзя", r.status_code == 404, r.status_code)
r = post(A, "/api/wallet/ton/demo-pay", {"deposit_id": i1["deposit_id"], "amount_nano": 10**12})
check("имитация оплаты в боевом режиме -> 403", r.status_code == 403 and vdt(A) == 0, r.status_code)

tx("h-unknown", 5, "vlffffffffffff")                       # чужой/неизвестный комментарий
tx("h-nocomment", 5, "")
tx("h-small", 0.2, i1["comment"])                          # меньше минимума
post(A, "/api/wallet/ton/check", {"deposit_id": i1["deposit_id"]})
check("неизвестный комментарий, пустой и слишком маленький перевод не зачислены", vdt(A) == 0 and bal(A) == 0, vdt(A))

tx("h-good", 2.5, i1["comment"])                           # прислал 2.5 вместо 2
r = post(A, "/api/wallet/ton/check", {"deposit_id": i1["deposit_id"]}).get_json()
check("зачислено по факту пришедшей суммы: 2.5 TON = 2.5 VDT (2500 милли), VLD не тронут",
      r["status"] == "credited" and r["credited"] == 2500 and vdt(A) == 2500 and bal(A) == 0, r)
for _ in range(3):
    post(A, "/api/wallet/ton/check", {"deposit_id": i1["deposit_id"]})
c.post("/api/admin/ton/scan", headers=ADMIN)
check("повторные сверки не зачисляют ту же транзакцию дважды", vdt(A) == 2500, vdt(A))

tx("h-again", 1, i1["comment"])
c.post("/api/admin/ton/scan", headers=ADMIN)
check("повторный перевод с тем же комментарием тоже зачислен", vdt(A) == 3500, vdt(A))

i2 = post(B, "/api/wallet/ton/intent", {"amount_ton": 1}).get_json()
tx("h-data", 1, i2["comment"], source="UQsomeoneElse", as_data=True)
chain["down"] = True
r = post(B, "/api/wallet/ton/check", {"deposit_id": i2["deposit_id"]}).get_json()
check("блокчейн-API недоступен: без ошибки, депозит ждёт", r["status"] == "pending" and vdt(B) == 0, r)
chain["down"] = False
check("депозит найден при следующем заходе в профиль (base64-комментарий)", vdt(B) == 1000 and bal(B) == 0, vdt(B))
check("комментарии разных игроков не пересекаются", i1["comment"] != i2["comment"] and vdt(A) == 3500)
r = c.post("/api/admin/ton/scan")
check("принудительная сверка без секрета админа -> 403", r.status_code == 403, r.status_code)

# ---------- покупка VLD за звёзды
HOOK = {"X-Telegram-Bot-Api-Secret-Token": "hook-s"}
pay = {"message": {"from": {"id": BEN}, "successful_payment": {
    "currency": "XTR", "total_amount": 200, "telegram_payment_charge_id": "charge-1"}}}
c.post("/api/telegram_payment", headers=HOOK, json=pay)
check("200 Stars -> 200 VLD, VDT не тронут", bal(B) == 200 and vdt(B) == 1000, bal(B))
c.post("/api/telegram_payment", headers=HOOK, json=pay)
check("повтор того же платежа не зачисляется", bal(B) == 200, bal(B))
r = c.post("/api/telegram_payment", json=pay)
check("вебхук оплаты без секрета -> 403", r.status_code == 403, r.status_code)

# ---------- вывод в TON (из VDT)
r = post(A, "/api/payout", {"amount": 2500, "destination": "not-an-address", "currency": "VDT"})
check("вывод на некорректный TON-адрес -> отказ", r.status_code == 400, r.status_code)
r = post(A, "/api/payout", {"amount": 2500, "destination": "@ann", "method": "BTC"})
check("неизвестный способ вывода -> отказ", r.status_code == 400, r.status_code)
dest = "EQ" + "B" * 46
r = post(A, "/api/payout", {"amount": 3000, "destination": dest, "currency": "VDT"}).get_json()
q = r["request"]
check("вывод TON: списано 3 VDT, комиссия 11.5%, к выплате 2.655 TON",
      vdt(A) == 500 and q["commission"] == 345 and q["net"] == 2655 and q["currency"] == "VDT"
      and q["method"] == "TON" and abs(q["net_ton"] - 2.655) < 1e-9, q)
lst = c.get("/api/admin/payouts", headers=ADMIN).get_json()["items"]
mine = next(x for x in lst if x["id"] == q["id"])
check("в админке сумма к выплате в TON и адрес", abs(mine["net_ton"] - 2.655) < 1e-9 and mine["destination"] == dest
      and mine["currency"] == "VDT", mine)
c.post(f"/api/admin/payouts/{q['id']}", headers=ADMIN, json={"action": "reject"})
check("отклонённый вывод возвращён полностью в VDT", vdt(A) == 3500 and bal(A) == 0, (vdt(A), bal(A)))
r = post(B, "/api/payout", {"amount": 200, "destination": "@ben", "method": "STARS"})
check("вывод в Stars ниже 275 VLD -> отказ", r.status_code == 400, r.status_code)
c.post("/api/telegram_payment", headers=HOOK, json={"message": {"from": {"id": BEN}, "successful_payment": {
    "currency": "XTR", "total_amount": 100, "telegram_payment_charge_id": "charge-2"}}})
r = post(B, "/api/payout", {"amount": 300, "destination": "@ben", "method": "STARS"}).get_json()
check("вывод в Stars: комиссия 13.5%", r["request"]["commission"] == 40 and r["request"]["net"] == 260
      and r["request"]["currency"] == "VLD" and bal(B) == 0 and vdt(B) == 1000, r["request"])

rates = prof(A)["rates"]
check("клиент получает курсы", rates == {"stars_to_vld": 1, "ton_to_vdt": 1, "vld_per_ton": 1, "ton_min": 0.5,
                                         "ton_enabled": True}, rates)

# ---------- уборка
with app.app_context():
    users = User.query.filter(User.telegram_id.in_([ANN, BEN])).all()
    uids = [u.id for u in users]
    for model in (TonDeposit, PayoutRequest, LedgerTx):
        model.query.filter(model.user_id.in_(uids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(uids)).delete(synchronize_session=False)
    db.session.commit()
srv.shutdown()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

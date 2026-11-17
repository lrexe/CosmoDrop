"""Сервис картинок NFT-подарков на ПОДДЕЛЬНОМ CDN (настоящий nft.fragment.com не вызывается)."""
import os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RATE_LIMIT="100000", GIFT_CDN_BASE="http://127.0.0.1:5082")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, GiftItem                          # noqa: E402
from bot import giftart                                        # noqa: E402

OWNER = 990000300
ok = True
JPG = b"\xff\xd8\xff\xe0" + b"J" * 100
JSON = b'{"v":"5.7","layers":[]}'
hits = []
trap_hits = []


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


class CDN(BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        p = self.path
        if "testgift-7." in p:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:5084/evil.medium.jpg")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if "testgift-1." in p:
            body, ctype, code = (JSON, "application/json", 200) if p.endswith(".json") else (JPG, "image/jpeg", 200)
        elif "testgift-3." in p:
            body, ctype, code = b"<html>nope</html>", "text/html", 200
        elif "testgift-4." in p:
            body, ctype, code = b"X" * (1024 * 1024 + 1), "image/jpeg", 200
        else:
            body, ctype, code = b"<html>404</html>", "text/html", 404
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 5082), CDN)
threading.Thread(target=srv.serve_forever, daemon=True).start()


class Trap(BaseHTTPRequestHandler):
    def do_GET(self):
        trap_hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(JPG)))
        self.end_headers()
        self.wfile.write(JPG)

    def log_message(self, *a):
        pass


trap = HTTPServer(("127.0.0.1", 5084), Trap)
threading.Thread(target=trap.serve_forever, daemon=True).start()

SLUGS = [f"testgift-{i}" for i in (1, 2, 3, 4, 5, 6, 7)]
cache_dir = os.path.join(ROOT, "instance", "gift_cache")


def cleanup():
    with app.app_context():
        me = User.query.filter_by(telegram_id=OWNER).first()
        if me:
            GiftItem.query.filter_by(owner_id=me.id).delete(synchronize_session=False)
            db.session.delete(me)
        GiftItem.query.filter(GiftItem.slug.in_(SLUGS)).delete(synchronize_session=False)
        db.session.commit()
    for s in SLUGS:
        for ext in ("jpg", "webp", "json"):
            try:
                os.remove(os.path.join(cache_dir, f"{s}.{ext}"))
            except OSError:
                pass


cleanup()
with app.app_context():
    u = User(telegram_id=OWNER, first_name="art-test")
    db.session.add(u); db.session.flush()
    for s in SLUGS:
        db.session.add(GiftItem(owner_id=u.id, name="T " + s, slug=s, status="held"))
    db.session.add(GiftItem(owner_id=u.id, name="no slug", status="held"))
    db.session.commit()

c = app.test_client()
try:
    # to_dict
    with app.app_context():
        d = GiftItem.query.filter_by(slug="testgift-1").first().to_dict()
        nd = GiftItem.query.filter_by(name="no slug").first().to_dict()
    check("to_dict has image/anim and keeps art", d["image"] == "/gift-art/testgift-1.jpg"
          and d["anim"] == "/gift-art/testgift-1.json" and "art" in d, d)
    check("to_dict without slug -> None", nd["image"] is None and nd["anim"] is None)

    r = c.get("/gift-art/testgift-1.jpg")
    path = os.path.join(cache_dir, "testgift-1.jpg")
    check("valid slug in db -> 200 image/jpeg and cached on disk",
          r.status_code == 200 and r.mimetype == "image/jpeg" and r.data == JPG
          and "max-age=86400" in r.headers.get("Cache-Control", "") and os.path.isfile(path),
          (r.status_code, r.mimetype))
    n = len(hits)
    r = c.get("/gift-art/testgift-1.jpg")
    check("second request does not hit CDN", r.status_code == 200 and r.data == JPG and len(hits) == n == 1, len(hits))

    n = len(hits)
    r = c.get("/gift-art/testgift-9.jpg")
    check("slug not in db -> 404 and CDN counter unchanged",
          r.status_code == 404 and r.get_json() == {"error": "not found"} and len(hits) == n)

    n = len(hits)
    codes = [c.get(u).status_code for u in (
        "/gift-art/..%2Fetc%2Fpasswd.jpg", "/gift-art/PLUSHPEPE-1.jpg", "/gift-art/plushpepe-99999999.jpg",
        "/gift-art/a-1.jpg", "/gift-art/.jpg", "/gift-art/testgift-1.exe", "/gift-art/testgift-1.png")]
    check("bad slugs/ext -> 404 and no outbound request", codes == [404] * 7 and len(hits) == n, codes)

    n = len(hits)
    r1 = c.get("/gift-art/testgift-2.jpg")
    r2 = c.get("/gift-art/testgift-2.jpg")
    check("CDN 404 -> our 404, repeat within 10 min does not re-hit CDN",
          r1.status_code == 404 and r2.status_code == 404 and len(hits) == n + 1, len(hits) - n)

    os.environ["GIFT_CDN_BASE"] = "http://127.0.0.1:5099"      # никто не слушает
    try:
        r = c.get("/gift-art/testgift-6.jpg")
        check("CDN down -> 404, no exception", r.status_code == 404, r.status_code)
    finally:
        os.environ["GIFT_CDN_BASE"] = "http://127.0.0.1:5082"

    n = len(hits)
    r3, r4 = c.get("/gift-art/testgift-3.jpg"), c.get("/gift-art/testgift-4.jpg")
    check("CDN text/html or >1 MB -> 404 and nothing cached",
          r3.status_code == 404 and r4.status_code == 404 and len(hits) == n + 2
          and not os.path.exists(os.path.join(cache_dir, "testgift-3.jpg"))
          and not os.path.exists(os.path.join(cache_dir, "testgift-4.jpg")))
    left = [f for f in (os.listdir(cache_dir) if os.path.isdir(cache_dir) else []) if ".tmp" in f or f.startswith("tmp")]
    check("no temp files left behind", not left, left)

    n = len(hits)
    r = c.get("/gift-art/testgift-7.jpg")
    r2 = c.get("/gift-art/testgift-7.jpg")
    check("CDN redirect is never followed -> 404, target got 0 hits, nothing cached",
          r.status_code == 404 and r2.status_code == 404 and not trap_hits and len(hits) == n + 1
          and not os.path.exists(os.path.join(cache_dir, "testgift-7.jpg")), (trap_hits, len(hits) - n))

    r = c.get("/gift-art/testgift-1.json")
    check("ext=json returns application/json", r.status_code == 200 and r.mimetype == "application/json"
          and r.data == JSON, (r.status_code, r.mimetype))
    check("get_art direct call", giftart.get_art("testgift-1", "jpg") == (JPG, "image/jpeg")
          and giftart.get_art("../x-1", "jpg") is None and giftart.get_art("testgift-1", "png") is None)
finally:
    cleanup()
    srv.shutdown()
    trap.shutdown()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

"""Сервис картинок NFT-подарков на ПОДДЕЛЬНОМ CDN (настоящий nft.fragment.com не вызывается)."""
import hashlib, hmac, json, os, sys, threading, time
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.update(BOT_TOKEN="123456:MAIN-TEST", SECRET_KEY="x" * 32, DEMO_MODE="",
                  RATE_LIMIT="100000", GIFT_CDN_BASE="http://127.0.0.1:5082",
                  TELEGRAM_API_BASE="http://127.0.0.1:5083")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from app import app                                            # noqa: E402
from models import db, User, GiftItem                          # noqa: E402
from bot import giftart                                        # noqa: E402

OWNER = 990000300
ok = True
JPG = b"\xff\xd8\xff\xe0" + b"J" * 100
JSON = b'{"v":"5.7","fr":60,"layers":[]}'
# lottie с числовыми "x" (кривые сглаживания) — легальный; со строкой в "x" — это выражение (исполняется через eval)
JSON_OK_X = b'{"v":"5.7","fr":30,"layers":[{"ks":{"o":{"k":[{"o":{"x":[0.5],"y":[0]},"t":0}]}}}]}'
JSON_EXPR = b'{"v":"5.7","fr":30,"layers":[{"ks":{"p":{"a":0,"x":"var $bm_rt = 1;","k":[0,0]}}}]}'
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
        if "testgift-10." in p:
            body, ctype, code = JSON_OK_X, "application/json", 200
        elif "testgift-11." in p:
            body, ctype, code = JSON_EXPR, "application/json", 200
        elif "testgift-12." in p:
            body, ctype, code = b"this is not json", "application/json", 200
        elif "testgift-1." in p:
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

# ---- поддельный Bot API (настоящий Telegram не вызывается) ----
GID_A, GID_B, GID_C = "5170145012310081615", "5170233102089322756", "5170250947678437525"
WEBP = b"RIFF" + (100).to_bytes(4, "little") + b"WEBP" + b"W" * 100
api_hits = {"gifts": 0, "getfile": 0, "file": 0}
api_paths = []
api_mode = {"fail": False}
THUMBS = {"thumb-A": "thumbnails/file_1.webp", "thumb-B": "stickers/file_2.tgs", "thumb-C": "thumbnails/file_3.webp"}
# вредоносные file_path от «Telegram»: попадают в каталог только на время отдельной проверки (EXTRA)
BAD_PATHS = ["../x.webp", "/abs/x.webp", "http://evil.example/x.webp", "a/b?x=1.webp", "x.tgs"]
EXTRA = {}
for _i, _bp in enumerate(BAD_PATHS):
    THUMBS[f"thumb-bad{_i}"] = _bp
BAD_GIDS = [str(5170000000000000000 + _i) for _i in range(len(BAD_PATHS))]


class BotApi(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        api_paths.append(path)
        if "/getAvailableGifts" in path:
            api_hits["gifts"] += 1
            if api_mode["fail"]:
                return self._send(500, b'{"ok":false}')
            gifts = [{"id": g, "star_count": n, "sticker": {"file_id": "x", "emoji": e, "is_animated": True,
                                                            "thumbnail": {"file_id": t}}}
                     for g, n, e, t in ((GID_A, 15, "\U0001F9F8", "thumb-A"), (GID_B, 25, "\U0001F339", "thumb-B"),
                                        (GID_C, 50, "\U0001F381", "thumb-C"))]
            if EXTRA:
                gifts += [{"id": g, "star_count": 5, "sticker": {"file_id": "x", "emoji": "?", "thumbnail": {"file_id": t}}}
                          for g, t in EXTRA.items()]
            return self._send(200, json.dumps({"ok": True, "result": {"gifts": gifts}}).encode())
        if "/getFile" in path:
            api_hits["getfile"] += 1
            fid = query.split("file_id=")[-1]
            if fid not in THUMBS:
                return self._send(400, b'{"ok":false}')
            return self._send(200, json.dumps({"ok": True, "result": {"file_path": THUMBS[fid]}}).encode())
        if "/file/bot" in path:
            api_hits["file"] += 1
            if path.endswith("file_3.webp"):
                return self._send(200, b"RIFF" + b"X" * (200 * 1024 + 1), "application/octet-stream")
            return self._send(200, WEBP, "application/octet-stream")
        self._send(404, b"{}")

    def log_message(self, *a):
        pass


botapi = HTTPServer(("127.0.0.1", 5083), BotApi)
threading.Thread(target=botapi.serve_forever, daemon=True).start()


def hdr():
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": OWNER, "first_name": "art-test"})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


SLUGS = [f"testgift-{i}" for i in (1, 2, 3, 4, 5, 6, 7, 10, 11, 12)]
cache_dir = os.path.join(ROOT, "instance", "gift_cache")


def cleanup():
    with app.app_context():
        me = User.query.filter_by(telegram_id=OWNER).first()
        if me:
            GiftItem.query.filter_by(owner_id=me.id).delete(synchronize_session=False)
            db.session.delete(me)
        GiftItem.query.filter(GiftItem.slug.in_(SLUGS)).delete(synchronize_session=False)
        db.session.commit()
    names = [f"{s}.{ext}" for s in SLUGS for ext in ("jpg", "webp", "json")]
    names += [f"regular-{g}.webp" for g in (GID_A, GID_B, GID_C, *BAD_GIDS)]
    for n in names:
        try:
            os.remove(os.path.join(cache_dir, n))
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
    # ---- индекс gift_items.slug (в том числе в «старой» БД, где колонку добавил ensure_columns) ----
    from models import ensure_columns
    def slug_idx():
        with app.app_context():
            return [i["name"] for i in db.inspect(db.engine).get_indexes("gift_items") if i["column_names"] == ["slug"]]
    check("gift_items.slug index exists after app start", slug_idx() != [], slug_idx())
    with app.app_context():
        for nm in slug_idx():
            db.session.execute(db.text(f"DROP INDEX {nm}"))
        db.session.commit()
    check("(index dropped for the upgrade scenario)", slug_idx() == [])
    with app.app_context():
        ensure_columns()
    check("ensure_columns recreates ix_gift_items_slug on an upgraded DB", "ix_gift_items_slug" in slug_idx(), slug_idx())
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
    # ---- безопасность lottie JSON (выражения исполняются через eval в полной сборке lottie) ----
    r = c.get("/gift-art/testgift-10.json")
    check("valid lottie json (numeric x easing handles) -> 200 and cached",
          r.status_code == 200 and r.mimetype == "application/json" and r.data == JSON_OK_X
          and os.path.isfile(os.path.join(cache_dir, "testgift-10.json")), r.status_code)
    r = c.get("/gift-art/testgift-11.json")
    check("lottie json with an expression string in 'x' -> 404 and not cached",
          r.status_code == 404 and not os.path.exists(os.path.join(cache_dir, "testgift-11.json")), r.status_code)
    r = c.get("/gift-art/testgift-12.json")
    check("non-JSON body with a json content type -> 404 and not cached",
          r.status_code == 404 and not os.path.exists(os.path.join(cache_dir, "testgift-12.json")), r.status_code)
    check("_safe_lottie: missing keys, non-object, deep nesting handled",
          not giftart._safe_lottie(b'{"v":"5","layers":[]}') and not giftart._safe_lottie(b"[1,2]")
          and giftart._safe_lottie(b'{"v":"5","fr":1,"layers":[]}')
          and not giftart._safe_lottie(b'{"v":"5","fr":1,"layers":' + b"[" * 100000 + b"]" * 100000 + b"}")
          and not giftart._safe_lottie(b'{"v":"5","fr":1,"layers":' + b'{"a":' * 3000 + b'{"x":"e"}' + b"}" * 3000 + b"}"))
    # ---- slug: fullmatch + ASCII ----
    n = len(hits)
    codes = [c.get(u).status_code for u in ("/gift-art/testgift-1%0A.jpg", "/gift-art/testgift-%D9%A3.jpg",
                                            "/gift-art/testgift-1%0A.json")]
    direct = [giftart.get_art(sl, "jpg") for sl in ("testgift-1\n", "testgift-\u0663", "testgift-\u0663\n")]
    check("trailing newline / Arabic-Indic digit in slug -> 404 and no outbound request",
          codes == [404] * 3 and direct == [None] * 3 and len(hits) == n, (codes, direct, len(hits) - n))
    check("get_art direct call", giftart.get_art("testgift-1", "jpg") == (JPG, "image/jpeg")
          and giftart.get_art("../x-1", "jpg") is None and giftart.get_art("testgift-1", "png") is None)
    # ---- обычные подарки за Stars ----
    giftart._cat["at"], giftart._cat["items"] = 0, None
    api_hits.update(gifts=0, getfile=0, file=0)
    r = c.get("/api/gifts/catalog", headers=hdr())
    j = r.get_json() or {}
    check("catalog lists gifts with image urls", r.status_code == 200 and j.get("items") == [
        {"id": g, "stars": n, "image": f"/gift-art/regular/{g}.webp"}
        for g, n in ((GID_A, 15), (GID_B, 25), (GID_C, 50))], j)
    check("catalog requires auth (401 without initData)", c.get("/api/gifts/catalog").status_code == 401)
    check("regular_catalog elements have id/stars/emoji", giftart.regular_catalog()[0] == {
        "id": GID_A, "stars": 15, "emoji": "\U0001F9F8"})
    c.get("/api/gifts/catalog", headers=hdr())
    check("catalog cached (one getAvailableGifts call for two requests)", api_hits["gifts"] == 1, api_hits)

    r = c.get(f"/gift-art/regular/{GID_A}.webp")
    check("regular image served as image/webp and cached on disk",
          r.status_code == 200 and r.mimetype == "image/webp" and r.data == WEBP
          and os.path.isfile(os.path.join(cache_dir, f"regular-{GID_A}.webp")), (r.status_code, r.mimetype))
    r = c.get(f"/gift-art/regular/{GID_A}.webp")
    check("image served from our cache on the second request (fake getFile called once)",
          r.status_code == 200 and r.data == WEBP and api_hits["getfile"] == 1 and api_hits["file"] == 1, api_hits)
    check("token only in the Bot API path, never in the client url",
          all("MAIN-TEST" in p for p in api_paths) and "MAIN-TEST" not in json.dumps(j))

    n = dict(api_hits)
    r = c.get("/gift-art/regular/5170145012310081999.webp")
    check("unknown id -> 404", r.status_code == 404 and r.get_json() == {"error": "not found"}
          and api_hits["getfile"] == n["getfile"])
    r = c.get("/gift-art/regular/1.webp")
    check("an id that merely looks numeric but is not in the catalog (e.g. 1) -> 404 with zero getFile calls",
          r.status_code == 404 and api_hits["getfile"] == n["getfile"] and api_hits["file"] == n["file"], api_hits)
    codes = [c.get(u).status_code for u in ("/gift-art/regular/abc.webp", "/gift-art/regular/-5.webp",
                                            f"/gift-art/regular/{GID_A}.jpg", "/gift-art/regular/../x.webp")]
    check("malformed regular ids/ext -> 404", codes == [404] * 4, codes)
    r1, r2 = c.get(f"/gift-art/regular/{GID_B}.webp"), c.get(f"/gift-art/regular/{GID_C}.webp")
    check(".tgs file or >200 KB -> 404 and nothing cached",
          r1.status_code == 404 and r2.status_code == 404
          and not os.path.exists(os.path.join(cache_dir, f"regular-{GID_B}.webp"))
          and not os.path.exists(os.path.join(cache_dir, f"regular-{GID_C}.webp")))
    left = [f for f in os.listdir(cache_dir) if ".tmp" in f or f.startswith("tmp")]
    check("no temp files left behind (regular)", not left, left)

    saved = {k: os.environ.pop(k, None) for k in ("BOT_TOKEN", "RELAY_BOT_TOKEN")}
    try:
        giftart._cat["at"], giftart._cat["items"] = 0, None
        n = api_hits["gifts"]
        try:
            res = giftart.regular_catalog()
        except Exception as e:
            res = e
        check("no BOT_TOKEN and no RELAY_BOT_TOKEN -> empty catalog, no exception",
              res == [] and api_hits["gifts"] == n, res)
        os.environ["RELAY_BOT_TOKEN"] = "777:RELAY-TEST"
        res = giftart.regular_catalog()
        check("RELAY_BOT_TOKEN fallback when BOT_TOKEN unset",
              len(res) == 3 and "RELAY-TEST" in api_paths[-1], api_paths[-1])
    finally:
        os.environ.pop("RELAY_BOT_TOKEN", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    giftart._cat["at"], giftart._cat["items"] = 0, None
    api_mode["fail"] = True
    try:
        try:
            res = giftart.regular_catalog()
        except Exception as e:
            res = e
        r = c.get("/api/gifts/catalog", headers=hdr())
        check("API answer 5xx from Telegram -> empty catalog, no exception",
              res == [] and r.status_code == 200 and r.get_json() == {"items": []}, (res, r.status_code))
    finally:
        api_mode["fail"] = False
        giftart._cat["at"], giftart._cat["items"] = 0, None
    # ---- вредоносный file_path из getFile для миниатюр каталога ----
    EXTRA.update({g: f"thumb-bad{i}" for i, g in enumerate(BAD_GIDS)})
    giftart._cat["at"], giftart._cat["items"] = 0, None
    try:
        n = dict(api_hits)
        codes = [c.get(f"/gift-art/regular/{g}.webp") for g in BAD_GIDS]
        check("malicious getFile file_path (../, /abs, http://, ?query, .tgs) -> our 404 json",
              all(r.status_code == 404 and r.get_json() == {"error": "not found"} for r in codes),
              [r.status_code for r in codes])
        check("...getFile was asked for each, but NO file download request was made",
              api_hits["getfile"] - n["getfile"] == len(BAD_GIDS) and api_hits["file"] == n["file"], api_hits)
        check("...and nothing cached",
              not any(os.path.exists(os.path.join(cache_dir, f"regular-{g}.webp")) for g in BAD_GIDS))
    finally:
        EXTRA.clear()
        giftart._cat["at"], giftart._cat["items"] = 0, None
finally:
    cleanup()
    srv.shutdown()
    trap.shutdown()
    botapi.shutdown()

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

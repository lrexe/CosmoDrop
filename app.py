import hmac
import os
import secrets

from bot.envfile import load_env

load_env()        # секреты из .env — до импорта модулей, которые читают окружение

from flask import Flask, render_template, jsonify, request  # noqa: E402
from flask_migrate import Migrate

from models import db, ensure_columns, GiftItem
from bot import giftart
from bot.auth import init_security, DEMO_MODE, WEBHOOK_SECRET
from bot.vloody import vloody_bp, handle_payment_update, COMMISSION_RATE

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# ---------------------------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# telegram_id демо-пользователя для локального запуска вне Telegram
DEMO_TELEGRAM_ID = int(os.getenv("DEMO_TELEGRAM_ID", "111222333"))

# Старые игры против платформы (кейсы, ракета, мины, кости, апгрейд, колесо).
# В Vloody платформа не платит из своего кармана, поэтому по умолчанию они выключены.
LEGACY_GAMES = os.getenv("LEGACY_GAMES", "").strip() == "1"

BOT_USERNAME = os.getenv("BOT_USERNAME", "VloodyGamesBot")
RELAY_USERNAME = os.getenv("RELAY_USERNAME", "VloodyRelay")


def secret_key():
    """В бою SECRET_KEY обязателен; в демо генерируем случайный на время запуска."""
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if not DEMO_MODE:
        raise RuntimeError("Задайте переменную окружения SECRET_KEY")
    return secrets.token_hex(32)


def build_database_uri():
    """PostgreSQL, если заданы переменные окружения, иначе локальный SQLite."""
    if os.getenv("DB_HOST"):
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "")
        host = os.getenv("DB_HOST", "localhost:5432")
        name = os.getenv("DB_NAME", "Cosmos_Drop")
        return f"postgresql://{user}:{password}@{host}/{name}"
    return "sqlite:///Cosmos_Drop.db"


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = secret_key()
    app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "files")
    app.config["JSON_AS_ASCII"] = False
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024      # тела запросов у нас крошечные

    db.init_app(app)
    Migrate(app, db)

    with app.app_context():
        db.create_all()
        ensure_columns()

    app.register_blueprint(vloody_bp)
    init_security(app)

    @app.context_processor
    def inject_globals():
        return {"DEMO_TELEGRAM_ID": DEMO_TELEGRAM_ID, "DEMO_MODE": DEMO_MODE,
                "BOT_USERNAME": BOT_USERNAME, "RELAY_USERNAME": RELAY_USERNAME,
                "COMMISSION_PCT": int(COMMISSION_RATE * 100)}

    # ----------------------------- СТРАНИЦЫ -----------------------------
    @app.route("/")
    def index():
        return render_template("vloody.html")

    @app.route("/tonconnect-manifest.json")
    def tonconnect_manifest():
        # за туннелем/прокси TLS завершается снаружи, и Flask видит http:// —
        # кошельку нужен настоящий публичный адрес, поэтому берём PUBLIC_URL
        base = (os.getenv("PUBLIC_URL") or request.url_root).rstrip("/")
        return jsonify({"url": base, "name": "Vloody",
                        "iconUrl": base + "/static/img/vloody-icon.png"})

    @app.route("/admin")
    def admin_page():
        # сама страница ничего не раскрывает: данные отдаёт только /api/admin/* по секрету
        resp = app.make_response(render_template("admin.html"))
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/gift-art/<slug>.<ext>")
    def gift_art(slug, ext):
        # публичный маршрут: сначала дешёвая проверка формата, потом БД, и только потом сеть;
        # отдаём лишь slug'и, которые есть у нас в gift_items (это не открытый прокси)
        miss = (jsonify({"error": "not found"}), 404)
        if ext not in giftart.EXTS or not giftart.SLUG_RE.fullmatch(slug):
            return miss
        if not GiftItem.query.filter_by(slug=slug).first():
            return miss
        art = giftart.get_art(slug, ext)
        if art is None:
            return miss
        resp = app.response_class(art[0], mimetype=art[1])
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/gift-art/regular/<int:gid>.webp")
    def gift_art_regular(gid):
        # id в пути — только ключ поиска: отдаём лишь подарки из каталога getAvailableGifts
        art = giftart.get_regular_art(str(gid))
        if art is None:
            return jsonify({"error": "not found"}), 404
        resp = app.response_class(art[0], mimetype=art[1])
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.route("/api/gifts/catalog")
    def gifts_catalog():
        # под общей проверкой подписи /api/; image — наш маршрут, токен бота наружу не уходит
        return jsonify({"items": [{"id": g["id"], "stars": g["stars"],
                                   "image": f"/gift-art/regular/{g['id']}.webp"}
                                  for g in giftart.regular_catalog()]})

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    if LEGACY_GAMES:
        register_legacy(app)

    # ----------------------- TELEGRAM PAYMENT --------------------------
    @app.route("/api/telegram_payment", methods=["POST"])
    def telegram_payment():
        # вебхук принимает только Telegram: он присылает секрет, заданный в setWebhook
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not WEBHOOK_SECRET or not hmac.compare_digest(got, WEBHOOK_SECRET):
            return jsonify({"error": "Forbidden"}), 403
        return jsonify(handle_payment_update(request.get_json(silent=True) or {}))

    return app


def register_legacy(app):
    """Старый CosmoDrop: страницы и API игр против платформы (LEGACY_GAMES=1)."""
    from bot.cases import cases_bp
    from bot.games import games_bp
    from bot.arcade import arcade_bp

    app.register_blueprint(cases_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(arcade_bp)

    pages = {"main": ("/legacy", "main.html", "home"), "cases": ("/cases", "cases.html", "cases"),
             "games": ("/games", "games.html", "games"), "rating": ("/rating", "rating.html", "rating"),
             "profile": ("/profile", "profile.html", "profile")}
    for endpoint, (url, template, active) in pages.items():
        app.add_url_rule(url, endpoint,
                         lambda t=template, a=active: render_template(t, active=a))


app = create_app()


if __name__ == "__main__":
    if DEMO_MODE:
        print("⚠️  ДЕМО-РЕЖИМ: BOT_TOKEN не задан (или DEMO_MODE=1) — все запросы без "
              "Telegram initData идут от демо-пользователя, пополнение открыто.")
    # отладчик Flask даёт выполнение кода из браузера — только локально и только в демо
    debug = DEMO_MODE and os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=debug)

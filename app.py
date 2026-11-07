import os

from flask import Flask, render_template, jsonify, request
from flask_migrate import Migrate

from models import db, User
from bot.cases import cases_bp
from bot.games import games_bp

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# ---------------------------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# telegram_id демо-пользователя для локального запуска вне Telegram
DEMO_TELEGRAM_ID = int(os.getenv("DEMO_TELEGRAM_ID", "111222333"))


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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cosmo-drop-dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "files")
    app.config["JSON_AS_ASCII"] = False

    db.init_app(app)
    Migrate(app, db)

    with app.app_context():
        db.create_all()

    app.register_blueprint(cases_bp)
    app.register_blueprint(games_bp)

    # демо-id доступен во всех шаблонах как DEMO_TELEGRAM_ID
    @app.context_processor
    def inject_globals():
        return {"DEMO_TELEGRAM_ID": DEMO_TELEGRAM_ID}

    # ----------------------------- СТРАНИЦЫ -----------------------------
    @app.route("/")
    def main():
        return render_template("main.html", active="home")

    @app.route("/cases")
    def cases():
        return render_template("cases.html", active="cases")

    @app.route("/games")
    def games():
        return render_template("games.html", active="games")

    @app.route("/rating")
    def rating():
        return render_template("rating.html", active="rating")

    @app.route("/profile")
    def profile():
        return render_template("profile.html", active="profile")

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    # ----------------------- TELEGRAM PAYMENT --------------------------
    @app.route("/api/telegram_payment", methods=["POST"])
    def telegram_payment():
        data = request.get_json(silent=True) or {}

        if "pre_checkout_query" in data:
            return jsonify({"ok": True})

        if "message" in data and "successful_payment" in data["message"]:
            payment = data["message"]["successful_payment"]
            telegram_user = data["message"]["from"]
            telegram_id = telegram_user["id"]
            amount = payment["total_amount"] // 100

            user = User.query.filter_by(telegram_id=telegram_id).first()
            if not user:
                return jsonify({"error": "User not found"}), 404

            user.stars_balance += amount
            db.session.commit()
            return jsonify({"telegram_id": telegram_id,
                            "new_balance": user.stars_balance})

        return jsonify({"status": "ignored"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

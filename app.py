import os
import random
from flask import Flask, render_template, jsonify, request
from flask_migrate import Migrate
from models import db, User, Case, CasePrize, CaseHistory
from bot.cases import cases_bp

app = Flask(__name__)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = "static/files"

DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '02022022')
DB_HOST = os.getenv('DB_HOST', 'localhost:5432')
DB_NAME = os.getenv('DB_NAME', 'Cosmos_Drop')

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'
)
app.config['SECRET_KEY'] = 'xyjfgchdfxjrd'

db.init_app(app)
migrate = Migrate(app, db)

with app.app_context():
    db.create_all()

app.register_blueprint(cases_bp)


# ---------- CASE LOGIC ----------

def roll_prize(case: Case):
    roll = random.uniform(0, 100)
    current = 0

    for prize in case.prizes:
        current += prize.chance
        if roll <= current:
            return prize

    return case.prizes[-1]


# ---------- ROUTES ----------

@app.route("/")
def main():
    return render_template("main.html")


@app.route("/cases")
def cases():
    return render_template("cases.html")


@app.route("/rating")
def rating():
    return render_template("rating.html")


@app.route("/profile")
def profile():
    return render_template("profile.html")


# ---------- TELEGRAM PAYMENT ----------

@app.route("/api/telegram_payment", methods=["POST"])
def telegram_payment():
    data = request.json

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

        return jsonify({
            "telegram_id": telegram_id,
            "new_balance": user.stars_balance
        })

    return jsonify({"status": "ignored"})


if __name__ == "__main__":
    app.run(port=5000, debug=True)

from flask import Blueprint, jsonify, request
from models import Case, CasePrize, User, CaseHistory, db
import random

cases_bp = Blueprint("cases_api", __name__)


def roll_prize(case):
    roll = random.uniform(0, 100)
    current = 0
    for prize in case.prizes:
        current += prize.chance
        if roll <= current:
            return prize
    return case.prizes[-1]


@cases_bp.route("/api/cases", methods=["GET"])
def get_cases():
    cases = Case.query.filter_by(is_active=True).all()
    result = []
    for c in cases:
        result.append({
            "id": c.id,
            "name": c.name,
            "price": c.price,
            "image": c.image
        })
    return jsonify(result)


@cases_bp.route("/api/open-case", methods=["POST"])
def open_case_api():
    data = request.json
    case_id = data.get("case_id")
    telegram_id = data.get("telegram_id")

    user = User.query.filter_by(telegram_id=telegram_id).first()
    case = Case.query.get(case_id)

    if not user or not case:
        return jsonify({"error": "Not found"}), 404

    if user.stars_balance < case.price:
        return jsonify({"error": "Not enough stars"}), 400

    prize = roll_prize(case)

    user.stars_balance -= case.price
    user.stars_balance += prize.stars

    history = CaseHistory(
        case_name=case.name,
        prize_name=f"{prize.stars} ⭐",
        user_id=user.id
    )
    db.session.add(history)
    CENTER_INDEX = 10
    roller = []
    prizes = [p.stars for p in case.prizes]
    for i in range(20):
        if i == CENTER_INDEX:
            roller.append(prize.stars)  # 💥 гарантированный выигрыш
        else:
            roller.append(random.choice(prizes))
    db.session.commit()
    return jsonify({
        "win": prize.stars,
        "new_balance": user.stars_balance,
        "roller": roller,
        "center_index": CENTER_INDEX
    })

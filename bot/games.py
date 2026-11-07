"""
CosmoDrop — игровые режимы и прогрессия:
апгрейд, контракты, колесо фортуны, задания, достижения, промокоды, рефералы.
"""

import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from models import (
    db, User, InventoryItem, Achievement, PromoCode, PromoRedemption,
)
from bot.cases import get_or_create_user, err, user_rank
from bot.engine import (
    award_xp, generate_item, level_info, quests_state, achievements_state,
    QUESTS, ACHIEVEMENTS, get_daily,
)

games_bp = Blueprint("games_api", __name__)

UPGRADE_MULTIPLIERS = {1.5: 0.60, 2: 0.45, 3: 0.30, 5: 0.18, 10: 0.09}
WHEEL_SEGMENTS = [10, 25, 50, 75, 100, 150, 250, 500]
WHEEL_WEIGHTS = [26, 22, 18, 13, 10, 6, 3, 2]
WHEEL_COOLDOWN = timedelta(hours=6)


def live_inventory(user):
    return (InventoryItem.query
            .filter_by(user_id=user.id, is_sold=False)
            .order_by(InventoryItem.won_at.desc()).all())


# ============================================================ АПГРЕЙД
@games_bp.route("/api/upgrade", methods=["POST"])
def upgrade():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    item = InventoryItem.query.filter_by(
        id=data.get("item_id"), user_id=user.id, is_sold=False).first()
    if not item:
        return err("Предмет не найден", 404)

    try:
        mult = float(data.get("multiplier"))
    except (TypeError, ValueError):
        return err("Неверный множитель", 400)
    if mult not in UPGRADE_MULTIPLIERS:
        return err("Недоступный множитель", 400)

    chance = UPGRADE_MULTIPLIERS[mult]
    target = max(1, round(item.stars * mult))
    roll = random.random()
    won = roll < chance

    before = item.to_dict()
    result = None
    if won:
        up = generate_item(target)
        item.name, item.emoji, item.stars, item.rarity = (
            up["name"], up["emoji"], up["stars"], up["rarity"])
        item.case_name = "Апгрейд"
        user.best_drop = max(user.best_drop or 0, target)
        if up["rarity"] == "legendary":
            user.legendary_count = (user.legendary_count or 0) + 1
        award_xp(user, max(5, (target - before["stars"]) // 10))
        result = item.to_dict()
        # зона успеха — сектор [0, chance); наводим стрелку внутрь него
        landing = random.uniform(0, chance) * 360
    else:
        item.is_sold = True
        landing = random.uniform(chance, 1) * 360

    db.session.commit()
    return jsonify({
        "won": won, "chance": round(chance, 4), "multiplier": mult,
        "target": target, "before": before, "result": result,
        "landing_deg": round(landing, 2),
        "new_balance": user.stars_balance,
    })


# ============================================================ КОНТРАКТЫ
@games_bp.route("/api/contract", methods=["POST"])
def contract():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    ids = data.get("item_ids") or []
    if not isinstance(ids, list) or len(ids) < 2:
        return err("Выберите минимум 2 предмета", 400)
    if len(ids) > 10:
        return err("Максимум 10 предметов", 400)

    items = InventoryItem.query.filter(
        InventoryItem.id.in_(ids),
        InventoryItem.user_id == user.id,
        InventoryItem.is_sold == False,  # noqa: E712
    ).all()
    if len(items) != len(set(ids)):
        return err("Некоторые предметы недоступны", 400)

    input_value = sum(i.stars for i in items)
    mult = random.uniform(0.2, 1.6)              # риск/награда
    output_value = max(1, round(input_value * mult))

    for it in items:
        it.is_sold = True

    new = generate_item(output_value)
    new_item = InventoryItem(
        user_id=user.id, name=new["name"], emoji=new["emoji"],
        stars=new["stars"], rarity=new["rarity"], case_name="Контракт",
    )
    db.session.add(new_item)
    user.best_drop = max(user.best_drop or 0, output_value)
    if new["rarity"] == "legendary":
        user.legendary_count = (user.legendary_count or 0) + 1
    award_xp(user, max(5, output_value // 15))
    db.session.flush()

    db.session.commit()
    return jsonify({
        "input_value": input_value,
        "output_value": output_value,
        "profit": output_value - input_value,
        "result": new_item.to_dict(),
        "new_balance": user.stars_balance,
        "inventory_count": len(live_inventory(user)),
    })


# ============================================================ КОЛЕСО ФОРТУНЫ
def wheel_available(user):
    last = user.last_wheel_spin
    if not last:
        return True, 0
    delta = datetime.utcnow() - last
    if delta >= WHEEL_COOLDOWN:
        return True, 0
    return False, int((WHEEL_COOLDOWN - delta).total_seconds())


@games_bp.route("/api/wheel/status", methods=["GET"])
def wheel_status():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    ok, cd = wheel_available(user)
    return jsonify({"available": ok, "cooldown_seconds": cd, "segments": WHEEL_SEGMENTS})


@games_bp.route("/api/wheel/spin", methods=["POST"])
def wheel_spin():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    ok, cd = wheel_available(user)
    if not ok:
        return jsonify({"spun": False, "cooldown_seconds": cd})

    idx = random.choices(range(len(WHEEL_SEGMENTS)), weights=WHEEL_WEIGHTS, k=1)[0]
    reward = WHEEL_SEGMENTS[idx]
    user.stars_balance += reward
    user.last_wheel_spin = datetime.utcnow()
    db.session.commit()
    return jsonify({
        "spun": True, "index": idx, "reward": reward,
        "segments": WHEEL_SEGMENTS, "new_balance": user.stars_balance,
    })


# ============================================================ ЗАДАНИЯ
@games_bp.route("/api/quests", methods=["GET"])
def quests():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    state = quests_state(user)
    db.session.commit()
    return jsonify({"quests": state})


@games_bp.route("/api/quests/claim", methods=["POST"])
def quests_claim():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    key = data.get("key")

    state = {q["key"]: q for q in quests_state(user)}
    q = state.get(key)
    if not q:
        return err("Задание не найдено", 404)
    if not q["completed"]:
        return err("Задание не выполнено", 400)
    if q["claimed"]:
        return err("Награда уже получена", 400)

    row = get_daily(user)
    claimed = [c for c in (row.claimed or "").split(",") if c]
    claimed.append(key)
    row.claimed = ",".join(claimed)
    user.stars_balance += q["reward"]
    db.session.commit()
    return jsonify({"claimed": True, "reward": q["reward"], "new_balance": user.stars_balance})


# ============================================================ ДОСТИЖЕНИЯ
@games_bp.route("/api/achievements", methods=["GET"])
def achievements():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    return jsonify({"achievements": achievements_state(user)})


@games_bp.route("/api/achievements/claim", methods=["POST"])
def achievements_claim():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    key = data.get("key")

    state = {a["key"]: a for a in achievements_state(user)}
    a = state.get(key)
    if not a:
        return err("Достижение не найдено", 404)
    if not a["unlocked"]:
        return err("Достижение ещё не открыто", 400)
    if a["claimed"]:
        return err("Награда уже получена", 400)

    db.session.add(Achievement(user_id=user.id, key=key))
    user.stars_balance += a["reward"]
    db.session.commit()
    return jsonify({"claimed": True, "reward": a["reward"], "new_balance": user.stars_balance})


# ============================================================ ПРОМОКОДЫ
@games_bp.route("/api/promo/redeem", methods=["POST"])
def promo_redeem():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    code = (data.get("code") or "").strip().upper()
    if not code:
        return err("Введите промокод", 400)

    promo = PromoCode.query.filter_by(code=code, is_active=True).first()
    if not promo:
        return err("Промокод не найден", 404)
    if promo.max_uses and promo.uses >= promo.max_uses:
        return err("Промокод исчерпан", 400)
    if PromoRedemption.query.filter_by(user_id=user.id, code=code).first():
        return err("Вы уже активировали этот код", 400)

    promo.uses += 1
    db.session.add(PromoRedemption(user_id=user.id, code=code))
    user.stars_balance += promo.reward
    db.session.commit()
    return jsonify({"reward": promo.reward, "code": code, "new_balance": user.stars_balance})


# ============================================================ РЕФЕРАЛЫ
@games_bp.route("/api/referral", methods=["GET"])
def referral_info():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    invited = User.query.filter_by(referred_by=user.telegram_id).count()
    return jsonify({
        "code": user.referral_code,
        "invited": invited,
        "earned": user.referral_earned or 0,
        "link": f"https://t.me/Cosmos67Drop_Bot/CosmosDrop?startapp={user.referral_code}",
    })


@games_bp.route("/api/referral/apply", methods=["POST"])
def referral_apply():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    if user.referred_by:
        return err("Реферал уже применён", 400)

    code = (data.get("code") or "").strip().upper()
    referrer = User.query.filter_by(referral_code=code).first()
    if not referrer:
        return err("Код не найден", 404)
    if referrer.telegram_id == user.telegram_id:
        return err("Нельзя пригласить самого себя", 400)

    user.referred_by = referrer.telegram_id
    user.stars_balance += 100
    referrer.stars_balance += 200
    referrer.referral_earned = (referrer.referral_earned or 0) + 200
    db.session.commit()
    return jsonify({"applied": True, "bonus": 100, "new_balance": user.stars_balance})

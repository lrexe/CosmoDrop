"""
CosmoDrop — REST API.

Весь публичный API мини-приложения собран в одном блюпринте cases_bp
(имя сохранено для совместимости с app.py).
"""

import hashlib
import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from models import db, User, Case, CasePrize, InventoryItem, CaseHistory, gift_image
from bot.engine import (
    award_xp, bump_daily, gen_referral_code, level_info, RARITY_RANK,
)

cases_bp = Blueprint("cases_api", __name__)

FAIR_SECRET = "cosmo-drop-fair-v1"

DAILY_COOLDOWN = timedelta(hours=24)
DAILY_STREAK_WINDOW = timedelta(hours=48)
DAILY_BASE = 50
DAILY_STEP = 25
DAILY_MAX = 300


# ----------------------------------------------------------------------------
# ХЕЛПЕРЫ
# ----------------------------------------------------------------------------

def get_or_create_user(telegram_id, username=None, first_name=None, photo_url=None):
    """Находит пользователя по telegram_id, создавая его при первом заходе."""
    if telegram_id is None:
        return None
    try:
        telegram_id = int(telegram_id)
    except (TypeError, ValueError):
        return None

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name or username or "Космонавт",
            photo_url=photo_url,
            stars_balance=0,
            referral_code=gen_referral_code(telegram_id),
        )
        db.session.add(user)
        db.session.commit()
    else:
        if not user.referral_code:
            user.referral_code = gen_referral_code(telegram_id)
            db.session.commit()
        # аккуратно обновляем профиль, если пришли новые данные
        changed = False
        if username and user.username != username:
            user.username = username; changed = True
        if first_name and user.first_name != first_name:
            user.first_name = first_name; changed = True
        if photo_url and user.photo_url != photo_url:
            user.photo_url = photo_url; changed = True
        if changed:
            db.session.commit()
    return user


def user_rank(user):
    """Место пользователя в рейтинге по total_earned (1 = лидер)."""
    if user is None:
        return None
    higher = User.query.filter(
        User.is_banned == False,  # noqa: E712
        User.total_earned > user.total_earned,
    ).count()
    return higher + 1


def me_payload(user):
    data = user.to_dict()
    inv = [i for i in user.inventory if not i.is_sold]
    data["rank"] = user_rank(user)
    data["inventory_count"] = len(inv)
    data["inventory_value"] = sum(i.stars for i in inv)
    data["level_info"] = level_info(user)
    return data


def roll_prize(case):
    """Взвешенный случайный приз по полю chance."""
    total = sum(p.chance for p in case.prizes) or 1
    roll = random.uniform(0, total)
    acc = 0
    for prize in case.prizes:
        acc += prize.chance
        if roll <= acc:
            return prize
    return case.prizes[-1]


def err(message, code=400):
    return jsonify({"error": message}), code


# ----------------------------------------------------------------------------
# ПОЛЬЗОВАТЕЛЬ
# ----------------------------------------------------------------------------

@cases_bp.route("/api/user/sync", methods=["POST"])
def sync_user():
    """Создаёт/обновляет пользователя (вызывается фронтом при загрузке)."""
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(
        data.get("telegram_id"),
        username=data.get("username"),
        first_name=data.get("first_name"),
        photo_url=data.get("photo_url"),
    )
    if not user:
        return err("telegram_id required", 400)
    return jsonify(me_payload(user))


@cases_bp.route("/api/me", methods=["GET"])
def me():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    return jsonify(me_payload(user))


# ----------------------------------------------------------------------------
# КЕЙСЫ
# ----------------------------------------------------------------------------

@cases_bp.route("/api/cases", methods=["GET"])
def get_cases():
    cases = (Case.query
             .filter_by(is_active=True)
             .order_by(Case.sort_order, Case.price)
             .all())
    return jsonify([c.to_dict() for c in cases])


@cases_bp.route("/api/cases/<int:case_id>", methods=["GET"])
def get_case(case_id):
    case = Case.query.get(case_id)
    if not case:
        return err("Case not found", 404)
    return jsonify(case.to_dict(with_prizes=True))


@cases_bp.route("/api/open-case", methods=["POST"])
def open_case_api():
    data = request.get_json(silent=True) or {}
    case_id = data.get("case_id")
    user = get_or_create_user(data.get("telegram_id"))
    case = Case.query.get(case_id) if case_id else None

    if not user:
        return err("User not found", 404)
    if not case:
        return err("Case not found", 404)
    if not case.prizes:
        return err("Case has no prizes", 400)
    if user.is_banned:
        return err("Доступ заблокирован", 403)
    if user.stars_balance < case.price:
        return err("Недостаточно звёзд", 400)

    prize = roll_prize(case)

    # provably fair: детерминированный хеш раунда
    user.fair_nonce = (user.fair_nonce or 0) + 1
    fair_hash = hashlib.sha256(
        f"{user.telegram_id}:{case.id}:{user.fair_nonce}:{FAIR_SECRET}".encode()
    ).hexdigest()

    # экономика
    user.stars_balance = user.stars_balance - case.price + prize.stars
    user.total_spent += case.price
    user.total_earned += prize.stars
    user.cases_opened += 1
    user.best_drop = max(user.best_drop or 0, prize.stars)
    if prize.rarity == "legendary":
        user.legendary_count = (user.legendary_count or 0) + 1

    # инвентарь + история
    item = InventoryItem(
        user_id=user.id, name=prize.name, emoji=prize.emoji,
        stars=prize.stars, rarity=prize.rarity, case_name=case.name,
    )
    db.session.add(item)
    db.session.add(CaseHistory(
        case_name=case.name,
        prize_name=f"{prize.emoji} {prize.name}",
        prize_stars=prize.stars,
        prize_rarity=prize.rarity,
        user_id=user.id,
    ))

    # прогрессия: XP + ежедневные задания
    xp = award_xp(user, case.price // 2 + prize.stars // 5)
    bump_daily(user, cases=1, stars_won=prize.stars,
               rare_won=1 if RARITY_RANK.get(prize.rarity, 0) >= 1 else 0)

    # лента рулетки с гарантированным выигрышем в центре
    CENTER_INDEX = 40
    pool = list(case.prizes)
    roller = []
    for i in range(80):
        p = prize if i == CENTER_INDEX else random.choice(pool)
        roller.append({"stars": p.stars, "emoji": p.emoji, "image": gift_image(p.emoji),
                       "name": p.name, "rarity": p.rarity})

    db.session.commit()

    net = prize.stars - case.price
    return jsonify({
        "win": {
            "name": prize.name, "emoji": prize.emoji, "image": gift_image(prize.emoji),
            "stars": prize.stars, "rarity": prize.rarity,
        },
        "net": net,
        "profit": net >= 0,
        "new_balance": user.stars_balance,
        "roller": roller,
        "center_index": CENTER_INDEX,
        "item_id": item.id,
        "xp": xp,
        "level_info": level_info(user),
        "fair": {"nonce": user.fair_nonce, "hash": fair_hash[:16]},
    })


# ----------------------------------------------------------------------------
# ИНВЕНТАРЬ
# ----------------------------------------------------------------------------

@cases_bp.route("/api/inventory", methods=["GET"])
def inventory():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    items = (InventoryItem.query
             .filter_by(user_id=user.id, is_sold=False)
             .order_by(InventoryItem.won_at.desc())
             .all())
    return jsonify({
        "items": [i.to_dict() for i in items],
        "total_value": sum(i.stars for i in items),
        "count": len(items),
    })


@cases_bp.route("/api/inventory/sell", methods=["POST"])
def sell_item():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    item_id = data.get("item_id")
    sell_all = data.get("all", False)

    if sell_all:
        items = InventoryItem.query.filter_by(user_id=user.id, is_sold=False).all()
    else:
        item = InventoryItem.query.filter_by(
            id=item_id, user_id=user.id, is_sold=False).first()
        if not item:
            return err("Item not found", 404)
        items = [item]

    gained = 0
    for it in items:
        it.is_sold = True
        gained += it.stars
    user.stars_balance += gained
    db.session.commit()

    return jsonify({
        "sold": len(items),
        "gained": gained,
        "new_balance": user.stars_balance,
    })


# ----------------------------------------------------------------------------
# РЕЙТИНГ
# ----------------------------------------------------------------------------

@cases_bp.route("/api/rating", methods=["GET"])
def rating():
    limit = min(int(request.args.get("limit", 50)), 100)
    top = (User.query
           .filter_by(is_banned=False)
           .order_by(User.total_earned.desc(), User.cases_opened.desc())
           .limit(limit)
           .all())

    leaderboard = []
    for i, u in enumerate(top, start=1):
        leaderboard.append({
            "place": i,
            "name": u.first_name or u.username or "Космонавт",
            "username": u.username,
            "avatar": u.avatar,
            "score": u.total_earned,
            "cases_opened": u.cases_opened,
        })

    me_entry = None
    user = get_or_create_user(request.args.get("telegram_id"))
    if user:
        me_entry = {
            "place": user_rank(user),
            "name": user.first_name or user.username or "Космонавт",
            "avatar": user.avatar,
            "score": user.total_earned,
            "cases_opened": user.cases_opened,
            "telegram_id": user.telegram_id,
        }

    return jsonify({"leaderboard": leaderboard, "me": me_entry})


# ----------------------------------------------------------------------------
# ИСТОРИЯ / ЛЕНТА ВЫИГРЫШЕЙ
# ----------------------------------------------------------------------------

@cases_bp.route("/api/history", methods=["GET"])
def history():
    scope = request.args.get("scope", "me")
    limit = min(int(request.args.get("limit", 20)), 50)
    q = CaseHistory.query

    if scope == "me":
        user = get_or_create_user(request.args.get("telegram_id"))
        if not user:
            return jsonify([])
        q = q.filter_by(user_id=user.id)

    rows = q.order_by(CaseHistory.opened_at.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


# ----------------------------------------------------------------------------
# ЕЖЕДНЕВНЫЙ БОНУС
# ----------------------------------------------------------------------------

@cases_bp.route("/api/daily-bonus", methods=["POST"])
def daily_bonus():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)

    now = datetime.utcnow()
    last = user.last_daily_bonus

    if last and (now - last) < DAILY_COOLDOWN:
        remaining = int((DAILY_COOLDOWN - (now - last)).total_seconds())
        return jsonify({
            "claimed": False,
            "cooldown_seconds": remaining,
            "streak": user.daily_streak,
        })

    # продолжаем серию, если прошло меньше окна, иначе сбрасываем
    if last and (now - last) <= DAILY_STREAK_WINDOW:
        user.daily_streak = (user.daily_streak or 0) + 1
    else:
        user.daily_streak = 1

    reward = min(DAILY_BASE + (user.daily_streak - 1) * DAILY_STEP, DAILY_MAX)
    user.stars_balance += reward
    user.last_daily_bonus = now
    db.session.commit()

    return jsonify({
        "claimed": True,
        "reward": reward,
        "streak": user.daily_streak,
        "new_balance": user.stars_balance,
    })


@cases_bp.route("/api/daily-bonus/status", methods=["GET"])
def daily_bonus_status():
    user = get_or_create_user(request.args.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    now = datetime.utcnow()
    last = user.last_daily_bonus
    available = (last is None) or (now - last) >= DAILY_COOLDOWN
    remaining = 0
    if not available:
        remaining = int((DAILY_COOLDOWN - (now - last)).total_seconds())
    next_reward = min(DAILY_BASE + (user.daily_streak or 0) * DAILY_STEP, DAILY_MAX)
    return jsonify({
        "available": available,
        "cooldown_seconds": remaining,
        "streak": user.daily_streak or 0,
        "next_reward": next_reward,
    })


# ----------------------------------------------------------------------------
# ПОПОЛНЕНИЕ (демо)
# ----------------------------------------------------------------------------

@cases_bp.route("/api/balance/add", methods=["POST"])
def add_balance():
    data = request.get_json(silent=True) or {}
    user = get_or_create_user(data.get("telegram_id"))
    if not user:
        return err("User not found", 404)
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return err("Invalid amount", 400)
    if amount <= 0 or amount > 100000:
        return err("Amount must be between 1 and 100000", 400)
    user.stars_balance += amount
    db.session.commit()
    return jsonify({"new_balance": user.stars_balance, "added": amount})


# ----------------------------------------------------------------------------
# ГЛОБАЛЬНАЯ СТАТИСТИКА
# ----------------------------------------------------------------------------

@cases_bp.route("/api/stats", methods=["GET"])
def stats():
    total_cases = db.session.query(db.func.coalesce(db.func.sum(User.cases_opened), 0)).scalar()
    total_users = User.query.filter_by(is_banned=False).count()
    stars_circulation = db.session.query(db.func.coalesce(db.func.sum(User.stars_balance), 0)).scalar()
    biggest = db.session.query(db.func.coalesce(db.func.max(User.best_drop), 0)).scalar()
    active_cases = Case.query.filter_by(is_active=True).count()
    return jsonify({
        "total_cases_opened": int(total_cases),
        "total_users": int(total_users),
        "stars_circulation": int(stars_circulation),
        "biggest_win": int(biggest),
        "active_cases": active_cases,
    })

"""
CosmoDrop — аркадные игры на ставках: Ракета (crash), Мины, Кости.

Вся логика исхода — на сервере: клиент никогда не получает точку взрыва ракеты
или расположение мин до завершения раунда.
"""

import json
import math
import random
from datetime import datetime

from flask import Blueprint, jsonify, request

from models import db, GameRound
from bot.cases import get_or_create_user, err
from bot.engine import award_xp, level_info

arcade_bp = Blueprint("arcade_api", __name__)

MIN_BET = 10
MAX_BET = 10000
HOUSE_EDGE = 0.04                 # 4% — RTP 96% во всех трёх играх

CRASH_GROWTH = 0.14               # множитель = e^(CRASH_GROWTH * секунды)
CRASH_MAX = 100.0

MINES_CELLS = 25
MINES_MIN, MINES_MAX = 1, 24

DICE_MIN, DICE_MAX = 5, 95        # шанс победы, %

rng = random.SystemRandom()


# ----------------------------------------------------------------- хелперы
def _player():
    """Пользователь из запроса (JSON-тело или query-параметр)."""
    data = request.get_json(silent=True) or {}
    tid = data.get("telegram_id") or request.args.get("telegram_id")
    return get_or_create_user(tid), data


def _parse_bet(user, raw):
    try:
        bet = int(raw)
    except (TypeError, ValueError):
        return None, err("Неверная ставка", 400)
    if bet < MIN_BET or bet > MAX_BET:
        return None, err(f"Ставка от {MIN_BET} до {MAX_BET} ⭐", 400)
    if user.is_banned:
        return None, err("Доступ заблокирован", 403)
    if user.stars_balance < bet:
        return None, err("Недостаточно звёзд", 400)
    return bet, None


def _active(user, game):
    return (GameRound.query
            .filter_by(user_id=user.id, game=game, state="active")
            .order_by(GameRound.id.desc()).first())


def _open_round(user, game, bet, data):
    user.stars_balance -= bet
    user.total_spent = (user.total_spent or 0) + bet
    rnd = GameRound(user_id=user.id, game=game, bet=bet, state="active",
                    data=json.dumps(data), created_at=datetime.utcnow())
    db.session.add(rnd)
    award_xp(user, max(1, bet // 4))
    db.session.flush()
    return rnd


def _finish(user, rnd, multiplier, won):
    rnd.state = "won" if won else "lost"
    rnd.multiplier = multiplier
    rnd.payout = int(math.floor(rnd.bet * multiplier)) if won else 0
    rnd.finished_at = datetime.utcnow()
    if won:
        user.stars_balance += rnd.payout
        user.total_earned = (user.total_earned or 0) + rnd.payout
    return rnd.payout


def _result(user, rnd, **extra):
    out = {
        "round_id": rnd.id, "state": rnd.state, "bet": rnd.bet,
        "payout": rnd.payout or 0, "multiplier": round(rnd.multiplier or 0, 2),
        "new_balance": user.stars_balance, "level_info": level_info(user),
    }
    out.update(extra)
    return jsonify(out)


# ================================================================== РАКЕТА
def _crash_point():
    """Точка взрыва: P(crash >= x) = (1 - edge) / x."""
    r = rng.random()
    return max(1.0, min(CRASH_MAX, math.floor((1 - HOUSE_EDGE) / (1 - r) * 100) / 100))


def _crash_mult(rnd, now=None):
    elapsed = ((now or datetime.utcnow()) - rnd.created_at).total_seconds()
    return math.floor(math.exp(CRASH_GROWTH * max(0.0, elapsed)) * 100) / 100


def _crash_settle(user, rnd):
    """Доводит раунд до актуального состояния. Возвращает (множитель, точка взрыва)."""
    d = json.loads(rnd.data or "{}")
    crash, auto = d["crash"], d.get("auto")
    mult = _crash_mult(rnd)
    if rnd.state != "active":
        return mult, crash
    if auto and auto <= crash and mult >= auto:
        _finish(user, rnd, auto, True)          # сработал авто-вывод
    elif mult >= crash:
        _finish(user, rnd, crash, False)        # взрыв
    return mult, crash


def _crash_round(user, round_id):
    try:
        rnd = db.session.get(GameRound, int(round_id))
    except (TypeError, ValueError):
        return None
    if not user or not rnd or rnd.user_id != user.id or rnd.game != "crash":
        return None
    return rnd


@arcade_bp.route("/api/crash/start", methods=["POST"])
def crash_start():
    user, data = _player()
    if not user:
        return err("User not found", 404)

    old = _active(user, "crash")
    if old:
        _crash_settle(user, old)
        db.session.commit()
        if old.state == "active":
            return err("Раунд уже идёт", 400)

    auto = None
    if data.get("auto_cashout"):
        try:
            auto = round(float(data["auto_cashout"]), 2)
        except (TypeError, ValueError):
            return err("Неверный авто-вывод", 400)
        if auto < 1.01 or auto > CRASH_MAX:
            return err(f"Авто-вывод от 1.01 до {int(CRASH_MAX)}", 400)

    bet, e = _parse_bet(user, data.get("bet"))
    if e:
        return e

    rnd = _open_round(user, "crash", bet, {"crash": _crash_point(), "auto": auto})
    db.session.commit()
    return _result(user, rnd, growth=CRASH_GROWTH, auto_cashout=auto)


@arcade_bp.route("/api/crash/tick", methods=["GET"])
def crash_tick():
    """Опрос состояния: клиент узнаёт о взрыве только когда он уже случился."""
    user, _ = _player()
    rnd = _crash_round(user, request.args.get("round_id"))
    if not rnd:
        return err("Раунд не найден", 404)
    mult, crash = _crash_settle(user, rnd)
    db.session.commit()
    extra = {"current": mult}
    if rnd.state != "active":
        extra["crash_point"] = crash
    return _result(user, rnd, **extra)


@arcade_bp.route("/api/crash/cashout", methods=["POST"])
def crash_cashout():
    user, data = _player()
    rnd = _crash_round(user, data.get("round_id"))
    if not rnd:
        return err("Раунд не найден", 404)
    mult, crash = _crash_settle(user, rnd)
    if rnd.state == "active":
        _finish(user, rnd, max(1.0, mult), True)
    db.session.commit()
    return _result(user, rnd, current=mult, crash_point=crash)


# ==================================================================== МИНЫ
def _mines_mult(mines, picks):
    """Честный множитель за picks безопасных клеток минус комиссия."""
    if picks <= 0:
        return 1.0
    safe = MINES_CELLS - mines
    m = 1.0
    for k in range(picks):
        m *= (MINES_CELLS - k) / (safe - k)
    return math.floor(m * (1 - HOUSE_EDGE) * 100) / 100


def _mines_view(d, reveal=False):
    picks = len(d["open"])
    view = {
        "mines_count": d["count"], "opened": d["open"], "picks": picks,
        "current": _mines_mult(d["count"], picks),
        "next": (_mines_mult(d["count"], picks + 1)
                 if picks < MINES_CELLS - d["count"] else None),
    }
    if reveal:
        view["mines"] = d["mines"]
    return view


@arcade_bp.route("/api/mines/state", methods=["GET"])
def mines_state():
    user, _ = _player()
    if not user:
        return err("User not found", 404)
    rnd = _active(user, "mines")
    if not rnd:
        return jsonify({"active": False})
    d = json.loads(rnd.data)
    return jsonify({"active": True, "round_id": rnd.id, "bet": rnd.bet, **_mines_view(d)})


@arcade_bp.route("/api/mines/start", methods=["POST"])
def mines_start():
    user, data = _player()
    if not user:
        return err("User not found", 404)
    if _active(user, "mines"):
        return err("Сначала заверши текущую игру", 400)
    try:
        count = int(data.get("mines", 3))
    except (TypeError, ValueError):
        return err("Неверное число мин", 400)
    if count < MINES_MIN or count > MINES_MAX:
        return err(f"Мин от {MINES_MIN} до {MINES_MAX}", 400)
    bet, e = _parse_bet(user, data.get("bet"))
    if e:
        return e

    d = {"count": count, "mines": sorted(rng.sample(range(MINES_CELLS), count)), "open": []}
    rnd = _open_round(user, "mines", bet, d)
    db.session.commit()
    return _result(user, rnd, **_mines_view(d))


@arcade_bp.route("/api/mines/reveal", methods=["POST"])
def mines_reveal():
    user, data = _player()
    if not user:
        return err("User not found", 404)
    rnd = _active(user, "mines")
    if not rnd:
        return err("Нет активной игры", 400)
    try:
        cell = int(data.get("cell"))
    except (TypeError, ValueError):
        return err("Неверная клетка", 400)
    d = json.loads(rnd.data)
    if cell < 0 or cell >= MINES_CELLS or cell in d["open"]:
        return err("Неверная клетка", 400)

    if cell in d["mines"]:
        _finish(user, rnd, 0, False)
        db.session.commit()
        return _result(user, rnd, hit=True, cell=cell, **_mines_view(d, reveal=True))

    d["open"].append(cell)
    rnd.data = json.dumps(d)
    view = _mines_view(d)
    if view["next"] is None:                       # открыты все безопасные клетки
        _finish(user, rnd, view["current"], True)
        view = _mines_view(d, reveal=True)
    db.session.commit()
    return _result(user, rnd, hit=False, cell=cell, **view)


@arcade_bp.route("/api/mines/cashout", methods=["POST"])
def mines_cashout():
    user, _ = _player()
    if not user:
        return err("User not found", 404)
    rnd = _active(user, "mines")
    if not rnd:
        return err("Нет активной игры", 400)
    d = json.loads(rnd.data)
    if not d["open"]:
        return err("Открой хотя бы одну клетку", 400)
    _finish(user, rnd, _mines_mult(d["count"], len(d["open"])), True)
    db.session.commit()
    return _result(user, rnd, **_mines_view(d, reveal=True))


# =================================================================== КОСТИ
@arcade_bp.route("/api/dice", methods=["POST"])
def dice():
    user, data = _player()
    if not user:
        return err("User not found", 404)
    try:
        chance = int(data.get("chance", 50))
    except (TypeError, ValueError):
        return err("Неверный шанс", 400)
    if chance < DICE_MIN or chance > DICE_MAX:
        return err(f"Шанс от {DICE_MIN} до {DICE_MAX}%", 400)
    bet, e = _parse_bet(user, data.get("bet"))
    if e:
        return e

    roll = rng.randrange(0, 10000) / 100            # 0.00 … 99.99
    won = roll < chance
    mult = math.floor((1 - HOUSE_EDGE) * 100 / chance * 100) / 100
    rnd = _open_round(user, "dice", bet, {"chance": chance, "roll": roll})
    _finish(user, rnd, mult if won else 0, won)
    db.session.commit()
    return _result(user, rnd, roll=roll, chance=chance, won=won, win_multiplier=mult)


# ============================================================ ИСТОРИЯ / КОНФИГ
@arcade_bp.route("/api/arcade/config", methods=["GET"])
def arcade_config():
    return jsonify({
        "min_bet": MIN_BET, "max_bet": MAX_BET, "house_edge": HOUSE_EDGE,
        "crash": {"growth": CRASH_GROWTH, "max": CRASH_MAX},
        "mines": {"cells": MINES_CELLS, "min": MINES_MIN, "max": MINES_MAX},
        "dice": {"min": DICE_MIN, "max": DICE_MAX},
    })


@arcade_bp.route("/api/arcade/history", methods=["GET"])
def arcade_history():
    scope = request.args.get("scope", "me")
    limit = min(request.args.get("limit", 15, type=int) or 15, 50)
    q = GameRound.query.filter(GameRound.state != "active")
    game = request.args.get("game")
    if game:
        q = q.filter_by(game=game)
    if scope == "me":
        user, _ = _player()
        if not user:
            return jsonify([])
        q = q.filter_by(user_id=user.id)
    rows = q.order_by(GameRound.id.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])

"""
CosmoDrop — игровой движок: уровни/XP, задания, достижения, генерация предметов.
Общие хелперы, которыми пользуются и cases.py, и games.py.
"""

import random
import string
from datetime import datetime

from models import db, DailyProgress

RARITY_RANK = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}

# пулы подарков по редкости (тематика Telegram Gifts / NFT) — для апгрейда/контрактов
ITEM_POOLS = {
    "common":    [("Мишка", "🧸"), ("Сердечко", "💝"), ("Роза", "🌹")],
    "rare":      [("Подарок", "🎁"), ("Ракета", "🚀"), ("Букет", "💐"), ("Шампанское", "🍾")],
    "epic":      [("Торт", "🎂"), ("Кубок", "🏆"), ("Кольцо", "💍"), ("Персик", "🍑")],
    "legendary": [("Бриллиант", "💎"), ("Кепка Дурова", "🎩"), ("Плюш Пепе", "🐸"), ("Золотой слиток", "🥇")],
}


def rarity_for_value(value):
    if value < 50:
        return "common"
    if value < 200:
        return "rare"
    if value < 800:
        return "epic"
    return "legendary"


def generate_item(value):
    """Собирает предмет (имя, эмодзи, редкость) под заданную стоимость в звёздах."""
    value = max(1, int(value))
    rarity = rarity_for_value(value)
    name, emoji = random.choice(ITEM_POOLS[rarity])
    return {"name": name, "emoji": emoji, "stars": value, "rarity": rarity}


# ---------------------------------------------------------------- уровни / XP
def cum_xp(level):
    """Суммарный XP, необходимый чтобы ДОСТИЧЬ уровня level."""
    return 50 * (level - 1) * level


def level_from_xp(xp):
    lvl = 1
    while cum_xp(lvl + 1) <= xp and lvl < 999:
        lvl += 1
    return lvl


def level_info(user):
    lvl = user.level or 1
    base = cum_xp(lvl)
    nxt = cum_xp(lvl + 1)
    span = max(1, nxt - base)
    return {
        "level": lvl,
        "xp": user.xp or 0,
        "xp_into_level": (user.xp or 0) - base,
        "xp_for_level": span,
        "xp_to_next": max(0, nxt - (user.xp or 0)),
        "progress": round(min(1.0, ((user.xp or 0) - base) / span), 4),
    }


def award_xp(user, amount):
    """Начисляет XP, обрабатывает level-up и выдаёт награды за новые уровни."""
    amount = max(0, int(amount))
    old_level = user.level or 1
    user.xp = (user.xp or 0) + amount
    new_level = level_from_xp(user.xp)
    reward = 0
    if new_level > old_level:
        for lv in range(old_level + 1, new_level + 1):
            reward += lv * 50
        user.stars_balance += reward
        user.level = new_level
    return {
        "gained": amount,
        "leveled_up": new_level > old_level,
        "old_level": old_level,
        "new_level": new_level,
        "level_reward": reward,
    }


# ---------------------------------------------------------------- рефералы
def gen_referral_code(telegram_id):
    base = "CD"
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"{base}{suffix}"


# ---------------------------------------------------------------- задания
def today_str():
    return datetime.utcnow().strftime("%Y-%m-%d")


def get_daily(user, create=True):
    day = today_str()
    row = DailyProgress.query.filter_by(user_id=user.id, day=day).first()
    if row is None and create:
        row = DailyProgress(user_id=user.id, day=day, cases=0, stars_won=0, rare_won=0, claimed="")
        db.session.add(row)
        db.session.flush()
    return row


def bump_daily(user, cases=0, stars_won=0, rare_won=0):
    row = get_daily(user)
    row.cases = (row.cases or 0) + cases
    row.stars_won = (row.stars_won or 0) + stars_won
    row.rare_won = (row.rare_won or 0) + rare_won
    return row


QUESTS = [
    {"key": "q1", "title": "Открой 3 кейса",         "emoji": "🎁", "goal": 3,   "reward": 100, "metric": "cases"},
    {"key": "q2", "title": "Выиграй 400 ⭐ за день",  "emoji": "⭐", "goal": 400, "reward": 150, "metric": "stars_won"},
    {"key": "q3", "title": "Получи редкий+ предмет",  "emoji": "💎", "goal": 1,   "reward": 120, "metric": "rare_won"},
]


def quests_state(user):
    row = get_daily(user)
    claimed = set((row.claimed or "").split(",")) if row.claimed else set()
    out = []
    for q in QUESTS:
        progress = min(getattr(row, q["metric"], 0) or 0, q["goal"])
        out.append({
            **{k: q[k] for k in ("key", "title", "emoji", "goal", "reward")},
            "progress": progress,
            "completed": progress >= q["goal"],
            "claimed": q["key"] in claimed,
        })
    return out


# ---------------------------------------------------------------- достижения
ACHIEVEMENTS = [
    {"key": "open10",   "title": "Новичок",        "desc": "Открыть 10 кейсов",       "emoji": "🎁", "goal": 10,    "metric": "cases_opened",   "reward": 100},
    {"key": "open100",  "title": "Коллекционер",   "desc": "Открыть 100 кейсов",      "emoji": "📦", "goal": 100,   "metric": "cases_opened",   "reward": 500},
    {"key": "earn1k",   "title": "Звёздный доход", "desc": "Выиграть 1 000 ⭐",        "emoji": "⭐", "goal": 1000,  "metric": "total_earned",   "reward": 150},
    {"key": "earn10k",  "title": "Магнат",         "desc": "Выиграть 10 000 ⭐",       "emoji": "💰", "goal": 10000, "metric": "total_earned",   "reward": 800},
    {"key": "best1k",   "title": "Крупный куш",    "desc": "Дроп на 1 000+ ⭐",        "emoji": "💎", "goal": 1000,  "metric": "best_drop",      "reward": 300},
    {"key": "legend1",  "title": "Легенда",        "desc": "Выбить легендарный предмет","emoji": "🌟", "goal": 1,     "metric": "legendary_count","reward": 500},
    {"key": "level5",   "title": "Опытный",        "desc": "Достичь 5 уровня",         "emoji": "🚀", "goal": 5,     "metric": "level",          "reward": 250},
    {"key": "level10",  "title": "Ветеран космоса","desc": "Достичь 10 уровня",        "emoji": "👑", "goal": 10,    "metric": "level",          "reward": 600},
]


def achievements_state(user):
    claimed = {a.key for a in user_achievements(user)}
    out = []
    for a in ACHIEVEMENTS:
        cur = getattr(user, a["metric"], 0) or 0
        out.append({
            **{k: a[k] for k in ("key", "title", "desc", "emoji", "goal", "reward")},
            "progress": min(cur, a["goal"]),
            "unlocked": cur >= a["goal"],
            "claimed": a["key"] in claimed,
        })
    return out


def user_achievements(user):
    from models import Achievement
    return Achievement.query.filter_by(user_id=user.id).all()

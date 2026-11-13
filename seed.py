"""
Seed-скрипт для CosmoDrop.

Наполняет базу демо-данными под новую схему:
  - кейсы с призами-предметами (имя, эмодзи, редкость, шанс);
  - демо-пользователь (telegram_id=111222333 — его подхватывает фронтенд);
  - игроки для рейтинга, инвентарь и глобальная лента выигрышей.

Запуск:  .venv/bin/python seed.py
Идемпотентно: пересоздаёт кейсы, историю и инвентарь, обновляет статы игроков.
"""

from datetime import datetime, timedelta

from app import app
from models import (
    db, User, Case, CasePrize, InventoryItem, CaseHistory,
    DailyProgress, Achievement, PromoCode, PromoRedemption,
)
from bot.engine import level_from_xp

MAIN_TELEGRAM_ID = 111222333

PROMO_CODES = [
    ("COSMO100", 100, 0),     # безлимитный
    ("WELCOME", 250, 0),
    ("STARGIFT", 500, 100),
    ("LREXE1000", 1000, 50),
]

CASES = [
    {
        "name": "Стартовый кейс", "emoji": "💝", "price": 50,
        "rarity": "common", "accent": "#8a96a3", "sort_order": 1,
        "description": "Базовый набор подарков для новичков.",
        "prizes": [
            {"name": "Носки Пепе", "emoji": "🧦", "stars": 10, "rarity": "common", "chance": 45},
            {"name": "Леденец", "emoji": "🍭", "stars": 30, "rarity": "common", "chance": 30},
            {"name": "Пряник", "emoji": "🍪", "stars": 70, "rarity": "common", "chance": 18},
            {"name": "Плюш-сердце", "emoji": "💝", "stars": 150, "rarity": "rare", "chance": 7},
        ],
    },
    {
        "name": "Премиум кейс", "emoji": "🐱", "price": 150,
        "rarity": "rare", "accent": "#3390ec", "sort_order": 2,
        "description": "Повышенный шанс на ценные подарки.",
        "prizes": [
            {"name": "Пряник", "emoji": "🍪", "stars": 40, "rarity": "common", "chance": 42},
            {"name": "Напуганный кот", "emoji": "🐱", "stars": 120, "rarity": "rare", "chance": 33},
            {"name": "Коробка ягод", "emoji": "🍓", "stars": 300, "rarity": "rare", "chance": 18},
            {"name": "Колпак шута", "emoji": "🤡", "stars": 600, "rarity": "epic", "chance": 7},
        ],
    },
    {
        "name": "NFT кейс", "emoji": "🧠", "price": 500,
        "rarity": "epic", "accent": "#a76bf3", "sort_order": 3,
        "description": "Коллекционные NFT-подарки Telegram.",
        "prizes": [
            {"name": "Колпак шута", "emoji": "🤡", "stars": 200, "rarity": "rare", "chance": 50},
            {"name": "Перстень", "emoji": "💍", "stars": 450, "rarity": "epic", "chance": 30},
            {"name": "Вуду-кукла", "emoji": "🧿", "stars": 900, "rarity": "epic", "chance": 15},
            {"name": "Астральный кристалл", "emoji": "💎", "stars": 2000, "rarity": "legendary", "chance": 5},
        ],
    },
    {
        "name": "Легендарный кейс", "emoji": "🎩", "price": 1000,
        "rarity": "legendary", "accent": "#f5b544", "sort_order": 4,
        "description": "Самые редкие NFT: Кепка Дурова и Астральный кристалл.",
        "prizes": [
            {"name": "Куб-мозг", "emoji": "🧠", "stars": 500, "rarity": "epic", "chance": 55},
            {"name": "Золотые туфли", "emoji": "👠", "stars": 1200, "rarity": "epic", "chance": 27},
            {"name": "Кепка Дурова", "emoji": "🎩", "stars": 2500, "rarity": "legendary", "chance": 13},
            {"name": "Астральный кристалл", "emoji": "💎", "stars": 5000, "rarity": "legendary", "chance": 5},
        ],
    },
]

#         telegram_id, username,  first_name,  avatar, balance, earned, spent, cases, best
PLAYERS = [
    (900000001, "LREXE",     "LREXE",     "👑", 8600, 12400, 11200, 180, 5000),
    (900000002, "licexsy",   "licexsy",   "🦊", 4200,  9800,  8900, 140, 2500),
    (900000003, "nebula",    "Nebula",    "🌌", 3300,  8600,  7800, 120, 2000),
    (900000004, "galaxyx",   "GalaxyX",   "🚀", 2100,  6400,  5900,  90, 1200),
    (900000005, "astroboy",  "AstroBoy",  "👨‍🚀", 1500, 5100, 4700,  75,  900),
    (900000006, "nova",      "Nova",      "⭐", 900,   4300,  4000,  60,  600),
    (900000007, "orbit",     "Orbit",     "🛰️", 700,   2600,  2400,  40,  450),
    (900000008, "pixel",     "Pixel",     "🤖", 400,   1800,  1700,  28,  300),
]


def upsert_user(telegram_id, **fields):
    u = User.query.filter_by(telegram_id=telegram_id).first()
    if u is None:
        u = User(telegram_id=telegram_id)
        db.session.add(u)
    for k, v in fields.items():
        setattr(u, k, v)
    return u


def seed():
    with app.app_context():
        db.create_all()

        # --- чистим фичевые таблицы (идемпотентность) ---
        PromoRedemption.query.delete()
        PromoCode.query.delete()
        Achievement.query.delete()
        DailyProgress.query.delete()

        # --- промокоды ---
        for code, reward, max_uses in PROMO_CODES:
            db.session.add(PromoCode(code=code, reward=reward, max_uses=max_uses, uses=0, is_active=True))

        # --- кейсы (пересоздаём) ---
        # bulk-delete не каскадит ORM-связи, поэтому чистим призы явно и в порядке FK
        CasePrize.query.delete()
        Case.query.delete()
        db.session.flush()
        for c in CASES:
            case = Case(
                name=c["name"], emoji=c["emoji"], description=c["description"],
                image="/static/img/photo_2025-12-16_21-02-55.jpg",
                price=c["price"], rarity=c["rarity"], accent=c["accent"],
                sort_order=c["sort_order"], is_active=True,
            )
            for p in c["prizes"]:
                case.prizes.append(CasePrize(
                    name=p["name"], emoji=p["emoji"], stars=p["stars"],
                    rarity=p["rarity"], chance=p["chance"],
                ))
            db.session.add(case)

        # --- демо-пользователь ---
        demo = upsert_user(
            MAIN_TELEGRAM_ID, username="cosmo_demo", first_name="Космонавт",
            photo_url="🧑‍🚀", stars_balance=5000, total_earned=840,
            total_spent=600, cases_opened=12, best_drop=300,
            daily_streak=2, last_daily_bonus=None, last_wheel_spin=None,
            xp=1800, level=level_from_xp(1800), legendary_count=0,
            referral_code="CDDEMO", referral_earned=0, fair_nonce=0,
        )

        # --- игроки рейтинга ---
        players = []
        for tid, un, fn, av, bal, earned, spent, cs, best in PLAYERS:
            xp = earned // 3
            players.append(upsert_user(
                tid, username=un, first_name=fn, photo_url=av,
                stars_balance=bal, total_earned=earned, total_spent=spent,
                cases_opened=cs, best_drop=best,
                xp=xp, level=level_from_xp(xp),
                legendary_count=(1 if best >= 2000 else 0),
                referral_code=f"CD{un[:6].upper()}", referral_earned=0,
            ))
        db.session.flush()

        # --- инвентарь демо-пользователя (пересоздаём) ---
        InventoryItem.query.filter_by(user_id=demo.id).delete()
        for name, emoji, stars, rarity, case_name in [
            ("Плюш-сердце", "💝", 150, "rare", "Стартовый кейс"),
            ("Перстень", "💍", 450, "epic", "NFT кейс"),
            ("Напуганный кот", "🐱", 120, "rare", "Премиум кейс"),
            ("Леденец", "🍭", 30, "common", "Стартовый кейс"),
        ]:
            db.session.add(InventoryItem(
                user_id=demo.id, name=name, emoji=emoji, stars=stars,
                rarity=rarity, case_name=case_name,
            ))

        # --- глобальная лента выигрышей ---
        CaseHistory.query.delete()
        db.session.flush()
        now = datetime.utcnow()
        feed = [
            (players[0], "Легендарный кейс", "💎 Астральный кристалл", 5000, "legendary", 2),
            (players[1], "NFT кейс", "💎 Астральный кристалл", 2000, "legendary", 9),
            (demo, "Премиум кейс", "🐱 Напуганный кот", 120, "rare", 18),
            (players[2], "Премиум кейс", "🤡 Колпак шута", 600, "epic", 27),
            (players[4], "Стартовый кейс", "💝 Плюш-сердце", 150, "rare", 44),
            (players[3], "NFT кейс", "💍 Перстень", 450, "epic", 70),
            (demo, "Стартовый кейс", "🍪 Пряник", 70, "common", 95),
            (players[5], "Стартовый кейс", "🍭 Леденец", 30, "common", 130),
        ]
        for user, case_name, prize_name, stars, rarity, mins_ago in feed:
            db.session.add(CaseHistory(
                case_name=case_name, prize_name=prize_name, prize_stars=stars,
                prize_rarity=rarity, user_id=user.id,
                opened_at=now - timedelta(minutes=mins_ago),
            ))

        db.session.commit()

        # --- отчёт ---
        print("✅ База наполнена.")
        print(f"   Кейсов: {Case.query.count()} · Призов: {CasePrize.query.count()}")
        print(f"   Игроков: {User.query.count()} · История: {CaseHistory.query.count()} · Промокодов: {PromoCode.query.count()}")
        print(f"   Промокоды: {', '.join(c for c, _, _ in PROMO_CODES)}")
        print(f"   Демо-игрок: telegram_id={MAIN_TELEGRAM_ID}, баланс={demo.stars_balance} ⭐, "
              f"инвентарь={InventoryItem.query.filter_by(user_id=demo.id, is_sold=False).count()} шт.")
        print()
        for case in Case.query.order_by(Case.sort_order).all():
            lo, hi = case.prize_range()
            print(f"   {case.emoji} {case.name} — {case.price}⭐  (призы ⭐{lo}–{hi}, {case.rarity})")


if __name__ == "__main__":
    seed()

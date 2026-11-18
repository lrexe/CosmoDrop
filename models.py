from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# Картинки подарков: эмодзи -> файл в static/img/gifts/<slug>.png
# Если файла нет на диске, фронтенд автоматически откатится на эмодзи.
# ---------------------------------------------------------------------------
GIFT_SLUGS = {
    "🧦": "pepe-socks", "🍭": "lollipop", "🍪": "ginger-cookie", "💝": "plush-heart",
    "🐱": "scared-cat", "🍓": "berry-box", "🤡": "jester-hat",
    "💍": "signet-ring", "🧿": "voodoo-doll", "🧠": "brain-box", "👠": "high-heels",
    "🎩": "durov-cap", "💎": "astral-crystal",
}


def gift_image(emoji):
    slug = GIFT_SLUGS.get(emoji)
    return f"/static/img/gifts/{slug}.png" if slug else None


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(64))
    first_name = db.Column(db.String(64))
    photo_url = db.Column(db.String(255))            # URL или emoji-аватар
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    stars_balance = db.Column(db.Integer, default=0)
    total_earned = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Integer, default=0)
    cases_opened = db.Column(db.Integer, default=0)
    best_drop = db.Column(db.Integer, default=0)
    legendary_count = db.Column(db.Integer, default=0)

    # прогрессия
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)

    # ежедневный бонус / колесо
    daily_streak = db.Column(db.Integer, default=0)
    last_daily_bonus = db.Column(db.DateTime)
    last_wheel_spin = db.Column(db.DateTime)

    # рефералы
    referral_code = db.Column(db.String(16), unique=True, index=True)
    referred_by = db.Column(db.BigInteger)
    referral_earned = db.Column(db.Integer, default=0)

    # provably fair
    fair_nonce = db.Column(db.Integer, default=0)

    is_banned = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default="user")

    case_history = db.relationship("CaseHistory", backref="user", lazy=True, cascade="all, delete-orphan")
    inventory = db.relationship("InventoryItem", backref="user", lazy=True, cascade="all, delete-orphan")

    @property
    def avatar(self):
        if self.photo_url and len(self.photo_url) <= 4:
            return self.photo_url
        return "🧑‍🚀"

    @property
    def photo(self):
        """Фото из профиля Telegram (https-ссылка) или None — тогда показываем эмодзи-аватар."""
        u = self.photo_url
        return u if u and u.startswith("https://") else None

    def to_dict(self):
        return {
            "telegram_id": self.telegram_id,
            "username": self.username,
            "first_name": self.first_name or self.username or "Космонавт",
            "avatar": self.avatar,
            "stars_balance": self.stars_balance,
            "total_earned": self.total_earned,
            "total_spent": self.total_spent,
            "cases_opened": self.cases_opened,
            "best_drop": self.best_drop,
            "legendary_count": self.legendary_count,
            "xp": self.xp,
            "level": self.level,
            "daily_streak": self.daily_streak,
            "referral_code": self.referral_code,
            "role": self.role,
        }


class Case(db.Model):
    __tablename__ = "cases"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(120))
    image = db.Column(db.String(255))
    emoji = db.Column(db.String(8), default="🎁")
    price = db.Column(db.Integer, nullable=False)
    rarity = db.Column(db.String(20), default="common")
    accent = db.Column(db.String(16), default="#7c3aed")
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    prizes = db.relationship("CasePrize", backref="case", lazy=True, cascade="all, delete-orphan")

    def prize_range(self):
        if not self.prizes:
            return (0, 0)
        values = [p.stars for p in self.prizes]
        return (min(values), max(values))

    def to_dict(self, with_prizes=False):
        lo, hi = self.prize_range()
        data = {
            "id": self.id, "name": self.name, "description": self.description,
            "image": gift_image(self.emoji), "emoji": self.emoji, "price": self.price,
            "rarity": self.rarity, "accent": self.accent,
            "prize_min": lo, "prize_max": hi,
        }
        if with_prizes:
            total = sum(p.chance for p in self.prizes) or 1
            data["prizes"] = [{
                "name": p.name, "emoji": p.emoji, "image": gift_image(p.emoji),
                "stars": p.stars, "rarity": p.rarity,
                "chance": round(p.chance / total * 100, 2),
            } for p in sorted(self.prizes, key=lambda x: x.stars, reverse=True)]
        return data


class CasePrize(db.Model):
    __tablename__ = "case_prizes"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    name = db.Column(db.String(60), default="Звёздный осколок")
    emoji = db.Column(db.String(8), default="✨")
    stars = db.Column(db.Integer, nullable=False)
    rarity = db.Column(db.String(20), default="common")
    chance = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {"name": self.name, "emoji": self.emoji, "image": gift_image(self.emoji),
                "stars": self.stars, "rarity": self.rarity}


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    emoji = db.Column(db.String(8), default="✨")
    stars = db.Column(db.Integer, nullable=False)
    rarity = db.Column(db.String(20), default="common")
    case_name = db.Column(db.String(50))
    won_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_sold = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "emoji": self.emoji,
            "image": gift_image(self.emoji),
            "stars": self.stars, "rarity": self.rarity, "case_name": self.case_name,
            "won_at": self.won_at.isoformat() if self.won_at else None,
            "is_sold": self.is_sold,
        }


class CaseHistory(db.Model):
    __tablename__ = "case_history"

    id = db.Column(db.Integer, primary_key=True)
    case_name = db.Column(db.String(50), nullable=False)
    prize_name = db.Column(db.String(100), nullable=False)
    prize_stars = db.Column(db.Integer, default=0)
    prize_rarity = db.Column(db.String(20), default="common")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "case_name": self.case_name, "prize_name": self.prize_name,
            "prize_stars": self.prize_stars, "prize_rarity": self.prize_rarity,
            "username": (self.user.username or self.user.first_name) if self.user else None,
            "avatar": self.user.avatar if self.user else "🧑‍🚀",
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
        }


class DailyProgress(db.Model):
    """Прогресс ежедневных заданий за конкретный день (UTC)."""
    __tablename__ = "daily_progress"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    day = db.Column(db.String(10), nullable=False, index=True)   # YYYY-MM-DD
    cases = db.Column(db.Integer, default=0)
    stars_won = db.Column(db.Integer, default=0)
    rare_won = db.Column(db.Integer, default=0)
    claimed = db.Column(db.String(64), default="")               # "q1,q3"


class Achievement(db.Model):
    """Полученные (заклейменные) достижения пользователя."""
    __tablename__ = "achievements"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    key = db.Column(db.String(32), nullable=False)
    claimed_at = db.Column(db.DateTime, default=datetime.utcnow)


class PromoCode(db.Model):
    __tablename__ = "promo_codes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    reward = db.Column(db.Integer, nullable=False)
    max_uses = db.Column(db.Integer, default=0)    # 0 = безлимит
    uses = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)


class PromoRedemption(db.Model):
    __tablename__ = "promo_redemptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    code = db.Column(db.String(32), nullable=False)
    redeemed_at = db.Column(db.DateTime, default=datetime.utcnow)


class GameRound(db.Model):
    """Раунд аркадной игры (ракета / мины / кости): ставка, исход, состояние."""
    __tablename__ = "game_rounds"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    game = db.Column(db.String(16), nullable=False, index=True)     # crash | mines | dice
    bet = db.Column(db.Integer, nullable=False)
    payout = db.Column(db.Integer, default=0)
    multiplier = db.Column(db.Float, default=0)
    state = db.Column(db.String(10), default="active", index=True)  # active | won | lost
    data = db.Column(db.Text, default="{}")                         # JSON: скрытое состояние раунда
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    user = db.relationship("User", lazy=True)

    def to_dict(self):
        return {
            "id": self.id, "game": self.game, "bet": self.bet, "payout": self.payout or 0,
            "multiplier": round(self.multiplier or 0, 2), "state": self.state,
            "profit": (self.payout or 0) - self.bet,
            "name": (self.user.first_name or self.user.username or "Космонавт") if self.user else "Космонавт",
            "avatar": self.user.avatar if self.user else "🧑‍🚀",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ===========================================================================
# VLOODY — PvP-розыгрыши NFT-подарков
# ===========================================================================

class GiftItem(db.Model):
    """NFT-подарок на хранении у платформы (эскроу).

    Подарок появляется здесь только после того, как бот-хранитель реально
    получил его в Telegram. Раунд можно создать только из такого подарка,
    поэтому организатор не может «разыграть» то, чего у платформы нет.
    """
    __tablename__ = "gift_items"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    emoji = db.Column(db.String(8), default="🎁")
    art = db.Column(db.String(4), default="a1")
    tg_gift_id = db.Column(db.String(64), unique=True)           # id подарка в Telegram
    # held — лежит в инвентаре | locked — в активном раунде
    # withdraw_requested — владелец запросил выдачу | withdrawn — выдан
    status = db.Column(db.String(20), default="held", index=True)
    source = db.Column(db.String(10), default="deposit")          # deposit | win
    # сколько звёзд Telegram берёт за передачу этого подарка — оплачивает тот, кто выводит
    transfer_fee = db.Column(db.Integer, default=0)
    # slug NFT-подарка (plushpepe-1337) — по нему берём настоящую картинку с CDN
    slug = db.Column(db.String(64), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "emoji": self.emoji, "art": self.art,
                "status": self.status, "source": self.source,
                "transfer_fee": self.transfer_fee or 0,
                "image": f"/gift-art/{self.slug}.jpg" if self.slug else None,
                "anim": f"/gift-art/{self.slug}.json" if self.slug else None}


class Pool(db.Model):
    """Раунд розыгрыша: wheel (колесо) | vault (сейф) | auction (слепой аукцион)."""
    __tablename__ = "pools"

    id = db.Column(db.Integer, primary_key=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    gift_id = db.Column(db.Integer, db.ForeignKey("gift_items.id"), nullable=False)
    mode = db.Column(db.String(10), nullable=False)
    min_stake = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default="live", index=True)   # live | finished | cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ends_at = db.Column(db.DateTime, index=True)                    # None — бессрочно (сейф)
    finished_at = db.Column(db.DateTime)

    bank = db.Column(db.Integer, default=0)                         # сумма всех ставок
    winner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    commission = db.Column(db.Integer, default=0)                   # доход платформы
    organizer_payout = db.Column(db.Integer, default=0)

    # честность: seed_hash публикуется при создании, seed — после завершения
    seed = db.Column(db.String(64), nullable=False)
    seed_hash = db.Column(db.String(64), nullable=False)
    cfg = db.Column(db.Text, default="{}")                          # JSON: настройки режима
    result = db.Column(db.Text, default="{}")                       # JSON: данные для проверки

    organizer = db.relationship("User", foreign_keys=[organizer_id], lazy=True)
    winner = db.relationship("User", foreign_keys=[winner_id], lazy=True)
    gift = db.relationship("GiftItem", lazy=True)


class PoolEntry(db.Model):
    """Ставка игрока в раунде (в сейфе — попытка с числом)."""
    __tablename__ = "pool_entries"

    id = db.Column(db.Integer, primary_key=True)
    pool_id = db.Column(db.Integer, db.ForeignKey("pools.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    number = db.Column(db.Integer)                                  # только для сейфа
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", lazy=True)
    __table_args__ = (db.UniqueConstraint("pool_id", "number", name="uq_pool_number"),)


class LedgerTx(db.Model):
    """Журнал движения звёзд. user_id = NULL — доход платформы."""
    __tablename__ = "ledger"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)                  # + зачисление, − списание
    title = db.Column(db.String(120), default="")
    ref = db.Column(db.String(128), unique=True)                    # id внешнего платежа — от дублей
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "amount": self.amount, "title": self.title,
                "ts": int(self.created_at.replace(tzinfo=timezone.utc).timestamp())}


class PayoutRequest(db.Model):
    """Заявка на вывод. Сумма списывается сразу, выплату подтверждает администратор."""
    __tablename__ = "payout_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    method = db.Column(db.String(10), default="STARS")
    destination = db.Column(db.String(128), nullable=False)
    amount = db.Column(db.Integer, nullable=False)                  # списано с баланса
    commission = db.Column(db.Integer, nullable=False)
    net = db.Column(db.Integer, nullable=False)                     # к выплате
    status = db.Column(db.String(10), default="pending", index=True)  # pending | paid | rejected
    net_nano = db.Column(db.BigInteger, default=0)                  # для TON: к выплате в nanoTON (курс на момент заявки)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    user = db.relationship("User", lazy=True)

    def to_dict(self, admin=False):
        d = {"id": self.id, "method": self.method, "destination": self.destination,
             "amount": self.amount, "commission": self.commission, "net": self.net,
             "status": self.status, "net_ton": (self.net_nano or 0) / 1e9,
             "ts": int(self.created_at.replace(tzinfo=timezone.utc).timestamp())}
        if admin and self.user:
            d["telegram_id"] = self.user.telegram_id
            d["username"] = self.user.username
        return d


class TonDeposit(db.Model):
    """Намерение пополнить баланс в TON. Перевод ищется в блокчейне по уникальному комментарию."""
    __tablename__ = "ton_deposits"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    comment = db.Column(db.String(32), unique=True, nullable=False, index=True)
    status = db.Column(db.String(10), default="pending", index=True)   # pending | credited
    amount_nano = db.Column(db.BigInteger, default=0)                   # сколько реально пришло
    vld = db.Column(db.Integer, default=0)                              # сколько зачислено
    tx_hash = db.Column(db.String(128), unique=True)                    # защита от повторного зачисления
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    credited_at = db.Column(db.DateTime)


def ensure_columns():
    """Мини-миграция: добавляет в существующие таблицы колонки, появившиеся позже."""
    added = {"gift_items": [("transfer_fee", "INTEGER DEFAULT 0"), ("slug", "VARCHAR(64)")],
             "payout_requests": [("net_nano", "BIGINT DEFAULT 0")]}
    inspector = db.inspect(db.engine)
    for table, columns in added.items():
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns:
            if name not in existing:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    # an upgraded DB gets the slug column but not the index the model declares for fresh DBs
    if inspector.has_table("gift_items"):
        db.session.execute(db.text("CREATE INDEX IF NOT EXISTS ix_gift_items_slug ON gift_items (slug)"))
    db.session.commit()

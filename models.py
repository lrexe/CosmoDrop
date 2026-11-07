from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


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
            "image": self.image, "emoji": self.emoji, "price": self.price,
            "rarity": self.rarity, "accent": self.accent,
            "prize_min": lo, "prize_max": hi,
        }
        if with_prizes:
            total = sum(p.chance for p in self.prizes) or 1
            data["prizes"] = [{
                "name": p.name, "emoji": p.emoji, "stars": p.stars,
                "rarity": p.rarity, "chance": round(p.chance / total * 100, 2),
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
        return {"name": self.name, "emoji": self.emoji, "stars": self.stars, "rarity": self.rarity}


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

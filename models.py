from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(64))
    first_name = db.Column(db.String(64))
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    stars_balance = db.Column(db.Integer, default=0)
    is_banned = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default="user")

    case_history = db.relationship(
        "CaseHistory",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "telegram_id": self.telegram_id,
            "username": self.username,
            "first_name": self.first_name,
            "stars_balance": self.stars_balance
        }


class Case(db.Model):
    __tablename__ = "cases"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(100))
    image = db.Column(db.String(255))
    price = db.Column(db.Integer, nullable=False)
    rarity = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

    prizes = db.relationship(
        "CasePrize",
        backref="case",
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "image": self.image,
            "price": self.price,
            "rarity": self.rarity
        }


class CasePrize(db.Model):
    __tablename__ = "case_prizes"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    stars = db.Column(db.Integer, nullable=False)
    chance = db.Column(db.Float, nullable=False)


class CaseHistory(db.Model):
    __tablename__ = "case_history"

    id = db.Column(db.Integer, primary_key=True)
    case_name = db.Column(db.String(50), nullable=False)
    prize_name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow)

"""Демо-данные Vloody: подарки в эскроу, живые раунды трёх режимов, один завершённый."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from models import db, User, GiftItem, Pool, PoolEntry, LedgerTx, PayoutRequest
from bot.vloody import settle


def _pool(organizer, name, emoji, art, mode, min_stake, minutes=None, vault_max=None, secret=None):
    gift = GiftItem(owner_id=organizer.id, name=name, emoji=emoji, art=art, status="locked")
    db.session.add(gift)
    db.session.flush()
    seed = secrets.token_hex(32)
    cfg = {}
    if mode == "vault":
        cfg = {"max": vault_max, "secret": secret}
        seed_hash = hashlib.sha256(f"{secret}:{seed}".encode()).hexdigest()
    else:
        seed_hash = hashlib.sha256(bytes.fromhex(seed)).hexdigest()
    pool = Pool(organizer_id=organizer.id, gift_id=gift.id, mode=mode, min_stake=min_stake,
                ends_at=datetime.utcnow() + timedelta(minutes=minutes) if minutes is not None else None,
                seed=seed, seed_hash=seed_hash, cfg=json.dumps(cfg), created_at=datetime.utcnow())
    db.session.add(pool)
    db.session.flush()
    return pool


def _entry(pool, user, amount, number=None, mins_ago=5):
    db.session.add(PoolEntry(pool_id=pool.id, user_id=user.id, amount=amount, number=number,
                             created_at=datetime.utcnow() - timedelta(minutes=mins_ago)))
    pool.bank = (pool.bank or 0) + amount


def seed_vloody(demo_telegram_id):
    """Пересоздаёт раунды и подарки. Балансы игроков не трогает."""
    for model in (PoolEntry, Pool, GiftItem, LedgerTx, PayoutRequest):
        model.query.delete()
    db.session.flush()

    demo = User.query.filter_by(telegram_id=demo_telegram_id).first()
    players = (User.query.filter(User.telegram_id != demo_telegram_id)
               .order_by(User.id).limit(6).all())
    if not demo or len(players) < 5:
        return 0
    p = players

    wheel = _pool(p[0], "Plush Pepe #1337", "🐸", "a1", "wheel", 5, minutes=84)
    _entry(wheel, p[1], 90, mins_ago=30)
    _entry(wheel, p[2], 40, mins_ago=12)

    vault = _pool(p[1], "Evil Eye #88", "👁", "a2", "vault", 10, vault_max=125, secret=77)
    for user, number in ((p[0], 7), (p[2], 13), (p[3], 100), (p[4], 42)):
        _entry(vault, user, 10, number=number)

    cigar = _pool(p[2], "Vintage Cigar #7", "🚬", "a3", "wheel", 25, minutes=22 * 60)
    _entry(cigar, p[3], 75)

    auction = _pool(p[3], "Jelly Rabbit #42", "🎭", "a4", "auction", 20, minutes=190)
    _entry(auction, p[0], 60)
    _entry(auction, p[4], 45)

    done = _pool(p[4], "Durov's Cap #9", "🎩", "a1", "wheel", 10, minutes=0)
    _entry(done, p[0], 120, mins_ago=90)
    _entry(done, p[1], 200, mins_ago=80)
    _entry(done, p[2], 60, mins_ago=70)
    db.session.flush()
    settle(done)

    for name, emoji, art in (("Astral Shard #404", "💎", "a2"), ("Spring Basket #21", "🥚", "a4")):
        db.session.add(GiftItem(owner_id=demo.id, name=name, emoji=emoji, art=art))
    db.session.commit()
    return Pool.query.count()

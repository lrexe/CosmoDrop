"""
Vloody — PvP-розыгрыши NFT-подарков.

Модель: организатор вносит подарок (эскроу у бота-хранителя) и открывает раунд,
игроки делают ставки во внутренней валюте VLD, победитель забирает подарок, организатор —
ставки за вычетом комиссии платформы. Платформа никогда не платит из своего
кармана: все выплаты — это перераспределение ставок игроков.

Режимы:
  wheel   — колесо: шанс пропорционален сумме ставок, розыгрыш по таймеру;
  vault   — кибер-сейф: угадай секретное число, каждое число можно занять один раз;
  auction — слепой накопительный аукцион: ставки скрыты и не возвращаются,
            побеждает наибольшая накопленная ставка.

Честность: исход не зависит от того, кто игрок. При создании раунда публикуется
seed_hash = sha256(seed); после завершения раскрывается seed, по которому любой
может пересчитать результат (см. /api/pools/<id>, поле fair).
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from models import db, User, GiftItem, Pool, PoolEntry, LedgerTx, PayoutRequest, TonDeposit
from bot.cases import get_or_create_user, err
from bot import envfile
from bot.giftart import SLUG_RE
from bot.engine import gen_referral_code, level_from_xp, cum_xp
from bot.auth import (
    BOT_TOKEN, DEMO_MODE, RELAY_SECRET, ADMIN_SECRET, clean_text, service_auth,
)

vloody_bp = Blueprint("vloody_api", __name__)

# ------------------------------------------------------------------ экономика
COMMISSION_RATE = 0.045         # платформа берёт 4.5% банка, организатор — остальное
REF_RATE = 0.01                 # рефереру — 1% ставок друга (из комиссии платформы)
# Две независимые валюты: VLD (1 Star = 1 VLD) и VDT (1 TON = 1 VDT, хранится в милли-VDT).
# Ни один путь не меняет VLD на VDT и обратно. Комиссии — в промилле, округление вниз (целочисленно).
TRANSFER_MIN = {"VLD": 150, "VDT": 1500}
TRANSFER_FEE_PERMILLE = 100                       # 10%
PAYOUT_MIN = {"VLD": 275, "VDT": 2500}            # VLD -> Stars, VDT -> TON
PAYOUT_FEE_PERMILLE = {"VLD": 135, "VDT": 115}    # 13.5% и 11.5%
PAYOUT_METHOD = {"VLD": "STARS", "VDT": "TON"}
STARS_TO_VLD = 1                                  # 1 ⭐ -> 1 VLD, без комиссии
NANO_PER_MILLI = 10**6                            # 1 TON = 1 VDT: милли-VDT = nanoTON // 10⁶
TON_MIN_DEPOSIT_NANO = int(float(os.getenv("TON_MIN_DEPOSIT", "0.5")) * 1e9)
TON_WALLET = os.getenv("TON_WALLET_ADDRESS", "").strip()        # кошелёк платформы для депозитов
TON_API_BASE = os.getenv("TON_API_BASE", "https://toncenter.com/api/v2").rstrip("/")
TON_API_KEY = os.getenv("TON_API_KEY", "").strip()
TON_SCAN_EVERY = 5                # не чаще раза в N секунд ходим в блокчейн-API
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")     # https-адрес Mini App
START_PARAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TON_ADDRESS_RE = re.compile(r"^(?:[EUk0]Q[A-Za-z0-9_-]{46}|-?\d:[0-9a-fA-F]{64})$")

MODES = ("wheel", "vault", "auction")
DURATIONS_MIN = (15, 30, 60, 180, 360)
ROUND_LIFE = timedelta(hours=6)       # сейф живёт 6 часов; колесо и аукцион — не дольше
CREATE_FEE_VDT = 100                  # 0.1 VDT за запуск раунда, не возвращается
VAULT_SIZES = (25, 50, 100, 125)
# в единицах валюты (VDT — милли): допустимая минимальная ставка/цена билета и потолок одной ставки
MIN_STAKE_RANGE = {"VLD": (1, 10000), "VDT": (10, 100000)}
MAX_STAKE = {"VLD": 100000, "VDT": 100000}
ARTS = ("a1", "a2", "a3", "a4")

# (название, эмодзи, slug) — каждый slug проверен на CDN (nft.fragment.com/gift/<slug>.medium.jpg -> 200)
DEMO_GIFTS = [("Plush Pepe", "🐸", "plushpepe-1337"), ("Evil Eye", "👁", "evileye-88"),
              ("Vintage Cigar", "🚬", "vintagecigar-7"), ("Jelly Bunny", "🎭", "jellybunny-42"),
              ("Astral Shard", "💎", "astralshard-404"), ("Durov's Cap", "🎩", "durovscap-9"),
              ("Spring Basket", "🥚", "springbasket-21"), ("Witch Hat", "🕯️", "witchhat-1")]


def clean_slug(raw):
    """slug NFT-подарка (plushpepe-1337): только если проходит SLUG_RE, иначе None."""
    slug = str(raw or "").strip().lower()
    return slug if SLUG_RE.fullmatch(slug) else None


# ------------------------------------------------------------------ хелперы
def now():
    return datetime.utcnow()


def ts(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt else None


def me():
    return get_or_create_user(None)


def display_name(u):
    if not u:
        return "Игрок"
    return ("@" + u.username) if u.username else (u.first_name or "Игрок")


def lock(user):
    """Блокирует строку пользователя на время денежной операции (PostgreSQL)."""
    db.session.flush()            # иначе refresh затрёт ещё не записанные изменения этой же строки
    db.session.refresh(user, with_for_update=True)
    return user


CURRENCIES = ("VLD", "VDT")


def _move(user, amount, kind, title, ref, cur, field, label):
    if user is not None:
        if (getattr(user, field) or 0) + amount < 0:
            raise ValueError(f"Недостаточно {label}")
        setattr(user, field, (getattr(user, field) or 0) + amount)
    db.session.add(LedgerTx(user_id=user.id if user else None, kind=kind, amount=amount,
                            currency=cur, title=title[:120], ref=ref))


def move_vld(user, amount, kind, title, ref=None):
    """Единственная точка изменения баланса VLD. user=None — доход платформы."""
    _move(user, amount, kind, title, ref, "VLD", "stars_balance", "VLD")


def move_vdt(user, amount, kind, title, ref=None):
    """Единственная точка изменения баланса VDT (в милли-VDT). user=None — доход платформы."""
    _move(user, amount, kind, title, ref, "VDT", "vdt_balance", "VDT")


move = move_vld      # старое имя для кода, который ещё не знает про две валюты


def mover(cur):
    if cur == "VLD":
        return move_vld
    if cur == "VDT":
        return move_vdt
    raise ValueError("Неизвестная валюта")


def fee_floor(amount, permille):
    return amount * permille // 1000


def clean_currency(raw, default="VLD"):
    """Валюта из тела запроса: только из белого списка, иначе None."""
    cur = default if raw is None or raw == "" else raw
    return cur if cur in CURRENCIES else None


def balance_of(user, cur):
    mover(cur)
    return (user.stars_balance if cur == "VLD" else user.vdt_balance) or 0


def fmt_cur(amount, cur):
    mover(cur)
    if cur == "VLD":
        return f"{amount} VLD"
    sign, a = ("-" if amount < 0 else ""), abs(amount)
    frac = f"{a % 1000:03d}".rstrip("0")
    return f"{sign}{a // 1000}{'.' + frac if frac else ''} VDT"


def bump_activity(user, staked):
    """Стрик активных дней и опыт — без каких-либо начислений звёзд."""
    today = now().date()
    last = user.last_daily_bonus.date() if user.last_daily_bonus else None
    if last != today:
        user.daily_streak = (user.daily_streak or 0) + 1 if last == today - timedelta(days=1) else 1
        user.last_daily_bonus = now()
    user.xp = (user.xp or 0) + max(1, staked // 2)
    user.level = level_from_xp(user.xp)
    user.total_spent = (user.total_spent or 0) + staked


# ------------------------------------------------------------------ завершение раундов
def pool_ref(pool, what):
    """Ключ проводки платформы по раунду. seed_hash в ключе — id раунда в SQLite может повториться."""
    return f"pool:{pool.id}:{pool.seed_hash[:16]}:{what}"


def _finish(pool, winner_id, result):
    entries = PoolEntry.query.filter_by(pool_id=pool.id).all()
    bank = sum(e.amount for e in entries)
    commission = int(bank * COMMISSION_RATE)
    payout = bank - commission

    pool.status, pool.finished_at = "finished", now()
    pool.winner_id, pool.bank = winner_id, bank
    pool.organizer_payout = payout
    pool.result = json.dumps(result)

    gift = pool.gift
    gift.owner_id, gift.status, gift.source = winner_id, "held", "win"

    title = f"{gift.emoji} {gift.name}"
    pay = mover(pool.currency)                 # всё — в валюте раунда, никаких пересчётов
    organizer = lock(pool.organizer)
    pay(organizer, payout, "organizer_payout", f"Ставки раунда #{pool.id} · {title}")
    if pool.currency == "VLD":                 # статистика заработка ведётся в VLD
        organizer.total_earned = (organizer.total_earned or 0) + payout

    # реферальные — из комиссии платформы, не из кармана
    per_user = {}
    for e in entries:
        per_user[e.user_id] = per_user.get(e.user_id, 0) + e.amount
    for uid, total in per_user.items():
        staker = db.session.get(User, uid)
        bonus = int(total * REF_RATE)
        if not staker or not staker.referred_by or bonus <= 0 or bonus > commission:
            continue
        referrer = User.query.filter_by(telegram_id=staker.referred_by).first()
        if referrer and not referrer.is_banned:
            pay(lock(referrer), bonus, "referral", f"Реферал {display_name(staker)} · раунд #{pool.id}")
            if pool.currency == "VLD":
                referrer.referral_earned = (referrer.referral_earned or 0) + bonus
            commission -= bonus

    pool.commission = commission
    # ref уникален в БД: вторая комиссия по тому же раунду физически не запишется
    pay(None, commission, "commission", f"Комиссия раунда #{pool.id}", ref=pool_ref(pool, "commission"))


CANCEL_REASONS = ("no_players", "not_cracked", "organizer", "admin")


def _cancel(pool, reason, extra=None):
    """Раунд отменён: подарок возвращается организатору. Сбор за запуск не возвращается."""
    assert reason in CANCEL_REASONS
    pool.status, pool.finished_at = "cancelled", now()
    pool.result = json.dumps({**(extra or {}), "cancel_reason": reason})
    pool.gift.status = "held"


def _refund_all(pool, reason):
    """Возвращает каждую ставку ровно в той сумме и валюте, в какой она была сделана."""
    refund = mover(pool.currency)
    refunded = 0
    for e in PoolEntry.query.filter_by(pool_id=pool.id).order_by(PoolEntry.id).all():
        staker = lock(db.session.get(User, e.user_id))
        refund(staker, e.amount, "refund", f"Возврат ставки · раунд #{pool.id} отменён")
        if pool.currency == "VLD":
            staker.total_spent = max(0, (staker.total_spent or 0) - e.amount)
        refunded += e.amount
    pool.bank = 0
    _cancel(pool, reason, {"refunded": refunded})
    return refunded


def settle(pool):
    """Подводит итог раунда, у которого вышло время. Повторный вызов ничего не делает."""
    db.session.flush()
    db.session.refresh(pool, with_for_update=True)     # статус — под блокировкой строки
    if pool.status != "live" or not pool.ends_at or pool.ends_at > now():
        return
    entries = PoolEntry.query.filter_by(pool_id=pool.id).order_by(PoolEntry.id).all()
    if pool.mode == "vault":
        # вскрытый сейф завершается сразу в vault_try; живой по истечении 6 часов — не вскрыт
        return _refund_all(pool, "not_cracked")
    if len({e.user_id for e in entries}) < 2:
        return _refund_all(pool, "no_players")

    if pool.mode == "wheel":
        total = sum(e.amount for e in entries)
        digest = hmac.new(bytes.fromhex(pool.seed), f"{pool.id}:{total}:{len(entries)}".encode(),
                          hashlib.sha256).hexdigest()
        ticket = int(digest, 16) % total
        acc, winner_id = 0, entries[-1].user_id
        for e in entries:
            acc += e.amount
            if ticket < acc:
                winner_id = e.user_id
                break
        _finish(pool, winner_id, {"ticket": ticket, "total": total, "entries": len(entries)})

    elif pool.mode == "auction":
        totals, reached = {}, {}
        for e in entries:
            totals[e.user_id] = totals.get(e.user_id, 0) + e.amount
            reached[e.user_id] = e.id               # когда игрок достиг своей итоговой суммы
        winner_id = max(totals, key=lambda u: (totals[u], -reached[u]))
        _finish(pool, winner_id, {"top": totals[winner_id], "bidders": len(totals)})


def settle_due():
    due = Pool.query.filter(Pool.status == "live", Pool.ends_at != None,  # noqa: E711
                            Pool.ends_at <= now()).all()
    for p in due:
        settle(p)
    if due:
        db.session.commit()


@vloody_bp.before_request
def _auto_settle():
    settle_due()


# ------------------------------------------------------------------ сериализация
def pool_dict(pool, user, detail=False):
    cfg = json.loads(pool.cfg or "{}")
    entries = PoolEntry.query.filter_by(pool_id=pool.id).order_by(PoolEntry.id).all()
    finished = pool.status != "live"
    blind = pool.mode == "auction" and not finished
    uid = user.id if user else None

    mine = sum(e.amount for e in entries if e.user_id == uid)
    bank = sum(e.amount for e in entries)
    participants = len({e.user_id for e in entries})
    gift = pool.gift
    art = gift.to_dict()

    d = {
        "id": pool.id, "mode": pool.mode, "status": pool.status,
        "title": gift.name, "emoji": gift.emoji, "art": gift.art,
        "image": art["image"], "anim": art["anim"],
        "min_stake": pool.min_stake,
        "ends_ts": ts(pool.ends_at), "created_ts": ts(pool.created_at), "now_ts": ts(now()),
        "organizer": display_name(pool.organizer), "is_organizer": pool.organizer_id == uid,
        "bank": None if blind else bank,
        "participants": None if blind else participants,
        "my_total": mine,
        "my_chance": round(mine / bank * 100, 1) if (pool.mode == "wheel" and bank) else None,
        "winner": ({"name": display_name(pool.winner), "avatar": pool.winner.avatar, "photo": pool.winner.photo,
                    "is_me": pool.winner_id == uid} if pool.winner_id else None),
        "commission_rate": COMMISSION_RATE,
        "currency": pool.currency or "VLD", "create_fee": CREATE_FEE_VDT,
    }
    if pool.status == "cancelled":
        res = json.loads(pool.result or "{}")
        # у старых отменённых раундов причины нет: админ помечал by=admin, остальные были пустыми
        d["cancel_reason"] = res.get("cancel_reason") or ("admin" if res.get("by") == "admin" else "no_players")
    if pool.mode == "vault":
        d["vault_max"] = cfg.get("max")
        d["taken"] = len(entries)
    if not detail:
        return d

    d["fair"] = {"seed_hash": pool.seed_hash}
    if finished:
        d["fair"].update(seed=pool.seed, result=json.loads(pool.result or "{}"))

    if pool.mode == "wheel":
        agg, order = {}, []
        for e in entries:
            if e.user_id not in agg:
                order.append(e.user_id)
                agg[e.user_id] = {"key": e.user_id, "name": display_name(e.user),
                                  "avatar": e.user.avatar, "photo": e.user.photo, "amount": 0, "is_me": e.user_id == uid}
            agg[e.user_id]["amount"] += e.amount
        d["stakes"] = [agg[k] for k in order]
        d["winner_key"] = pool.winner_id
    elif pool.mode == "vault":
        d["numbers"] = [{"number": e.number, "name": display_name(e.user), "is_me": e.user_id == uid,
                         "win": finished and e.number == cfg.get("secret")} for e in entries]
        d["fair"]["how"] = "seed_hash = sha256('<секретное число>:<seed>')"
        if finished:
            d["secret"] = cfg.get("secret")
    elif pool.mode == "auction" and finished:
        totals = {}
        for e in entries:
            row = totals.setdefault(e.user_id, {"name": display_name(e.user), "amount": 0,
                                                "is_me": e.user_id == uid})
            row["amount"] += e.amount
        d["bids"] = sorted(totals.values(), key=lambda r: -r["amount"])
    return d


# ================================================================== РАУНДЫ
@vloody_bp.route("/api/pools", methods=["GET"])
def pools_list():
    user = me()
    live = Pool.query.filter_by(status="live").order_by(Pool.id.desc()).limit(60).all()
    done = Pool.query.filter_by(status="finished").order_by(Pool.finished_at.desc()).limit(10).all()
    return jsonify({"live": [pool_dict(p, user) for p in live],
                    "finished": [pool_dict(p, user) for p in done]})


@vloody_bp.route("/api/pools/<int:pool_id>", methods=["GET"])
def pool_get(pool_id):
    pool = db.session.get(Pool, pool_id)
    if not pool:
        return err("Раунд не найден", 404)
    return jsonify(pool_dict(pool, me(), detail=True))


@vloody_bp.route("/api/pools", methods=["POST"])
def pool_create():
    user = me()
    data = request.get_json(silent=True) or {}
    if user.is_banned:
        return err("Доступ заблокирован", 403)

    mode = data.get("mode")
    if mode not in MODES:
        return err("Неизвестный режим", 400)
    currency = data.get("currency") or "VLD"
    if currency not in CURRENCIES:
        return err("Неизвестная валюта", 400)
    try:
        min_stake = int(data.get("min_stake"))
        gift_id = int(data.get("gift_id"))
    except (TypeError, ValueError):
        return err("Заполни настройки раунда", 400)
    lo, hi = MIN_STAKE_RANGE[currency]
    if not lo <= min_stake <= hi:
        return err(f"Ставка от {fmt_cur(lo, currency)} до {fmt_cur(hi, currency)}", 400)

    # эскроу: раунд создаётся только из подарка, который уже лежит у платформы
    gift = GiftItem.query.filter_by(id=gift_id, owner_id=user.id).with_for_update().first()
    if not gift or gift.status != "held":
        return err("Сначала передай подарок боту-хранителю — раунд создаётся только из инвентаря", 400)

    cfg, minutes = {}, None
    seed = secrets.token_hex(32)
    if mode == "vault":
        try:
            size = int(data.get("vault_max", 100))
        except (TypeError, ValueError):
            return err("Неверный размер сейфа", 400)
        if size not in VAULT_SIZES:
            return err("Неверный размер сейфа", 400)
        # число выбирает сервер, а не организатор: иначе он мог бы слить его «своему» игроку
        secret = secrets.randbelow(size) + 1
        cfg = {"max": size, "secret": secret}
        seed_hash = hashlib.sha256(f"{secret}:{seed}".encode()).hexdigest()
    else:
        try:
            minutes = int(data.get("duration_min"))
        except (TypeError, ValueError):
            return err("Выбери время окончания", 400)
        if minutes not in DURATIONS_MIN:
            return err("Недопустимая длительность", 400)
        seed_hash = hashlib.sha256(bytes.fromhex(seed)).hexdigest()

    if (lock(user).vdt_balance or 0) < CREATE_FEE_VDT:
        return err("Нужно 0.1 VDT на запуск раунда — пополни баланс TON", 400)

    gift.status = "locked"
    created = now()
    pool = Pool(organizer_id=user.id, gift_id=gift.id, mode=mode, currency=currency, min_stake=min_stake,
                # сейф живёт ровно 6 часов, колесо и аукцион — выбранное время (не больше 6 часов)
                ends_at=created + (timedelta(minutes=minutes) if minutes else ROUND_LIFE),
                seed=seed, seed_hash=seed_hash, cfg=json.dumps(cfg), created_at=created)
    db.session.add(pool)
    db.session.flush()
    move_vdt(user, -CREATE_FEE_VDT, "create_fee", f"Сбор за запуск раунда #{pool.id}")
    move_vdt(None, CREATE_FEE_VDT, "create_fee", f"Сбор за запуск раунда #{pool.id}", ref=pool_ref(pool, "fee"))
    db.session.commit()
    return jsonify(pool_dict(pool, user, detail=True))


@vloody_bp.route("/api/pools/<int:pool_id>/cancel", methods=["POST"])
def pool_cancel(pool_id):
    user = me()
    pool = Pool.query.filter_by(id=pool_id).with_for_update().first()
    if not pool or pool.organizer_id != user.id:
        return err("Раунд не найден", 404)
    if pool.status != "live":
        return err("Раунд уже завершён", 400)
    if PoolEntry.query.filter_by(pool_id=pool.id).count():
        return err("В раунде уже есть ставки — отменить нельзя", 400)
    _cancel(pool, "organizer")                  # сбор за запуск не возвращается
    db.session.commit()
    return jsonify({"cancelled": True})


def _stake_guard(pool_id, mode):
    """Общие проверки перед ставкой. Возвращает (user, pool, error)."""
    user = me()
    pool = Pool.query.filter_by(id=pool_id).with_for_update().first()
    if not pool or pool.mode != mode:
        return None, None, err("Раунд не найден", 404)
    if pool.status != "live" or (pool.ends_at and pool.ends_at <= now()):
        return None, None, err("Раунд уже завершён", 400)
    if user.is_banned:
        return None, None, err("Доступ заблокирован", 403)
    if pool.organizer_id == user.id:
        return None, None, err("Организатор не может участвовать в своём раунде", 400)
    return lock(user), pool, None


def _place(user, pool, amount, kind, number=None):
    """Ставка всегда в валюте раунда: валюта из тела запроса не читается вовсе."""
    title = f"{pool.gift.emoji} {pool.gift.name} · раунд #{pool.id}"
    mover(pool.currency)(user, -amount, kind, title)
    db.session.add(PoolEntry(pool_id=pool.id, user_id=user.id, amount=amount,
                             number=number, created_at=now()))
    pool.bank = (pool.bank or 0) + amount
    # опыт и статистика ставок ведутся в VLD; VDT-ставка засчитывает только активность дня
    bump_activity(user, amount if pool.currency == "VLD" else 0)


def _amount(data, pool):
    cur = pool.currency
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return None, err("Неверная сумма", 400)
    minimum = max(pool.min_stake, MIN_STAKE_RANGE[cur][0])
    if amount < minimum:
        return None, err(f"Минимальная ставка — {fmt_cur(minimum, cur)}", 400)
    if amount > MAX_STAKE[cur]:
        return None, err(f"Максимальная ставка — {fmt_cur(MAX_STAKE[cur], cur)}", 400)
    return amount, None


def _stake_or_bid(pool_id, mode, kind):
    user, pool, e = _stake_guard(pool_id, mode)
    if e:
        return e
    amount, e = _amount(request.get_json(silent=True) or {}, pool)
    if e:
        return e
    if balance_of(user, pool.currency) < amount:
        return err(f"Недостаточно {pool.currency}", 400)
    _place(user, pool, amount, kind)
    db.session.commit()
    return jsonify({"balance": user.stars_balance, "balances": {"VLD": user.stars_balance or 0,
                                                                "VDT": user.vdt_balance or 0},
                    "pool": pool_dict(pool, user, detail=True)})


@vloody_bp.route("/api/pools/<int:pool_id>/stake", methods=["POST"])
def wheel_stake(pool_id):
    return _stake_or_bid(pool_id, "wheel", "stake")


@vloody_bp.route("/api/pools/<int:pool_id>/bid", methods=["POST"])
def auction_bid(pool_id):
    return _stake_or_bid(pool_id, "auction", "bid")


@vloody_bp.route("/api/pools/<int:pool_id>/vault", methods=["POST"])
def vault_try(pool_id):
    user, pool, e = _stake_guard(pool_id, "vault")
    if e:
        return e
    cfg = json.loads(pool.cfg)
    try:
        number = int((request.get_json(silent=True) or {}).get("number"))
    except (TypeError, ValueError):
        return err("Введи число", 400)
    if number < 1 or number > cfg["max"]:
        return err(f"Число от 1 до {cfg['max']}", 400)
    if PoolEntry.query.filter_by(pool_id=pool.id, number=number).first():
        return err("Это число уже занято", 400)
    if balance_of(user, pool.currency) < pool.min_stake:
        return err(f"Недостаточно {pool.currency}", 400)

    _place(user, pool, pool.min_stake, "vault", number=number)
    db.session.flush()
    hit = number == cfg["secret"]
    if hit:
        _finish(pool, user.id, {"secret": cfg["secret"]})
    db.session.commit()
    return jsonify({"hit": hit, "number": number, "balance": user.stars_balance,
                    "balances": {"VLD": user.stars_balance or 0, "VDT": user.vdt_balance or 0},
                    "pool": pool_dict(pool, user, detail=True)})


# ================================================================== ПРОФИЛЬ
def profile_dict(user):
    lvl = user.level or 1
    base, nxt = cum_xp(lvl), cum_xp(lvl + 1)
    paid = db.session.query(db.func.coalesce(db.func.sum(PayoutRequest.net), 0)).filter_by(
        user_id=user.id, status="paid").scalar()
    return {
        "telegram_id": user.telegram_id, "name": user.first_name or "Игрок",
        "username": user.username, "avatar": user.avatar, "photo": user.photo,
        "balance": user.stars_balance,
        "balances": {"VLD": user.stars_balance or 0, "VDT": user.vdt_balance or 0},
        "stats": {
            "nft_won": Pool.query.filter_by(winner_id=user.id, status="finished").count(),
            "participations": db.session.query(PoolEntry.pool_id).filter_by(
                user_id=user.id).distinct().count(),
            "withdrawn": int(paid),
            "organized": Pool.query.filter_by(organizer_id=user.id).count(),
        },
        "streak": user.daily_streak or 0,
        "streak_today": bool(user.last_daily_bonus and user.last_daily_bonus.date() == now().date()),
        "level": {"level": lvl, "xp": (user.xp or 0) - base, "need": nxt - base},
        "referral": {
            "code": user.referral_code,
            "invited": User.query.filter_by(referred_by=user.telegram_id).count(),
            "earned": user.referral_earned or 0,
            "rate": REF_RATE,
        },
        "demo": DEMO_MODE,
        "limits": {
            "payout_min_vld": PAYOUT_MIN["VLD"], "payout_fee_vld": PAYOUT_FEE_PERMILLE["VLD"] / 1000,
            "payout_min_vdt": PAYOUT_MIN["VDT"], "payout_fee_vdt": PAYOUT_FEE_PERMILLE["VDT"] / 1000,
            "transfer_min_vld": TRANSFER_MIN["VLD"], "transfer_min_vdt": TRANSFER_MIN["VDT"],
            "transfer_fee": TRANSFER_FEE_PERMILLE / 1000, "commission": COMMISSION_RATE,
            "create_fee_vdt": CREATE_FEE_VDT,
            # старые ключи — их читает текущий интерфейс (до его переделки под две валюты)
            "transfer_min": TRANSFER_MIN["VLD"], "payout_min": PAYOUT_MIN["VLD"],
            "payout_fee": PAYOUT_FEE_PERMILLE["VLD"] / 1000, "payout_fee_ton": PAYOUT_FEE_PERMILLE["VDT"] / 1000,
        },
        "rates": {"stars_to_vld": STARS_TO_VLD, "ton_to_vdt": 1,
                  "vld_per_ton": 1,           # старый ключ для текущего интерфейса: 1 TON = 1 VDT
                  "ton_min": TON_MIN_DEPOSIT_NANO / 1e9,
                  "ton_enabled": bool(TON_WALLET) or DEMO_MODE},
    }


WELCOME_VLD = int(os.getenv("WELCOME_VLD", "1000"))
WELCOME_VDT = 1000                    # 1 VDT в милли
# User.welcome_bonus: 0 — ничего; 1 — выдано 1000 VLD и NFT (до появления VDT); 2 — выдано всё, включая 1 VDT


def grant_welcome(user):
    """Демо-режим: каждому игроку один раз — 1000 VLD, случайный NFT-подарок и 1 VDT (не настоящие).

    Тем, кто получил бонус до появления VDT (welcome_bonus=1), один раз доначисляется только 1 VDT.
    """
    if not DEMO_MODE or (user.welcome_bonus or 0) >= 2:
        return False
    lock(user)
    stage = user.welcome_bonus or 0
    if stage >= 2:                            # параллельный запрос успел раньше
        return False
    if stage < 1:
        name, emoji, slug = secrets.choice(DEMO_GIFTS)
        db.session.add(GiftItem(owner_id=user.id, name=f"{name} #{slug.rsplit('-', 1)[1]}", emoji=emoji,
                                art=secrets.choice(ARTS), slug=slug, source="bonus"))
        move_vld(user, WELCOME_VLD, "bonus", f"Приветственный бонус · {WELCOME_VLD} VLD и {emoji} {name}")
    move_vdt(user, WELCOME_VDT, "bonus", f"Приветственный бонус · {fmt_cur(WELCOME_VDT, 'VDT')}")
    user.welcome_bonus = 2
    db.session.commit()
    return True


@vloody_bp.route("/api/profile", methods=["GET", "POST"])
def profile():
    user = me()
    grant_welcome(user)
    if not user.referral_code:
        user.referral_code = gen_referral_code(user.telegram_id)
        db.session.commit()
    # если игрок закрыл приложение сразу после перевода TON — зачислим при следующем заходе
    if TonDeposit.query.filter(TonDeposit.user_id == user.id, TonDeposit.status == "pending",
                               TonDeposit.created_at >= now() - timedelta(hours=2)).first():
        scan_ton_deposits()
    return jsonify(profile_dict(user))


@vloody_bp.route("/api/referral/bind", methods=["POST"])
def referral_bind():
    user = me()
    code = clean_text((request.get_json(silent=True) or {}).get("code") or "", 16)
    if user.referred_by or not code:
        return jsonify({"bound": False})
    referrer = User.query.filter_by(referral_code=code.upper().replace("REF_", "")).first()
    if not referrer or referrer.id == user.id:
        return jsonify({"bound": False})
    user.referred_by = referrer.telegram_id
    db.session.commit()
    return jsonify({"bound": True})


@vloody_bp.route("/api/inventory/gifts", methods=["GET"])
def gifts():
    user = me()
    items = (GiftItem.query.filter(GiftItem.owner_id == user.id, GiftItem.status != "withdrawn")
             .order_by(GiftItem.id.desc()).all())
    return jsonify({"gifts": [g.to_dict() for g in items]})


@vloody_bp.route("/api/inventory/gifts/<int:gift_id>/withdraw", methods=["POST"])
def gift_withdraw(gift_id):
    user = me()
    if DEMO_MODE:
        return err("В демо-режиме подарки нельзя вывести в Telegram — они не настоящие", 403)
    gift = GiftItem.query.filter_by(id=gift_id, owner_id=user.id).with_for_update().first()
    if not gift or gift.status != "held":
        return err("Подарок недоступен для вывода", 400)
    if user.is_banned:
        return err("Доступ заблокирован", 403)
    fee = gift.transfer_fee or 0
    if fee:
        # Telegram берёт звёзды за передачу подарка — платит тот, кто выводит, а не платформа
        if lock(user).stars_balance < fee:
            return err(f"Для вывода нужно {fee} VLD — столько Telegram берёт за передачу подарка", 400)
        move(user, -fee, "gift_fee", f"Плата Telegram за передачу · {gift.emoji} {gift.name}")
        move(None, fee, "gift_fee", f"Резерв на передачу подарка #{gift.id}")
    gift.status = "withdraw_requested"
    db.session.commit()
    return jsonify({"gift": gift.to_dict(), "fee": fee, "balance": user.stars_balance})


@vloody_bp.route("/api/transactions", methods=["GET"])
def transactions():
    user = me()
    rows = LedgerTx.query.filter_by(user_id=user.id).order_by(LedgerTx.id.desc()).limit(40).all()
    return jsonify({"items": [r.to_dict() for r in rows]})


# ================================================================== КОШЕЛЁК
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


AMBIGUOUS_USERNAME = "Этот @username неоднозначен — попроси друга открыть Vloody, чтобы обновить профиль"


def find_by_username(raw):
    """Пользователь по @username без учёта регистра -> (user|None, problem).

    problem: None; "bad" — имя некорректное; "ambiguous" — имя есть у нескольких активных
    игроков (у кого-то оно устарело). Тогда не угадываем: перевод необратим.
    """
    name = str(raw or "").strip()
    if name.startswith("@"):
        name = name[1:]
    if not USERNAME_RE.fullmatch(name):
        return None, "bad"
    rows = User.query.filter(db.func.lower(User.username) == name.lower()).limit(10).all()
    active = [u for u in rows if not u.is_banned]
    if len(active) > 1:
        return None, "ambiguous"
    return (active or rows or [None])[0], None


def _int_arg(raw):
    if isinstance(raw, bool):
        raise ValueError
    return int(raw)


@vloody_bp.route("/api/users/lookup", methods=["GET"])
def user_lookup():
    if "username" in request.args or "telegram_id" not in request.args:
        u, problem = find_by_username(request.args.get("username"))
        if problem == "bad":
            return err("Укажи @username: латиница, цифры и _, от 3 до 32 символов", 400)
        if problem == "ambiguous":
            return err(AMBIGUOUS_USERNAME, 409)
    else:                                     # запасной способ — по Telegram ID
        try:
            tid = int(request.args.get("telegram_id", ""))
        except ValueError:
            return err("Неверный Telegram ID", 400)
        u = User.query.filter_by(telegram_id=tid).first()
    if not u or u.is_banned:
        return err("Пользователь не найден", 404)
    return jsonify({"telegram_id": u.telegram_id, "name": u.first_name or display_name(u),
                    "username": u.username, "photo": u.photo})


@vloody_bp.route("/api/transfer", methods=["POST"])
def transfer():
    user = me()
    data = request.get_json(silent=True) or {}
    cur = clean_currency(data.get("currency"))
    if not cur:
        return err("Неизвестная валюта", 400)
    try:
        amount = _int_arg(data.get("amount"))
    except (TypeError, ValueError):
        return err("Проверь получателя и сумму", 400)
    if data.get("to_username") not in (None, ""):
        target, problem = find_by_username(data.get("to_username"))
        if problem == "bad":
            return err("Проверь @username получателя", 400)
        if problem == "ambiguous":
            return err(AMBIGUOUS_USERNAME, 409)
    else:                                     # старый клиент: по Telegram ID
        try:
            target = User.query.filter_by(telegram_id=_int_arg(data.get("to_telegram_id"))).first()
        except (TypeError, ValueError):
            return err("Проверь получателя и сумму", 400)
    if amount < TRANSFER_MIN[cur]:
        return err(f"Минимальная сумма перевода — {fmt_cur(TRANSFER_MIN[cur], cur)}", 400)
    if not target or target.is_banned:
        return err("Пользователь не найден", 404)
    if target.id == user.id:
        return err("Нельзя перевести самому себе", 400)

    # блокируем в порядке id, чтобы встречные переводы не зависли
    for u in sorted((user, target), key=lambda x: x.id):
        lock(u)
    if user.is_banned:
        return err("Доступ заблокирован", 403)
    if balance_of(user, cur) < amount:
        return err(f"Недостаточно {cur}", 400)
    fee = fee_floor(amount, TRANSFER_FEE_PERMILLE)
    net = amount - fee
    pay = mover(cur)                          # обе стороны и комиссия — в одной валюте
    ref = "transfer:" + secrets.token_hex(10)
    pay(user, -amount, "transfer_out", f"Перевод → {display_name(target)}", ref=ref + ":out")
    pay(target, net, "transfer_in", f"Перевод от {display_name(user)}", ref=ref + ":in")
    pay(None, fee, "commission", "Комиссия перевода", ref=ref + ":fee")
    db.session.commit()
    return jsonify({"currency": cur, "sent": amount, "fee": fee, "received": net,
                    "balance": user.stars_balance,
                    "balances": {"VLD": user.stars_balance or 0, "VDT": user.vdt_balance or 0}})


def payout_ref(req, what):
    """Ключ проводки по заявке на вывод. Время создания в ключе — id в SQLite может повториться."""
    return f"payout:{req.id}:{req.created_at:%Y%m%d%H%M%S%f}:{what}"


@vloody_bp.route("/api/payout", methods=["POST"])
def payout_request():
    if DEMO_MODE:
        return err("В демо-режиме вывод отключён: VLD, VDT и подарки не настоящие", 403)
    user = lock(me())
    if user.is_banned:
        return err("Доступ заблокирован", 403)
    data = request.get_json(silent=True) or {}
    raw = data.get("currency")
    if raw in (None, ""):                     # старый клиент: method STARS -> VLD, TON -> VDT
        raw = {"STARS": "VLD", "TON": "VDT"}.get(str(data.get("method") or "STARS"))
    cur = clean_currency(raw, default=None)
    if not cur:
        return err("Неизвестная валюта вывода", 400)
    method = PAYOUT_METHOD[cur]
    destination = clean_text(data.get("destination") or "", 128)
    try:
        amount = _int_arg(data.get("amount"))
    except (TypeError, ValueError):
        return err("Неверная сумма", 400)
    if method == "TON":
        if not destination or not TON_ADDRESS_RE.match(destination):
            return err("Укажи адрес TON-кошелька (EQ… или UQ…)", 400)
    elif not destination or len(destination) < 3:
        return err("Укажи, куда выводить", 400)
    if amount < PAYOUT_MIN[cur]:
        return err(f"Минимальный вывод — {fmt_cur(PAYOUT_MIN[cur], cur)}", 400)
    if balance_of(user, cur) < amount:
        return err(f"Недостаточно {cur}", 400)

    fee = fee_floor(amount, PAYOUT_FEE_PERMILLE[cur])
    net = amount - fee
    # 1 VDT = 1 TON: администратор выплатит ровно net_nano; Stars выплачиваются по net (1 VLD = 1 ⭐)
    net_nano = net * NANO_PER_MILLI if cur == "VDT" else 0
    req = PayoutRequest(user_id=user.id, method=method, currency=cur, destination=destination,
                        amount=amount, commission=fee, net=net, net_nano=net_nano, created_at=now())
    db.session.add(req)
    db.session.flush()
    mover(cur)(user, -amount, "payout", f"Заявка на вывод ({method}) → {destination[:24]}",
               ref=payout_ref(req, "out"))
    db.session.commit()
    return jsonify({"request": req.to_dict(), "balance": user.stars_balance,
                    "balances": {"VLD": user.stars_balance or 0, "VDT": user.vdt_balance or 0}})


@vloody_bp.route("/api/payouts", methods=["GET"])
def payouts_mine():
    rows = PayoutRequest.query.filter_by(user_id=me().id).order_by(PayoutRequest.id.desc()).limit(20).all()
    return jsonify({"items": [r.to_dict() for r in rows]})


# ---- пополнение ----
def tg_api(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def stars_to_vld(stars):
    """1 ⭐ = 1 VLD, без комиссии."""
    return int(stars) * STARS_TO_VLD


@vloody_bp.route("/api/wallet/topup", methods=["POST"])
def topup():
    """Покупка VLD за Telegram Stars. Демо: мгновенно. Бой: ссылка на счёт."""
    user = me()
    try:
        stars = int((request.get_json(silent=True) or {}).get("amount"))
    except (TypeError, ValueError):
        return err("Неверная сумма", 400)
    if stars < 1 or stars > 100000:
        return err("Сумма от 1 до 100 000 Stars", 400)

    vld = stars_to_vld(stars)
    if DEMO_MODE:
        move_vld(lock(user), vld, "deposit", f"Демо-пополнение · {stars} Stars")
        db.session.commit()
        return jsonify({"credited": vld, "balance": user.stars_balance})
    try:
        res = tg_api("createInvoiceLink", {
            "title": "Пополнение Vloody", "description": f"{vld} VLD на баланс",
            "payload": f"topup:{user.telegram_id}:{stars}", "currency": "XTR",
            "prices": [{"label": "VLD", "amount": stars}]})
        return jsonify({"invoice_link": res["result"], "will_credit": vld})
    except Exception:
        return err("Не удалось создать счёт, попробуй позже", 502)


# ---- пополнение в TON --------------------------------------------------------
_last_scan = 0.0


def nano_to_vdt(nano):
    """1 TON = 1 VDT: nanoTON -> милли-VDT (остаток меньше 0.001 TON отбрасывается)."""
    return int(nano) // NANO_PER_MILLI


def _credit_ton(dep, nano, tx_hash):
    """TON зачисляется только в VDT. ref ton:<hash> уникален — одна транзакция не зачтётся дважды."""
    user = db.session.get(User, dep.user_id)
    milli = nano_to_vdt(nano)
    dep.status, dep.amount_nano, dep.vld = "credited", nano, milli
    dep.tx_hash, dep.credited_at = tx_hash, now()
    move_vdt(lock(user), milli, "deposit", f"Пополнение {nano / 1e9:g} TON", ref=f"ton:{tx_hash}")


def _tx_comment(msg):
    text = msg.get("message")
    if not text:
        data = msg.get("msg_data") or {}
        if data.get("@type") == "msg.dataText" and data.get("text"):
            try:
                text = base64.b64decode(data["text"]).decode("utf-8", "ignore")
            except Exception:
                text = ""
    return (text or "").strip()


def scan_ton_deposits(force=False):
    """Ищет входящие переводы на кошелёк платформы и зачисляет их по комментарию.

    Зачисляется только то, что реально пришло в блокчейн, и только один раз
    (уникальность по хешу транзакции). Возвращает число зачисленных депозитов.
    """
    global _last_scan
    if not TON_WALLET or (not force and time.time() - _last_scan < TON_SCAN_EVERY):
        return 0
    _last_scan = time.time()
    url = (f"{TON_API_BASE}/getTransactions?"
           + urllib.parse.urlencode({"address": TON_WALLET, "limit": 100}))
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": TON_API_KEY} if TON_API_KEY else {})
        with urllib.request.urlopen(req, timeout=10) as r:
            txs = json.loads(r.read()).get("result") or []
    except Exception:
        return 0

    credited = 0
    for tx in txs:
        msg = tx.get("in_msg") or {}
        tx_hash = (tx.get("transaction_id") or {}).get("hash")
        try:
            nano = int(msg.get("value") or 0)
        except (TypeError, ValueError):
            continue
        comment = _tx_comment(msg)
        if not tx_hash or not msg.get("source") or nano < TON_MIN_DEPOSIT_NANO or not comment:
            continue
        if TonDeposit.query.filter_by(tx_hash=tx_hash).first():
            continue
        dep = TonDeposit.query.filter_by(comment=comment).with_for_update().first()
        if not dep:
            continue
        if dep.status != "pending":
            # игрок перевёл ещё раз с тем же комментарием — деньги не должны пропасть
            dep = TonDeposit(user_id=dep.user_id, comment=f"{comment}:{secrets.token_hex(4)}",
                             created_at=now())
            db.session.add(dep)
            db.session.flush()
        try:
            _credit_ton(dep, nano, tx_hash)
            db.session.commit()          # по одному: дубль одной транзакции не откатывает остальные
            credited += 1
        except IntegrityError:           # параллельная сверка уже зачислила этот хеш
            db.session.rollback()
    return credited


@vloody_bp.route("/api/wallet/ton/intent", methods=["POST"])
def ton_intent():
    """Выдаёт адрес и уникальный комментарий для перевода."""
    user = me()
    if not TON_WALLET and not DEMO_MODE:
        return err("Пополнение в TON пока не настроено", 503)
    try:
        ton = float((request.get_json(silent=True) or {}).get("amount_ton"))
    except (TypeError, ValueError):
        return err("Неверная сумма", 400)
    nano = int(round(ton * 1e9))
    if nano < TON_MIN_DEPOSIT_NANO or ton > 100000:
        return err(f"Минимум {TON_MIN_DEPOSIT_NANO / 1e9:g} TON", 400)
    if TonDeposit.query.filter(TonDeposit.user_id == user.id, TonDeposit.status == "pending",
                               TonDeposit.created_at >= now() - timedelta(hours=1)).count() >= 10:
        return err("Слишком много незавершённых пополнений, подожди", 429)

    dep = TonDeposit(user_id=user.id, comment="vl" + secrets.token_hex(6), created_at=now())
    db.session.add(dep)
    db.session.commit()
    address = TON_WALLET or "EQDemoWa11etDemoWa11etDemoWa11etDemoWa11etDemoWa1"
    link = f"ton://transfer/{address}?" + urllib.parse.urlencode({"amount": nano, "text": dep.comment})
    return jsonify({"deposit_id": dep.id, "address": address, "comment": dep.comment,
                    "amount_nano": str(nano), "will_credit": nano_to_vdt(nano), "currency": "VDT", "link": link,
                    "demo": not TON_WALLET})


@vloody_bp.route("/api/wallet/ton/check", methods=["POST"])
def ton_check():
    user = me()
    dep = TonDeposit.query.filter_by(id=(request.get_json(silent=True) or {}).get("deposit_id") or 0,
                                     user_id=user.id).first()
    if not dep:
        return err("Пополнение не найдено", 404)
    if dep.status == "pending":
        scan_ton_deposits()
        db.session.refresh(dep)
    db.session.refresh(user)
    return jsonify({"status": dep.status, "credited": dep.vld or 0, "currency": "VDT",
                    "balance": user.stars_balance, "balances": {"VLD": user.stars_balance or 0,
                                                                "VDT": user.vdt_balance or 0}})


@vloody_bp.route("/api/wallet/ton/demo-pay", methods=["POST"])
def ton_demo_pay():
    """Только демо: имитирует приход перевода в блокчейн."""
    if not DEMO_MODE or TON_WALLET:
        return err("Недоступно", 403)
    user = me()
    data = request.get_json(silent=True) or {}
    dep = TonDeposit.query.filter_by(id=data.get("deposit_id") or 0, user_id=user.id,
                                     status="pending").first()
    try:
        nano = int(data.get("amount_nano"))
    except (TypeError, ValueError):
        nano = 0
    if not dep or nano < TON_MIN_DEPOSIT_NANO or nano > 10**14:
        return err("Пополнение не найдено", 404)
    _credit_ton(dep, nano, "demo-" + secrets.token_hex(8))
    db.session.commit()
    return jsonify({"status": "credited", "credited": dep.vld, "currency": "VDT",
                    "balance": user.stars_balance, "balances": {"VLD": user.stars_balance or 0,
                                                                "VDT": user.vdt_balance or 0}})


WELCOME_TEXT = (
    "🩸 Добро пожаловать в Vloody{name}!\n\n"
    "Честные розыгрыши NFT-подарков между игроками. Платформа ничего не выплачивает "
    "из своего кармана — победитель получает банк раунда, а результат можно проверить.\n\n"
    "🎡 Колесо — шанс растёт вместе со ставкой\n"
    "🔐 Кибер-сейф — угадай число, открой сейф\n"
    "🔨 Слепой аукцион — ставки скрыты до конца\n\n"
    "Как начать:\n"
    "1️⃣ Нажми «Открыть Vloody» и пополни баланс звёздами или TON\n"
    "2️⃣ Выбери раунд и сделай ставку — или внеси свой подарок и запусти свой раунд\n"
    "3️⃣ Выиграл — подарок можно вывести прямо в Telegram\n\n"
    "/help — подробная справка · /fair — как проверить честность"
)

HELP_TEXT = (
    "📖 Справка Vloody\n\n"
    "💰 Баланс — две отдельные валюты: VLD (пополнение Telegram Stars, 1 ⭐ = 1 VLD) и VDT "
    "(пополнение TON, 1 TON = 1 VDT). Друг в друга не обмениваются. Вывод — по заявке.\n\n"
    "🎁 Подарки — принимаются уникальные (NFT) подарки. Отправь их аккаунту-хранителю "
    "(инструкция — в боте хранителя, команда /start). Подарок появится в Профиле → Инвентарь.\n\n"
    "🎯 Раунд — подарок лежит у хранителя, игроки делают ставки. Комиссия платформы — 4.5% с банка, запуск раунда — 0.1 VDT. Раунд живёт до 6 часов; если игроков меньше двух (или сейф не вскрыт) — ставки возвращаются.\n\n"
    "👥 Друзья — приглашай по реферальной ссылке из Профиля и получай процент с комиссии.\n\n"
    "Вопросы по честности — /fair"
)

FAIR_TEXT = (
    "🛡 Честность (Provably Fair)\n\n"
    "• Перед раундом мы публикуем хэш секретного числа — изменить его потом невозможно.\n"
    "• После раунда раскрывается само число. Победитель определяется из него по открытой формуле.\n"
    "• Любой может сам посчитать хэш и убедиться, что результат не подменён.\n"
    "• Раунд стартует только с подарка, который реально лежит у хранителя.\n\n"
    "Проверка — на экране раунда, кнопка «Проверить честность»."
)

BOT_COMMANDS = [{"command": "start", "description": "Открыть Vloody"},
                {"command": "help", "description": "Как это работает"},
                {"command": "fair", "description": "Как проверить честность"}]
BOT_SHORT_DESC = "Честные PvP-розыгрыши NFT-подарков: колесо, сейф, аукцион."
BOT_LONG_DESC = ("Vloody — честные розыгрыши NFT-подарков между игроками. Колесо, кибер-сейф и слепой "
                 "аукцион, результат каждого раунда можно проверить. Нажми «Открыть» или /start.")


def _send_welcome(chat_id, param="", first_name="", text=None):
    """Ответ на /start, /help, /fair: кнопки открывают Mini App (с кодом друга или раундом из ссылки)."""
    public = envfile.current("PUBLIC_URL").strip().rstrip("/")
    if not public:
        return {"status": "no_public_url"}
    url = public + "/"
    if param and START_PARAM_RE.match(param):
        url += "?startapp=" + param
    if text is None:
        safe = re.sub(r"[^\w .\-]", "", first_name or "", flags=re.UNICODE).strip()[:30]
        text = WELCOME_TEXT.format(name=f", {safe}" if safe else "")
    rows = [[{"text": "🎡 Открыть Vloody", "web_app": {"url": url}}]]
    relay = os.getenv("RELAY_USERNAME", "").strip().lstrip("@")
    if relay:
        rows.append([{"text": "🎁 Как внести подарок", "url": f"https://t.me/{relay}?start=help"}])
    try:
        tg_api("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": {"inline_keyboard": rows}})
    except Exception:
        return {"status": "send_failed"}
    return {"status": "welcome_sent"}


def handle_payment_update(update):
    """Обработка вебхука Telegram (вызывается из app.py после проверки секрета)."""
    pcq = update.get("pre_checkout_query")
    if pcq:
        try:
            tg_api("answerPreCheckoutQuery", {"pre_checkout_query_id": pcq["id"], "ok": True})
        except Exception:
            pass
        return {"ok": True}

    msg = update.get("message") or {}
    text = msg.get("text") or ""
    if text.startswith("/") and (msg.get("chat") or {}).get("type") == "private":
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].split("@")[0].lower()
        if cmd == "start":
            return _send_welcome(msg["chat"]["id"], parts[1].strip() if len(parts) > 1 else "",
                                 (msg.get("from") or {}).get("first_name", ""))
        if cmd in ("help", "fair"):
            return _send_welcome(msg["chat"]["id"], text=HELP_TEXT if cmd == "help" else FAIR_TEXT)

    pay = msg.get("successful_payment")
    if not pay or pay.get("currency") != "XTR":
        return {"status": "ignored"}
    charge = pay.get("telegram_payment_charge_id")
    if not charge or LedgerTx.query.filter_by(ref=charge).first():
        return {"status": "duplicate"}
    user = User.query.filter_by(telegram_id=(msg.get("from") or {}).get("id")).first()
    if not user:
        return {"status": "user_not_found"}
    stars = int(pay["total_amount"])                  # у XTR нет копеек: сумма уже в звёздах
    vld = stars_to_vld(stars)
    move_vld(lock(user), vld, "deposit", f"Пополнение · {stars} Telegram Stars", ref=charge)
    db.session.commit()
    return {"status": "credited", "amount": vld}


@vloody_bp.route("/api/demo/gift", methods=["POST"])
def demo_gift():
    """Только демо: имитирует получение подарка ботом-хранителем."""
    if not DEMO_MODE:
        return err("Передай подарок боту-хранителю", 403)
    user = me()
    if GiftItem.query.filter_by(owner_id=user.id, status="held").count() >= 12:
        return err("Инвентарь полон", 400)
    name, emoji, slug = secrets.choice(DEMO_GIFTS)
    gift = GiftItem(owner_id=user.id, name=f"{name} #{slug.rsplit('-', 1)[1]}", emoji=emoji,
                    art=secrets.choice(ARTS), slug=slug)
    db.session.add(gift)
    db.session.commit()
    return jsonify({"gift": gift.to_dict()})


# ================================================================== ЛИДЕРЫ
PERIODS = {"day": 1, "week": 7, "month": 30, "all": None}


@vloody_bp.route("/api/leaderboard/<period>", methods=["GET"])
def leaderboard(period):
    if period not in PERIODS:
        return err("Неизвестный период", 400)
    user = me()
    q = db.session.query(PoolEntry.user_id, db.func.sum(PoolEntry.amount).label("vol"))
    wins_q = db.session.query(Pool.winner_id, db.func.count(Pool.id)).filter(Pool.status == "finished")
    if PERIODS[period]:
        since = now() - timedelta(days=PERIODS[period])
        q = q.filter(PoolEntry.created_at >= since)
        wins_q = wins_q.filter(Pool.finished_at >= since)
    rows = q.group_by(PoolEntry.user_id).order_by(db.desc("vol")).all()
    wins = dict(wins_q.group_by(Pool.winner_id).all())

    users = {u.id: u for u in User.query.filter(User.id.in_([r[0] for r in rows[:100]] + [user.id])).all()}
    entries = [{"rank": i, "name": display_name(users[uid]), "avatar": users[uid].avatar, "photo": users[uid].photo,
                "volume": int(vol), "wins": wins.get(uid, 0), "is_me": uid == user.id}
               for i, (uid, vol) in enumerate(rows[:100], start=1) if uid in users]
    my_rank = next((i for i, (uid, _) in enumerate(rows, start=1) if uid == user.id), None)
    my_vol = next((int(v) for uid, v in rows if uid == user.id), 0)
    top100 = int(rows[99][1]) if len(rows) >= 100 else 0
    return jsonify({"entries": entries,
                    "me": {"rank": my_rank, "volume": my_vol, "wins": wins.get(user.id, 0),
                           "to_top100": max(0, top100 - my_vol + 1) if (my_rank or 101) > 100 else 0}})


@vloody_bp.route("/api/winners", methods=["GET"])
def winners():
    rows = (Pool.query.filter(Pool.status == "finished", Pool.winner_id != None)  # noqa: E711
            .order_by(Pool.finished_at.desc()).limit(10).all())
    items = []
    for p in rows:
        art = p.gift.to_dict()  # картинка и анимация подарка — те же адреса, что в инвентаре
        items.append({"pool_id": p.id, "title": p.gift.name, "emoji": p.gift.emoji,
                      "winner": display_name(p.winner), "ts": ts(p.finished_at),
                      "bank": p.bank, "image": art["image"], "anim": art["anim"]})
    return jsonify({"items": items})


# ================================================================== БОТ-ХРАНИТЕЛЬ (эскроу)
def _relay_only():
    return None if service_auth(RELAY_SECRET, "X-Relay-Secret") else err("Forbidden", 403)


@vloody_bp.route("/api/relay/gift-deposit", methods=["POST"])
def relay_deposit():
    """Бот-хранитель сообщает: подарок от пользователя реально получен."""
    denied = _relay_only()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        tid = int(data.get("telegram_id"))
    except (TypeError, ValueError):
        return err("telegram_id required", 400)
    tg_gift_id = clean_text(str(data.get("tg_gift_id") or ""), 64)
    name = clean_text(data.get("name") or "", 60)
    if not tg_gift_id or not name:
        return err("tg_gift_id and name required", 400)
    if GiftItem.query.filter_by(tg_gift_id=tg_gift_id).first():
        return jsonify({"status": "duplicate"})

    user = User.query.filter_by(telegram_id=tid).first()
    if not user:
        user = User(telegram_id=tid, first_name="Игрок", stars_balance=0,
                    referral_code=gen_referral_code(tid))
        db.session.add(user)
        db.session.flush()
    emoji = clean_text(data.get("emoji") or "", 8) or "🎁"
    try:
        fee = max(0, min(int(data.get("transfer_star_count") or 0), 100000))
    except (TypeError, ValueError):
        fee = 0
    gift = GiftItem(owner_id=user.id, name=name, emoji=emoji, tg_gift_id=tg_gift_id,
                    art=ARTS[user.id % len(ARTS)], transfer_fee=fee, slug=clean_slug(data.get("slug")))
    db.session.add(gift)
    db.session.commit()
    return jsonify({"status": "credited", "gift": gift.to_dict()})


@vloody_bp.route("/api/relay/withdrawals", methods=["GET"])
def relay_withdrawals():
    denied = _relay_only()
    if denied:
        return denied
    rows = GiftItem.query.filter_by(status="withdraw_requested").all()
    owners = {u.id: u.telegram_id for u in User.query.filter(User.id.in_([g.owner_id for g in rows])).all()}
    return jsonify({"items": [{"gift_id": g.id, "tg_gift_id": g.tg_gift_id, "name": g.name,
                               "telegram_id": owners.get(g.owner_id),
                               "transfer_fee": g.transfer_fee or 0} for g in rows]})


@vloody_bp.route("/api/relay/gift-delivered", methods=["POST"])
def relay_delivered():
    denied = _relay_only()
    if denied:
        return denied
    gift = db.session.get(GiftItem, (request.get_json(silent=True) or {}).get("gift_id") or 0)
    if not gift or gift.status != "withdraw_requested":
        return err("Gift not found", 404)
    gift.status, gift.tg_gift_id = "withdrawn", None
    db.session.commit()
    return jsonify({"status": "withdrawn"})


@vloody_bp.route("/api/relay/gift-failed", methods=["POST"])
def relay_failed():
    """Передать подарок не удалось: возвращаем его в инвентарь и плату за передачу — владельцу."""
    denied = _relay_only()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    gift = db.session.get(GiftItem, data.get("gift_id") or 0)
    if not gift or gift.status != "withdraw_requested":
        return err("Gift not found", 404)
    gift.status = "held"
    fee = gift.transfer_fee or 0
    owner = db.session.get(User, gift.owner_id)
    if fee and owner:
        move(lock(owner), fee, "gift_fee_refund", f"Возврат платы за передачу · {gift.emoji} {gift.name}")
        move(None, -fee, "gift_fee", f"Возврат резерва на передачу подарка #{gift.id}")
    db.session.commit()
    return jsonify({"status": "held", "refunded": fee})


# ================================================================== АДМИН
_admin_fails = {}                 # ip -> (число неудач, время первой)
ADMIN_MAX_FAILS, ADMIN_FAIL_WINDOW = 10, 600


def _admin_only():
    ip = request.remote_addr or "?"
    fails, since = _admin_fails.get(ip, (0, 0.0))
    if time.time() - since > ADMIN_FAIL_WINDOW:
        fails = 0
    if fails >= ADMIN_MAX_FAILS:
        return err("Слишком много неверных попыток, подожди 10 минут", 429)
    # в демо-режиме без заданного секрета пускаем по слову «demo» — только для локальных проб
    secret = ADMIN_SECRET or ("demo" if DEMO_MODE else "")
    if service_auth(secret, "X-Admin-Secret"):
        _admin_fails.pop(ip, None)
        return None
    _admin_fails[ip] = (fails + 1, since if fails else time.time())
    return err("Forbidden", 403)


@vloody_bp.route("/api/admin/payouts", methods=["GET"])
def admin_payouts():
    denied = _admin_only()
    if denied:
        return denied
    status = request.args.get("status", "pending")
    q = PayoutRequest.query
    if status != "all":
        q = q.filter_by(status=status)
    order = PayoutRequest.id if status == "pending" else PayoutRequest.id.desc()
    return jsonify({"items": [r.to_dict(admin=True) for r in q.order_by(order).limit(200).all()]})


@vloody_bp.route("/api/admin/payouts/<int:req_id>", methods=["POST"])
def admin_payout_process(req_id):
    denied = _admin_only()
    if denied:
        return denied
    action = (request.get_json(silent=True) or {}).get("action")
    req = PayoutRequest.query.filter_by(id=req_id).with_for_update().first()
    if not req or req.status != "pending":
        return err("Заявка не найдена", 404)
    pay = mover(req.currency or "VLD")        # валюта заявки; деньги уже списаны при подаче
    if action == "paid":
        req.status = "paid"
        pay(None, req.commission, "commission", f"Комиссия вывода #{req.id}", ref=payout_ref(req, "fee"))
    elif action == "reject":
        req.status = "rejected"
        pay(lock(req.user), req.amount, "payout_refund", f"Возврат заявки #{req.id}", ref=payout_ref(req, "refund"))
    else:
        return err("action: paid | reject", 400)
    req.processed_at = now()
    db.session.commit()
    return jsonify({"request": req.to_dict(admin=True)})


@vloody_bp.route("/api/admin/ton/scan", methods=["POST"])
def admin_ton_scan():
    """Принудительная сверка депозитов (удобно дёргать по cron раз в минуту)."""
    denied = _admin_only()
    if denied:
        return denied
    return jsonify({"credited": scan_ton_deposits(force=True)})


def _sum(col, *filters):
    return int(db.session.query(db.func.coalesce(db.func.sum(col), 0)).filter(*filters).scalar())


@vloody_bp.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    denied = _admin_only()
    if denied:
        return denied
    platform = LedgerTx.user_id == None                                   # noqa: E711
    today = datetime.combine(now().date(), datetime.min.time())

    def revenue(since=None, cur="VLD"):
        # валюты не складываем: VLD и милли-VDT — разные единицы
        f = [platform, LedgerTx.kind == "commission", LedgerTx.currency == cur]
        if since:
            f.append(LedgerTx.created_at >= since)
        return _sum(LedgerTx.amount, *f)

    def by_source(cur):
        return {name: _sum(LedgerTx.amount, platform, LedgerTx.kind == "commission", LedgerTx.currency == cur,
                           LedgerTx.title.like(prefix + "%"))
                for name, prefix in (("rounds", "Комиссия раунда"), ("transfers", "Комиссия перевода"),
                                     ("payouts", "Комиссия вывода"))}
    pending = PayoutRequest.query.filter_by(status="pending")
    return jsonify({
        "revenue": {"today": revenue(today), "week": revenue(now() - timedelta(days=7)),
                    "total": revenue(), "by_source": by_source("VLD")},
        "revenue_vdt": {"today": revenue(today, "VDT"), "week": revenue(now() - timedelta(days=7), "VDT"),
                        "total": revenue(cur="VDT"), "by_source": by_source("VDT"),
                        "create_fees": _sum(LedgerTx.amount, platform, LedgerTx.kind == "create_fee",
                                            LedgerTx.currency == "VDT")},
        "liabilities": {
            "user_balances": _sum(User.stars_balance),
            "locked_in_live_pools": _sum(Pool.bank, Pool.status == "live"),
            "pending_payouts": _sum(PayoutRequest.amount, PayoutRequest.status == "pending",
                                    PayoutRequest.currency == "VLD"),
            "user_balances_vdt": _sum(User.vdt_balance),
            "pending_payouts_vdt": _sum(PayoutRequest.amount, PayoutRequest.status == "pending",
                                        PayoutRequest.currency == "VDT"),
            "gift_fee_reserve": _sum(LedgerTx.amount, platform, LedgerTx.kind == "gift_fee"),
        },
        "counts": {
            "users": User.query.count(), "banned": User.query.filter_by(is_banned=True).count(),
            "pools": {st: Pool.query.filter_by(status=st).count() for st in ("live", "finished", "cancelled")},
            "pending_payouts": pending.count(),
            "gift_withdrawals": GiftItem.query.filter_by(status="withdraw_requested").count(),
            "gifts_in_escrow": GiftItem.query.filter(GiftItem.status.in_(("held", "locked"))).count(),
        },
        "deposits": {
            "ton_nano": _sum(TonDeposit.amount_nano, TonDeposit.status == "credited"),
            "ton_vld": _sum(TonDeposit.vld, TonDeposit.status == "credited"),   # старый ключ: это милли-VDT
            "ton_vdt_milli": _sum(TonDeposit.vld, TonDeposit.status == "credited"),
            "ton_pending": TonDeposit.query.filter(
                TonDeposit.status == "pending", TonDeposit.created_at >= now() - timedelta(hours=2)).count(),
            "paid_out_vld": _sum(PayoutRequest.amount, PayoutRequest.status == "paid", PayoutRequest.currency == "VLD"),
            "paid_out_vdt": _sum(PayoutRequest.amount, PayoutRequest.status == "paid", PayoutRequest.currency == "VDT"),
        },
        "config": {"demo": DEMO_MODE, "vld_per_ton": 1, "ton_to_vdt": 1, "ton_wallet": TON_WALLET,
                   "commission": COMMISSION_RATE},
    })


@vloody_bp.route("/api/admin/pools", methods=["GET"])
def admin_pools():
    denied = _admin_only()
    if denied:
        return denied
    status = request.args.get("status", "live")
    q = Pool.query
    if status != "all":
        q = q.filter_by(status=status)
    out = []
    for p in q.order_by(Pool.id.desc()).limit(100).all():
        entries = PoolEntry.query.filter_by(pool_id=p.id).all()
        out.append({
            "id": p.id, "mode": p.mode, "status": p.status, "title": p.gift.name, "emoji": p.gift.emoji,
            "organizer": display_name(p.organizer), "organizer_tid": p.organizer.telegram_id,
            "min_stake": p.min_stake, "bank": sum(e.amount for e in entries), "entries": len(entries),
            "participants": len({e.user_id for e in entries}),
            "created_ts": ts(p.created_at), "ends_ts": ts(p.ends_at),
            "winner": display_name(p.winner) if p.winner_id else None,
            "commission": p.commission or 0, "organizer_payout": p.organizer_payout or 0,
        })
    return jsonify({"items": out})


@vloody_bp.route("/api/admin/pools/<int:pool_id>/refund", methods=["POST"])
def admin_pool_refund(pool_id):
    """Аварийная отмена живого раунда: все ставки возвращаются игрокам, подарок — организатору."""
    denied = _admin_only()
    if denied:
        return denied
    pool = Pool.query.filter_by(id=pool_id).with_for_update().first()
    if not pool or pool.status != "live":
        return err("Живой раунд не найден", 404)
    refunded = _refund_all(pool, "admin")       # в валюте раунда
    db.session.commit()
    return jsonify({"cancelled": True, "refunded": refunded})


@vloody_bp.route("/api/admin/users", methods=["GET"])
def admin_users():
    denied = _admin_only()
    if denied:
        return denied
    term = (request.args.get("q") or "").strip().lstrip("@")
    q = User.query
    if term.isdigit():
        q = q.filter(User.telegram_id == int(term))
    elif term:
        like = f"%{term}%"
        q = q.filter(db.or_(User.username.ilike(like), User.first_name.ilike(like)))
    rows = q.order_by(User.stars_balance.desc()).limit(50).all()
    return jsonify({"items": [{
        "telegram_id": u.telegram_id, "name": display_name(u), "first_name": u.first_name,
        "balance": u.stars_balance, "banned": bool(u.is_banned), "level": u.level or 1,
        "staked": u.total_spent or 0, "earned": u.total_earned or 0,
        "registered_ts": ts(u.registered_at),
    } for u in rows]})


@vloody_bp.route("/api/admin/users/<int:tid>", methods=["GET", "POST"])
def admin_user(tid):
    denied = _admin_only()
    if denied:
        return denied
    u = User.query.filter_by(telegram_id=tid).first()
    if not u:
        return err("Пользователь не найден", 404)
    if request.method == "POST":
        action = (request.get_json(silent=True) or {}).get("action")
        if action not in ("ban", "unban"):
            return err("action: ban | unban", 400)
        u.is_banned = action == "ban"
        db.session.commit()
    ledger = LedgerTx.query.filter_by(user_id=u.id).order_by(LedgerTx.id.desc()).limit(40).all()
    return jsonify({
        "telegram_id": u.telegram_id, "name": display_name(u), "balance": u.stars_balance,
        "banned": bool(u.is_banned),
        "referred_by": u.referred_by, "referral_earned": u.referral_earned or 0,
        "gifts": [g.to_dict() for g in GiftItem.query.filter(
            GiftItem.owner_id == u.id, GiftItem.status != "withdrawn").all()],
        "ledger": [r.to_dict() for r in ledger],
    })


@vloody_bp.route("/api/admin/gifts", methods=["GET"])
def admin_gifts():
    denied = _admin_only()
    if denied:
        return denied
    status = request.args.get("status", "withdraw_requested")
    q = GiftItem.query
    if status != "all":
        q = q.filter_by(status=status)
    rows = q.order_by(GiftItem.id.desc()).limit(200).all()
    owners = {u.id: u for u in User.query.filter(User.id.in_([g.owner_id for g in rows])).all()}
    return jsonify({"items": [{**g.to_dict(), "owner": display_name(owners.get(g.owner_id)),
                               "owner_tid": owners[g.owner_id].telegram_id if g.owner_id in owners else None,
                               "tg_gift_id": g.tg_gift_id, "created_ts": ts(g.created_at)} for g in rows]})


@vloody_bp.route("/api/admin/revenue", methods=["GET"])
def admin_revenue():
    denied = _admin_only()
    if denied:
        return denied
    rows = (LedgerTx.query.filter(LedgerTx.user_id == None, LedgerTx.kind == "commission")  # noqa: E711
            .order_by(LedgerTx.id.desc()).limit(100).all())
    deposits = (TonDeposit.query.filter_by(status="credited")
                .order_by(TonDeposit.credited_at.desc()).limit(50).all())
    users = {u.id: u for u in User.query.filter(User.id.in_([d.user_id for d in deposits])).all()}
    return jsonify({
        "items": [r.to_dict() for r in rows],
        "ton_deposits": [{"ton": d.amount_nano / 1e9, "vld": d.vld, "tx_hash": d.tx_hash,
                          "user": display_name(users.get(d.user_id)), "ts": ts(d.credited_at)}
                         for d in deposits],
    })

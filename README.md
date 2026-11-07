# 🚀 CosmoDrop

Космическое Telegram Mini App для открытия кейсов за звёзды ⭐.
Flask + SQLite на бэкенде, одностраничный адаптивный интерфейс в стиле «дальний космос».

## ✨ Возможности

**Кейсы**
- 4 уровня редкости (common / rare / epic / legendary), таблица дропа и шансы.
- Рулетка открытия с анимацией, звуком, конфетти при профите и гарантированным призом.
- Инвентарь выигранных предметов с продажей поштучно и «продать всё».
- Живая лента последних дропов (бегущая строка).

**Мини-игры** (вкладка 🎮 Игры)
- **Апгрейд** — рискни предметом ради множителя ×1.5…×10 с круговым индикатором шанса.
- **Контракты** — объедини 2–10 предметов в один новый случайной ценности (trade-up).
- **Колесо фортуны** — бесплатный спин раз в 6 часов.

**Прогрессия и ретеншн**
- **Уровни/XP** с наградами за каждый новый уровень (бейдж в шапке + полоса в профиле).
- **Ежедневные задания** с прогрессом и наградами.
- **Достижения** (8 ачивок) с ручным клеймом награды.
- **Промокоды** (`COSMO100`, `WELCOME`, `STARGIFT`, `LREXE1000`).
- **Реферальная система** — личный код/ссылка, бонус приглашающему и другу.
- **Ежедневный бонус** со стриком и кулдауном 24 часа.

**Прочее**
- **Рейтинг** — подиум топ-3 + таблица лидеров с подсветкой игрока.
- **Профиль** с реальной статистикой, достижениями, настройками звука.
- **Provably-fair** — хеш раунда возвращается при каждом открытии кейса.
- **Звуковые эффекты** (WebAudio-синтез, без внешних файлов) с переключателем.
- Интеграция с **Telegram WebApp** (`initData`, `start_param` для рефералов, haptic) + фолбэк на демо-пользователя вне Telegram.

## 🛠️ Технологии

- Backend: Flask 3, Flask-SQLAlchemy, Flask-Migrate, SQLite (PostgreSQL — опционально через env).
- Frontend: ванильный JS (без сборки), единая дизайн-система `static/css/app.css`, canvas-starfield.
- REST API собран в блюпринте `bot/cases.py`.

## ▶️ Запуск локально

```bash
# 1. окружение и зависимости
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 2. тестовые данные (кейсы, игроки, инвентарь, лента)
.venv/bin/python seed.py

# 3. запуск
.venv/bin/python app.py
```

Открой **http://localhost:5000**.
Вне Telegram используется демо-пользователь `telegram_id=111222333` (баланс 5000 ⭐).

## 🔌 API

| Метод | Эндпоинт | Назначение |
|------|----------|-----------|
| POST | `/api/user/sync` | создать/обновить пользователя |
| GET  | `/api/me` | профиль + ранг + инвентарь |
| GET  | `/api/stats` | глобальная статистика |
| GET  | `/api/cases` · `/api/cases/<id>` | список кейсов · детали с шансами |
| POST | `/api/open-case` | открыть кейс (рулетка + дроп) |
| GET  | `/api/inventory` · POST `/api/inventory/sell` | инвентарь · продажа |
| GET  | `/api/rating` | таблица лидеров + «я» |
| GET  | `/api/history` | история (`scope=me|global`) |
| GET  | `/api/daily-bonus/status` · POST `/api/daily-bonus` | ежедневный бонус |
| POST | `/api/balance/add` | демо-пополнение |
| POST | `/api/upgrade` | апгрейд предмета на множитель |
| POST | `/api/contract` | контракт (trade-up) из N предметов |
| GET  | `/api/wheel/status` · POST `/api/wheel/spin` | колесо фортуны |
| GET  | `/api/quests` · POST `/api/quests/claim` | ежедневные задания |
| GET  | `/api/achievements` · POST `/api/achievements/claim` | достижения |
| POST | `/api/promo/redeem` | активация промокода |
| GET  | `/api/referral` · POST `/api/referral/apply` | рефералы |

## ⚙️ Конфигурация (env, опционально)

- `DEMO_TELEGRAM_ID` — id демо-пользователя (по умолчанию `111222333`).
- `SECRET_KEY` — секрет Flask.
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — если заданы, используется PostgreSQL вместо SQLite.

## 📁 Структура

```
app.py              — фабрика приложения, страницы, конфиг
models.py           — User, Case, CasePrize, InventoryItem, CaseHistory,
                      DailyProgress, Achievement, PromoCode, PromoRedemption
bot/cases.py        — REST API кейсов/профиля/рейтинга (блюпринт)
bot/games.py        — REST API игр и прогрессии (блюпринт)
bot/engine.py       — движок: уровни/XP, задания, достижения, генерация предметов
bot/bot.py          — отдельный Telegram-бот (для веб-сайта не нужен)
seed.py             — наполнение демо-данными (идемпотентно)
templates/          — base.html + home/cases/games/rating/profile (Jinja)
static/css/app.css  — единая дизайн-система
static/js/          — app.js (общий слой) + home/cases/games/rating/profile
```

> ⚠️ В `bot/bot.py` в открытом виде лежит токен бота — перевыпустите его в @BotFather перед публичным использованием.

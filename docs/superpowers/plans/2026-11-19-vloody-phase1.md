# Vloody Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two isolated currencies (VLD on Stars, VDT on TON), the owner's economy numbers, a 6-hour life with refunding cancel for every round mode, organizer-priced vault, transfers by @username, channel posting bot, glass tab bar, and a deposit/bug audit.

**Architecture:** Flask + SQLAlchemy monolith. Money lives in two integer balance columns on `users`; every balance change goes through two currency-specific ledger functions that write `LedgerTx` rows tagged with the currency. Rounds carry a `currency`; all stake/payout/refund code resolves the mover from `pool.currency` (a whitelisted enum), never from request text. Frontend is one vanilla-JS file plus CSS bundles served by `bot/assets.py`.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 2.0.45 (SQLite locally), vanilla JS, CSS tokens; tests are plain scripts under `tests/` run by `tests/run_all.py` (`PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/run_all.py`).

**Spec:** `docs/superpowers/specs/2026-11-19-vloody-phase1-design.md`

## Global Constraints

- VLD unit = 1 VLD (integer). VDT stored as integer **milli-VDT** (1 VDT = 1000); display with up to 3 decimals. 1 TON = 1 VDT, so `milli = nano // 10**6`.
- Stars → VLD 1:1, no fee. TON → VDT 1:1, no fee.
- No code path converts VLD ↔ VDT (not deposits, rounds, refunds, transfers, payouts).
- Round commission **4.5%** (`COMMISSION_RATE = 0.045`), organizer gets the rest, in the round's currency. Commission rounding: `int(bank * 0.045)` (floor).
- Round creation fee **0.1 VDT = 100 milli**, debited from `vdt_balance`, never refunded.
- Payout Stars: min **275 VLD**, fee **13.5%**; payout TON: min **2.5 VDT (2500 milli)**, fee **11.5%**. Fee = floor.
- Transfer: same currency both sides; min 150 VLD / 1500 milli-VDT; fee 10%.
- Stake/ticket limits: VLD 1–10 000; VDT 10–100 000 milli (0.01–100 VDT).
- Durations (wheel, auction): 15, 30, 60, 180, 360 minutes. Vault: `ends_at = created_at + 6 h`.
- Cancel at end: wheel/auction with < 2 distinct participants; vault not cracked. Full refund of each entry in round currency; gift back to organizer (`status="held"`); creation fee kept.
- Demo welcome bonus: 1000 VLD + random NFT + **1 VDT (1000 milli)**, once per user.
- Demo mode never allows payouts or gift withdrawals (already enforced).
- All new user-facing text in Russian. Keep `prefers-reduced-motion`, both themes, phone + desktop.
- Commit after each task with trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A request that sends `currency` in a stake/bid/vault body must be ignored — the stake always uses `pool.currency`.
2. Cancel/refund must return exactly what each user paid, in the round currency, and leave platform ledger untouched except the kept 0.1 VDT fee.
3. Double-settle: two concurrent requests hitting `settle_due` for the same pool must not double-pay or double-refund (status check under row lock).
4. Transfer by username: case-insensitive, leading `@` stripped, unknown/banned/self rejected, no enumeration of non-public data beyond name/photo.
5. TON deposit credited twice (same tx hash) or credited into VLD — must be impossible.

---

### Task 1: Two-currency money core

**Files:**
- Modify: `models.py` (User, LedgerTx, Pool, PayoutRequest, ensure_columns)
- Modify: `bot/vloody.py` (money helpers, constants, profile_dict)
- Create: `tests/phase1test.py` (new suite; add to `SUITES` in `tests/run_all.py`)

**Interfaces:**
- Produces:
  - `User.vdt_balance: int` (milli-VDT, default 0); `LedgerTx.currency: str` ("VLD"|"VDT", default "VLD"); `Pool.currency: str` (default "VLD"); `PayoutRequest.currency: str` (default "VLD").
  - `CURRENCIES = ("VLD", "VDT")`
  - `move_vld(user|None, amount:int, kind:str, title:str, ref:str|None=None)` — changes `stars_balance`, writes LedgerTx(currency="VLD").
  - `move_vdt(user|None, amount:int, kind, title, ref=None)` — changes `vdt_balance`, LedgerTx(currency="VDT").
  - `mover(cur:str) -> callable` — returns `move_vld`/`move_vdt`; raises `ValueError` for anything else.
  - `balance_of(user, cur) -> int`; `fmt_cur(amount:int, cur) -> str` ("12 VLD" / "1.25 VDT").
  - `move` stays as an alias of `move_vld` for untouched legacy code.
  - `profile_dict` adds `"balances": {"VLD": int, "VDT": int}` (VDT in milli) and keeps `"balance"` = VLD.

- [ ] **Step 1: Failing tests** in `tests/phase1test.py` (same harness style as `tests/vtest.py`: `check()`, signed `hdr()`, `BOT_TOKEN` set, `DEMO_MODE=""`):
  - `move_vdt(u, 1500, "t", "t")` → `u.vdt_balance == 1500`, last LedgerTx has `currency == "VDT"`, `stars_balance` unchanged.
  - `mover("VDT") is move_vdt`, `mover("vld")` raises `ValueError`.
  - `move_vld(u, -10**9, ...)` raises `ValueError("Недостаточно VLD")`; `move_vdt` overdraft raises `ValueError("Недостаточно VDT")`.
  - `GET /api/profile` returns `balances == {"VLD": <int>, "VDT": <int>}`.
- [ ] **Step 2:** run `PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/phase1test.py` → FAIL.
- [ ] **Step 3:** implement; `ensure_columns` adds `users.vdt_balance INTEGER DEFAULT 0`, `ledger_tx.currency VARCHAR(4) DEFAULT 'VLD'`, `pools.currency VARCHAR(4) DEFAULT 'VLD'`, `payout_requests.currency VARCHAR(4) DEFAULT 'VLD'` (check real table names in models).
- [ ] **Step 4:** phase1test PASS and `tests/run_all.py` all PASS.
- [ ] **Step 5:** commit `feat: две валюты — VLD и VDT, раздельный учёт`.

### Task 2: Rounds in a currency, new commission, creation fee, 6-hour rule

**Files:** Modify `bot/vloody.py` (pool_create, _place, _finish, _cancel, settle, stake/bid/vault, pool_dict, constants); extend `tests/phase1test.py`; update existing assertions in `tests/vtest.py` that assume 10% commission, 1440-minute durations, untimed vault or single-player wheel wins.

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces:
  - `POST /api/pools` body adds `currency` ("VLD"|"VDT", default "VLD") and `min_stake` in units of that currency (VDT in milli). Vault price is `min_stake` (any value in limits, not a preset list).
  - `DURATIONS_MIN = (15, 30, 60, 180, 360)`, `ROUND_LIFE = timedelta(hours=6)`, `CREATE_FEE_VDT = 100`.
  - `_refund_all(pool)` — refunds every entry via `mover(pool.currency)` with kind `"refund"`, sets `status="cancelled"`, gift → organizer `held`.
  - `pool_dict` adds `"currency"`, `"create_fee": 100`, and `"cancel_reason"` when cancelled.

- [ ] **Step 1: Failing tests:**
  - Creating a round with `vdt_balance < 100` → 400 "Нужно 0.1 VDT…"; with enough → `vdt_balance` drops by 100, platform LedgerTx `+100 VDT kind="create_fee"`.
  - VDT wheel: two players stake 1000 and 3000 milli; after `ends_at` passes, `settle_due()` → organizer `vdt_balance` += `4000 - int(4000*0.045)` = 3820; platform ledger +180 VDT; nobody's `stars_balance` changed.
  - Stake body `{"amount": 50, "currency": "VLD"}` on a VDT round debits VDT, not VLD.
  - Wheel with one participant at end → cancelled, participant refunded in full, gift `held` by organizer, fee not refunded.
  - Vault created → `ends_at == created_at + 6h` (±5 s); uncracked at end → cancelled with refunds.
  - Vault `min_stake=37` (VLD) accepted; `min_stake=0` and `10001` rejected.
  - `duration_min=1440` rejected; `360` accepted.
  - Settling the same pool twice does not double-pay.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement; settle must re-check `pool.status == "live"` after `with_for_update()`.
- [ ] **Step 4:** phase1test + run_all PASS.
- [ ] **Step 5:** commit `feat: раунды в валюте, комиссия 4.5%, сбор 0.1 VDT, правило 6 часов`.

### Task 3: Wallet — deposits, payouts, transfers by username, demo bonus

**Files:** Modify `bot/vloody.py` (topup, stars_to_vld, _credit_ton, nano_to_vld, handle_payment_update, payout_request, admin payout processing, user_lookup, transfer, grant_welcome, constants); `tests/tontest.py`, `tests/vtest.py`, `tests/admintest.py` assertions that assume ×0.95 / 100 VLD per TON / old payout numbers; extend `tests/phase1test.py`.

**Interfaces:**
- Produces:
  - Stars deposit (invoice and demo) credits VLD 1:1. TON deposit credits **VDT** `nano // 10**6` milli via `move_vdt`, ref `ton:<hash>` unique; `TonDeposit.vld` column now stores milli-VDT credited (keep column name, document it).
  - `POST /api/payout` body `{currency: "VLD"|"VDT", amount, destination}`; VLD→Stars (min 275, fee 13.5%), VDT→TON (min 2500 milli, fee 11.5%, `net_nano = net_milli * 10**6`). Legacy `method` accepted as alias (STARS→VLD, TON→VDT).
  - Admin reject refunds in the request's currency.
  - `GET /api/users/lookup?username=<name>` → `{telegram_id, name, username, photo}`; strip `@`, case-insensitive; 404 unknown/banned.
  - `POST /api/transfer` body `{to_username, amount, currency}`; same currency both sides; min 150 VLD / 1500 milli; fee 10% to platform in that currency.
  - `grant_welcome` also gives 1000 milli-VDT (kind `"bonus"`).
  - `profile_dict.limits` updated: `payout_min_vld=275, payout_fee_vld=0.135, payout_min_vdt=2500, payout_fee_vdt=0.115, transfer_min_vld=150, transfer_min_vdt=1500, transfer_fee=0.10, commission=0.045, create_fee_vdt=100`; `rates.stars_to_vld = 1`.

- [ ] **Step 1: Failing tests:** TON deposit of 2.5 TON credits 2500 milli-VDT and 0 VLD; same tx scanned twice credits once; Stars payment of 100 XTR credits 100 VLD; payout VLD 274 → 400, 275 → net 238; payout VDT 2499 → 400, 2500 → net 2213 and `net_nano == 2213*10**6`; payout VDT with only VLD balance → 400; transfer `@Bob` (any case) works, VDT transfer moves only VDT, self/unknown → 400/404; demo welcome gives 1000 VLD + 1000 milli-VDT once.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** all suites PASS.
- [ ] **Step 5:** commit `feat: кошелёк в двух валютах — депозиты, выводы, переводы по username`.

### Task 4: Channel bot

**Files:** Modify `models.py` (new `Channel` model), `bot/vloody.py` (webhook handling, channel API, post on create/finish), `bot/setup_main.py` (`allowed_updates` add `"my_chat_member"`); extend `tests/maintest.py` (mock Telegram already exists there).

**Interfaces:**
- Produces:
  - `Channel(id, chat_id BigInteger unique, title, username, added_by_tg BigInteger, owner_id FK users nullable, active bool, created_at)`.
  - Webhook `my_chat_member` where bot became `administrator` in a channel → upsert Channel(active=True, added_by_tg=from.id); left/kicked → active=False.
  - `GET /api/channels` — channels linked to me; `POST /api/channels/link {chat_id}` — allowed only if `getChatMember(chat_id, my telegram_id)` status in (`creator`,`administrator`); sets `owner_id`.
  - `POST /api/pools` accepts `channel_id` (must be mine and active); after commit, `post_pool_to_channel(pool)` sends `sendMessage` (or `sendPhoto` with gift art URL when `PUBLIC_URL` set) with inline button `{"text": "🎯 Участвовать", "url": "https://t.me/<BOT_USERNAME>?startapp=pool_<id>"}`; on finish/cancel `post_pool_result(pool)`. Telegram errors are swallowed and logged, never break the round.
- [ ] **Step 1: Failing tests** with the mock API: my_chat_member admin → Channel row; link by non-admin (mock getChatMember returns `member`) → 403; link by admin → 200; pool with `channel_id` → a `sendMessage`/`sendPhoto` call whose button URL ends with `startapp=pool_<id>`; finish → result post.
- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** commit `feat: бот публикует раунды в канале`.

### Task 5: Frontend — two balances, currency in create, vault price, durations, transfer by username, payouts, channels, glass tab bar

**Files:** Modify `templates/vloody.html`, `static/js/vloody.js`, `static/css/vl-shell.css`, `static/css/vl-screens.css`, `static/css/vl-rounds.css`, `static/css/vl-overlays.css`; keep `tests/test_frontend_ids.py` and `tests/test_contrast.py` passing (extend contrast pairs if new colors are introduced).

**Interfaces:** Consumes the API shapes from Tasks 1–4.

- [ ] Header/sidebar show two balance chips: VLD (gold, star icon) and VDT (TON blue `#0098EA`, TON icon), from `profile.balances`; `setBalance` becomes `setBalances({VLD, VDT})` and every caller passes the server response.
- [ ] Round cards/screens show amounts with the round's currency (`fmtCur(amount, cur)`, VDT as milli → "1.25 VDT"); feed filter chips add `VLD • Stars` / `VDT • TON`.
- [ ] Create screen: currency switch (VLD/VDT); stake/price is a number input with presets as shortcuts (vault label "Цена попытки"); durations 15 мин/30 мин/1 ч/3 ч/6 ч; vault note "Сейф живёт 6 часов"; summary shows "Запуск: 0.1 VDT · Вам: 95.5% банка · Срок: до 6 ч" and disables the button with a hint if `VDT < 0.1`; optional "Опубликовать в канале" select when channels exist.
- [ ] Cancelled rounds show "Отменён — ставки возвращены".
- [ ] Wallet: Stars top-up says "1 ⭐ = 1 VLD"; TON top-up says "1 TON = 1 VDT".
- [ ] Payout modal: currency tabs (Stars from VLD / TON from VDT) with the new minimums and fees in the live calculation.
- [ ] Transfer modal: `@username` field with lookup preview (name + photo), currency switch, live fee calc.
- [ ] Profile → Каналы: instruction (add `@<bot>` as admin with "post messages" right), list of linked channels, "Привязать" for channels the bot sees (if the API returns pending ones) — or a chat_id input with "Проверить".
- [ ] Tab bar (phone): glass — translucent `color-mix` background, `backdrop-filter: blur(18px) saturate(160%)`, hairline top border, floating rounded capsule inset from the screen edges with safe-area padding, active item as a lit pill; fallback solid background when `backdrop-filter` unsupported; both themes.
- [ ] Run `tests/run_all.py`, then load `http://localhost:5000/` in the browser pane at 375 px and 1280 px, both themes, and confirm no console errors from the bundle.
- [ ] Commit `feat: интерфейс двух валют, каналы, стеклянное меню`.

### Task 6: Deposit and whole-app bug audit

**Files:** any touched by findings; tests for each fix in `tests/phase1test.py`.

- [ ] Audit list (each item: read code path, try to break it with a test, fix if broken):
  - Stars: `pre_checkout_query` answered without validating payload/amount/user; `successful_payment` payload user ≠ `from.id`; replay of the same `telegram_payment_charge_id`.
  - TON: intent spam (unbounded pending TonDeposit rows per user), comment collisions, bounced/failed tx credited, amount below `TON_MIN_DEPOSIT`, credit to wrong currency, demo-pay endpoint reachable in production.
  - Demo top-up limits (abuse is harmless but must stay demo-only).
  - Rounds: stake after `ends_at` before settle, organizer staking via transfer to an alt (note only — phase 2), vault number race (unique per pool), negative/zero amounts, int overflow > MAX_STAKE.
  - Transfers/payouts: concurrent double-spend (lock order), negative amounts, currency spoofing.
  - Admin: payout approve twice, reject twice.
- [ ] Every confirmed bug gets a failing test first, then the fix.
- [ ] `tests/run_all.py` all PASS; restart server (`app.py`) so bundles rebuild; commit `fix: аудит депозитов и денежных путей`.

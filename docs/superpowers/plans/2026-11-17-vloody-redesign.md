# Vloody Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить оформление Vloody на единую голубую дизайн-систему (тёмная и светлая темы, телефон и десктоп) с настоящими картинками подарков, 3D и анимацией, не меняя серверную логику.

**Architecture:** Новый слой оформления (токены, база, каркас, экраны) подключается вместо `vloody.css`/`vloody-app.css`; рендереры в `vloody.js` получают новую разметку, но те же данные и обработчики. Картинки подарков отдаёт наш сервер через кэширующий маршрут `/gift-art/...`. Эффекты (наклон, 3D, переходы) вынесены в отдельный `vl-fx.js`.

**Tech Stack:** Flask, SQLAlchemy (SQLite), HTML/CSS/vanilla JS без сборщика, Onest + JetBrains Mono (Google Fonts), lottie-web (cdnjs, MIT), тесты: обычные Python-скрипты, печатающие `PASS`/`FAIL`.

**Spec:** `docs/superpowers/specs/2026-11-17-vloody-redesign-design.md`

## Global Constraints

- Без сборщика и фреймворков; серверное API, экономика и поведение не меняются.
- Пять существующих наборов проверок проходят без правок логики: `vtest` 42, `tontest` 24, `relaytest` 24, `admintest` 31, `maintest` 19.
- Ширина-порог десктопа 861px; максимальная ширина контента 1180px; боковая панель 248px.
- Радиусы 12 / 16 / 22; шрифты Onest (текст) и JetBrains Mono (числа, таймеры, хеши, табличные цифры).
- Контраст текста не ниже WCAG AA (4.5:1) в обеих темах; значения цветов из спецификации иллюстративны, при провале проверки корректируются, пока не пройдут.
- Эмодзи не используются как иконки интерфейса и как картинки подарков; иконки только инлайн-SVG.
- Все 3D и движение отключаются при `prefers-reduced-motion: reduce`; ховер-эффекты не обязательны для работы (только `@media (hover: hover) and (pointer: fine)`).
- Картинки подарков только настоящие; запасная генерируемая плитка лишь при ошибке загрузки.
- Не коммитить без команды пользователя: в рабочем дереве уже лежит ~25 незакоммиченных файлов прежней работы. Шаги «Commit» ниже — точки, где нужно спросить.
- Тема по умолчанию: `Telegram.WebApp.colorScheme`, иначе `prefers-color-scheme`, иначе тёмная; выбор хранится в `localStorage` ключом `vl_theme` (`dark` | `light`).

## Review Focus

1. Картинка подарка не загрузилась (404, нет сети, медленный CDN): остаётся запасная плитка того же размера, раскладка не прыгает. Проверяется в Task 2 и Task 7.
2. Путь `/gift-art/` получает `../etc`, заглавные буквы, огромный номер, slug не из нашей базы: ответ 404 и нет исходящего запроса. Task 2.
3. `localStorage` недоступен (приватный режим, Telegram WebView): переключатель темы не падает, тема применяется на сессию. Task 5.
4. Длинные имена (40 символов), семизначные суммы VLD, `@username` в 32 символа: ничего не вылезает за карточку в обеих раскладках. Task 7 и Task 9.
5. Окно пересекает порог 861px при открытом раунде или модалке: состояние сохраняется, холст колеса пересчитывает размер. Task 8 и Task 10.

---

### Task 1: Перенести проверки в репозиторий

**Files:**
- Create: `tests/run_all.py`, `tests/vtest.py`, `tests/tontest.py`, `tests/relaytest.py`, `tests/admintest.py`, `tests/maintest.py` (копии из `C:/Users/Aziz/AppData/Local/Temp/claude/bac1b460f6e0abe4/a249bff7-8b98-41b0-bd98-8fdb59d20877/scratchpad/`)

**Interfaces:**
- Produces: `python tests/run_all.py` печатает по строке `<имя>: ALL PASS (<n>)` и завершается кодом 0 только если прошли все.

- [ ] **Step 1: Скопировать пять скриптов в `tests/`**; в каждом заменить `sys.argv[1]` на `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`, чтобы запуск не требовал аргумента.
- [ ] **Step 2: Реализовать `tests/run_all.py`**: запускает каждый скрипт подпроцессом с `PYTHONIOENCODING=utf-8`, считает строки `PASS`, ищет `ALL PASS`, печатает итог.
- [ ] **Step 3: Запустить** `.venv/Scripts/python tests/run_all.py`. Ожидается: пять строк `ALL PASS` с числами 42, 24, 24, 31, 19, код 0.
- [ ] **Step 4: Commit** (спросить пользователя): `git add tests && git commit -m "test: move end-to-end suites into the repo"`.

### Task 2: Сервис картинок NFT-подарков

**Files:**
- Create: `bot/giftart.py`, `tests/test_giftart.py`
- Modify: `models.py` (`GiftItem.slug`, `ensure_columns`), `app.py` (маршрут), `.gitignore` (`instance/gift_cache/`)

**Interfaces:**
- Produces:
  - `models.GiftItem.slug: str | None` (`String(64)`, индекс); `GiftItem.to_dict()` дополняется ключами `image: str | None` и `anim: str | None` (URL вида `/gift-art/<slug>.jpg` и `/gift-art/<slug>.json`; `None`, если `slug` пуст). Ключ `art` (CSS-класс) остаётся.
  - `bot.giftart.SLUG_RE = re.compile(r"^[a-z0-9]{2,40}-\d{1,7}$")`
  - `bot.giftart.get_art(slug: str, ext: str) -> tuple[bytes, str] | None` — `ext` из `jpg|webp|json`; возвращает (байты, content-type) или `None`.
  - Маршрут `GET /gift-art/<slug>.<ext>`: 200 с `Cache-Control: public, max-age=86400`; иначе 404 с телом `{"error":"not found"}`.
  - Переменная окружения `GIFT_CDN_BASE`, по умолчанию `https://nft.fragment.com/gift`.

- [ ] **Step 1: Написать `tests/test_giftart.py`** с поддельным CDN на локальном порту (`GIFT_CDN_BASE=http://127.0.0.1:5082`). Тесты: `valid slug in db -> 200 image/jpeg and cached on disk`; `second request does not hit CDN` (счётчик запросов 1); `slug not in db -> 404 and CDN counter unchanged`; `../etc/passwd, PLUSHPEPE-1, plushpepe-99999999, a-1, empty -> 404 and no outbound request`; `CDN 404 -> our 404, and repeated request within 10 min does not re-hit CDN`; `CDN down -> 404, no exception`; `CDN returns text/html or >1 MB -> 404 and nothing cached`; `ext=json returns application/json`.
- [ ] **Step 2: Запустить** `.venv/Scripts/python tests/test_giftart.py`. Ожидается: падает (модуля нет).
- [ ] **Step 3: Реализовать `bot/giftart.py`**: проверка `SLUG_RE` и `ext` до любой работы; соответствие `ext` → суффикс CDN (`jpg`→`.medium.jpg`, `webp`→`.webp`, `json`→`.lottie.json`); лимиты 1 МБ (картинки) и 600 КБ (json); сверка `Content-Type`; запись в `instance/gift_cache/<slug>.<ext>` через временный файл и `os.replace`; отрицательный кэш в памяти на 10 минут. Маршрут в `app.py` сперва проверяет `GiftItem.query.filter_by(slug=slug).first()`.
- [ ] **Step 4: Добавить колонку и `to_dict`-ключи в `models.py`**; в `ensure_columns` добавить `("slug", "VARCHAR(64)")` для `gift_items`.
- [ ] **Step 5: Запустить** `tests/test_giftart.py`. Ожидается: `ALL PASS`.
- [ ] **Step 6: Commit** (спросить).

### Task 3: Бот-хранитель и сид передают настоящие подарки

**Files:**
- Modify: `bot/relay.py`, `bot/vloody.py` (`relay_deposit`, `pool_dict`, `gifts`), `bot/vloody_seed.py`, `tests/relaytest.py`

**Interfaces:**
- Consumes: `GiftItem.slug` и `to_dict` из Task 2.
- Produces: тело `POST /api/relay/gift-deposit` принимает необязательные `slug: str` (из `owned["gift"]["name"]`, приводится к нижнему регистру) и `sticker_file_id: str`; `pool_dict` получает ключи `image` и `anim` подарка раунда.

- [ ] **Step 1: Дополнить `tests/relaytest.py`**: поддельный Telegram отдаёт `gift.name = "PlushPepe-1337"`; проверить, что после `sync()` у подарка в инвентаре `image == "/gift-art/plushpepe-1337.jpg"`, а у `pool_dict` раунда с этим подарком те же ключи; подарок без `name` → `image is None` и зачисление не ломается.
- [ ] **Step 2: Запустить** `tests/relaytest.py`. Ожидается: новые проверки падают.
- [ ] **Step 3: Реализовать**: в `Relay.sync_deposits` передавать `slug`; в `relay_deposit` сохранять `clean_slug(data["slug"])` (только если проходит `SLUG_RE`, иначе `None`).
- [ ] **Step 4: Заменить выдуманные названия в `vloody_seed.py` настоящими** и проставить `slug`. Перед использованием проверить каждый slug запросом `curl -I https://nft.fragment.com/gift/<slug>.medium.jpg` (ожидается 200); подарки без подтверждённого slug в сид не включать.
- [ ] **Step 5: Запустить** `python tests/run_all.py`. Ожидается: все пять наборов `ALL PASS` (числа у `relaytest` вырастут).
- [ ] **Step 6: Commit** (спросить).

### Task 4: Обычные подарки за Stars

**Files:**
- Modify: `bot/giftart.py`, `app.py`, `tests/test_giftart.py`

**Interfaces:**
- Produces:
  - `bot.giftart.regular_catalog() -> list[dict]` — элементы `{"id": str, "stars": int, "emoji": str}`; данные из `getAvailableGifts` основного бота (`BOT_TOKEN`), кэш в памяти на 6 часов; без токена или при ошибке — `[]`.
  - Маршрут `GET /gift-art/regular/<int:gid>.webp` отдаёт превью-стикер (файл через `getFile`), кэш в `instance/gift_cache/regular-<id>.webp`; неизвестный id → 404.
  - `GET /api/gifts/catalog` (требует подпись Telegram, как остальное API) возвращает `{"items": [{"id", "stars", "image"}]}`.

- [ ] **Step 1: Тесты в `tests/test_giftart.py`** с поддельным Bot API (`TELEGRAM_API_BASE`): `catalog lists gifts with image urls`; `unknown id -> 404`; `no BOT_TOKEN -> empty catalog, no exception`; `catalog cached (one getAvailableGifts call for two requests)`.
- [ ] **Step 2: Запустить.** Ожидается: новые проверки падают.
- [ ] **Step 3: Реализовать** `regular_catalog`, маршрут и `/api/gifts/catalog`; id берётся только из каталога, а не из пути запроса.
- [ ] **Step 4: Запустить** `tests/test_giftart.py`. Ожидается: `ALL PASS`.
- [ ] **Step 5: Commit** (спросить).

### Task 5: Токены, темы, база, иконки

**Files:**
- Create: `static/css/vl-tokens.css`, `static/css/vl-base.css`, `static/js/vl-theme.js`, `templates/_icons.html` (SVG-спрайт), `tests/test_contrast.py`
- Modify: `templates/vloody.html` (подключение, переключатель темы)

**Interfaces:**
- Produces:
  - CSS-переменные на `:root[data-theme="dark"]` и `:root[data-theme="light"]`: `--bg --bg-glow --surface --surface-2 --line --text --muted --accent --accent-2 --on-accent --success --warn --danger --shadow-1 --shadow-2 --r-sm:12px --r-md:16px --r-lg:22px --font --mono`.
  - `window.VLTheme = { get(): "dark"|"light", set(theme): void, toggle(): void }`; событие `vl:theme` на `document`.
  - Спрайт символов `#i-rounds #i-leaders #i-create #i-profile #i-shield #i-star #i-ton #i-wallet #i-send #i-out #i-copy #i-share #i-clock #i-lock #i-eye #i-back #i-close #i-sun #i-moon`, использование `<svg class="ic"><use href="#i-name"/></svg>`.
  - Классы базы: `.btn .btn-primary .btn-ghost .btn-sm .input .card .chip .pill .tag .num` (`.num` — JetBrains Mono, табличные цифры), `.skeleton`, `.sr-only`.

- [ ] **Step 1: Написать `tests/test_contrast.py`**: парсит `vl-tokens.css`, для каждой темы считает контраст WCAG для пар `text/bg`, `muted/bg`, `text/surface`, `muted/surface`, `on-accent/accent` (светлый конец градиента) и требует ≥ 4.5; печатает `PASS`/`FAIL` на пару.
- [ ] **Step 2: Запустить.** Ожидается: падает (файла нет).
- [ ] **Step 3: Написать токены обеих тем** по таблице спецификации; запустить тест, подправить значения (вероятно, `--muted` светлой темы и `--accent` светлой темы), пока все пары не пройдут.
- [ ] **Step 4: Реализовать `vl-theme.js`**: порядок выбора темы из Global Constraints; чтение и запись `localStorage` в `try/catch` (при ошибке тема живёт в памяти); установка `data-theme` и `<meta name="theme-color">`; вызов `Telegram.WebApp.setHeaderColor/setBackgroundColor` при наличии. Скрипт подключается в `<head>` до отрисовки, чтобы не было вспышки неверной темы.
- [ ] **Step 5: Написать `vl-base.css` и спрайт иконок**; подключить в `vloody.html`, старые `vloody.css`/`vloody-app.css` пока оставить подключёнными ниже.
- [ ] **Step 6: Проверка в браузере**: `VLTheme.toggle()` переключает тему; при заблокированном `localStorage` (переопределить в консоли `Storage.prototype.setItem` на бросающую функцию) переключение не падает. Ожидается: ошибок в консоли нет.
- [ ] **Step 7: Commit** (спросить).

### Task 6: Каркас — боковая панель и нижняя навигация

**Files:**
- Create: `static/css/vl-shell.css`
- Modify: `templates/vloody.html` (структура `<body>`), `static/js/vloody.js` (`tab()`, `show()`; логика маршрутизации сохраняется)

**Interfaces:**
- Consumes: токены, иконки, `VLTheme` из Task 5.
- Produces: контейнеры `#shell` > `aside#sidebar` + `main#content` + `nav#tabbar`; пункты навигации с `data-tab="home|events|create|profile"` и `data-act="fair-info"` (идентификаторы сохраняются); верхняя строка `#topbar` с `#tb-stars-val`, кнопкой темы `data-act="theme"` и `data-act="topup"`. На ≤860px виден `#tabbar`, `#sidebar` скрыт; на ≥861px наоборот.

- [ ] **Step 1: Перестроить разметку** `vloody.html`: сохранить все существующие `id` экранов (`sc-home`, `sc-wheel`, `sc-vault`, `sc-auction`, `sc-events`, `sc-create`, `sc-profile`) и модальных окон.
- [ ] **Step 2: Реализовать `vl-shell.css`** (две раскладки и пороги из Global Constraints) и обработчик `data-act="theme"` в `ACTIONS` вызывает `VLTheme.toggle()`.
- [ ] **Step 3: Запустить** `python tests/run_all.py`. Ожидается: все `ALL PASS` (серверные наборы не зависят от разметки).
- [ ] **Step 4: Проверка в браузере** на 390px и 1280px, обе темы: переходы между вкладками работают, активный пункт подсвечен, баланс в верхней строке обновляется после ставки.
- [ ] **Step 5: Commit** (спросить).

### Task 7: Главная, карточки раундов, 3D-наклон

**Files:**
- Create: `static/js/vl-fx.js`, `static/css/vl-cards.css`
- Modify: `static/js/vloody.js` (`poolCard`, `renderPools`), `templates/vloody.html` (фильтры)

**Interfaces:**
- Consumes: `image`/`anim` из `pool_dict` (Task 3), токены и иконки.
- Produces:
  - `giftImg(item: {image: string|null, title: string, art: string}, cls?: string) -> string` — HTML `<img>` с `loading="lazy"`, фиксированным `aspect-ratio`, и обработчиком `onerror`, заменяющим картинку плиткой-запаской (градиент из хеша названия + монограмма) без смены размеров.
  - `VLFx.tilt(root: ParentNode): void` — навешивает наклон на `[data-tilt]` (до ±8°, блик по положению курсора) только при `(hover: hover) and (pointer: fine)` и без `prefers-reduced-motion`.
  - `VLFx.countUp(el: HTMLElement, to: number, ms?: number): void`, `VLFx.stagger(container: ParentNode): void`.

- [ ] **Step 1: Реализовать `giftImg` и `VLFx`** (чистые функции без зависимостей от DOM-структуры экранов).
- [ ] **Step 2: Переделать `poolCard`**: сетка 1 колонка на телефоне, 2–3 на десктопе; в карточке картинка подарка, режим, банк, участники, таймер (`.num`), кнопки «Перейти»/«Результат» и копирование ссылки; тот же `data-pool`/`data-share`.
- [ ] **Step 3: Проверка запасной плитки**: в консоли заменить у одной карточки `src` на несуществующий адрес. Ожидается: появляется плитка того же размера, высота карточки не меняется (сравнить `getBoundingClientRect().height` до и после).
- [ ] **Step 4: Проверка длинных значений**: выставить в консоли у карточки название из 40 символов и банк `9 999 999`. Ожидается: текст обрезается многоточием, ничего не выходит за границы на 390px и 1280px.
- [ ] **Step 5: Проверка наклона** на 1280px: при наведении у карточки меняется `transform`; в эмуляции `prefers-reduced-motion: reduce` и на 390px — не меняется.
- [ ] **Step 6: Commit** (спросить).

### Task 8: Экраны раундов — колесо, сейф, аукцион

**Files:**
- Create: `static/css/vl-rounds.css`
- Modify: `static/js/vloody.js` (`renderWheel`, `drawWheel`, `renderVault`, `renderAuction`), `templates/vloody.html`

**Interfaces:**
- Consumes: `giftImg`, `VLFx` (Task 7), `anim` (Task 3).
- Produces: `VLFx.lottie(el: HTMLElement, src: string, opts?: {loop?: boolean}): {destroy(): void}` — лениво подгружает lottie-web с cdnjs; при ошибке оставляет статичную картинку.

- [ ] **Step 1: Колесо**: на ≥861px две колонки (слева подарок, условия, кнопка ставки; справа колесо и список ставок); холст масштабируется по `devicePixelRatio` и перерисовывается на `resize` и `matchMedia("(min-width: 861px)")` `change`. Сектора с глубиной (тень, объёмный обод), стрелка «отбивает» при пересечении границы сектора.
- [ ] **Step 2: Сейф**: 3D-дверца на CSS (`perspective`, `rotateY`); при `hit` — открытие, при промахе — тряска; поле чисел адаптивно (10 колонок на десктопе, 6 на телефоне).
- [ ] **Step 3: Аукцион**: шторка блэкаута с анимацией раскрытия, при завершении ставки появляются по очереди.
- [ ] **Step 4: Проверка пересечения порога**: открыть раунд-колесо на 1280px, сделать ставку, сузить окно до 390px и обратно. Ожидается: ставка в списке на месте, колесо отрисовано чётко, ошибок в консоли нет.
- [ ] **Step 5: Запустить** `python tests/run_all.py`. Ожидается: все `ALL PASS`.
- [ ] **Step 6: Commit** (спросить).

### Task 9: Создание, ивенты, профиль

**Files:**
- Create: `static/css/vl-screens.css`
- Modify: `static/js/vloody.js` (`loadCreate`, `renderCreateMode`, `loadEvents`, `loadProfile`, `renderInventory`, `loadTx`, `loadPayouts`), `templates/vloody.html`

**Interfaces:**
- Consumes: `giftImg`, токены, иконки.

- [ ] **Step 1: Создание**: выбор подарка плитками с настоящими картинками, три режима переключателем, настройки, блок условий; на десктопе две колонки (слева выбор, справа сводка раунда).
- [ ] **Step 2: Ивенты**: подиум топ-3 с объёмными ступенями, таблица лидеров, баннер «твой ранг».
- [ ] **Step 3: Профиль**: две колонки на десктопе (кошелёк и инвентарь / транзакции, выводы, рефералы); инвентарь с картинками подарков; переключатель темы в настройках профиля.
- [ ] **Step 4: Проверка длинных значений**: подставить в консоли имя из 40 символов, `@username` из 32 и баланс `9 999 999`. Ожидается: шапка профиля и строки таблицы не ломаются на 390px и 1280px.
- [ ] **Step 5: Commit** (спросить).

### Task 10: Модальные окна и формы

**Files:**
- Create: `static/css/vl-overlays.css`
- Modify: `templates/vloody.html`, `static/js/vloody.js` (`openOv`, `closeOv`)

**Interfaces:**
- Produces: `openOv(id)`/`closeOv(id)` сохраняют сигнатуры; окна как шторки снизу на ≤860px и диалоги по центру на ≥861px; фокус переходит в окно, `Esc` закрывает, фон не прокручивается.

- [ ] **Step 1: Переделать окна**: ставка, пополнение (Stars/TON), перевод, вывод, честность, TON-ожидание.
- [ ] **Step 2: Проверка пересечения порога с открытым окном**: открыть окно ставки на 1280px, сузить до 390px. Ожидается: окно остаётся открытым, введённое значение сохранено.
- [ ] **Step 3: Запустить** `python tests/run_all.py`. Ожидается: все `ALL PASS`.
- [ ] **Step 4: Commit** (спросить).

### Task 11: Движение, переходы, доступность

**Files:**
- Modify: `static/js/vl-fx.js`, `static/css/vl-base.css`, `static/css/vl-shell.css`

**Interfaces:**
- Produces: `VLFx.transition(from: HTMLElement, to: HTMLElement): void` (≤220 мс, смещение + прозрачность); конфетти в палитре темы `VLFx.confetti(kind: "win"|"jackpot"): void`.

- [ ] **Step 1: Переходы между экранами, появление списков по очереди, «докрутка» балансов** (заменить локальный `countUp` на `VLFx.countUp`).
- [ ] **Step 2: Полная поддержка `prefers-reduced-motion`**: все `transition`/`animation` с длительностью ≈ 0, наклон и 3D отключены, содержимое доступно.
- [ ] **Step 3: Фокус и клавиатура**: видимый `:focus-visible` во всех элементах, порядок табуляции в каркасе.
- [ ] **Step 4: Проверка**: эмуляция `prefers-reduced-motion: reduce` — экраны переключаются без анимации и без ошибок; обычный режим — переход ≤ 220 мс (замер `performance.now()` вокруг события `transitionend`).
- [ ] **Step 5: Commit** (спросить).

### Task 12: Админ-панель на тех же токенах

**Files:**
- Modify: `templates/admin.html`

- [ ] **Step 1: Заменить цвета и шрифты админки на токены** `vl-tokens.css` и подключить `vl-theme.js`; раскладку не менять.
- [ ] **Step 2: Запустить** `.venv/Scripts/python tests/admintest.py`. Ожидается: `ALL PASS` (31).
- [ ] **Step 3: Проверка в браузере**: `/admin` открывается в обеих темах, таблицы читаемы.
- [ ] **Step 4: Commit** (спросить).

### Task 13: Финальная проверка и документация

**Files:**
- Modify: `README.md`; удалить `static/css/vloody.css`, `static/css/vloody-app.css` и неиспользуемые стили, если на них больше нет ссылок

- [ ] **Step 1: Убедиться, что на старые файлы стилей нет ссылок** (`grep -rn "vloody.css\|vloody-app.css" templates static`), затем удалить их.
- [ ] **Step 2: Запустить** `.venv/Scripts/python tests/run_all.py` и `tests/test_giftart.py`, `tests/test_contrast.py`. Ожидается: всё `ALL PASS`.
- [ ] **Step 3: Пройти все экраны** на 390px и 1280px, в обеих темах: главная, колесо, сейф, аукцион, создание, ивенты, профиль, пять модальных окон, админка. Ожидается: нет ошибок в консоли, нет горизонтальной прокрутки, нет эмодзи вместо иконок.
- [ ] **Step 4: Дополнить README** разделами «Темы и раскладки», «Картинки подарков» (источники, кэш, риск с Fragment CDN, переменная `GIFT_CDN_BASE`).
- [ ] **Step 5: Commit** (спросить).

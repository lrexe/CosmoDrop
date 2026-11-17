/* Vloody — клиент PvP-розыгрышей. Все исходы и балансы считает сервер. */
(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
  const VL = window.VL || {};
  const $ = (id) => document.getElementById(id);
  const STAR = '<span class="star-i"></span>';
  const MODE_INFO = { wheel: { name: "Колесо", icon: "i-wheel" }, vault: { name: "Сейф", icon: "i-lock" },
    auction: { name: "Аукцион", icon: "i-eye-off" } };
  const MODE_SCREEN = { wheel: "wheel", vault: "vault", auction: "auction" };
  const STAKE_CHIPS = { wheel: [5, 25, 50, 100], vault: [5, 10, 25, 50], auction: [20, 50, 100, 250] };
  const MODE_HINT = {
    wheel: "Шанс каждого участника равен его доле в банке. Колесо крутится по таймеру.",
    vault: "Участники платят за попытку угадать секретное число. Угадавший забирает подарок сразу.",
    auction: "Ставки скрыты и не возвращаются. Подарок получает тот, кто накопил больше всех.",
  };

  const state = {
    profile: null, pools: { live: [], finished: [] }, filter: "all",
    pool: null, back: "home", wheelMode: "av", wheelRot: 0, spinning: false,
    create: { mode: "wheel", gift: null }, gifts: [], lb: "month", offset: 0, pt: "inv",
  };

  // ------------------------------------------------------------------ утилиты
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (Number(n) || 0).toLocaleString("ru-RU");
  const nowTs = () => Math.floor(Date.now() / 1000) + state.offset;

  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("on");
    clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("on"), 2600);
  }
  function haptic(type) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (type === "ok" || type === "error") tg.HapticFeedback.notificationOccurred(type === "ok" ? "success" : "error");
      else tg.HapticFeedback.impactOccurred(type || "light");
    } catch (e) {}
  }
  function ripple(e, el) {
    const d = document.createElement("span"); d.className = "rp-wave";
    const r = el.getBoundingClientRect(), sz = Math.max(r.width, r.height) * 1.5;
    d.style.cssText = `width:${sz}px;height:${sz}px;left:${e.clientX - r.left - sz / 2}px;top:${e.clientY - r.top - sz / 2}px`;
    el.appendChild(d); setTimeout(() => d.remove(), 600);
  }
  function hms(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
  }
  function ago(ts) {
    const d = nowTs() - ts;
    if (d < 60) return "только что";
    if (d < 3600) return Math.floor(d / 60) + " мин назад";
    if (d < 86400) return Math.floor(d / 3600) + " ч назад";
    return Math.floor(d / 86400) + " дн назад";
  }

  async function api(path, body) {
    const opts = { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" } };
    if (tg && tg.initData) opts.headers["X-Telegram-Init-Data"] = tg.initData;
    if (body !== undefined) opts.body = JSON.stringify(body || {});
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) throw new Error((data && data.error) || `Ошибка ${res.status}`);
    return data;
  }

  function setBalance(v) {
    if (state.profile) state.profile.balance = v;
    // the balance «rolls» to the new value (VLFx.countUp: instant with reduced motion or in a hidden tab)
    ["tb-stars-val", "sb-stars-val", "pf-bal"].forEach((id) => VLFx.countUp($(id), v));
  }

  // ------------------------------------------------------------------ навигация
  const SCREEN_TITLE = { home: "Раунды", events: "Лидеры", create: "Новый раунд", profile: "Профиль",
    wheel: "Колесо", vault: "Сейф", auction: "Аукцион" };
  // подсветка пункта в боковой панели (#sidebar) и в нижней навигации (#tabbar)
  function markNav(name) {
    document.querySelectorAll("#sidebar [data-tab], #tabbar [data-tab]").forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle("on", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
  }
  // exactly one .scr.on at the end; the entrance (≤ 220 ms shift + fade) is VLFx.transition's, and a quick second
  // call cancels the first one, so rapid tab clicks never leave two screens or a half-faded one
  function show(screen) {
    const to = $("sc-" + screen), from = document.querySelector("#screens > .scr.on");
    document.querySelectorAll(".scr.on").forEach((s) => { if (s !== to && s !== from) s.classList.remove("on"); });
    VLFx.transition(from || to, to);
    $("screens").scrollTop = 0;
    $("vl-title").textContent = SCREEN_TITLE[screen] || "Vloody";
  }
  function tab(name) {
    stopPoolWatch();
    markNav(name);
    show(name);
    state.back = name;
    if (name === "home") loadPools();
    if (name === "events") loadEvents();
    if (name === "create") loadCreate();
    if (name === "profile") loadProfile(true);
  }
  // ------------------------------------------------------------------ модальные окна
  // Разметка одна на обе раскладки (шторка ≤860px, диалог ≥861px) — переключает только CSS (vl-overlays.css),
  // поэтому введённые значения переживают смену ширины. Здесь: фокус внутрь, ловушка Tab, Esc, блок прокрутки
  // фона (#app inert + .vl-ov-lock на <html>), возврат фокуса к кнопке, которой окно открыли.
  const OV_FOCUSABLE = "button:not([disabled]), input:not([disabled]), select:not([disabled]), "
    + "textarea:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";
  const ovStack = [];      // открытые окна, верхнее — последнее
  let ovTrigger = null;    // [data-act], по которому кликнули (Safari не фокусирует кнопки по клику)
  let ovDownEl = null;     // где начался жест: закрываем по фону, только если и нажали, и отпустили на фоне
  const ovDialog = (id) => $(id).querySelector(".vl-dialog");
  const ovFocusables = (dlg) => Array.from(dlg.querySelectorAll(OV_FOCUSABLE)).filter((el) => el.getClientRects().length);
  function rangeFill(r) {
    const min = parseFloat(r.min) || 0, max = parseFloat(r.max) || 100, v = parseFloat(r.value) || 0;
    r.style.setProperty("--vl-fill", (max > min ? Math.min(100, Math.max(0, (v - min) / (max - min) * 100)) : 0) + "%");
  }
  function ovKey(e) {
    const id = ovStack[ovStack.length - 1]; if (!id) return;
    if (e.key === "Escape") { e.preventDefault(); closeOv(id); return; }
    if (e.key !== "Tab") return;
    const dlg = ovDialog(id), f = ovFocusables(dlg), a = document.activeElement;
    if (!f.length) { e.preventDefault(); dlg.focus(); return; }
    const first = f[0], last = f[f.length - 1], inside = dlg.contains(a);
    if (e.shiftKey && (a === first || a === dlg || !inside)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (a === last || !inside)) { e.preventDefault(); first.focus(); }
  }
  function openOv(id) {
    const ov = $(id); if (!ov || ovStack.includes(id)) return;
    const from = ovTrigger || document.activeElement;
    ov._opener = from && from !== document.body && !ov.contains(from) ? from : null;
    ov._openerAct = ov._opener && ov._opener.dataset ? ov._opener.dataset.act || "" : "";
    if (!ovStack.length) {
      document.documentElement.classList.add("vl-ov-lock");
      $("app").inert = true;
      document.addEventListener("keydown", ovKey);
    }
    ovStack.push(id);
    ov.querySelectorAll(".vl-range").forEach(rangeFill);
    const dlg = ovDialog(id);
    ov.classList.add("on");
    dlg.querySelector(".vl-dlg-body").scrollTop = 0;
    dlg.focus({ preventScroll: true });
  }
  function closeOv(id) {
    const ov = $(id); if (!ov) return;
    if (id === "topup-modal") tonReset();
    ov.classList.remove("on");
    const i = ovStack.indexOf(id); if (i < 0) return;
    ovStack.splice(i, 1);
    let back = ov._opener;
    // кнопку могли перерисовать, пока окно было открыто, — ищем такую же
    if (back && !back.isConnected && ov._openerAct) back = document.querySelector(`[data-act="${CSS.escape(ov._openerAct)}"]`);
    ov._opener = null;
    if (ovStack.length) { // a stacked window closed: back to the control inside the lower window that opened it
      const lower = ovDialog(ovStack[ovStack.length - 1]);
      if (back && back.isConnected && lower.contains(back) && back.getClientRects().length) back.focus({ preventScroll: true });
      else lower.focus({ preventScroll: true });
      return;
    }
    document.removeEventListener("keydown", ovKey);
    $("app").inert = false;
    document.documentElement.classList.remove("vl-ov-lock");
    if (back && back.isConnected && back.getClientRects().length) back.focus({ preventScroll: true });
  }

  // ================================================================== ГЛАВНАЯ
  async function loadPools() {
    try {
      state.pools = await api("/api/pools");
      const all = state.pools.live.concat(state.pools.finished);
      if (all.length) state.offset = all[0].now_ts - Math.floor(Date.now() / 1000);
      renderPools();
    } catch (e) {
      $("pools-list").removeAttribute("aria-busy");
      $("pools-list").innerHTML = emptyState("i-close", esc(e.message));
    }
  }

  // карточки раунда: разметка и стили — static/css/vl-cards.css, картинка и эффекты — static/js/vl-fx.js
  const icon = (id, cls) => `<svg class="ic ${cls || ""}" aria-hidden="true"><use href="#${id}"/></svg>`;
  const HIDDEN = `<span class="vl-pc-hidden">${icon("i-lock", "ic-sm")}Скрыто</span>`;
  const seenBank = {}; // id → последний показанный банк: «докручиваем» только новое или изменившееся

  function emptyState(ic, text, action) {
    return `<div class="vl-empty">${icon(ic, "ic-lg")}<p>${text}</p>${action || ""}</div>`;
  }
  function stat(lbl, val, cls) {
    return `<div class="vl-pc-stat ${cls || ""}"><dt>${lbl}</dt><dd>${val}</dd></div>`;
  }
  function meta(lbl, val) {
    return `<div class="vl-pc-meta-i"><span>${lbl}</span><b class="num">${val}</b></div>`;
  }

  function poolCard(p, featured) {
    const live = p.status === "live";
    const m = MODE_INFO[p.mode] || { name: p.mode, icon: "i-rounds" };
    const bank = p.bank == null ? HIDDEN
      : `<span class="num" data-bank="${p.id}" data-v="${p.bank}">${fmt(p.bank)}</span>`;
    const people = p.participants == null ? HIDDEN : `<span class="num">${fmt(p.participants)}</span>`;
    let third, bar = null, metas;
    if (!live) {
      const w = p.winner ? (p.winner.is_me ? "Ты" : esc(p.winner.name)) : "—";
      third = stat("Победитель", `<span class="vl-pc-winner">${w}</span>`, "vl-pc-stat-win");
      metas = meta("Завершён", ago(p.ends_ts || p.created_ts));
    } else if (p.mode === "vault") {
      third = stat("Занято чисел", `<span class="num">${p.taken}/${p.vault_max}</span>`);
      bar = p.vault_max ? p.taken / p.vault_max * 100 : 0;
      metas = meta("Попытка", fmt(p.min_stake) + " VLD") + meta("Окончание", "бессрочно");
    } else {
      third = stat(p.mode === "auction" ? "До раскрытия" : "Осталось",
        `<span class="num" data-ends="${p.ends_ts}">—</span>`);
      bar = timeBar(p);
      metas = meta("Мин. ставка", fmt(p.min_stake) + " VLD")
        + (p.mode === "auction" && p.my_total ? meta("Твоя ставка", fmt(p.my_total) + " VLD") : "");
    }
    const status = live ? `<span class="tag tag-live">идёт</span>` : `<span class="tag">завершён</span>`;
    const mine = p.is_organizer ? `<span class="tag tag-accent">твой раунд</span>` : "";
    const tid = `pc-t-${p.id}`;
    const cls = "vl-pc" + (featured ? " vl-pc-feat" : "") + (live ? "" : " vl-pc-done");
    return `<div class="vl-cell${featured ? " vl-cell-feat" : ""}">
      <article class="${cls}" aria-labelledby="${tid}" data-pool="${p.id}"${live ? " data-tilt" : ""}>
        <span class="vl-pc-sheen" data-tilt-sheen aria-hidden="true"></span>
        <div class="vl-pc-head">
          <div class="vl-pc-gift" data-tilt-float>${VLFx.giftImg(p, "vl-pc-pic")}</div>
          <div class="vl-pc-id">
            <div class="vl-pc-kicker"><span class="vl-pc-mode">${icon(m.icon)}${m.name}</span>${status}${mine}</div>
            <h3 class="vl-pc-title" id="${tid}" title="${esc(p.title)}">${esc(p.title)}</h3>
            <div class="vl-pc-org">от <b>${esc(p.organizer)}</b></div>
          </div>
        </div>
        <dl class="vl-pc-stats">${stat("Банк, VLD", bank)}${stat("Участники", people)}${third}</dl>
        ${bar == null ? "" : `<div class="vl-pc-bar" aria-hidden="true"><i style="width:${Math.min(100, bar).toFixed(0)}%"></i></div>`}
        <div class="vl-pc-foot">
          <div class="vl-pc-meta">${metas}</div>
          <button type="button" class="vl-btn vl-btn-sm ${live ? "vl-btn-primary" : "vl-btn-ghost"} vl-pc-go" data-pool="${p.id}"
            aria-label="${live ? "Перейти" : "Результат"}: ${esc(p.title)}">${live ? "Перейти" : "Результат"}</button>
          <button type="button" class="vl-btn vl-btn-ghost vl-btn-sm vl-btn-icon vl-pc-share" data-share="${p.id}"
            aria-label="Скопировать ссылку на раунд" title="Скопировать ссылку">${icon("i-share")}</button>
        </div>
      </article></div>`;
  }
  // банк «докручивается», когда карточка появилась впервые или сумма изменилась после обновления
  function animateBanks(root) {
    root.querySelectorAll("[data-bank]").forEach((el) => {
      const id = el.dataset.bank, to = +el.dataset.v, prev = seenBank[id];
      seenBank[id] = to;
      if (prev === to) return;
      el.textContent = fmt(prev || 0);
      VLFx.countUp(el, to);
    });
  }
  function timeBar(p) {
    if (!p.ends_ts) return 0;
    const span = p.ends_ts - p.created_ts || 1;
    return Math.max(2, (1 - (p.ends_ts - nowTs()) / span) * 100);
  }

  function renderPools() {
    let list = state.pools.live.slice();
    const f = state.filter;
    if (f === "hot") list.sort((a, b) => (b.bank || 0) - (a.bank || 0));
    else if (f === "new") list.sort((a, b) => b.created_ts - a.created_ts);
    else if (f === "soon") list = list.filter((p) => p.ends_ts).sort((a, b) => a.ends_ts - b.ends_ts);
    else if (MODE_INFO[f]) list = list.filter((p) => p.mode === f);
    // «Все»: самый активный раунд (больше участников, затем банк) — первой крупной карточкой
    let feat = -1;
    if (f === "all" && list.length) {
      const score = (p) => (p.participants || 0) * 1e9 + (p.bank || 0);
      feat = list.reduce((bi, p, i) => (score(p) > score(list[bi]) ? i : bi), 0);
      list.unshift(list.splice(feat, 1)[0]); feat = 0;
    }
    const live = $("pools-list"), done = $("pools-finished");
    live.removeAttribute("aria-busy");
    live.innerHTML = list.length ? list.map((p, i) => poolCard(p, i === feat)).join("")
      : state.pools.live.length
        ? emptyState("i-rounds", "В этом разделе сейчас нет раундов")
        : emptyState("i-rounds", "Активных раундов пока нет. Создай первый — подарок уйдёт в эскроу до розыгрыша.",
          `<button type="button" class="vl-btn vl-btn-primary vl-btn-sm" data-tab="create">${icon("i-create")}Создать раунд</button>`);
    done.innerHTML = state.pools.finished.length ? state.pools.finished.map((p) => poolCard(p, false)).join("")
      : emptyState("i-clock", "Завершённых раундов пока нет");
    tickTimers();
    animateBanks(live); animateBanks(done);
    VLFx.tilt(live);
    VLFx.stagger(live); VLFx.stagger(done);
  }

  // ================================================================== РАУНД
  // Разметка — templates/vloody.html (#sc-wheel / #sc-vault / #sc-auction), стили — static/css/vl-rounds.css.
  let watchTimer = 0;
  const reducedMotion = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const YOU = `<span class="vl-you">ты</span>`;
  const fmtPct = (v) => (Number(v) || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) + "%";

  // Картинка подарка (+ lottie, если есть p.anim) в коробке экрана раунда. Пересобирается только когда подарок
  // меняется, поэтому опрос раз в 4 с не перезапускает анимацию; при уходе с раунда все экземпляры уничтожаются.
  const giftBoxes = new Map(); // box → {key, anim}
  function mountGift(box, p, cls, withAnim) {
    if (!box) return;
    const anim = withAnim && p.anim ? p.anim : "";
    const key = `${p.id}|${p.image || ""}|${anim}`;
    const cur = giftBoxes.get(box);
    if (cur && cur.key === key) return;
    if (cur && cur.anim) cur.anim.destroy();
    box.innerHTML = VLFx.giftImg(p, cls);
    giftBoxes.set(box, { key, anim: anim ? VLFx.lottie(box, anim, { loop: true }) : null });
  }
  function unmountGifts() {
    giftBoxes.forEach((g) => { if (g.anim) g.anim.destroy(); });
    giftBoxes.clear();
  }

  function stopPoolWatch() { clearInterval(watchTimer); watchTimer = 0; state.pool = null; unmountGifts(); }

  async function openPool(id) {
    let p;
    try { p = await api("/api/pools/" + id); } catch (e) { toast(e.message); return; }
    stopPoolWatch();
    state.pool = p; state.spinning = false; state.wheelRot = 0;
    state.offset = p.now_ts - Math.floor(Date.now() / 1000);
    markNav(state.back || "home"); // раунд открыт из этого раздела, «назад» вернёт в него
    show(MODE_SCREEN[p.mode]);
    state.poolFresh = true; // первая отрисовка: дверь сейфа без анимации, раскрытие аукциона проигрывается
    renderPool(false);
    state.poolFresh = false;
    watchTimer = setInterval(refreshPool, 4000);
  }

  async function refreshPool() {
    const cur = state.pool;
    if (!cur || state.spinning) return;
    if (cur.status !== "live") { clearInterval(watchTimer); return; }
    try {
      const p = await api("/api/pools/" + cur.id);
      // параллельный запрос (таймер + опрос) уже применил завершение — второй раз не проигрываем раскрытие
      if (!state.pool || state.pool.id !== p.id || state.pool.status !== "live") return;
      const justFinished = p.status === "finished";
      state.pool = p;
      renderPool(justFinished);
    } catch (e) {}
  }

  function applyPool(p, animate) { state.pool = p; renderPool(animate); }

  function renderPool(animate) {
    const p = state.pool; if (!p) return;
    if (p.mode === "wheel") renderWheel(animate);
    else if (p.mode === "vault") renderVault();
    else renderAuction(animate);
    tickTimers();
  }

  function setStatus(el, p) {
    const s = { live: ["идёт", "tag tag-live"], finished: ["завершён", "tag"], cancelled: ["отменён", "tag tag-danger"] }[p.status]
      || [p.status, "tag"];
    el.textContent = s[0]; el.className = s[1];
  }

  function fairHtml(p) {
    const f = p.fair || {}, r = f.result || {};
    let rows = `<div class="vl-fair-row"><span>Хеш, опубликованный при создании</span><code class="num">${esc(f.seed_hash)}</code></div>`;
    let note = "";
    if (f.seed) {
      rows += `<div class="vl-fair-row"><span>Раскрытый seed</span><code class="num">${esc(f.seed)}</code></div>`;
      if (p.mode === "wheel" && r.total) {
        note = `Билет <b class="num">${fmt(r.ticket)}</b> из <b class="num">${fmt(r.total)}</b>, ставок: <b class="num">${fmt(r.entries)}</b>. Побеждает тот, чей отрезок ставок накрывает билет.`;
      } else if (p.mode === "vault" && p.secret != null) {
        note = `Секретное число <b class="num">${esc(p.secret)}</b>: sha256("${esc(p.secret)}:seed") совпадает с хешем.`;
      } else if (p.mode === "auction") note = "Все накопленные ставки открыты. Побеждает наибольшая; при равенстве — кто достиг её раньше.";
    } else if (p.mode === "auction") note = "Суммы ставок и банк откроются только в момент раскрытия.";
    else note = "Seed раскроется после завершения — по нему можно пересчитать результат.";
    return `<h3 class="vl-fair-h">${icon("i-shield")}Проверка честности</h3>${rows}`
      + (note ? `<p class="vl-fair-note">${note}</p>` : "")
      + `<button type="button" class="vl-fair-more" data-act="fair-info">Как это устроено</button>`;
  }

  // банк раунда: при открытии — сразу итог, при обновлении (новые ставки) — «докручивается»
  function setBank(el, v) {
    if (state.poolFresh) { el.textContent = fmt(v); return; }
    VLFx.countUp(el, v);
  }

  function showWinner(box, title, sub) {
    if (title == null) { box.classList.remove("is-on"); return; }
    box.querySelector(".vl-win-t").textContent = title;
    box.querySelector(".vl-win-s").textContent = sub;
    box.classList.add("is-on");
  }

  // ---------------------------------------------------------------- колесо
  // Углы — радианы холста (0 = «3 часа», по часовой). Сектор i начинается в −π/2 + rot + 2π·(сумма ставок до него)/банк.
  // Стрелка сверху (−π/2), поэтому под ней всегда точка колеса с локальным углом (−rot) mod 2π от начала первого сектора.
  const TAU = Math.PI * 2;
  const WheelMath = {
    total: (stakes) => stakes.reduce((s, x) => s + x.amount, 0),
    // поворот, при котором середина сектора победителя стоит под стрелкой
    winnerAngle(stakes, winnerKey) {
      const total = WheelMath.total(stakes);
      let before = 0;
      for (const s of stakes) {
        if (s.key === winnerKey) return -((before + s.amount / 2) / total) * TAU;
        before += s.amount;
      }
      return 0;
    },
    // индекс ставки под стрелкой при повороте rot (−1 — пустое колесо)
    sectorAt(stakes, rot) {
      const total = WheelMath.total(stakes);
      if (!total) return -1;
      const u = (((-rot) % TAU) + TAU) % TAU / TAU * total;
      let acc = 0;
      for (let i = 0; i < stakes.length; i++) { acc += stakes[i].amount; if (u < acc) return i; }
      return stakes.length - 1;
    },
    // счётчик пройденных стрелкой границ секторов (растёт с каждой границей, в том числе на колесе из одной ставки)
    borderCount(stakes, rot) {
      return Math.floor(-rot / TAU) * stakes.length + WheelMath.sectorAt(stakes, rot);
    },
  };
  window.VLWheelMath = WheelMath; // чистые функции без состояния — для проверки углов из консоли
  function winnerAngle(p) { return WheelMath.winnerAngle(p.stakes, p.winner_key); }

  // Палитра колеса — CSS-переменные темы (vl-rounds.css), читаются один раз и сбрасываются при смене темы.
  const WH_SEG = 8;
  let wheelPal = null, wheelPx = 0;
  function readWheelPal() {
    const cs = getComputedStyle($("wcanvas")), v = (n) => cs.getPropertyValue("--vl-wh-" + n).trim();
    const seg = [];
    for (let i = 1; i <= WH_SEG; i++) seg.push(v(i));
    return { seg, ink: v("ink"), me: v("me"), meInk: v("me-ink"), win: v("win"), winInk: v("win-ink"),
      dim: v("dim"), rimA: v("rim-a"), rimB: v("rim-b"), rimHi: v("rim-hi"), peg: v("peg"), sep: v("sep"),
      sepHi: v("sep-hi"), shade: v("shade"), light: v("light"), empty: v("empty"), emptyInk: v("empty-ink") };
  }
  // номер цвета сектора: «me» / «win» или 1..WH_SEG; соседние сектора (и последний с первым) не совпадают
  function wheelSlot(stakes, i, winKey) {
    const s = stakes[i];
    if (winKey != null && s.key === winKey) return "win";
    if (s.is_me) return "me";
    let n = (i % WH_SEG) + 1;
    if (i === stakes.length - 1 && i > 0 && n === 1) n = 2;
    return n;
  }
  const slotColor = (P, slot) => (slot === "win" ? P.win : slot === "me" ? P.me : P.seg[slot - 1]);

  // холст: CSS-размер — целые px по ширине коробки, буфер = CSS × devicePixelRatio (без размытия)
  function sizeWheel() {
    const c = $("wcanvas"), box = $("wheel-box");
    const css = Math.floor(box.getBoundingClientRect().width);
    if (!css) return false;
    const px = Math.round(css * Math.min(3, window.devicePixelRatio || 1));
    if (c.style.width !== css + "px") { c.style.width = c.style.height = css + "px"; }
    if (c.width !== px || c.height !== px) { c.width = px; c.height = px; }
    wheelPx = css;
    return true;
  }

  const EMOJI_FONT = '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
  function drawWheel(rot) {
    const p = state.pool, c = $("wcanvas");
    if (!p || p.mode !== "wheel") return;
    if (!wheelPx && !sizeWheel()) return;
    const P = wheelPal || (wheelPal = readWheelPal());
    const ctx = c.getContext("2d"), S = wheelPx, k = c.width / S;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.clearRect(0, 0, S, S);
    const cx = S / 2, cy = S / 2, R = S / 2 - 1, rimW = Math.max(9, Math.round(S * 0.048)), r = R - rimW;
    const disc = () => { ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); };

    // обод: металлическая полоса, свет сверху
    const rg = ctx.createLinearGradient(0, cy - R, 0, cy + R);
    rg.addColorStop(0, P.rimA); rg.addColorStop(1, P.rimB);
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.fillStyle = rg; ctx.fill();
    ctx.beginPath(); ctx.arc(cx, cy, R - 0.75, Math.PI * 1.1, Math.PI * 1.9);
    ctx.strokeStyle = P.rimHi; ctx.lineWidth = 1.5; ctx.stroke();
    // фаска внутренней кромки обода: снизу светлее (отражённый свет), сверху — тень
    const bg = ctx.createLinearGradient(0, cy - r, 0, cy + r);
    bg.addColorStop(0, P.sep); bg.addColorStop(1, P.rimHi);
    ctx.beginPath(); ctx.arc(cx, cy, r + 2.5, 0, TAU); ctx.strokeStyle = bg; ctx.lineWidth = 3; ctx.stroke();

    const stakes = p.stakes || [], total = WheelMath.total(stakes);
    if (!total) {
      disc(); ctx.fillStyle = P.empty; ctx.fill();
      ctx.fillStyle = P.emptyInk; ctx.font = `600 ${Math.round(S * 0.042)}px Onest, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("Ждём первую ставку", cx, cy + r * 0.55);
      shadeDisc(ctx, P, cx, cy, r);
      return;
    }
    const fin = p.status === "finished" && !state.spinning;
    const winKey = fin ? p.winner_key : null;

    // сектора
    let cur = -Math.PI / 2 + rot;
    const borders = [];
    stakes.forEach((s, i) => {
      const arc = s.amount / total * TAU, slot = wheelSlot(stakes, i, winKey);
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, r, cur, cur + arc); ctx.closePath();
      ctx.fillStyle = slotColor(P, slot); ctx.fill();
      if (fin && slot !== "win") { ctx.fillStyle = P.dim; ctx.fill(); }
      borders.push(cur);
      cur += arc;
    });
    shadeDisc(ctx, P, cx, cy, r);

    // границы: тёмная линия + светлая фаска рядом
    if (stakes.length > 1) {
      borders.forEach((a) => {
        const x = Math.cos(a), y = Math.sin(a), hi = a + 1.4 / r;
        ctx.beginPath(); ctx.moveTo(cx + x * r * 0.18, cy + y * r * 0.18); ctx.lineTo(cx + x * r, cy + y * r);
        ctx.strokeStyle = P.sep; ctx.lineWidth = 2; ctx.stroke();
        ctx.beginPath(); ctx.moveTo(cx + Math.cos(hi) * r * 0.2, cy + Math.sin(hi) * r * 0.2);
        ctx.lineTo(cx + Math.cos(hi) * r, cy + Math.sin(hi) * r);
        ctx.strokeStyle = P.sepHi; ctx.lineWidth = 1; ctx.stroke();
      });
    }
    // кромка между ободом и секторами
    disc(); ctx.strokeStyle = P.sep; ctx.lineWidth = 2; ctx.stroke();
    // штифты на ободе у каждой границы — о них «отбивает» стрелка
    const pegR = Math.max(2.2, rimW * 0.24), pegD = r + rimW / 2;
    borders.forEach((a) => {
      const x = cx + Math.cos(a) * pegD, y = cy + Math.sin(a) * pegD;
      ctx.beginPath(); ctx.arc(x, y + 0.8, pegR, 0, TAU); ctx.fillStyle = "rgba(0,0,0,.35)"; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, pegR, 0, TAU); ctx.fillStyle = P.peg; ctx.fill();
    });

    // подписи: аватар или процент поперёк радиуса, всегда читаются сверху вниз
    const fs = Math.round(Math.max(13, Math.min(26, S * 0.062))), dist = r * 0.7;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    cur = -Math.PI / 2 + rot;
    stakes.forEach((s, i) => {
      const arc = s.amount / total * TAU, ma = cur + arc / 2, slot = wheelSlot(stakes, i, winKey);
      cur += arc;
      if (arc * dist < fs * 1.3) return; // узкий сектор — без подписи (участник есть в списке ниже)
      ctx.save();
      ctx.translate(cx + Math.cos(ma) * dist, cy + Math.sin(ma) * dist);
      ctx.rotate(Math.sin(ma) > 0 ? ma - Math.PI / 2 : ma + Math.PI / 2); // в нижней половине — не вверх ногами
      ctx.globalAlpha = fin && slot !== "win" ? 0.55 : 1;
      if (state.wheelMode === "av") {
        ctx.font = `${fs}px ${EMOJI_FONT}`;
        ctx.fillStyle = slot === "win" ? P.winInk : slot === "me" ? P.meInk : P.ink; // monochrome glyph fallback
        ctx.fillText(s.avatar, 0, 0);
      } else {
        ctx.font = `700 ${Math.round(fs * 0.66)}px "JetBrains Mono", monospace`;
        ctx.fillStyle = slot === "win" ? P.winInk : slot === "me" ? P.meInk : P.ink;
        ctx.fillText(Math.round(s.amount / total * 100) + "%", 0, 0);
      }
      ctx.restore();
    });
  }
  // объём: тень к ободу + свет сверху
  function shadeDisc(ctx, P, cx, cy, r) {
    const sh = ctx.createRadialGradient(cx, cy, r * 0.25, cx, cy, r);
    sh.addColorStop(0, "rgba(0,0,0,0)"); sh.addColorStop(0.72, "rgba(0,0,0,0)"); sh.addColorStop(1, P.shade);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, TAU); ctx.fillStyle = sh; ctx.fill();
    const lg = ctx.createLinearGradient(0, cy - r, 0, cy + r);
    lg.addColorStop(0, P.light); lg.addColorStop(0.55, "rgba(255,255,255,0)");
    ctx.fillStyle = lg; ctx.fill();
  }

  function spinToWinner() {
    const p = state.pool, base = winnerAngle(p);
    if (reducedMotion()) { state.wheelRot = base; renderWheel(false); return; }
    state.spinning = true;
    const from = state.wheelRot, target = base + TAU * (Math.ceil((from - base) / TAU) + 8);
    const dur = 6000, st = performance.now(), ease = (t) => 1 - Math.pow(1 - t, 4);
    const ptr = $("w-ptr"), scr = $("sc-wheel");
    let ptrDeg = 0, lastBorder = null, lastT = st, lastRot = from;
    scr.classList.add("is-spinning");
    const finish = () => { ptr.style.transform = ""; scr.classList.remove("is-spinning"); state.spinning = false; };
    (function fr(now) {
      if (state.pool !== p) return finish();
      const t = reducedMotion() ? 1 : Math.min((now - st) / dur, 1), rot = from + (target - from) * ease(t), dt = Math.max(1, now - lastT);
      // стрелка: удар при каждой пройденной границе, сила — от скорости, затем пружинит обратно
      const b = WheelMath.borderCount(p.stakes, rot);
      if (lastBorder !== null && b !== lastBorder) ptrDeg = Math.max(-28, ptrDeg - Math.min(24, 7 + (rot - lastRot) / dt * 420));
      ptrDeg *= Math.pow(0.84, dt / 16.7);
      lastBorder = b; lastT = now; lastRot = rot;
      ptr.style.transform = `rotate(${ptrDeg.toFixed(2)}deg)`;
      state.wheelRot = rot;
      drawWheel(rot);
      if (t < 1) return requestAnimationFrame(fr);
      finish();
      renderWheel(false);
      haptic(p.winner && p.winner.is_me ? "ok" : "medium");
      if (p.winner && p.winner.is_me) VLFx.confetti("win");
    })(st);
  }

  function renderWheel(animate) {
    const p = state.pool, live = p.status === "live", fin = p.status === "finished";
    const spin = animate && fin && p.stakes.length > 0 && !reducedMotion();
    mountGift($("det-gift"), p, "vl-rd-pic", true);
    mountGift($("w-hub"), p, "vl-wh-hub-pic", false);
    $("det-name").textContent = p.title; $("det-org").textContent = p.organizer;
    setStatus($("det-status"), p);
    $("det-min").textContent = fmt(p.min_stake);
    setBank($("det-bank"), p.bank);
    $("det-part").textContent = fmt(p.participants);
    $("det-mine").textContent = fmt(p.my_total);
    $("det-chance").textContent = fmtPct(p.my_chance);
    $("det-pf").style.width = (live ? Math.min(100, timeBar(p)) : 100) + "%";
    $("det-time-lbl").textContent = live ? "До розыгрыша" : (fin ? "Разыгран" : "Отменён");
    $("det-timer").textContent = live ? hms(p.ends_ts - nowTs()) : (p.ends_ts ? ago(p.ends_ts) : "—");
    $("det-buy").classList.toggle("hid", !live || p.is_organizer);
    $("det-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.stakes.length));
    $("wheel-cd").classList.toggle("hid", !live);
    $("wheel-fair").innerHTML = fairHtml(p);

    const total = WheelMath.total(p.stakes), winKey = fin && !spin ? p.winner_key : null;
    $("stakes-lbl").textContent = p.stakes.length ? `Ставки · ${p.stakes.length}` : "Ставки";
    $("stakes-list").innerHTML = p.stakes.length ? p.stakes.map((s, i) => {
      const slot = wheelSlot(p.stakes, i, winKey);
      return `<li class="vl-stake${slot === "win" ? " is-win" : ""}${s.is_me ? " is-me" : ""}">
        <i class="vl-stake-sw" style="background:var(--vl-wh-${slot})" aria-hidden="true"></i>
        <span class="vl-stake-av" aria-hidden="true">${esc(s.avatar)}</span>
        <span class="vl-stake-n">${esc(s.name)}${s.is_me ? YOU : ""}</span>
        <span class="vl-stake-pct num">${fmtPct(s.amount / total * 100)}</span>
        <b class="vl-stake-v num">${fmt(s.amount)}</b></li>`;
    }).join("") : `<li class="vl-list-empty">Ставок пока нет — первая ставка займёт всё колесо</li>`;

    sizeWheel();
    if (spin) { showWinner($("det-winner"), null); return spinToWinner(); }
    if (fin) state.wheelRot = winnerAngle(p);
    drawWheel(state.wheelRot);
    if (fin && p.winner) {
      const ws = p.stakes.find((s) => s.key === p.winner_key);
      showWinner($("det-winner"), p.winner.is_me ? "Ты выиграл подарок" : "Победитель — " + p.winner.name,
        (p.winner.is_me ? "Подарок уже в твоём инвентаре" : "Подарок передан победителю")
        + (ws && total ? ` · его доля была ${fmtPct(ws.amount / total * 100)}` : ""));
    } else showWinner($("det-winner"), null);
    if (p.status === "cancelled") toast("Раунд отменён — ставок не было");
  }

  // перерисовка при изменении размера окна, пересечении 860/861px и смене темы — слушатели ставятся один раз
  function redrawWheel() {
    const p = state.pool;
    if (!p || p.mode !== "wheel" || !$("sc-wheel").classList.contains("on")) return;
    if (sizeWheel() && !state.spinning) drawWheel(state.wheelRot);
  }
  window.addEventListener("resize", redrawWheel); // браузер шлёт resize не чаще раза за кадр
  if (window.matchMedia) {
    const mqDesk = window.matchMedia("(min-width: 861px)");
    if (mqDesk.addEventListener) mqDesk.addEventListener("change", redrawWheel); else if (mqDesk.addListener) mqDesk.addListener(redrawWheel);
  }
  new MutationObserver(() => { wheelPal = null; redrawWheel(); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawWheel);

  // ---------------------------------------------------------------- сейф
  const vaultCode = (v, max) => {
    const w = String(max || 100).length, n = parseInt(v, 10);
    return n > 0 ? String(n).padStart(w, "0") : Array(w).fill("–").join(" ");
  };
  // выбор числа (клетка поля или ввод): показать на табло двери и отметить клетку
  function vaultPick() {
    const p = state.pool; if (!p || p.mode !== "vault" || p.status !== "live") return;
    const v = parseInt($("vt-num").value, 10);
    $("vt-display").textContent = vaultCode(v, p.vault_max);
    $("vt-grid").querySelectorAll(".vl-vc.is-picked").forEach((c) => c.classList.remove("is-picked"));
    const cell = $("vt-grid").querySelector(`[data-num="${v}"]`);
    if (cell) cell.classList.add("is-picked");
  }

  function renderVault() {
    const p = state.pool, live = p.status === "live", fin = p.status === "finished";
    mountGift($("vt-gift"), p, "vl-rd-pic", !fin);
    mountGift($("vt-prize"), p, "vl-safe-pic", fin); // после вскрытия анимация играет внутри сейфа
    $("vt-name").textContent = p.title; $("vt-org").textContent = p.organizer;
    setStatus($("vt-status"), p);
    $("vt-min").textContent = fmt(p.min_stake);
    setBank($("vt-bank"), p.bank);
    $("vt-part").textContent = fmt(p.participants);
    $("vt-taken").textContent = `${fmt(p.taken)} / ${fmt(p.vault_max)}`;
    $("vt-hint").innerHTML = live
      ? `Угадай число от <b class="num">1</b> до <b class="num">${fmt(p.vault_max)}</b>. Попытка стоит <b class="num">${fmt(p.min_stake)}</b> VLD и уходит в банк; угадавший сразу забирает подарок.`
      : fin ? "Сейф вскрыт. Секретное число и seed раскрыты — результат можно проверить." : "Раунд отменён.";
    $("vt-num").max = p.vault_max;
    $("vt-form").classList.toggle("hid", !live || p.is_organizer);
    $("vt-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.numbers.length));

    const safe = $("vault-safe");
    if (state.poolFresh) { // открытый раунд показываем сразу в итоговом состоянии, без анимации двери
      safe.classList.add("vl-noanim");
      requestAnimationFrame(() => requestAnimationFrame(() => safe.classList.remove("vl-noanim")));
    }
    safe.classList.toggle("is-open", fin);
    safe.classList.toggle("is-shut", !live && !fin);
    // секретное число есть в ответе только после завершения; до этого на табло — выбранное игроком число
    $("vt-display").textContent = fin && p.secret != null ? vaultCode(p.secret, p.vault_max) : vaultCode($("vt-num").value, p.vault_max);
    $("vt-g-taken").textContent = `${fmt(p.numbers.length)} из ${fmt(p.vault_max)}`;
    $("vault-fair").innerHTML = fairHtml(p);

    const picked = parseInt($("vt-num").value, 10), canTry = live && !p.is_organizer;
    // поле пересобирается только когда что-то изменилось (опрос раз в 4 с не сбрасывает наведение и фокус)
    const grid = $("vt-grid"), gridKey = JSON.stringify([p.id, p.vault_max, canTry, p.numbers]);
    if (grid._key !== gridKey) { grid._key = gridKey; renderVaultGrid(p, picked, canTry); }
    $("vt-feed").innerHTML = p.numbers.length ? p.numbers.slice().reverse().slice(0, 12).map((n) => `
      <li class="vl-feed-row${n.win ? " is-win" : ""}">
        <b class="num">${esc(n.number)}</b><span class="vl-feed-n">${esc(n.name)}${n.is_me ? YOU : ""}</span>
        <span class="vl-feed-r">${n.win ? "вскрыл" : "мимо"}</span>
      </li>`).join("") : `<li class="vl-list-empty">Попыток пока не было</li>`;

    if (fin && p.winner) {
      showWinner($("vt-winner"), p.winner.is_me ? "Ты вскрыл сейф" : "Сейф вскрыл " + p.winner.name,
        `Секретное число — ${p.secret}. ${p.winner.is_me ? "Подарок уже в твоём инвентаре." : "Подарок передан победителю."}`);
    } else showWinner($("vt-winner"), null);
  }

  function renderVaultGrid(p, picked, canTry) {
    const taken = new Map(p.numbers.map((n) => [n.number, n]));
    const focusNum = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.num : null;
    let cells = "";
    for (let i = 1; i <= p.vault_max; i++) {
      const t = taken.get(i);
      cells += t
        ? `<div class="vl-vc is-taken${t.is_me ? " is-mine" : ""}${t.win ? " is-win" : ""}" title="${i} — ${esc(t.name)}"
            aria-label="Число ${i}: ${esc(t.name)}${t.win ? ", угадал" : ", мимо"}"><b>${i}</b><span>${esc(t.name)}</span></div>`
        : `<button type="button" class="vl-vc${i === picked ? " is-picked" : ""}" data-num="${i}"${canTry ? "" : " disabled"} aria-label="Число ${i}">${i}</button>`;
    }
    $("vt-grid").innerHTML = cells;
    if (focusNum) { const f = $("vt-grid").querySelector(`[data-num="${focusNum}"]`); if (f) f.focus({ preventScroll: true }); }
  }

  let vaultBusy = false;
  async function tryVault() {
    const p = state.pool; if (!p || vaultBusy) return;
    const num = parseInt($("vt-num").value, 10);
    if (!num || num < 1 || num > p.vault_max) { toast(`Введи число от 1 до ${p.vault_max}`); return; }
    vaultBusy = true;
    const safe = $("vault-safe");
    try {
      const r = await api(`/api/pools/${p.id}/vault`, { number: num });
      setBalance(r.balance);
      $("vt-num").value = "";
      if (r.hit) { haptic("ok"); toast("Сейф вскрыт — подарок твой"); VLFx.confetti("jackpot"); }
      else { haptic("error"); toast(`Число ${num} — мимо`); }
      applyPool(r.pool, false);
      if (!r.hit) { // промах: дверь вздрагивает, табло на мгновение показывает неверный код
        safe.classList.remove("is-miss"); void safe.offsetWidth; safe.classList.add("is-miss");
        $("vt-display").textContent = vaultCode(num, p.vault_max);
        clearTimeout(safe._miss);
        safe._miss = setTimeout(() => { safe.classList.remove("is-miss"); vaultPick(); }, 900);
      }
    } catch (e) { toast(e.message); haptic("error"); }
    vaultBusy = false;
  }

  // ---------------------------------------------------------------- аукцион
  const aucRevealed = new Set(); // id завершённых раундов, раскрытие которых уже показали в этой сессии
  function renderAuction(animate) {
    const p = state.pool, live = p.status === "live", fin = p.status === "finished";
    mountGift($("auc-gift"), p, "vl-rd-pic", true);
    $("auc-name").textContent = p.title; $("auc-org").textContent = p.organizer;
    setStatus($("auc-status"), p);
    $("auc-min").textContent = fmt(p.min_stake);
    // слепой аукцион: пока идёт, банк и чужие ставки не выводятся вовсе
    $("auc-bank").innerHTML = live || p.bank == null ? HIDDEN : `<span class="num">${fmt(p.bank)}</span><small>VLD</small>`;
    $("auc-part").innerHTML = p.participants == null ? HIDDEN : `<span class="num">${fmt(p.participants)}</span>`;
    $("auc-mine-val").innerHTML = p.my_total ? `<span class="num">${fmt(p.my_total)}</span><small>VLD</small>`
      : `<span class="vl-rd-muted">ещё не ставил</span>`;
    $("auc-amt").placeholder = `от ${p.min_stake} VLD`; $("auc-amt").min = p.min_stake;
    $("auc-form").classList.toggle("hid", !live || p.is_organizer);
    $("auc-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.my_total && p.bank === 0));
    $("auc-cd").dataset.ends = live ? p.ends_ts : "";
    $("auc-cd").textContent = live ? hms(p.ends_ts - nowTs()) : "—";
    $("auction-fair").innerHTML = fairHtml(p);

    const stage = $("auc-stage"), board = $("auc-result"), shut = $("auc-blackout");
    if (live) { board.innerHTML = ""; shut.classList.remove("is-open"); return; }
    if (fin && p.bids) {
      const w = p.winner;
      board.innerHTML = `<div class="vl-auc-res">
          <span class="vl-win-ic">${icon("i-leaders")}</span>
          <div class="vl-win-txt"><div class="vl-win-t">${w ? (w.is_me ? "Ты выиграл подарок" : "Победитель — " + esc(w.name)) : "Победителя нет"}</div>
          <div class="vl-win-s">Банк <b class="num">${fmt(p.bank)}</b> VLD · ставок: <b class="num">${fmt(p.bids.length)}</b></div></div>
        </div>
        <ol class="vl-bids">${p.bids.map((b, i) => `
          <li class="vl-bid${i === 0 ? " is-top" : ""}${b.is_me ? " is-me" : ""}">
            <span class="vl-bid-r num">${i + 1}</span><span class="vl-bid-n">${esc(b.name)}${b.is_me ? YOU : ""}</span>
            <b class="vl-bid-v num">${fmt(b.amount)}</b>
          </li>`).join("")}</ol>`;
    } else board.innerHTML = `<p class="vl-auc-empty">Раунд отменён — ставок не было.</p>`;

    // раскрытие: шторка уезжает вверх, ставки появляются по одной — в момент завершения или при первом
    // просмотре этого завершённого раунда за сессию (дальше открывается сразу открытым)
    const reveal = animate || (state.poolFresh && !aucRevealed.has(p.id));
    aucRevealed.add(p.id);
    if (reveal && !reducedMotion()) {
      stage.classList.add("vl-noanim"); shut.classList.remove("is-open");
      void stage.offsetWidth;
      stage.classList.remove("vl-noanim");
      requestAnimationFrame(() => shut.classList.add("is-open"));
      board.querySelectorAll(".vl-bid").forEach((el, i) => {
        if (typeof el.animate !== "function") return;
        el.animate([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }],
          { duration: 320, delay: 620 + Math.min(i, 12) * 160, easing: "cubic-bezier(.2,.7,.2,1)", fill: "backwards" });
      });
      if (animate && p.winner && p.winner.is_me) setTimeout(() => VLFx.confetti("win"), 700); // после шторки
    } else shut.classList.add("is-open");
  }

  async function placeBid() {
    const p = state.pool; if (!p) return;
    const amt = parseInt($("auc-amt").value, 10);
    if (!amt || amt < p.min_stake) { toast(`Минимум ${p.min_stake} VLD`); return; }
    try {
      const r = await api(`/api/pools/${p.id}/bid`, { amount: amt });
      setBalance(r.balance); $("auc-amt").value = "";
      haptic("ok"); toast("Ставка принята — она скрыта до раскрытия");
      applyPool(r.pool, false);
    } catch (e) { toast(e.message); haptic("error"); }
  }

  // ---------------------------------------------------------------- ставка в колесе
  function stakeOpen() {
    const p = state.pool; if (!p) return;
    const bal = state.profile ? state.profile.balance : 0;
    const sl = $("sm-slider");
    sl.min = p.min_stake; sl.step = p.min_stake >= 25 ? 25 : 5;
    sl.max = Math.max(p.min_stake, Math.min(bal, 1000));
    sl.value = Math.min(sl.max, Math.max(p.min_stake, 50));
    $("sm-min").textContent = p.min_stake; $("sm-bal").textContent = fmt(bal);
    $("sm-input").value = "";
    stakeSync(+sl.value);
    openOv("stake-modal");
  }
  function stakeSync(v) {
    const p = state.pool; if (!p) return;
    $("m-sv-num").textContent = fmt(v);
    $("sm-pcount").textContent = p.participants;
    const bank = (p.bank || 0) + v;
    $("sm-chance").textContent = (bank ? ((p.my_total + v) / bank * 100).toFixed(1) : 0) + "%";
  }
  const stakeValue = () => parseInt($("sm-input").value, 10) || parseInt($("sm-slider").value, 10);
  async function stakeConfirm() {
    const p = state.pool; if (!p) return;
    try {
      const r = await api(`/api/pools/${p.id}/stake`, { amount: stakeValue() });
      setBalance(r.balance); closeOv("stake-modal");
      haptic("ok"); toast("Ставка принята");
      applyPool(r.pool, false);
    } catch (e) { toast(e.message); haptic("error"); }
  }

  async function cancelPool() {
    const p = state.pool; if (!p) return;
    try {
      await api(`/api/pools/${p.id}/cancel`, {});
      toast("Раунд отменён, подарок вернулся в инвентарь");
      tab("home");
    } catch (e) { toast(e.message); }
  }

  // ---------------------------------------------------------------- вкладки (role="tablist")
  // Выбранная вкладка: .on + aria-selected="true" + tabindex=0, остальные tabindex=-1 (одна точка Tab на список);
  // стрелки ←/→, Home/End переводят фокус и сразу выбирают вкладку. Скрытые вкладки (инвентарь на десктопе) пропускаются.
  function selectTab(list, isOn) {
    list.querySelectorAll('[role="tab"]').forEach((b) => {
      const on = !!isOn(b);
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    });
  }
  function tabKeys(list, pick) {
    list.addEventListener("keydown", (e) => {
      const tabs = Array.from(list.querySelectorAll('[role="tab"]')).filter((b) => b.getClientRects().length);
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      let n = -1;
      if (e.key === "ArrowRight") n = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") n = 0;
      else if (e.key === "End") n = tabs.length - 1;
      if (n < 0) return;
      e.preventDefault();
      tabs[n].focus();
      pick(tabs[n]);
    });
  }

  // ================================================================== ЛИДЕРЫ
  // Разметка — templates/vloody.html (#sc-events), стили — static/css/vl-screens.css.
  const plural = (n, f) => {
    const a = Math.abs(n) % 100, b = a % 10;
    return f[a > 10 && a < 20 ? 2 : b === 1 ? 0 : b >= 2 && b <= 4 ? 1 : 2];
  };
  const vld = (n) => `<span class="num">${fmt(n)}</span><small>VLD</small>`;

  function switchLB(period) {
    state.lb = period;
    selectTab($("lb-tabs"), (b) => b.dataset.lb === period);
    $("lb-panel").setAttribute("aria-labelledby", "lbt-" + period);
    return loadEvents();
  }

  async function loadEvents() {
    try {
      const [lb, win] = await Promise.all([api("/api/leaderboard/" + state.lb), api("/api/winners")]);
      const label = { day: "день", week: "неделю", month: "месяц", all: "всё время" }[state.lb];
      const me = lb.me;
      $("lb-banner").innerHTML = me.rank
        ? `<div class="vl-ev-me-rank"><span>Твоё место</span><b class="num">#${fmt(me.rank)}</b></div>
           <dl class="vl-ev-me-stats">
             <div><dt>Оборот за ${label}</dt><dd>${vld(me.volume)}</dd></div>
             <div><dt>Победы</dt><dd><span class="num">${fmt(me.wins)}</span></dd></div>
             ${me.to_top100 ? `<div><dt>До топ-100</dt><dd>${vld(me.to_top100)}</dd></div>` : ""}
           </dl>`
        : `<div class="vl-ev-me-none">${icon("i-leaders", "ic-lg")}
             <p>За ${label} ты ещё не делал ставок. Сыграй в любом раунде — и попадёшь в рейтинг.</p>
             <button type="button" class="vl-btn vl-btn-ghost vl-btn-sm" data-tab="home">${icon("i-rounds")}К раундам</button></div>`;

      const top = lb.entries.slice(0, 3);
      $("lb-podium").innerHTML = top.map((e, i) => `
        <li class="vl-pod-col vl-pod-${i + 1}${e.is_me ? " is-me" : ""}">
          <div class="vl-pod-who">
            <span class="vl-pod-av" aria-hidden="true">${esc(e.avatar)}</span>
            <span class="vl-pod-name" title="${esc(e.name)}">${esc(e.name)}</span>
            ${e.is_me ? YOU : ""}
            <span class="vl-pod-vol">${vld(e.volume)}</span>
          </div>
          <div class="vl-pod-step"><span class="vl-pod-place num"><span class="sr-only">Место </span>${i + 1}</span></div>
        </li>`).join("");
      $("lb-podium").classList.toggle("hid", !top.length);

      const rest = lb.entries.slice(3);
      $("lb-list").innerHTML = rest.map((e) => `
        <li class="vl-lb-row${e.is_me ? " is-me" : ""}">
          <span class="vl-lb-rank num">${e.rank}</span>
          <span class="vl-lb-av" aria-hidden="true">${esc(e.avatar)}</span>
          <span class="vl-lb-id">
            <span class="vl-lb-name" title="${esc(e.name)}">${esc(e.name)}</span>
            <span class="vl-lb-sub">${e.is_me ? "это ты · " : ""}${fmt(e.wins)} ${plural(e.wins, ["победа", "победы", "побед"])}</span>
          </span>
          <span class="vl-lb-vol">${vld(e.volume)}</span>
        </li>`).join("")
        || (top.length ? "" : `<li class="vl-ev-empty">${emptyState("i-leaders", `За ${label} ставок не было`)}</li>`);

      $("winners-list").innerHTML = win.items.length ? win.items.map((w) => `
        <li><button type="button" class="vl-wf" data-pool="${+w.pool_id}">
          <span class="vl-wf-pic">${giftImg({ image: w.image, title: w.title }, "vl-wf-img")}</span>
          <span class="vl-wf-id">
            <span class="vl-wf-t" title="${esc(w.title)}">${esc(w.title)}</span>
            <span class="vl-wf-s"><b>${esc(w.winner)}</b> · ${ago(w.ts)}</span>
          </span>
          <span class="vl-wf-bank">${vld(w.bank)}</span>
        </button></li>`).join("")
        : `<li class="vl-ev-empty">${emptyState("i-clock", "Победителей пока нет")}</li>`;
      VLFx.stagger($("lb-podium")); VLFx.stagger($("lb-list")); VLFx.stagger($("winners-list"));
    } catch (e) { toast(e.message); }
  }

  // ================================================================== СОЗДАНИЕ
  // Разметка — templates/vloody.html (#sc-create), стили — static/css/vl-screens.css.
  // Шаги 1–3 слева; шаг 4 (#cr-sum… — сводка и кнопка) на десктопе липкий справа, на телефоне — последним блоком.
  const giftArt = (g) => ({ image: g.image, title: g.name });
  const timeLbl = (min) => (min < 60 ? `${min} мин` : `${min / 60} ч`);
  const chipHtml = (v, label, on) =>
    `<button type="button" class="vl-chip${on ? " is-on" : ""}" data-v="${v}" aria-pressed="${on}">${label}</button>`;

  async function loadGifts() {
    try { state.gifts = (await api("/api/inventory/gifts")).gifts; } catch (e) { state.gifts = []; }
    return state.gifts;
  }

  async function loadCreate() {
    await loadGifts();
    const held = state.gifts.filter((g) => g.status === "held");
    if (!held.find((g) => g.id === state.create.gift)) state.create.gift = held.length ? held[0].id : null;
    renderCreateGifts();
    renderCreateMode();
  }

  function renderCreateGifts() {
    const held = state.gifts.filter((g) => g.status === "held");
    const locked = state.gifts.filter((g) => g.status === "locked").length;
    $("cr-deposit").classList.toggle("hid", !held.length);
    if (!held.length) {
      const relay = esc(VL.relay);
      $("cr-gifts").innerHTML = `<div class="vl-cr-empty">
        <span class="vl-cr-empty-ic">${icon("i-rounds", "ic-lg")}</span>
        <div class="vl-cr-empty-b">
          <p class="vl-cr-empty-t">Свободных подарков нет</p>
          <ol class="vl-cr-empty-steps">
            <li>Открой бота-хранителя <b>@${relay}</b> в Telegram</li>
            <li>Отправь ему NFT-подарок через «Подарить»</li>
            <li>Через минуту подарок появится здесь — выбери его и запусти раунд</li>
          </ol>
          ${locked ? `<p class="vl-cr-empty-s">Ещё ${locked} ${plural(locked, ["подарок", "подарка", "подарков"])} сейчас в активных раундах.</p>` : ""}
          <button type="button" class="vl-btn vl-btn-primary vl-btn-sm" data-act="gift-deposit">${VL.demo
            ? icon("i-create") + "Получить демо-подарок" : icon("i-send") + "Открыть @" + relay}</button>
        </div></div>`;
      return;
    }
    $("cr-gifts").innerHTML = held.map((g) => {
      const on = g.id === state.create.gift;
      return `<button type="button" class="vl-cr-gift${on ? " is-on" : ""}" data-gift="${g.id}" aria-pressed="${on}" title="${esc(g.name)}">
        <span class="vl-cr-gift-pic">${giftImg(giftArt(g), "vl-cr-gift-img")}<span class="vl-cr-gift-ok" aria-hidden="true">${icon("i-check", "ic-sm")}</span></span>
        <span class="vl-cr-gift-n">${esc(g.name)}</span>
      </button>`;
    }).join("");
  }

  function renderCreateMode() {
    const m = state.create.mode;
    document.querySelectorAll("#cr-modes [data-cmode]").forEach((b) => {
      const on = b.dataset.cmode === m;
      b.classList.toggle("is-on", on); b.setAttribute("aria-pressed", String(on));
    });
    $("cr-mode-hint").textContent = MODE_HINT[m];
    $("cr-stake-lbl").textContent = m === "vault" ? "Ставка за попытку" : "Минимальная ставка";
    $("cr-stakes").innerHTML = STAKE_CHIPS[m].map((v, i) => chipHtml(v, `<span class="num">${v}</span> VLD`, i === 0)).join("");
    $("cr-vault-box").classList.toggle("hid", m !== "vault");
    $("cr-time-box").classList.toggle("hid", m === "vault");
    renderCreateSummary();
  }
  const chipVal = (id) => { const c = document.querySelector(`#${id} .vl-chip.is-on`); return c ? +c.dataset.v : null; };

  let sumGiftKey = null; // картинка в сводке пересобирается только при смене подарка
  function renderCreateSummary() {
    const m = state.create.mode, info = MODE_INFO[m];
    const g = state.gifts.find((x) => x.id === state.create.gift && x.status === "held");
    const pct = Number(VL.commission) || 0, stake = chipVal("cr-stakes") || 0;
    const key = g ? `${g.id}|${g.image || ""}` : "";
    if (key !== sumGiftKey) {
      sumGiftKey = key;
      $("cr-sum-gift").innerHTML = g ? giftImg(giftArt(g), "vl-cr-sum-img")
        : `<span class="vl-cr-sum-none">${icon("i-rounds", "ic-lg")}</span>`;
      $("cr-sum-name").textContent = g ? g.name : "Подарок не выбран";
      $("cr-sum-name").title = g ? g.name : "";
    }
    $("cr-sum-mode").innerHTML = icon(info.icon) + info.name;
    const row = (l, v) => `<div class="vl-cr-row"><dt>${l}</dt><dd>${v}</dd></div>`;
    $("cr-sum-rows").innerHTML =
      row(m === "vault" ? "Попытка" : "Мин. ставка", vld(stake))
      + (m === "vault" ? row("Сейф", `<span class="num">${chipVal("cr-vault-sizes") || 0}</span> чисел · без срока`)
        : row(m === "auction" ? "Раскрытие" : "Розыгрыш", `через <span class="num">${timeLbl(chipVal("cr-times") || 0)}</span>`))
      + row("Создание", "бесплатно")
      + row("Комиссия платформы", `<span class="num">${pct}%</span> банка`)
      + `<div class="vl-cr-row vl-cr-row-you"><dt>Ты получишь</dt><dd><span class="num">${100 - pct}%</span> банка</dd></div>`;
    $("cr-sum-ex").innerHTML = `Например, при банке <span class="num">1 000</span> VLD тебе придёт
      <span class="num">${fmt(Math.floor(1000 * (100 - pct) / 100))}</span> VLD сразу после завершения.`;
    $("cr-go").disabled = !g;
  }

  async function createPool() {
    if (!state.create.gift) { toast("Сначала передай подарок боту-хранителю"); return; }
    const body = { mode: state.create.mode, gift_id: state.create.gift, min_stake: chipVal("cr-stakes") };
    if (body.mode === "vault") body.vault_max = chipVal("cr-vault-sizes");
    else body.duration_min = chipVal("cr-times");
    try {
      const p = await api("/api/pools", body);
      haptic("ok"); toast("Раунд создан");
      state.create.gift = null;
      openPool(p.id);
    } catch (e) { toast(e.message); haptic("error"); }
  }

  async function giftDeposit() {
    if (!VL.demo) {
      toast(`Отправь подарок боту @${VL.relay}`);
      try { tg && tg.openTelegramLink(`https://t.me/${VL.relay}`); } catch (e) {}
      return;
    }
    try {
      const r = await api("/api/demo/gift", {});
      toast(`Демо: бот получил «${r.gift.name}»`);
      state.create.gift = r.gift.id;
      if ($("sc-create").classList.contains("on")) loadCreate(); else loadGifts().then(renderInventory);
    } catch (e) { toast(e.message); }
  }

  // ================================================================== ПРОФИЛЬ
  // Разметка — templates/vloody.html (#sc-profile), стили — static/css/vl-screens.css.
  // Десктоп: слева кошелёк + инвентарь (всегда виден, вкладка «Инвентарь» скрыта), справа вкладки
  // Транзакции / Выводы / Каналы, рефералы и оформление. Телефон: одна колонка, все четыре вкладки.
  const LEVELS = [[12, "Легенда"], [7, "Про"], [3, "Игрок"], [1, "Новичок"]];
  const deskMq = window.matchMedia ? window.matchMedia("(min-width: 861px)") : null;
  const isDesk = () => !!(deskMq && deskMq.matches);

  async function loadProfile(full) {
    try { state.profile = await api("/api/profile"); } catch (e) { toast(e.message); return; }
    const p = state.profile;
    setBalance(p.balance);
    $("pf-av").textContent = p.avatar; $("pf-name").textContent = p.name; $("pf-name").title = p.name;
    $("pf-handle").textContent = p.username ? "@" + p.username : "ID " + p.telegram_id;
    $("pf-won").textContent = fmt(p.stats.nft_won); $("pf-part").textContent = fmt(p.stats.participations);
    $("pf-wd").textContent = fmt(p.stats.withdrawn);
    $("streak-count").textContent = fmt(p.streak);
    $("streak-info").textContent = p.streak_today
      ? "Сегодня серия продлена — возвращайся завтра"
      : "Сделай ставку сегодня, чтобы продлить серию";
    $("ref-rate").textContent = (p.referral.rate * 100) + "%";
    $("ref-link").textContent = `https://t.me/${VL.bot}?startapp=${p.referral.code}`;
    $("ref-invited").textContent = fmt(p.referral.invited); $("ref-earned").textContent = fmt(p.referral.earned);
    const tier = (LEVELS.find(([from]) => p.level.level >= from) || LEVELS[3])[1];
    $("lvl-name").textContent = `Уровень ${p.level.level} · ${tier}`;
    $("lvl-xp").textContent = `${fmt(p.level.xp)} / ${fmt(p.level.need)} XP`;
    const pct = Math.max(0, Math.min(100, p.level.xp / (p.level.need || 1) * 100));
    $("lvl-f").style.width = pct + "%";
    $("lvl-bar").setAttribute("aria-valuenow", String(Math.round(pct)));
    syncThemeSeg();
    if (full) {
      if (isDesk() && state.pt === "inv") switchPT("tx");
      else if (state.pt === "tx") loadTx();       // открытая вкладка списков — свежие данные при каждом входе
      else if (state.pt === "wd") loadPayouts();
      await loadGifts(); renderInventory();
    }
  }

  // статус подарка: текст + иконка состояния (+ модификатор цвета)
  const GIFT_STATUS = { held: ["В инвентаре", "i-check", "ok"], locked: ["В раунде", "i-lock", "live"],
    withdraw_requested: ["Ожидает выдачи", "i-clock", "wait"] };
  function statusPill(st) {
    return st ? `<span class="pill vl-st vl-st-${st[2]}">${icon(st[1])}${st[0]}</span>` : "";
  }
  function renderInventory() {
    const box = $("pf-inv-body");
    const dep = `<button type="button" class="vl-btn vl-btn-ghost vl-btn-sm" data-act="gift-deposit">${VL.demo
      ? icon("i-create") + "Получить демо-подарок" : icon("i-send") + "Внести подарок"}</button>`;
    if (!state.gifts.length) {
      box.innerHTML = emptyState("i-rounds", `Инвентарь пуст. Отправь NFT-подарок боту-хранителю @${esc(VL.relay)} — он появится здесь.`, dep);
      return;
    }
    const tiles = state.gifts.map((g) => {
      const held = g.status === "held", fee = +g.transfer_fee || 0;
      // комиссия видна только там, где её правда спишут: свободный подарок и комиссия > 0
      const label = g.status === "withdraw_requested" ? `${icon("i-clock")}<span>Заявка отправлена</span>`
        : `${icon("i-out")}<span>Вывести</span>${held && fee > 0
          ? `<span class="vl-inv-fee"><span class="num">${fmt(fee)}</span> VLD</span>` : ""}`;
      return `<li class="card vl-inv-tile">
        <span class="vl-inv-pic">${giftImg(giftArt(g), "vl-inv-img")}</span>
        <span class="vl-inv-n" title="${esc(g.name)}">${esc(g.name)}</span>
        <span class="vl-inv-meta">${statusPill(GIFT_STATUS[g.status])}<span class="vl-inv-src">${g.source === "win" ? "выигран" : "внесён"}</span></span>
        <button type="button" class="vl-btn vl-btn-sm vl-btn-block vl-btn-ghost vl-inv-wd" data-gift-wd="${g.id}"
          ${held ? `title="${fee ? `Telegram берёт ${fee} VLD за передачу подарка` : "Передача бесплатна"}"` : "disabled"}>${label}</button>
      </li>`;
    }).join("");
    box.innerHTML = `<ul class="vl-inv">${tiles}</ul><div class="vl-pf-more">${dep}</div>`;
    VLFx.stagger(box.querySelector(".vl-inv"));
  }

  const TX_IC = { stake: "i-wheel", vault: "i-lock", bid: "i-eye-off", organizer_payout: "i-wallet", referral: "i-profile",
    transfer_out: "i-send", transfer_in: "i-wallet", payout: "i-out", payout_refund: "i-back", deposit: "i-star",
    gift_fee: "i-rounds", gift_fee_refund: "i-back" };
  const listEmpty = (ic, text, action) => `<div class="vl-pf-listempty">${emptyState(ic, text, action)}</div>`;

  async function loadTx() {
    const box = $("ptc-tx");
    try {
      const { items } = await api("/api/transactions");
      box.innerHTML = items.length ? `<ul class="card vl-txl">${items.map((t) => `
        <li class="vl-tx">
          <span class="vl-tx-ic${t.amount >= 0 ? " is-pos" : ""}">${icon(TX_IC[t.kind] || "i-wallet")}</span>
          <span class="vl-tx-id"><span class="vl-tx-n">${esc(t.title)}</span><span class="vl-tx-s">${ago(t.ts)}</span></span>
          <span class="vl-tx-v num ${t.amount >= 0 ? "is-pos" : "is-neg"}">${t.amount >= 0 ? "+" : "−"}${fmt(Math.abs(t.amount))}</span>
        </li>`).join("")}</ul>` : listEmpty("i-wallet", "Операций пока нет");
      VLFx.stagger(box.querySelector(".vl-txl"));
    } catch (e) { box.innerHTML = listEmpty("i-close", esc(e.message)); }
  }

  const PO_STATUS = { pending: ["В обработке", "i-clock", "wait"], paid: ["Выплачено", "i-check", "ok"],
    rejected: ["Отклонено · возврат", "i-back", "bad"] };
  async function loadPayouts() {
    const box = $("ptc-wd");
    const btn = `<button type="button" class="vl-btn vl-btn-primary vl-btn-sm" data-act="payout-open">${icon("i-out")}Запросить вывод</button>`;
    try {
      const { items } = await api("/api/payouts");
      box.innerHTML = items.length ? `<ul class="card vl-txl">${items.map((r) => `
        <li class="vl-tx">
          <span class="vl-tx-ic">${icon(r.method === "TON" ? "i-ton" : "i-star")}</span>
          <span class="vl-tx-id">
            <span class="vl-tx-n num">${esc(r.destination.length > 20 ? shortAddr(r.destination) : r.destination)}</span>
            <span class="vl-tx-s">${statusPill(PO_STATUS[r.status])} ${ago(r.ts)}</span>
          </span>
          <span class="vl-tx-r"><span class="vl-tx-v num">${r.method === "TON" ? r.net_ton.toFixed(2) + " TON" : fmt(r.net) + " Stars"}</span>
            <span class="vl-tx-s">списано <span class="num">${fmt(r.amount)}</span> VLD</span></span>
        </li>`).join("")}</ul><div class="vl-pf-more">${btn}</div>` : listEmpty("i-out", "Заявок на вывод нет", btn);
      VLFx.stagger(box.querySelector(".vl-txl"));
    } catch (e) { box.innerHTML = listEmpty("i-close", esc(e.message)); }
  }

  function switchPT(t) {
    state.pt = t;
    selectTab($("ptabs"), (b) => b.dataset.pt === t);
    document.querySelectorAll("#sc-profile .vl-pf-panel").forEach((c) => c.classList.toggle("on", c.id === "ptc-" + t));
    if (t === "tx") loadTx();
    if (t === "wd") loadPayouts();
    if (t === "inv") loadGifts().then(renderInventory);
  }
  // на десктопе инвентарь всегда слева: если открыта вкладка «Инвентарь», справа показываем транзакции
  if (deskMq) {
    const onDesk = () => { if (isDesk() && state.pt === "inv" && $("sc-profile").classList.contains("on")) switchPT("tx"); };
    if (deskMq.addEventListener) deskMq.addEventListener("change", onDesk); else if (deskMq.addListener) deskMq.addListener(onDesk);
  }

  // переключатель темы в «Оформлении»: VLTheme.set, состояние кнопок — по событию vl:theme
  function syncThemeSeg() {
    const cur = window.VLTheme ? window.VLTheme.get() : "dark";
    document.querySelectorAll("[data-theme-set]").forEach((b) => {
      const on = b.dataset.themeSet === cur;
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
    });
  }
  document.addEventListener("vl:theme", syncThemeSeg);
  syncThemeSeg();

  // ---------------------------------------------------------------- TON Connect
  let tcUI = null, tonAddr = null;
  const shortAddr = (a) => (a && a.length > 12 ? a.slice(0, 4) + "…" + a.slice(-4) : a || "");

  function initTon() {
    try {
      if (!window.TON_CONNECT_UI) return;
      tcUI = new window.TON_CONNECT_UI.TonConnectUI({ manifestUrl: location.origin + "/tonconnect-manifest.json" });
      tcUI.onStatusChange((wallet) => {
        tonAddr = null;
        if (wallet && wallet.account) {
          const raw = wallet.account.address;
          try { tonAddr = window.TON_CONNECT_UI.toUserFriendlyAddress(raw); } catch (e) { tonAddr = raw; }
        }
        renderTon();
      });
    } catch (e) { tcUI = null; }
  }
  function renderTon() {
    $("tb-ton-text").textContent = tonAddr ? shortAddr(tonAddr) : "Подключить";
    $("pf-ton").textContent = tonAddr ? "TON-кошелёк: " + shortAddr(tonAddr) : "TON-кошелёк не подключён";
  }
  function tonToggle() {
    if (!tcUI) { toast("Подключение кошелька недоступно. Пополнить TON можно и без него — через «Пополнить»"); return; }
    if (tonAddr) tcUI.disconnect().then(() => toast("Кошелёк отключён")).catch(() => {});
    else tcUI.openModal();
  }
  // текстовый комментарий TON-перевода: ячейка [opcode 0 (32 бита) + utf-8], упакованная в BOC
  function commentPayload(text) {
    const t = new TextEncoder().encode(text), data = new Uint8Array(4 + t.length);
    data.set(t, 4);
    const cell = [0x00, data.length * 2, ...data];
    const boc = [0xb5, 0xee, 0x9c, 0x72, 0x01, 0x01, 0x01, 0x01, 0x00, cell.length, 0x00, ...cell];
    return btoa(String.fromCharCode(...boc));
  }

  // ---------------------------------------------------------------- пополнение
  let tuMode = "stars", tonDep = null, tonPoll = 0;

  function topupOpen() {
    const R = state.profile.rates;
    $("tu-note").textContent = VL.demo ? "Демо-режим: VLD зачисляются сразу и ничего не стоят" : "Оплата через Telegram Stars";
    $("tu-rate").textContent = `Курс: 100 Stars → ${Math.floor(100 * R.stars_to_vld)} VLD · включает комиссию платформы`;
    $("tu-amount").value = "";
    document.querySelectorAll("#tu-presets .vl-dlg-preset").forEach((c) => {
      c.classList.remove("is-on"); c.setAttribute("aria-pressed", "false");
      c.querySelector(".vl-dlg-preset-vld").textContent = Math.floor(+c.dataset.v * R.stars_to_vld) + " VLD";
    });
    $("tt-note").textContent = `Минимум ${R.ton_min} TON · 1 TON = ${R.vld_per_ton} VLD`;
    $("tt-slider").min = R.ton_min; $("tt-slider").value = Math.max(1, R.ton_min); $("tt-amount").value = "";
    tonReset(); starsCalc(); tonCalc();
    topupMode("stars");
    openOv("topup-modal");
  }
  function topupMode(m) {
    tuMode = m;
    document.querySelectorAll("#tu-tabs .vl-seg-btn").forEach((b) => {
      b.classList.toggle("on", b.dataset.tum === m); b.setAttribute("aria-pressed", String(b.dataset.tum === m));
    });
    $("tu-stars").classList.toggle("hid", m !== "stars");
    $("tu-ton").classList.toggle("hid", m !== "ton");
    if (m === "ton" && !state.profile.rates.ton_enabled) toast("Пополнение в TON пока не настроено");
  }
  function starsCalc() {
    const v = parseInt($("tu-amount").value, 10) || 0;
    $("tu-eq-stars").textContent = fmt(v);
    $("tu-eq-vld").textContent = fmt(Math.floor(v * state.profile.rates.stars_to_vld));
  }
  async function topupConfirm() {
    const amt = parseInt($("tu-amount").value, 10);
    if (!amt || amt < 1) { toast("Выбери сумму"); return; }
    try {
      const r = await api("/api/wallet/topup", { amount: amt });
      if (r.invoice_link) {
        closeOv("topup-modal");
        if (tg && tg.openInvoice) tg.openInvoice(r.invoice_link, (st) => { if (st === "paid") { toast(`Оплата прошла · +${fmt(r.will_credit)} VLD`); setTimeout(() => loadProfile(false), 1500); } });
        else window.open(r.invoice_link, "_blank");
        return;
      }
      setBalance(r.balance); closeOv("topup-modal"); haptic("ok");
      toast(`Баланс пополнен на ${fmt(r.credited)} VLD`);
    } catch (e) { toast(e.message); }
  }

  // ---- TON
  const tonAmount = () => parseFloat($("tt-amount").value) || parseFloat($("tt-slider").value) || 0;
  function tonCalc() {
    const v = tonAmount();
    $("tt-val").textContent = v; $("tt-eq-ton").textContent = v;
    $("tt-eq-vld").textContent = fmt(Math.floor(v * state.profile.rates.vld_per_ton));
  }
  function tonReset() {
    clearInterval(tonPoll); tonPoll = 0; tonDep = null;
    $("tt-form").classList.remove("hid"); $("tt-wait").classList.add("hid");
  }
  async function tonPay() {
    const R = state.profile.rates, amount = tonAmount();
    if (amount < R.ton_min) { toast(`Минимум ${R.ton_min} TON`); return; }
    try { tonDep = await api("/api/wallet/ton/intent", { amount_ton: amount }); }
    catch (e) { toast(e.message); return; }
    $("tt-form").classList.add("hid"); $("tt-wait").classList.remove("hid");
    $("tt-w-amount").textContent = `${amount} TON → ${fmt(tonDep.will_credit)} VLD`;
    $("tt-w-addr").textContent = tonDep.address; $("tt-w-comment").textContent = tonDep.comment;
    $("tt-status").textContent = tonDep.demo ? "Демо: настоящий перевод не нужен" : "Ждём перевод в блокчейне…";
    $("tt-demo").classList.toggle("hid", !tonDep.demo);
    document.querySelector('[data-act="ton-open"]').classList.toggle("hid", !!tonDep.demo);
    if (tonDep.demo) return;
    tonOpenWallet();
    let tries = 0;
    clearInterval(tonPoll);
    tonPoll = setInterval(async () => {
      if (!tonDep || ++tries > 60) { clearInterval(tonPoll); if (tonDep) $("tt-status").textContent = "Перевод пока не найден. Он зачислится автоматически, когда дойдёт."; return; }
      try {
        const r = await api("/api/wallet/ton/check", { deposit_id: tonDep.deposit_id });
        if (r.status === "credited") tonCredited(r);
      } catch (e) {}
    }, 5000);
  }
  function tonCredited(r) {
    setBalance(r.balance); haptic("ok");
    toast(`TON получен · +${fmt(r.credited)} VLD`);
    tonReset(); closeOv("topup-modal");
  }
  async function tonOpenWallet() {
    if (!tonDep || tonDep.demo) return;
    if (tcUI && tonAddr) {
      try {
        await tcUI.sendTransaction({
          validUntil: Math.floor(Date.now() / 1000) + 600,
          messages: [{ address: tonDep.address, amount: tonDep.amount_nano, payload: commentPayload(tonDep.comment) }],
        });
        $("tt-status").textContent = "Перевод отправлен, ждём подтверждения сети…";
        return;
      } catch (e) { /* отменил или кошелёк не ответил — ниже запасной путь */ }
    }
    const q = `?amount=${tonDep.amount_nano}&text=${encodeURIComponent(tonDep.comment)}`;
    try {
      if (tg && tg.openLink) tg.openLink(`https://app.tonkeeper.com/transfer/${tonDep.address}${q}`);
      else window.location.href = tonDep.link;
    } catch (e) {}
  }
  async function tonDemoPay() {
    if (!tonDep) return;
    try { tonCredited(await api("/api/wallet/ton/demo-pay", { deposit_id: tonDep.deposit_id, amount_nano: tonDep.amount_nano })); }
    catch (e) { toast(e.message); }
  }

  // предупреждение в окне (role="alert"): показываем блок, затем меняем текст — и только если он новый,
  // иначе экранный диктор повторял бы его на каждое нажатие клавиши
  function setAlert(w, msg) {
    w.classList.toggle("on", !!msg);
    if (w.textContent !== msg) w.textContent = msg;
  }

  // ---------------------------------------------------------------- перевод
  let lookupTimer = 0, recipientOk = false;
  function transferOpen() {
    $("tr-recipient").value = ""; $("tr-amount").value = ""; recipientOk = false;
    $("tr-recip-status").innerHTML = "&nbsp;"; $("tr-recip-status").className = "vl-dlg-recip";
    const L = state.profile.limits;
    $("tr-fee-label").textContent = `Комиссия перевода (${L.transfer_fee * 100}%)`;
    transferCalc(); openOv("transfer-modal");
  }
  function transferCalc() {
    const L = state.profile.limits, amt = parseInt($("tr-amount").value, 10) || 0;
    const fee = Math.floor(amt * L.transfer_fee);
    $("tr-calc-gross").textContent = fmt(amt); $("tr-calc-fee").textContent = "−" + fmt(fee);
    $("tr-calc-net").textContent = fmt(amt - fee);
    const w = $("tr-warn");
    let msg = "";
    if (amt && amt < L.transfer_min) msg = `Минимальная сумма перевода — ${L.transfer_min} VLD`;
    else if (amt > state.profile.balance) msg = "Недостаточно VLD на балансе";
    setAlert(w, msg);
    $("tr-submit-btn").disabled = !(recipientOk && amt >= L.transfer_min && amt <= state.profile.balance);
  }
  function transferLookup() {
    clearTimeout(lookupTimer); recipientOk = false; transferCalc();
    const st = $("tr-recip-status"), id = $("tr-recipient").value.trim();
    st.className = "vl-dlg-recip";
    if (!/^\d{3,}$/.test(id)) { st.innerHTML = "&nbsp;"; return; }
    st.textContent = "Ищем…";
    lookupTimer = setTimeout(async () => {
      try {
        const u = await api("/api/users/lookup?telegram_id=" + id);
        if ($("tr-recipient").value.trim() !== id) return;
        st.textContent = "✓ " + u.name; st.classList.add("ok"); recipientOk = true;
      } catch (e) { st.textContent = e.message; st.classList.add("err"); }
      transferCalc();
    }, 350);
  }
  async function transferConfirm() {
    try {
      const r = await api("/api/transfer", { to_telegram_id: $("tr-recipient").value.trim(), amount: parseInt($("tr-amount").value, 10) });
      setBalance(r.balance); closeOv("transfer-modal"); haptic("ok");
      toast(`Переведено: получатель зачислит ${fmt(r.received)} VLD`);
    } catch (e) { toast(e.message); haptic("error"); }
  }

  // ---------------------------------------------------------------- вывод
  let poMethod = "TON";
  const TON_RE = /^(?:[EUk0]Q[A-Za-z0-9_-]{46}|-?\d:[0-9a-fA-F]{64})$/;

  function payoutOpen() {
    $("po-amount").value = "";
    payoutMode(poMethod);
    openOv("payout-modal");
  }
  function payoutMode(m) {
    poMethod = m;
    const L = state.profile.limits, ton = m === "TON";
    document.querySelectorAll("#po-tabs .vl-seg-btn").forEach((b) => {
      b.classList.toggle("on", b.dataset.pom === m); b.setAttribute("aria-pressed", String(b.dataset.pom === m));
    });
    $("po-dest-label").textContent = ton ? "Адрес TON-кошелька (EQ… / UQ…)" : "Telegram @username для получения";
    $("po-destination").placeholder = ton ? "UQAbc123…" : "@username";
    $("po-destination").value = ton ? (tonAddr || "") : (state.profile.username ? "@" + state.profile.username : "");
    $("po-fee-label").textContent = `Комиссия вывода (${(ton ? L.payout_fee_ton : L.payout_fee) * 100}%)`;
    payoutCalc();
  }
  function payoutCalc() {
    const L = state.profile.limits, R = state.profile.rates, ton = poMethod === "TON";
    const amt = parseInt($("po-amount").value, 10) || 0;
    const fee = Math.floor(amt * (ton ? L.payout_fee_ton : L.payout_fee)), net = amt - fee;
    $("po-calc-fee").textContent = "−" + fmt(fee) + " VLD";
    $("po-calc-net").textContent = ton ? (net / R.vld_per_ton).toFixed(2) + " TON" : fmt(net) + " Stars";
    const dest = $("po-destination").value.trim();
    const destOk = ton ? TON_RE.test(dest) : dest.length >= 3;
    let msg = "";
    if (amt && amt < L.payout_min) msg = `Минимальный вывод — ${L.payout_min} VLD`;
    else if (amt > state.profile.balance) msg = "Недостаточно VLD на балансе";
    else if (dest && !destOk) msg = "Проверь адрес TON-кошелька";
    setAlert($("po-warn"), msg);
    $("po-submit-btn").disabled = !(amt >= L.payout_min && amt <= state.profile.balance && destOk);
  }
  async function payoutConfirm() {
    try {
      const r = await api("/api/payout", { amount: parseInt($("po-amount").value, 10), destination: $("po-destination").value.trim(), method: poMethod });
      setBalance(r.balance); closeOv("payout-modal"); haptic("ok");
      toast("Заявка на вывод создана");
      switchPT("wd");
    } catch (e) { toast(e.message); haptic("error"); }
  }

  async function giftWithdraw(id) {
    try {
      const r = await api(`/api/inventory/gifts/${id}/withdraw`, {});
      if (r.balance !== undefined) setBalance(r.balance);
      toast(r.fee ? `Заявка отправлена · за передачу списано ${r.fee} VLD` : "Заявка на выдачу подарка отправлена");
      await loadGifts(); renderInventory();
    } catch (e) { toast(e.message); }
  }

  function copyText(text, msg) {
    const done = () => toast(msg);
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done); else done();
  }
  function sharePool(id) {
    copyText(`https://t.me/${VL.bot}?startapp=pool_${id}`, "Ссылка на раунд скопирована!");
  }

  // ================================================================== таймеры
  function tickTimers() {
    const now = nowTs();
    document.querySelectorAll("[data-ends]").forEach((el) => {
      const ends = +el.dataset.ends;
      if (ends) el.textContent = hms(ends - now);
    });
    const p = state.pool;
    if (p && p.status === "live" && p.ends_ts) {
      const left = p.ends_ts - now;
      if (p.mode === "wheel") { $("det-timer").textContent = hms(left); $("spin-cd").textContent = hms(left); }
      if (left <= 0 && !state.spinning) refreshPool();
    }
  }
  setInterval(tickTimers, 1000);

  // ================================================================== события
  const ACTIONS = {
    "back": () => tab(state.back || "home"),
    "topup": topupOpen, "topup-confirm": topupConfirm,
    "ton-connect": tonToggle, "ton-pay": tonPay, "ton-open": tonOpenWallet, "ton-demo-pay": tonDemoPay,
    "stake-open": stakeOpen, "stake-confirm": stakeConfirm,
    "vault-try": tryVault, "auction-bid": placeBid, "pool-cancel": cancelPool,
    "pool-create": createPool, "gift-deposit": giftDeposit,
    "transfer-open": transferOpen, "transfer-confirm": transferConfirm,
    "payout-open": payoutOpen, "payout-confirm": payoutConfirm,
    "fair-info": () => openOv("fair-modal"),
    "theme": () => { if (window.VLTheme) window.VLTheme.toggle(); },
    "ref-copy": () => copyText($("ref-link").textContent, "Скопировано!"),
    "ref-share": () => {
      const url = "https://t.me/share/url?url=" + encodeURIComponent($("ref-link").textContent)
        + "&text=" + encodeURIComponent("Честные розыгрыши NFT-подарков в Vloody");
      try { tg ? tg.openTelegramLink(url) : window.open(url, "_blank"); } catch (e) { window.open(url, "_blank"); }
    },
  };

  document.addEventListener("click", (e) => {
    const rp = e.target.closest(".rp"); if (rp) ripple(e, rp);
    if (e.target.classList.contains("vl-overlay")) {
      if (ovDownEl === e.target) closeOv(e.target.id); // closeOv сбрасывает и TON-ожидание у пополнения
      return;
    }
    const t = (sel) => e.target.closest(sel);
    let el;
    if ((el = t("[data-ov-close]"))) return closeOv(el.closest(".vl-overlay").id);
    if ((el = t("[data-act]"))) {
      const fn = ACTIONS[el.dataset.act];
      if (fn) { ovTrigger = el; try { fn(); } finally { ovTrigger = null; } }
      return;
    }
    if ((el = t("[data-tab]"))) return tab(el.dataset.tab);
    // share first: on the home cards the share button sits inside the clickable card ([data-pool])
    if ((el = t("[data-share]"))) return sharePool(+el.dataset.share);
    if ((el = t("[data-pool]"))) {
      // the whole card is clickable, but not when the click ends a text selection inside it (copying a name)
      if (!e.target.closest("button") && window.getSelection && String(window.getSelection()).trim()) return;
      return openPool(+el.dataset.pool);
    }
    if ((el = t("[data-flt]"))) {
      state.filter = el.dataset.flt;
      document.querySelectorAll("#filters [data-flt]").forEach((b) => {
        b.classList.toggle("is-on", b === el); b.setAttribute("aria-pressed", String(b === el));
      });
      return renderPools();
    }
    if ((el = t("[data-wmode]"))) {
      state.wheelMode = el.dataset.wmode;
      document.querySelectorAll("[data-wmode]").forEach((b) => {
        b.classList.toggle("on", b === el); b.setAttribute("aria-pressed", String(b === el));
      });
      return drawWheel(state.wheelRot);
    }
    if ((el = t("[data-lb]"))) return switchLB(el.dataset.lb);
    if ((el = t("[data-cmode]"))) { state.create.mode = el.dataset.cmode; return renderCreateMode(); }
    if ((el = t("[data-gift]"))) { state.create.gift = +el.dataset.gift; renderCreateGifts(); return renderCreateSummary(); }
    if ((el = t("[data-gift-wd]"))) return giftWithdraw(+el.dataset.giftWd);
    if ((el = t("[data-pt]"))) return switchPT(el.dataset.pt);
    if ((el = t("[data-num]"))) { $("vt-num").value = el.dataset.num; return vaultPick(); }
    if ((el = t(".vl-cr-chips .vl-chip"))) {
      el.parentElement.querySelectorAll(".vl-chip").forEach((c) => {
        c.classList.toggle("is-on", c === el); c.setAttribute("aria-pressed", String(c === el));
      });
      return renderCreateSummary();
    }
    if ((el = t("[data-theme-set]"))) { if (window.VLTheme) window.VLTheme.set(el.dataset.themeSet); return syncThemeSeg(); }
    if ((el = t("[data-tum]"))) return topupMode(el.dataset.tum);
    if ((el = t("[data-pom]"))) return payoutMode(el.dataset.pom);
    if ((el = t("[data-copy]"))) return copyText($(el.dataset.copy).textContent, "Скопировано!");
    if ((el = t("#tu-presets .vl-dlg-preset"))) {
      document.querySelectorAll("#tu-presets .vl-dlg-preset").forEach((c) => {
        c.classList.toggle("is-on", c === el); c.setAttribute("aria-pressed", String(c === el));
      });
      $("tu-amount").value = el.dataset.v; starsCalc();
    }
  });
  document.addEventListener("pointerdown", (e) => { ovDownEl = e.target; });
  document.addEventListener("input", (e) => { if (e.target.classList && e.target.classList.contains("vl-range")) rangeFill(e.target); });

  tabKeys($("ptabs"), (b) => switchPT(b.dataset.pt));
  tabKeys($("lb-tabs"), (b) => switchLB(b.dataset.lb));

  $("sm-slider").addEventListener("input", (e) => { $("sm-input").value = ""; stakeSync(+e.target.value); });
  $("sm-input").addEventListener("input", (e) => stakeSync(parseInt(e.target.value, 10) || 0));
  $("vt-num").addEventListener("input", vaultPick);
  $("vt-num").addEventListener("keydown", (e) => { if (e.key === "Enter") tryVault(); });
  $("auc-amt").addEventListener("keydown", (e) => { if (e.key === "Enter") placeBid(); });
  $("tr-recipient").addEventListener("input", transferLookup);
  $("tr-amount").addEventListener("input", transferCalc);
  $("po-amount").addEventListener("input", payoutCalc);
  $("po-destination").addEventListener("input", payoutCalc);
  $("tu-amount").addEventListener("input", () => {
    document.querySelectorAll("#tu-presets .vl-dlg-preset").forEach((c) => {
      c.classList.remove("is-on"); c.setAttribute("aria-pressed", "false");
    });
    starsCalc();
  });
  $("tt-slider").addEventListener("input", () => { $("tt-amount").value = ""; tonCalc(); });
  $("tt-amount").addEventListener("input", tonCalc);

  // ================================================================== старт
  async function init() {
    initTon();
    try {
      await loadProfile(false);
      const start = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param)
        || new URLSearchParams(location.search).get("startapp") || "";
      if (start && !start.startsWith("pool_")) api("/api/referral/bind", { code: start }).catch(() => {});
      await loadPools();
      if (start.startsWith("pool_")) openPool(parseInt(start.slice(5), 10));
    } catch (e) { toast("Не удалось загрузить данные"); }
    $("app").classList.add("show");
    setTimeout(hideSplash, 1500);
  }
  // заставка гаснет (opacity, vloody.css) и уходит из DOM: по transitionend или по таймеру, если события не будет
  function hideSplash() {
    const sp = $("splash"); if (!sp) return;
    const drop = () => { clearTimeout(sp._t); if (sp.parentNode) sp.remove(); };
    sp.addEventListener("transitionend", drop, { once: true });
    sp._t = setTimeout(drop, 600);
    sp.classList.add("out");
  }
  init();
})();

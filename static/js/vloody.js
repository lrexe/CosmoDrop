/* Vloody — клиент PvP-розыгрышей. Все исходы и балансы считает сервер. */
(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
  const VL = window.VL || {};
  const $ = (id) => document.getElementById(id);
  const STAR = '<span class="star-i"></span>';
  const PAL = ["#3b0764", "#1e1b4b", "#0c4a6e", "#064e3b", "#1c1917", "#4a044e", "#0f172a", "#1a2e05", "#450a0a", "#0a0a2e"];
  const MODE_BADGE = { wheel: "🎡 Колесо", vault: "🔒 Сейф", auction: "🕶 Аукцион" };
  const MODE_BADGE_CLS = { wheel: "badge-w", vault: "badge-g", auction: "badge-auc" };
  const MODE_SCREEN = { wheel: "wheel", vault: "vault", auction: "auction" };
  const STAKE_CHIPS = { wheel: [5, 25, 50, 100], vault: [5, 10, 25, 50], auction: [20, 50, 100, 250] };
  const MODE_HINT = {
    wheel: "Шанс каждого участника равен его доле в банке. Колесо крутится по таймеру.",
    vault: "Участники платят за попытку угадать секретное число. Угадавший забирает подарок сразу.",
    auction: "Ставки скрыты и не возвращаются. Подарок получает тот, кто накопил больше всех.",
  };
  const TX_ICON = { stake: "🎟", vault: "🔒", bid: "🕶", organizer_payout: "💰", referral: "🤝",
    transfer_out: "↗", transfer_in: "↙", payout: "⬇️", payout_refund: "↩", deposit: "⭐",
    gift_fee: "🎁", gift_fee_refund: "↩" };

  const state = {
    profile: null, pools: { live: [], finished: [] }, filter: "all",
    pool: null, back: "home", wheelMode: "av", wheelRot: 0, spinning: false,
    create: { mode: "wheel", gift: null }, gifts: [], lb: "month", offset: 0,
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
    $("tb-stars-val").textContent = fmt(v);
    $("sb-stars-val").textContent = fmt(v);
    $("pf-bal").textContent = fmt(v);
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
  function show(screen) {
    document.querySelectorAll(".scr").forEach((s) => s.classList.remove("on"));
    $("sc-" + screen).classList.add("on");
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
  function openOv(id) { $(id).classList.add("on"); }
  function closeOv(id) { $(id).classList.remove("on"); }

  // ================================================================== ГЛАВНАЯ
  async function loadPools() {
    try {
      state.pools = await api("/api/pools");
      const all = state.pools.live.concat(state.pools.finished);
      if (all.length) state.offset = all[0].now_ts - Math.floor(Date.now() / 1000);
      renderPools();
    } catch (e) { $("pools-list").innerHTML = `<div class="empty-note">${esc(e.message)}</div>`; }
  }

  function stat(lbl, val, cls) {
    return `<div class="gwc-stat"><span class="gwc-lbl">${lbl}</span><span class="gwc-val ${cls || ""}">${val}</span></div>`;
  }

  function poolCard(p) {
    const live = p.status === "live";
    let stats = "", bar = 0;
    if (!live) {
      stats = stat("Победитель", p.winner ? esc(p.winner.name) + " 🏆" : "—", "em")
        + stat("Банк", fmt(p.bank) + " " + STAR) + stat("Статус", "Завершён", "em");
      bar = 100;
    } else if (p.mode === "wheel") {
      stats = stat("Банк", fmt(p.bank) + " " + STAR) + stat("Участников", p.participants + " чел.")
        + stat("Мин. ставка", p.min_stake + " " + STAR)
        + stat("Осталось", `<span data-ends="${p.ends_ts}">—</span>`);
      bar = timeBar(p);
    } else if (p.mode === "vault") {
      stats = stat("Банк", fmt(p.bank) + " " + STAR) + stat("Ставка", p.min_stake + " " + STAR)
        + stat("Занято чисел", `${p.taken}/${p.vault_max}`) + stat("Окончание", "Бессрочно", "rose");
      bar = p.taken / p.vault_max * 100;
    } else {
      stats = stat("Твоя ставка", p.my_total ? fmt(p.my_total) + " " + STAR : "Скрыто")
        + stat("Мин. ставка", p.min_stake + " " + STAR)
        + stat("До раскрытия", `<span data-ends="${p.ends_ts}">—</span>`);
      bar = timeBar(p);
    }
    const hot = live && p.bank >= 100 ? `<span class="badge badge-hot">🔥 ТОП</span>` : "";
    const mine = p.is_organizer ? `<span class="badge badge-g">Твой раунд</span>` : "";
    return `
      <div class="gwc ${live ? "" : "done"}">
        <div class="gwc-top"><span class="badge ${MODE_BADGE_CLS[p.mode]}">${MODE_BADGE[p.mode]}</span>${hot}${mine}</div>
        <div class="gwc-body">
          <div class="gwc-art ${esc(p.art)}">${esc(p.emoji)}</div>
          <div class="gwc-meta"><div class="gwc-name">${esc(p.title)}</div>${stats}</div>
        </div>
        <div class="gwc-bar"><div class="gwc-bar-fill" style="width:${Math.min(100, bar).toFixed(0)}%"></div></div>
        <div class="gwc-foot">
          <button class="btn-enter rp" data-pool="${p.id}">${live ? "Перейти" : "Результат"}</button>
          <div class="btn-shr rp" data-share="${p.id}">↗</div>
        </div>
      </div>`;
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
    else if (f === "soon") list = list.filter((p) => p.ends_ts).sort((a, b) => a.ends_ts - b.ends_ts);
    else if (MODE_BADGE[f]) list = list.filter((p) => p.mode === f);
    $("pools-list").innerHTML = list.length ? list.map(poolCard).join("")
      : `<div class="empty-note">Активных розыгрышей пока нет.<br>Стань первым — нажми «Создать».</div>`;
    $("pools-finished").innerHTML = state.pools.finished.length ? state.pools.finished.map(poolCard).join("")
      : `<div class="empty-note">Пока пусто</div>`;
    tickTimers();
  }

  // ================================================================== РАУНД
  let watchTimer = 0;
  function stopPoolWatch() { clearInterval(watchTimer); watchTimer = 0; state.pool = null; }

  async function openPool(id) {
    let p;
    try { p = await api("/api/pools/" + id); } catch (e) { toast(e.message); return; }
    stopPoolWatch();
    state.pool = p; state.spinning = false; state.wheelRot = 0;
    state.offset = p.now_ts - Math.floor(Date.now() / 1000);
    markNav(state.back || "home"); // раунд открыт из этого раздела, «назад» вернёт в него
    show(MODE_SCREEN[p.mode]);
    renderPool(false);
    watchTimer = setInterval(refreshPool, 4000);
  }

  async function refreshPool() {
    const cur = state.pool;
    if (!cur || state.spinning) return;
    if (cur.status !== "live") { clearInterval(watchTimer); return; }
    try {
      const p = await api("/api/pools/" + cur.id);
      if (!state.pool || state.pool.id !== p.id) return;
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
    else renderAuction();
    tickTimers();
  }

  function fairHtml(p) {
    const f = p.fair || {};
    let h = `<b>Проверка честности</b>Хеш, опубликованный при создании:<span class="mono">${esc(f.seed_hash)}</span>`;
    if (f.seed) {
      h += `Раскрытый seed:<span class="mono">${esc(f.seed)}</span>`;
      const r = f.result || {};
      if (p.mode === "wheel" && r.total) h += `Билет <b>${fmt(r.ticket)}</b> из <b>${fmt(r.total)}</b> · ставок: ${r.entries}`;
      if (p.mode === "vault") h += `Секретное число: <b>${esc(p.secret)}</b> · sha256("${esc(p.secret)}:seed") совпадает с хешем`;
    } else h += `Seed раскроется после завершения — по нему можно пересчитать результат.`;
    return h;
  }

  // ---------------------------------------------------------------- колесо
  function drawWheel(rot) {
    const p = state.pool, c = $("wcanvas"), ctx = c.getContext("2d");
    const cx = 139, cy = 139, r = 133; ctx.clearRect(0, 0, 278, 278);
    const stakes = (p && p.stakes) || [];
    if (!stakes.length) {
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = "#131316"; ctx.fill();
      ctx.fillStyle = "#ffffff33"; ctx.font = "bold 13px Inter,sans-serif"; ctx.textAlign = "center";
      ctx.textBaseline = "middle"; ctx.fillText("Ожидание ставок", cx, cy); return;
    }
    const total = stakes.reduce((s, x) => s + x.amount, 0);
    const winKey = state.spinning ? null : p.winner_key;
    let cur = -Math.PI / 2;
    stakes.forEach((s, i) => {
      const arc = s.amount / total * Math.PI * 2, sa = rot + cur, ea = sa + arc, isW = winKey === s.key && p.status === "finished";
      const g = ctx.createRadialGradient(cx, cy, r * 0.1, cx, cy, r);
      if (isW) { g.addColorStop(0, "rgba(245,158,11,.5)"); g.addColorStop(1, "rgba(245,158,11,.8)"); }
      else { g.addColorStop(0, PAL[i % PAL.length] + "ee"); g.addColorStop(1, PAL[i % PAL.length]); }
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, r, sa, ea); ctx.closePath();
      ctx.fillStyle = g; ctx.fill(); ctx.strokeStyle = "#08080f"; ctx.lineWidth = 2; ctx.stroke();
      const ma = sa + arc / 2, dist = r * 0.63, ax = cx + Math.cos(ma) * dist, ay = cy + Math.sin(ma) * dist;
      if (arc > 0.2) {
        ctx.save(); ctx.translate(ax, ay); ctx.textAlign = "center"; ctx.textBaseline = "middle";
        if (state.wheelMode === "av") { ctx.font = (arc > 0.5 ? "20px" : "13px") + " serif"; ctx.fillText(s.avatar, 0, 0); }
        else {
          ctx.fillStyle = "rgba(255,255,255,.92)"; ctx.font = `bold ${arc > 0.5 ? 13 : 9}px Inter,sans-serif`;
          ctx.shadowColor = "rgba(0,0,0,.9)"; ctx.shadowBlur = 3;
          ctx.fillText(Math.round(s.amount / total * 100) + "%", 0, 0);
        }
        ctx.restore();
      }
      cur += arc;
    });
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.strokeStyle = "rgba(184,0,31,.4)"; ctx.lineWidth = 3; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, r * 0.17, 0, Math.PI * 2); ctx.fillStyle = "#08080f"; ctx.fill();
  }

  function winnerAngle(p) {
    const total = p.stakes.reduce((s, x) => s + x.amount, 0);
    let before = 0;
    for (const s of p.stakes) {
      if (s.key === p.winner_key) return -((before + s.amount / 2) / total) * Math.PI * 2;
      before += s.amount;
    }
    return 0;
  }

  function spinToWinner() {
    const p = state.pool;
    state.spinning = true; $("w-hub").textContent = "⏳";
    const from = state.wheelRot, target = winnerAngle(p) + Math.PI * 2 * 9;
    const dur = 6000, st = performance.now(), ease = (t) => 1 - Math.pow(1 - t, 4);
    (function fr(now) {
      const t = Math.min((now - st) / dur, 1);
      state.wheelRot = from + (target - from) * ease(t);
      drawWheel(state.wheelRot);
      if (t < 1 && state.pool === p) return requestAnimationFrame(fr);
      state.spinning = false;
      if (state.pool === p) { renderWheel(false); haptic(p.winner && p.winner.is_me ? "ok" : "medium"); }
    })(st);
  }

  function renderWheel(animate) {
    const p = state.pool, live = p.status === "live";
    $("det-hero").className = "det-hero " + p.art;
    $("det-em").textContent = p.emoji; $("w-hub").textContent = p.emoji;
    $("det-name").textContent = p.title; $("det-org").textContent = p.organizer;
    $("det-status").textContent = live ? "Live" : (p.status === "finished" ? "Завершён" : "Отменён");
    $("det-min").textContent = p.min_stake;
    $("det-part").textContent = p.participants + " чел.";
    $("det-chance").textContent = (p.my_chance || 0) + "%";
    $("det-bank").textContent = fmt(p.bank);
    $("det-pf").style.width = Math.min(100, timeBar(p)) + "%";
    $("det-timer").dataset.ends = ""; $("det-timer").textContent = live ? hms(p.ends_ts - nowTs()) : "—";
    $("det-buy").classList.toggle("hid", !live || p.is_organizer);
    $("det-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.stakes.length));
    $("wheel-cd").classList.toggle("hid", !live);
    $("wheel-fair").innerHTML = fairHtml(p);

    $("stakes-lbl").textContent = `📋 Ставки (${p.stakes.length} участн.)`;
    $("stakes-list").innerHTML = p.stakes.length ? p.stakes.map((s, i) => `
      <div class="stake-row ${!state.spinning && p.winner_key === s.key && !live ? "win" : ""}">
        <div class="s-oct" style="background:${PAL[i % PAL.length]}55">${esc(s.avatar)}</div>
        <div class="s-name">${esc(s.name)}${s.is_me ? " · ты" : ""}</div>
        <div class="s-val">${STAR} ${fmt(s.amount)}</div>
      </div>`).join("") : `<div class="empty-note">Ставок пока нет</div>`;

    if (animate && p.status === "finished" && p.stakes.length) { $("det-winner").classList.remove("on"); return spinToWinner(); }
    if (p.status === "finished") state.wheelRot = winnerAngle(p);
    drawWheel(state.wheelRot);
    const w = $("det-winner");
    if (p.status === "finished" && p.winner) {
      $("det-wt").textContent = p.winner.is_me ? "Ты победил! 🎉" : "Победитель: " + p.winner.name;
      $("det-ws").textContent = p.winner.is_me ? "Подарок уже в твоём инвентаре" : "Подарок передан победителю";
      w.classList.add("on");
    } else w.classList.remove("on");
    if (p.status === "cancelled") toast("Раунд отменён — ставок не было");
  }

  // ---------------------------------------------------------------- сейф
  function renderVault() {
    const p = state.pool, live = p.status === "live";
    $("vt-img").className = "ghc-thumb " + p.art; $("vt-img").textContent = p.emoji;
    $("vt-name").textContent = p.title;
    $("vt-org").textContent = "Организатор " + p.organizer;
    $("vt-bank").textContent = fmt(p.bank);
    $("vt-hint").innerHTML = `Число от <b>1</b> до <b>${p.vault_max}</b> · ставка <b>${p.min_stake}</b> ${STAR} за попытку<br>Занято чисел: <b>${p.taken}</b>`;
    $("vt-num").max = p.vault_max;
    $("vt-form").classList.toggle("hid", !live || p.is_organizer);
    $("vt-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.numbers.length));
    $("vault-safe").classList.toggle("open", p.status === "finished");
    $("vt-g-taken").textContent = p.numbers.length;
    $("vault-fair").innerHTML = fairHtml(p);

    const taken = new Map(p.numbers.map((n) => [n.number, n]));
    let cells = "";
    for (let i = 1; i <= p.vault_max; i++) {
      const t = taken.get(i);
      cells += t
        ? `<div class="vg-cell taken ${t.is_me ? "mine" : ""} ${t.win ? "win" : ""}">${i}<span class="vg-who">${esc(t.name)}</span></div>`
        : `<div class="vg-cell" data-num="${i}">${i}</div>`;
    }
    $("vt-grid").innerHTML = cells;
    $("vt-feed").innerHTML = p.numbers.slice().reverse().slice(0, 12).map((n) => `
      <div class="vf-row ${n.win ? "win" : "miss"}">
        <span class="vf-n">${n.number}</span><span>${esc(n.name)}${n.is_me ? " · ты" : ""}</span>
        <span class="vf-badge">${n.win ? "Вскрыл!" : "Мимо"}</span>
      </div>`).join("");

    const w = $("vt-winner");
    if (p.status === "finished" && p.winner) {
      $("vt-wt").textContent = p.winner.is_me ? "Ты вскрыл сейф! 🎉" : "Сейф вскрыл " + p.winner.name;
      $("vt-ws").textContent = `Секретное число — ${p.secret}. Подарок передан победителю.`;
      w.classList.add("on");
    } else w.classList.remove("on");
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
      if (r.hit) { haptic("ok"); toast("🎉 Сейф вскрыт! Подарок твой"); }
      else {
        haptic("error"); safe.classList.add("shaking");
        setTimeout(() => safe.classList.remove("shaking"), 500);
        toast(`Число ${num} — мимо`);
      }
      applyPool(r.pool, false);
    } catch (e) { toast(e.message); haptic("error"); }
    vaultBusy = false;
  }

  // ---------------------------------------------------------------- аукцион
  function renderAuction() {
    const p = state.pool, live = p.status === "live";
    $("auc-img").className = "ghc-thumb " + p.art; $("auc-img").textContent = p.emoji;
    $("auc-name").textContent = p.title;
    $("auc-org").textContent = "Организатор " + p.organizer + " · победитель забирает подарок";
    $("auc-mine-val").innerHTML = p.my_total ? `${fmt(p.my_total)} ${STAR}` : "— (ещё не ставил)";
    $("auc-amt").placeholder = p.min_stake + "+"; $("auc-amt").min = p.min_stake;
    $("auc-form").classList.toggle("hid", !live || p.is_organizer);
    $("auc-cancel").classList.toggle("hid", !(live && p.is_organizer && !p.my_total && p.bank === 0));
    $("auc-blackout").classList.toggle("hid", !live);
    $("auc-cd-card").classList.toggle("hid", !live);
    $("auc-cd").dataset.ends = live ? p.ends_ts : "";
    $("auction-fair").innerHTML = live ? "" : `<b>Раскрытие</b>Все накопленные ставки открыты. Побеждает наибольшая; при равенстве — кто достиг её раньше.`;
    const res = $("auc-result");
    if (p.status === "finished" && p.bids) {
      res.classList.remove("hid");
      res.innerHTML = `<b>${p.winner && p.winner.is_me ? "Ты победил! 🎉" : "Победитель: " + esc(p.winner ? p.winner.name : "—")}</b> · банк ${fmt(p.bank)} ${STAR}`
        + p.bids.map((b, i) => `<div class="rr ${i === 0 ? "top" : ""}"><span>${i + 1}. ${esc(b.name)}${b.is_me ? " · ты" : ""}</span><span>${fmt(b.amount)}</span></div>`).join("");
    } else if (p.status === "cancelled") { res.classList.remove("hid"); res.textContent = "Раунд отменён — ставок не было."; }
    else res.classList.add("hid");
  }

  async function placeBid() {
    const p = state.pool; if (!p) return;
    const amt = parseInt($("auc-amt").value, 10);
    if (!amt || amt < p.min_stake) { toast(`Минимум ${p.min_stake} VLD`); return; }
    try {
      const r = await api(`/api/pools/${p.id}/bid`, { amount: amt });
      setBalance(r.balance); $("auc-amt").value = "";
      haptic("ok"); toast("Ставка доставлена 🕶");
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
      haptic("ok"); toast("Ставка принята ✅");
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

  // ================================================================== ИВЕНТЫ
  async function loadEvents() {
    try {
      const [lb, win] = await Promise.all([api("/api/leaderboard/" + state.lb), api("/api/winners")]);
      const label = { day: "День", week: "Неделю", month: "Месяц", all: "всё время" }[state.lb];
      const me = lb.me;
      $("lb-banner").innerHTML = me.rank
        ? `Твой ранг за ${label}: <b>#${me.rank}</b> · оборот <b>${fmt(me.volume)}</b> ${STAR}` +
          (me.to_top100 ? ` · до Топ-100 ещё <b>${fmt(me.to_top100)}</b> ${STAR}` : "")
        : `Ты ещё не участвовал за ${label}. Сделай ставку — и попадёшь в рейтинг.`;
      const top = lb.entries.slice(0, 3), order = [1, 0, 2], medal = ["🥇", "🥈", "🥉"];
      $("lb-podium").innerHTML = top.length ? order.filter((i) => top[i]).map((i) => `
        <div class="pod ${i === 0 ? "pod-1" : ""}">
          <span class="pod-medal">${medal[i]}</span>
          <div class="pod-av tier-${i === 0 ? 1 : 2}">${esc(top[i].avatar)}</div>
          <div class="pod-name">${esc(top[i].name)}</div>
          <div class="pod-val">${fmt(top[i].volume)} ${STAR}</div>
        </div>`).join("") : "";
      $("lb-list").innerHTML = lb.entries.slice(3).map((e) => `
        <div class="lb-row ${e.is_me ? "me" : ""}">
          <div class="lb-rank">${e.rank}</div><div class="lb-av">${esc(e.avatar)}</div>
          <div class="grow"><div class="lb-name">${esc(e.name)}</div><div class="lb-sub">${e.wins} побед</div></div>
          <div class="lb-val">${fmt(e.volume)}</div>
        </div>`).join("") || (top.length ? "" : `<div class="empty-note">За этот период ставок не было</div>`);
      $("winners-list").innerHTML = win.items.length ? win.items.map((w) => `
        <div class="tx rp" data-pool="${w.pool_id}">
          <div class="tx-ic">${esc(w.emoji)}</div>
          <div class="grow"><div class="tx-n">${esc(w.title)}</div><div class="tx-s">${esc(w.winner)} · ${ago(w.ts)}</div></div>
          <div class="tx-r"><div class="tx-v pos">Выиграл</div><div class="tx-d">банк ${fmt(w.bank)}</div></div>
        </div>`).join("") : `<div class="empty-note">Победителей пока нет</div>`;
    } catch (e) { toast(e.message); }
  }

  // ================================================================== СОЗДАНИЕ
  async function loadGifts() {
    try { state.gifts = (await api("/api/inventory/gifts")).gifts; } catch (e) { state.gifts = []; }
    return state.gifts;
  }

  async function loadCreate() {
    await loadGifts();
    const held = state.gifts.filter((g) => g.status === "held");
    if (!held.find((g) => g.id === state.create.gift)) state.create.gift = held.length ? held[0].id : null;
    $("cr-gifts").innerHTML = held.map((g) => `
      <div class="mgi ${g.id === state.create.gift ? "sel" : ""}" data-gift="${g.id}">
        <span class="mgi-em">${esc(g.emoji)}</span><div class="mgi-n">${esc(g.name)}</div>
      </div>`).join("");
    renderCreateMode();
  }

  function renderCreateMode() {
    const m = state.create.mode;
    document.querySelectorAll("#cr-modes .mtab").forEach((b) => b.classList.toggle("on", b.dataset.cmode === m));
    $("cr-mode-hint").textContent = MODE_HINT[m];
    $("cr-stake-lbl").textContent = m === "vault" ? "Ставка за попытку" : "Мин. ставка";
    $("cr-stakes").innerHTML = STAKE_CHIPS[m].map((v, i) =>
      `<div class="chip rp ${i === 0 ? "on" : ""}" data-v="${v}">${v} ${STAR}</div>`).join("");
    $("cr-vault-box").classList.toggle("hid", m !== "vault");
    $("cr-time-box").classList.toggle("hid", m === "vault");
  }
  const chipVal = (id) => { const c = document.querySelector(`#${id} .chip.on`); return c ? +c.dataset.v : null; };

  async function createPool() {
    if (!state.create.gift) { toast("Сначала передай подарок боту-хранителю"); return; }
    const body = { mode: state.create.mode, gift_id: state.create.gift, min_stake: chipVal("cr-stakes") };
    if (body.mode === "vault") body.vault_max = chipVal("cr-vault-sizes");
    else body.duration_min = chipVal("cr-times");
    try {
      const p = await api("/api/pools", body);
      haptic("ok"); toast("Раунд создан ✨");
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
      if ($("sc-create").classList.contains("on")) loadCreate(); else renderInventory();
    } catch (e) { toast(e.message); }
  }

  // ================================================================== ПРОФИЛЬ
  async function loadProfile(full) {
    try { state.profile = await api("/api/profile"); } catch (e) { toast(e.message); return; }
    const p = state.profile;
    setBalance(p.balance);
    $("pf-av").textContent = p.avatar; $("pf-name").textContent = p.name;
    $("pf-handle").textContent = p.username ? "@" + p.username : "ID " + p.telegram_id;
    $("pf-won").textContent = p.stats.nft_won; $("pf-part").textContent = p.stats.participations;
    $("pf-wd").textContent = fmt(p.stats.withdrawn);
    $("streak-count").textContent = p.streak;
    $("streak-info").textContent = p.streak_today
      ? "Сегодня стрик продлён — возвращайся завтра"
      : "Сделай ставку сегодня, чтобы продлить стрик";
    $("ref-rate").textContent = (p.referral.rate * 100) + "%";
    $("ref-link").textContent = `https://t.me/${VL.bot}?startapp=${p.referral.code}`;
    $("ref-invited").textContent = p.referral.invited; $("ref-earned").textContent = fmt(p.referral.earned);
    $("lvl-name").textContent = "Уровень " + p.level.level;
    $("lvl-xp").textContent = `${fmt(p.level.xp)} / ${fmt(p.level.need)} XP`;
    $("lvl-f").style.width = Math.min(100, p.level.xp / p.level.need * 100) + "%";
    let cur = null;
    document.querySelectorAll("#lvl-cards .lc").forEach((c) => { c.classList.remove("on"); if (p.level.level >= +c.dataset.from) cur = c; });
    if (cur) cur.classList.add("on");
    if (full) { await loadGifts(); renderInventory(); }
  }

  const GIFT_STATUS = { held: "В инвентаре", locked: "В активном раунде", withdraw_requested: "Ожидает выдачи" };
  function renderInventory() {
    const box = $("ptc-inv");
    const tiles = state.gifts.map((g) => `
      <div class="gift-tile ${esc(g.art)}">
        ${g.source === "win" ? `<span class="gt-win">ВЫИГРАН</span>` : ""}
        <span class="gt-em">${esc(g.emoji)}</span>
        <div class="gt-n">${esc(g.name)}</div>
        <div class="gt-s">${GIFT_STATUS[g.status] || ""}</div>
        <button class="gt-btn" data-gift-wd="${g.id}" ${g.status === "held" ? "" : "disabled"}>
          ${g.status === "withdraw_requested" ? "Заявка отправлена"
            : (g.transfer_fee ? `Вывести · ${g.transfer_fee} VLD` : "Вывести в Telegram")}</button>
      </div>`).join("");
    box.innerHTML = (tiles ? `<div class="inv-grid">${tiles}</div>` : `<div class="inv-empty">Инвентарь пуст</div>`)
      + `<button class="btn btn-dim rp" data-act="gift-deposit">📦 Внести подарок</button>`;
  }

  async function loadTx() {
    const box = $("ptc-tx");
    try {
      const { items } = await api("/api/transactions");
      box.innerHTML = items.length ? items.map((t) => `
        <div class="tx">
          <div class="tx-ic">${TX_ICON[t.kind] || "•"}</div>
          <div class="grow"><div class="tx-n">${esc(t.title)}</div><div class="tx-s">${ago(t.ts)}</div></div>
          <div class="tx-r"><div class="tx-v ${t.amount >= 0 ? "pos" : "neg"}">${t.amount >= 0 ? "+" : "−"}${fmt(Math.abs(t.amount))}</div></div>
        </div>`).join("") : `<div class="inv-empty">Операций пока нет</div>`;
    } catch (e) { box.innerHTML = `<div class="inv-empty">${esc(e.message)}</div>`; }
  }

  const PO_STATUS = { pending: "В обработке", paid: "Выплачено", rejected: "Отклонено · возврат" };
  async function loadPayouts() {
    const box = $("ptc-wd");
    try {
      const { items } = await api("/api/payouts");
      box.innerHTML = (items.length ? items.map((r) => `
        <div class="tx">
          <div class="tx-ic">⬇️</div>
          <div class="grow"><div class="tx-n">${esc(r.destination.length > 20 ? shortAddr(r.destination) : r.destination)}</div><div class="tx-s">${PO_STATUS[r.status]} · ${ago(r.ts)}</div></div>
          <div class="tx-r"><div class="tx-v">${r.method === "TON" ? r.net_ton.toFixed(2) + " TON" : fmt(r.net) + " ⭐"}</div><div class="tx-d">списано ${fmt(r.amount)} VLD</div></div>
        </div>`).join("") : `<div class="inv-empty">Заявок на вывод нет</div>`)
        + `<button class="btn btn-v rp" data-act="payout-open">Запросить вывод</button>`;
    } catch (e) { box.innerHTML = `<div class="inv-empty">${esc(e.message)}</div>`; }
  }

  function switchPT(t) {
    document.querySelectorAll("#ptabs .ptab").forEach((b) => b.classList.toggle("on", b.dataset.pt === t));
    document.querySelectorAll(".ptc").forEach((c) => c.classList.toggle("on", c.id === "ptc-" + t));
    if (t === "tx") loadTx();
    if (t === "wd") loadPayouts();
    if (t === "inv") loadGifts().then(renderInventory);
  }

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
    $("tu-rate").textContent = `Курс: 100 ⭐ → ${Math.floor(100 * R.stars_to_vld)} VLD · включает комиссию платформы`;
    $("tu-amount").value = "";
    document.querySelectorAll("#tu-presets .exc-card").forEach((c) => {
      c.classList.remove("sel");
      c.querySelector(".exc-card-vld").textContent = Math.floor(+c.dataset.v * R.stars_to_vld) + " VLD";
    });
    $("tt-note").textContent = `Минимум ${R.ton_min} TON · 1 TON = ${R.vld_per_ton} VLD`;
    $("tt-slider").min = R.ton_min; $("tt-slider").value = Math.max(1, R.ton_min); $("tt-amount").value = "";
    tonReset(); starsCalc(); tonCalc();
    topupMode("stars");
    openOv("topup-modal");
  }
  function topupMode(m) {
    tuMode = m;
    document.querySelectorAll("#tu-tabs .m-tab").forEach((b) => b.classList.toggle("on", b.dataset.tum === m));
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

  // ---------------------------------------------------------------- перевод
  let lookupTimer = 0, recipientOk = false;
  function transferOpen() {
    $("tr-recipient").value = ""; $("tr-amount").value = ""; recipientOk = false;
    $("tr-recip-status").innerHTML = "&nbsp;"; $("tr-recip-status").className = "recip-status";
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
    w.textContent = msg; w.classList.toggle("on", !!msg);
    $("tr-submit-btn").disabled = !(recipientOk && amt >= L.transfer_min && amt <= state.profile.balance);
  }
  function transferLookup() {
    clearTimeout(lookupTimer); recipientOk = false; transferCalc();
    const st = $("tr-recip-status"), id = $("tr-recipient").value.trim();
    st.className = "recip-status";
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
    document.querySelectorAll("#po-tabs .m-tab").forEach((b) => b.classList.toggle("on", b.dataset.pom === m));
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
    const w = $("po-warn"); w.textContent = msg; w.classList.toggle("on", !!msg);
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
    if (e.target.classList.contains("overlay")) {
      e.target.classList.remove("on");
      if (e.target.id === "topup-modal") tonReset();
      return;
    }
    const t = (sel) => e.target.closest(sel);
    let el;
    if ((el = t("[data-act]"))) { const fn = ACTIONS[el.dataset.act]; if (fn) fn(); return; }
    if ((el = t("[data-tab]"))) return tab(el.dataset.tab);
    if ((el = t("[data-pool]"))) return openPool(+el.dataset.pool);
    if ((el = t("[data-share]"))) return sharePool(+el.dataset.share);
    if ((el = t("[data-flt]"))) {
      state.filter = el.dataset.flt;
      document.querySelectorAll("#filters .ft").forEach((b) => b.classList.toggle("on", b === el));
      return renderPools();
    }
    if ((el = t("[data-wmode]"))) {
      state.wheelMode = el.dataset.wmode;
      document.querySelectorAll("[data-wmode]").forEach((b) => b.classList.toggle("on", b === el));
      return drawWheel(state.wheelRot);
    }
    if ((el = t("[data-lb]"))) {
      state.lb = el.dataset.lb;
      document.querySelectorAll("#lb-tabs .mtab").forEach((b) => b.classList.toggle("on", b === el));
      return loadEvents();
    }
    if ((el = t("[data-cmode]"))) { state.create.mode = el.dataset.cmode; return renderCreateMode(); }
    if ((el = t("[data-gift]"))) { state.create.gift = +el.dataset.gift; return loadCreate(); }
    if ((el = t("[data-gift-wd]"))) return giftWithdraw(+el.dataset.giftWd);
    if ((el = t("[data-pt]"))) return switchPT(el.dataset.pt);
    if ((el = t("[data-num]"))) { $("vt-num").value = el.dataset.num; return; }
    if ((el = t(".chips .chip"))) {
      el.parentElement.querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
      return el.classList.add("on");
    }
    if ((el = t("[data-tum]"))) return topupMode(el.dataset.tum);
    if ((el = t("[data-pom]"))) return payoutMode(el.dataset.pom);
    if ((el = t("[data-copy]"))) return copyText($(el.dataset.copy).textContent, "Скопировано!");
    if ((el = t("#tu-presets .exc-card"))) {
      document.querySelectorAll("#tu-presets .exc-card").forEach((c) => c.classList.toggle("sel", c === el));
      $("tu-amount").value = el.dataset.v; starsCalc();
    }
  });

  $("sm-slider").addEventListener("input", (e) => { $("sm-input").value = ""; stakeSync(+e.target.value); });
  $("sm-input").addEventListener("input", (e) => stakeSync(parseInt(e.target.value, 10) || 0));
  $("tr-recipient").addEventListener("input", transferLookup);
  $("tr-amount").addEventListener("input", transferCalc);
  $("po-amount").addEventListener("input", payoutCalc);
  $("po-destination").addEventListener("input", payoutCalc);
  $("tu-amount").addEventListener("input", () => {
    document.querySelectorAll("#tu-presets .exc-card").forEach((c) => c.classList.remove("sel")); starsCalc();
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
    setTimeout(() => $("splash").classList.add("out"), 1500);
  }
  init();
})();

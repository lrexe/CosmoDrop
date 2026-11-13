/* ===========================================================================
   CosmoDrop — общий клиентский слой: API, состояние, UI-утилиты
   =========================================================================== */
(function () {
  "use strict";

  const RARITY = {
    common:    { label: "обычный",     color: "#9ca3af" },
    rare:      { label: "редкий",      color: "#3b82f6" },
    epic:      { label: "эпический",   color: "#a855f7" },
    legendary: { label: "легендарный", color: "#f59e0b" },
  };

  // ---- Telegram WebApp / демо-пользователь --------------------------------
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }

  function resolveIdentity() {
    const u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    if (u && u.id) {
      return {
        telegram_id: u.id,
        username: u.username || null,
        first_name: u.first_name || u.username || "Космонавт",
        photo_url: u.photo_url || null,
      };
    }
    return {
      telegram_id: window.DEMO_TELEGRAM_ID,
      username: "cosmo_demo",
      first_name: "Космонавт",
      photo_url: null,
    };
  }

  const identity = resolveIdentity();

  // ---- API ----------------------------------------------------------------
  async function api(path, { method = "GET", body = null } = {}) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      const msg = (data && data.error) || `Ошибка ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  const withId = (extra = {}) => Object.assign({ telegram_id: identity.telegram_id }, extra);

  const API = {
    syncUser: () => api("/api/user/sync", { method: "POST", body: identity }),
    me: () => api(`/api/me?telegram_id=${identity.telegram_id}`),
    stats: () => api("/api/stats"),
    cases: () => api("/api/cases"),
    caseDetail: (id) => api(`/api/cases/${id}`),
    openCase: (caseId) => api("/api/open-case", { method: "POST", body: withId({ case_id: caseId }) }),
    rating: () => api(`/api/rating?telegram_id=${identity.telegram_id}`),
    history: (scope = "me", limit = 20) =>
      api(`/api/history?scope=${scope}&limit=${limit}&telegram_id=${identity.telegram_id}`),
    inventory: () => api(`/api/inventory?telegram_id=${identity.telegram_id}`),
    sell: (itemId) => api("/api/inventory/sell", { method: "POST", body: withId({ item_id: itemId }) }),
    sellAll: () => api("/api/inventory/sell", { method: "POST", body: withId({ all: true }) }),
    dailyStatus: () => api(`/api/daily-bonus/status?telegram_id=${identity.telegram_id}`),
    claimDaily: () => api("/api/daily-bonus", { method: "POST", body: withId() }),
    addBalance: (amount) => api("/api/balance/add", { method: "POST", body: withId({ amount }) }),
    // --- фичи ---
    upgrade: (itemId, multiplier) => api("/api/upgrade", { method: "POST", body: withId({ item_id: itemId, multiplier }) }),
    contract: (itemIds) => api("/api/contract", { method: "POST", body: withId({ item_ids: itemIds }) }),
    wheelStatus: () => api(`/api/wheel/status?telegram_id=${identity.telegram_id}`),
    wheelSpin: () => api("/api/wheel/spin", { method: "POST", body: withId() }),
    quests: () => api(`/api/quests?telegram_id=${identity.telegram_id}`),
    claimQuest: (key) => api("/api/quests/claim", { method: "POST", body: withId({ key }) }),
    achievements: () => api(`/api/achievements?telegram_id=${identity.telegram_id}`),
    claimAchievement: (key) => api("/api/achievements/claim", { method: "POST", body: withId({ key }) }),
    redeemPromo: (code) => api("/api/promo/redeem", { method: "POST", body: withId({ code }) }),
    referral: () => api(`/api/referral?telegram_id=${identity.telegram_id}`),
    applyReferral: (code) => api("/api/referral/apply", { method: "POST", body: withId({ code }) }),
  };

  // ---- состояние пользователя --------------------------------------------
  let currentUser = null;
  const listeners = [];
  function onUser(fn) { listeners.push(fn); if (currentUser) fn(currentUser); }
  function setUser(u) {
    currentUser = u;
    renderHeader(u);
    listeners.forEach((fn) => { try { fn(u); } catch (e) {} });
  }
  function patchBalance(newBalance) {
    if (currentUser) { currentUser.stars_balance = newBalance; renderHeader(currentUser); }
  }

  // ---- форматирование ------------------------------------------------------
  function fmt(n) {
    n = Number(n) || 0;
    return n.toLocaleString("ru-RU");
  }
  function haptic(type = "light") {
    try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(type); } catch (e) {}
  }

  // ---- иконка подарка: <img> с авто-фолбэком на эмодзи, если файла нет ----
  function gift(obj, extraClass = "") {
    const emoji = (obj && obj.emoji) || "🎁";
    const img = obj && obj.image;
    if (img) {
      const name = ((obj && obj.name) || "").replace(/"/g, "");
      return `<img class="gift-img ${extraClass}" src="${img}" alt="${name}" loading="lazy" data-emoji="${emoji}" onerror="CD.imgFallback(this)">`;
    }
    return `<span class="gift-emoji ${extraClass}">${emoji}</span>`;
  }
  function imgFallback(el) {
    const emoji = el.getAttribute("data-emoji") || "🎁";
    const span = document.createElement("span");
    span.className = ("gift-emoji " + el.className.replace("gift-img", "")).trim();
    span.textContent = emoji;
    el.replaceWith(span);
  }

  // ---- header --------------------------------------------------------------
  function renderHeader(u) {
    if (!u) return;
    document.querySelectorAll("[data-avatar]").forEach((el) => (el.textContent = u.avatar || "🧑‍🚀"));
    document.querySelectorAll("[data-username]").forEach((el) => (el.textContent = u.first_name || "Космонавт"));
    document.querySelectorAll("[data-earned]").forEach((el) => (el.textContent = `⭐ ${fmt(u.total_earned)} заработано`));
    const lvl = (u.level_info && u.level_info.level) || u.level || 1;
    document.querySelectorAll("[data-level]").forEach((el) => (el.textContent = `Lv ${lvl}`));
    document.querySelectorAll("[data-balance]").forEach((el) => {
      const prev = Number(el.dataset.v || 0);
      countUp(el, prev, u.stars_balance, (v) => `⭐ ${fmt(v)}`);
      el.dataset.v = u.stars_balance;
    });
  }

  // ---- count-up ------------------------------------------------------------
  function countUp(el, from, to, fmtFn) {
    from = Number(from) || 0; to = Number(to) || 0;
    fmtFn = fmtFn || ((v) => fmt(v));
    if (from === to) { el.textContent = fmtFn(to); return; }
    const dur = 600, start = performance.now(), diff = to - from;
    function step(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmtFn(Math.round(from + diff * eased));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // ---- тосты ---------------------------------------------------------------
  function toast(message, type = "info", ms = 2600) {
    let root = document.getElementById("toast-root");
    if (!root) { root = document.createElement("div"); root.id = "toast-root"; document.body.appendChild(root); }
    const ic = { ok: "✅", err: "⚠️", info: "✨" }[type] || "✨";
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<span class="t-ic">${ic}</span><span>${message}</span>`;
    root.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 300);
    }, ms);
  }

  // ---- конфетти ------------------------------------------------------------
  function confetti(amount = 80, colors) {
    colors = colors || ["#8b5cf6", "#3b82f6", "#ec4899", "#fbbf24", "#34d399"];
    for (let i = 0; i < amount; i++) {
      const c = document.createElement("div");
      c.className = "confetti";
      c.style.left = Math.random() * 100 + "vw";
      c.style.background = colors[(Math.random() * colors.length) | 0];
      c.style.animationDuration = 2.4 + Math.random() * 1.6 + "s";
      c.style.animationDelay = Math.random() * 0.3 + "s";
      c.style.transform = `rotate(${Math.random() * 360}deg)`;
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 4200);
    }
  }

  // ---- звук (WebAudio, синтез — без внешних файлов) -----------------------
  const sound = (function () {
    let ctx = null;
    let muted = localStorage.getItem("cd_muted") === "1";
    function ac() {
      if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
      if (ctx && ctx.state === "suspended") ctx.resume();
      return ctx;
    }
    function blip(freq, dur, type = "sine", vol = 0.12, when = 0) {
      const c = ac(); if (!c) return;
      const t = c.currentTime + when;
      const o = c.createOscillator(), g = c.createGain();
      o.type = type; o.frequency.setValueAtTime(freq, t);
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(vol, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g); g.connect(c.destination);
      o.start(t); o.stop(t + dur + 0.02);
    }
    const play = (name) => {
      if (muted) return;
      switch (name) {
        case "click": blip(420, 0.06, "triangle", 0.08); break;
        case "tick": blip(900, 0.03, "square", 0.04); break;
        case "coin": blip(880, 0.08, "triangle", 0.1); blip(1320, 0.1, "triangle", 0.08, 0.05); break;
        case "win": [523, 659, 784].forEach((f, i) => blip(f, 0.18, "triangle", 0.11, i * 0.09)); break;
        case "jackpot": [523, 659, 784, 1046, 1318].forEach((f, i) => blip(f, 0.22, "sawtooth", 0.1, i * 0.08)); break;
        case "lose": blip(300, 0.25, "sawtooth", 0.09); blip(180, 0.35, "sawtooth", 0.09, 0.12); break;
        case "level": [659, 880, 1174].forEach((f, i) => blip(f, 0.2, "triangle", 0.12, i * 0.1)); break;
        default: blip(500, 0.05);
      }
    };
    return {
      play,
      get muted() { return muted; },
      toggle() { muted = !muted; localStorage.setItem("cd_muted", muted ? "1" : "0"); if (!muted) play("click"); return muted; },
    };
  })();

  // ---- звёздное поле (canvas) ---------------------------------------------
  function initStarfield() {
    const host = document.getElementById("starfield");
    if (!host) return;
    const canvas = document.createElement("canvas");
    host.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    let w, h, stars, raf;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      w = host.clientWidth; h = host.clientHeight;
      canvas.width = w * DPR; canvas.height = h * DPR;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      const count = Math.min(140, Math.floor((w * h) / 9000));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        r: Math.random() * 1.4 + 0.3,
        a: Math.random(), s: Math.random() * 0.02 + 0.004,
        vy: Math.random() * 0.12 + 0.02,
        hue: Math.random() < 0.5 ? "255,255,255" : "190,170,255",
      }));
    }
    function draw() {
      ctx.clearRect(0, 0, w, h);
      for (const st of stars) {
        st.a += st.s; if (st.a > 1 || st.a < 0) st.s *= -1;
        st.y += st.vy; if (st.y > h) { st.y = 0; st.x = Math.random() * w; }
        ctx.beginPath();
        ctx.fillStyle = `rgba(${st.hue},${Math.max(0, st.a).toFixed(2)})`;
        ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    }
    resize(); draw();
    window.addEventListener("resize", () => { cancelAnimationFrame(raf); resize(); draw(); });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) cancelAnimationFrame(raf); else draw();
    });
  }

  // ---- модалка пополнения --------------------------------------------------
  function topUpModal() {
    let modal = document.getElementById("topup-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "topup-modal";
      modal.className = "modal";
      modal.innerHTML = `
        <div class="modal-card" style="max-width:380px;position:relative">
          <button class="modal-close" data-close>×</button>
          <h3>⭐ Пополнить баланс</h3>
          <p class="m-sub">Демо-пополнение звёздами для теста кейсов</p>
          <div class="stats-row" style="grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px">
            ${[100, 500, 1000].map((v) => `<button class="btn ghost topup-preset" data-amt="${v}">+${v}</button>`).join("")}
          </div>
          <input id="topup-input" type="number" min="1" placeholder="Своя сумма…"
            style="width:100%;padding:12px;border-radius:12px;border:1px solid var(--stroke-2);
                   background:var(--surface);color:var(--text);font-size:14px;font-family:inherit;margin-bottom:12px"/>
          <button class="btn gold block" id="topup-confirm">Пополнить</button>
        </div>`;
      document.body.appendChild(modal);
      modal.querySelectorAll("[data-close]").forEach((b) =>
        b.addEventListener("click", (e) => { e.stopPropagation(); close(); }));
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      modal.querySelectorAll(".topup-preset").forEach((b) =>
        b.addEventListener("click", () => (modal.querySelector("#topup-input").value = b.dataset.amt)));
      modal.querySelector("#topup-confirm").addEventListener("click", async () => {
        const amt = parseInt(modal.querySelector("#topup-input").value, 10);
        if (!amt || amt <= 0) { toast("Введите сумму", "err"); return; }
        try {
          const r = await API.addBalance(amt);
          patchBalance(r.new_balance);
          toast(`Баланс пополнен на ⭐ ${fmt(r.added)}`, "ok");
          haptic("medium");
          close();
          window.dispatchEvent(new CustomEvent("cd:balance", { detail: r.new_balance }));
        } catch (e) { toast(e.message, "err"); }
      });
    }
    function close() { modal.classList.add("hidden"); }
    modal.classList.remove("hidden");
    modal.querySelector("#topup-input").value = "";
  }

  // ---- init ----------------------------------------------------------------
  async function init() {
    initStarfield();
    document.querySelectorAll("[data-topup]").forEach((el) =>
      el.addEventListener("click", topUpModal));
    try {
      const u = await API.syncUser();
      setUser(u);
      maybeApplyReferral();
    } catch (e) {
      console.error("sync failed", e);
      toast("Не удалось загрузить профиль", "err");
    }
  }

  async function maybeApplyReferral() {
    const url = new URL(window.location.href);
    let code = url.searchParams.get("ref");
    const startParam = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (!code && startParam) code = startParam;
    if (!code) return;
    try {
      const r = await API.applyReferral(code);
      if (r.applied) { patchBalance(r.new_balance); toast(`Бонус за реферала: +⭐ ${fmt(r.bonus)}`, "ok"); }
    } catch (e) { /* уже применён / свой код — молча */ }
  }

  // экспорт
  window.CD = {
    API, RARITY, identity,
    onUser, setUser, patchBalance, refreshUser: async () => { try { setUser(await API.me()); } catch (e) {} },
    toast, confetti, countUp, fmt, haptic, topUpModal, sound, gift, imgFallback,
    get user() { return currentUser; },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

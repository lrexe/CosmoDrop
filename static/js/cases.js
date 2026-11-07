/* Кейсы: сетка → модалка с drop-table → рулетка → результат */
(function () {
  "use strict";
  const CD = window.CD, API = CD.API, fmt = CD.fmt, RARITY = CD.RARITY;

  const grid = document.getElementById("cases-grid");
  const modal = document.getElementById("caseModal");
  const body = document.getElementById("modalBody");
  let spinning = false;
  let casesCache = [];

  const rarLabel = (r) => (RARITY[r] || {}).label || r;
  const rarColorVar = (r) => ({ common: "muted", rare: "blue", epic: "violet", legendary: "gold" }[r] || "muted");

  // ---- сетка ----
  function load() {
    API.cases().then((cases) => {
      casesCache = cases;
      if (!cases.length) { grid.innerHTML = `<div class="empty"><span class="e-emoji">📦</span>Кейсов пока нет</div>`; return; }
      grid.innerHTML = cases.map(card).join("");
      grid.querySelectorAll("[data-case]").forEach((el) =>
        el.addEventListener("click", () => openDetail(+el.dataset.case)));
    }).catch((e) => { grid.innerHTML = `<div class="empty">Ошибка загрузки</div>`; });
  }

  function card(c) {
    const r = c.rarity || "common";
    return `
      <div class="case-card rarity-ring-${r}" data-case="${c.id}">
        <span class="rarity-badge r-${r}">${rarLabel(r)}</span>
        <div class="c-emoji">${c.emoji || "🎁"}</div>
        <div class="c-name">${c.name}</div>
        <div class="c-range">⭐ ${fmt(c.prize_min)}–${fmt(c.prize_max)}</div>
        <div class="c-price">⭐ ${fmt(c.price)}</div>
      </div>`;
  }

  // ---- детальная модалка с drop-table ----
  async function openDetail(id) {
    showModal();
    body.innerHTML = `<button class="modal-close" data-close>×</button>
      <div class="center" style="padding:30px"><div class="skeleton" style="height:120px"></div></div>`;
    bindClose();
    let c;
    try { c = await API.caseDetail(id); } catch (e) { CD.toast(e.message, "err"); closeModal(); return; }

    const bal = CD.user ? CD.user.stars_balance : 0;
    const canAfford = bal >= c.price;
    body.innerHTML = `
      <button class="modal-close" data-close>×</button>
      <div class="center" style="margin-bottom:6px">
        <div style="font-size:60px;filter:drop-shadow(0 8px 20px rgba(0,0,0,.4))">${c.emoji || "🎁"}</div>
        <h3 style="margin-top:6px">${c.name}</h3>
        <p class="m-sub">${c.description || ""}</p>
      </div>
      <div class="section-head" style="margin:4px 2px"><h3 style="font-size:13px;color:var(--muted)">Содержимое и шансы</h3></div>
      <div class="drop-list" style="max-height:260px;overflow:auto;margin-bottom:14px">
        ${c.prizes.map(dropRow).join("")}
      </div>
      <button class="btn block ${canAfford ? "gold" : ""}" id="openBtn" ${canAfford ? "" : "disabled"}>
        ${canAfford ? `🎲 Открыть за ⭐ ${fmt(c.price)}` : `Нужно ещё ⭐ ${fmt(c.price - bal)}`}
      </button>`;
    bindClose();
    const btn = body.querySelector("#openBtn");
    if (canAfford) btn.addEventListener("click", () => spin(c));
    else btn.addEventListener("click", () => { CD.topUpModal(); });
  }

  function dropRow(p) {
    return `
      <div class="drop-row" style="--rc:var(--r-${p.rarity})">
        <span class="d-emoji">${p.emoji}</span>
        <span class="d-name">${p.name}</span>
        <span class="d-stars">⭐ ${fmt(p.stars)}</span>
        <span class="d-chance">${p.chance}%</span>
      </div>`;
  }

  // ---- рулетка ----
  async function spin(c) {
    if (spinning) return;
    spinning = true;

    let data;
    try { data = await API.openCase(c.id); }
    catch (e) { CD.toast(e.message, "err"); spinning = false; return; }

    CD.haptic("light");
    body.innerHTML = `
      <h3 class="center">${c.emoji || "🎁"} ${c.name}</h3>
      <p class="m-sub center">Крутим рулетку…</p>
      <div class="roller-wrap">
        <div class="roller-pointer"></div>
        <div class="roller" id="roller"></div>
      </div>`;

    const roller = body.querySelector("#roller");
    roller.innerHTML = data.roller.map((p) => `
      <div class="roller-item" style="--rc:var(--r-${p.rarity})">
        <span class="ri-emoji">${p.emoji}</span>
        <span class="ri-stars">⭐ ${fmt(p.stars)}</span>
      </div>`).join("");

    // геометрия
    requestAnimationFrame(() => {
      const first = roller.children[0];
      const style = getComputedStyle(roller);
      const gap = parseFloat(style.gap) || 10;
      const itemW = first.getBoundingClientRect().width + gap;
      const wrap = roller.parentElement;
      const center = wrap.clientWidth / 2;
      const jitter = (Math.random() - 0.5) * (itemW - gap) * 0.6;
      const winIndex = data.center_index;
      const offset = winIndex * itemW + (itemW - gap) / 2 - center + jitter;

      roller.style.transition = "none";
      roller.style.transform = "translateX(0px)";

      requestAnimationFrame(() => {
        roller.style.transition = "transform 6s cubic-bezier(0.15, 0.85, 0.2, 1)";
        roller.style.transform = `translateX(-${offset}px)`;
      });

      let ticks = 0;
      const ti = setInterval(() => { CD.sound.play("tick"); if (++ticks > 22) clearInterval(ti); }, 240);
      setTimeout(() => { clearInterval(ti); showResult(c, data); }, 6200);
    });
  }

  function showResult(c, data) {
    const w = data.win;
    CD.patchBalance(data.new_balance);
    CD.haptic(data.profit ? "medium" : "light");
    if (data.profit && w.stars > 0) {
      const colors = w.rarity === "legendary"
        ? ["#fde68a", "#f59e0b", "#fbbf24"] : null;
      CD.confetti(w.rarity === "legendary" ? 140 : 80, colors);
      CD.sound.play(w.rarity === "legendary" ? "jackpot" : "win");
    } else {
      CD.sound.play("coin");
    }
    if (data.xp && data.xp.leveled_up) {
      CD.sound.play("level");
      CD.toast(`🚀 Уровень ${data.xp.new_level}! +⭐ ${fmt(data.xp.level_reward)}`, "ok");
    }

    const netCls = data.net > 0 ? "pos" : data.net < 0 ? "neg" : "";
    const netTxt = data.net > 0 ? `+⭐ ${fmt(data.net)} в плюс` :
                   data.net < 0 ? `−⭐ ${fmt(-data.net)}` : "в ноль";

    body.innerHTML = `
      <button class="modal-close" data-close>×</button>
      <div class="win-card" style="--glow:var(--r-${w.rarity})">
        <div class="w-emoji">${w.emoji}</div>
        <div class="w-name">${w.name}</div>
        <div class="w-stars">⭐ ${fmt(w.stars)} · ${rarLabel(w.rarity)}</div>
        <div class="w-net ${netCls}">${netTxt}</div>
      </div>
      <div class="win-actions">
        <button class="btn ghost block" id="sellBtn">💰 Продать ⭐ ${fmt(w.stars)}</button>
        <button class="btn block" id="againBtn">🎲 Ещё раз</button>
      </div>`;
    bindClose();

    body.querySelector("#againBtn").addEventListener("click", () => {
      spinning = false;
      const fresh = casesCache.find((x) => x.id === c.id);
      if (fresh && (CD.user?.stars_balance || 0) < fresh.price) { CD.toast("Недостаточно звёзд", "err"); openDetail(c.id); return; }
      spin(c);
    });
    body.querySelector("#sellBtn").addEventListener("click", async () => {
      try {
        const r = await API.sell(data.item_id);
        CD.patchBalance(r.new_balance);
        CD.toast(`Продано за ⭐ ${fmt(r.gained)}`, "ok");
        body.querySelector("#sellBtn").disabled = true;
        body.querySelector("#sellBtn").textContent = "Продано ✓";
      } catch (e) { CD.toast(e.message, "err"); }
    });

    spinning = false;
    CD.refreshUser();
  }

  // ---- модалка util ----
  function showModal() { modal.classList.remove("hidden"); }
  function closeModal() { if (spinning) return; modal.classList.add("hidden"); }
  function bindClose() {
    body.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
  }
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

  // ---- живая лента дропов ----
  function loadTicker() {
    API.history ? null : null;
    window.CD.API && fetch("/api/history?scope=global&limit=20").then((r) => r.json()).then((rows) => {
      if (!rows.length) return;
      const sec = document.getElementById("drops-ticker");
      const track = document.getElementById("drops-track");
      const chip = (r) => `<div class="tick-item">${r.avatar || "🧑‍🚀"} ${r.username || "Игрок"}: <b style="color:var(--${rarColorVar(r.prize_rarity)})">${r.prize_name}</b> ⭐${fmt(r.prize_stars)}</div>`;
      track.innerHTML = rows.map(chip).join("") + rows.map(chip).join(""); // дублируем для бесшовной прокрутки
      sec.style.display = "";
    }).catch(() => {});
  }

  load();
  loadTicker();
})();

/* Игры: апгрейд · контракты · колесо фортуны */
(function () {
  "use strict";
  const CD = window.CD, API = CD.API, fmt = CD.fmt, RARITY = CD.RARITY;
  const rarLabel = (r) => (RARITY[r] || {}).label || r;

  const root = document.getElementById("game-root");
  const seg = document.getElementById("game-seg");
  let tab = "upgrade";
  let inventory = [];
  let busy = false;

  seg.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]"); if (!b) return;
    tab = b.dataset.tab;
    seg.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
    CD.sound.play("click");
    render();
  });

  async function refreshInventory() {
    try { inventory = (await API.inventory()).items; } catch (e) { inventory = []; }
  }

  async function render() {
    if (tab === "upgrade") return renderUpgrade();
    if (tab === "contract") return renderContract();
    if (tab === "wheel") return renderWheel();
  }

  // ============================ АПГРЕЙД ============================
  let upSel = null, upMult = 2;
  const MULTS = [1.5, 2, 3, 5, 10];
  const CHANCES = { 1.5: 0.60, 2: 0.45, 3: 0.30, 5: 0.18, 10: 0.09 };

  async function renderUpgrade() {
    root.innerHTML = `<div class="center" style="padding:20px"><div class="skeleton" style="height:140px"></div></div>`;
    await refreshInventory();
    if (upSel && !inventory.find((i) => i.id === upSel)) upSel = null;

    root.innerHTML = `
      <div class="game-panel">
        <div class="card" style="padding:14px">
          <div class="upg-wheel">
            <div class="upg-ring" id="upRing"></div>
            <div class="upg-pointer" id="upPointer"></div>
            <div class="upg-center"><div class="uc-chance" id="upChance">—</div><div class="uc-lbl">шанс успеха</div></div>
          </div>
          <div id="upTarget" class="center game-hint" style="margin-top:4px">Выбери предмет и множитель</div>
          <div class="mult-row" style="margin-top:12px">
            ${MULTS.map((m) => `<button class="mult-btn ${m === upMult ? "active" : ""}" data-mult="${m}">×${m}</button>`).join("")}
          </div>
          <button class="btn block" id="upGo" style="margin-top:12px" disabled>Выбери предмет</button>
        </div>
        <div class="section-head"><h3 style="font-size:13px;color:var(--muted)">Твой инвентарь</h3></div>
        <div class="inv-grid picker" id="upPicker"></div>
      </div>`;

    renderPicker("upPicker", (id) => { upSel = (upSel === id ? null : id); CD.sound.play("click"); renderUpgrade(); }, (i) => i.id === upSel);
    root.querySelectorAll("[data-mult]").forEach((b) =>
      b.addEventListener("click", () => { upMult = +b.dataset.mult; CD.sound.play("click"); renderUpgrade(); }));
    updateUpgradeGauge();

    const go = root.querySelector("#upGo");
    if (upSel) { go.disabled = false; go.textContent = `🔼 Апгрейд ×${upMult}`; go.onclick = doUpgrade; }
  }

  function updateUpgradeGauge() {
    const chance = CHANCES[upMult];
    const ring = root.querySelector("#upRing");
    if (ring) ring.style.setProperty("--succ", (chance * 360).toFixed(1) + "deg");
    const ch = root.querySelector("#upChance");
    if (ch) ch.textContent = Math.round(chance * 100) + "%";
    const item = inventory.find((i) => i.id === upSel);
    const tgt = root.querySelector("#upTarget");
    if (tgt) tgt.innerHTML = item
      ? `${item.emoji} ${item.name} (⭐${fmt(item.stars)}) → <b>⭐ ${fmt(Math.round(item.stars * upMult))}</b>`
      : "Выбери предмет и множитель";
  }

  async function doUpgrade() {
    if (busy || !upSel) return; busy = true;
    const go = root.querySelector("#upGo"); go.disabled = true;
    const pointer = root.querySelector("#upPointer");
    CD.sound.play("tick");
    let data;
    try { data = await API.upgrade(upSel, upMult); }
    catch (e) { CD.toast(e.message, "err"); busy = false; go.disabled = false; return; }

    pointer.style.transition = "transform 3.2s cubic-bezier(0.15,0.85,0.2,1)";
    pointer.style.transform = `translate(-50%, 0) rotate(${360 * 5 + data.landing_deg}deg)`;

    setTimeout(() => {
      if (data.won) {
        CD.sound.play(data.result.rarity === "legendary" ? "jackpot" : "win");
        CD.confetti(data.result.rarity === "legendary" ? 120 : 70);
        showGameResult("win", data.result.emoji, `Апгрейд удался!`,
          `${data.result.name} · ⭐ ${fmt(data.result.stars)} · ${rarLabel(data.result.rarity)}`, data.result.rarity, data.result);
      } else {
        CD.sound.play("lose"); CD.haptic("heavy");
        showGameResult("lose", "💥", "Предмет сгорел", "В этот раз не повезло — попробуй ещё", "common");
      }
      CD.patchBalance(data.new_balance);
      upSel = null; busy = false; CD.refreshUser();
    }, 3300);
  }

  // ============================ КОНТРАКТЫ ============================
  const conSel = new Set();

  async function renderContract() {
    root.innerHTML = `<div class="center" style="padding:20px"><div class="skeleton" style="height:140px"></div></div>`;
    await refreshInventory();
    for (const id of [...conSel]) if (!inventory.find((i) => i.id === id)) conSel.delete(id);

    const sum = [...conSel].reduce((s, id) => s + (inventory.find((i) => i.id === id)?.stars || 0), 0);
    root.innerHTML = `
      <div class="game-panel">
        <div class="card center" style="padding:16px">
          <div style="font-size:40px">📄</div>
          <div class="game-hint" style="margin-top:4px">Выбери 2–10 предметов. Результат — новый предмет случайной ценности (×0.2…×1.6 от суммы).</div>
          <div style="margin:12px 0"><span class="chip">Выбрано: <b id="conCount">${conSel.size}</b></span>
            <span class="chip">Сумма: <b id="conSum">⭐ ${fmt(sum)}</b></span></div>
          <button class="btn block gold" id="conGo" ${conSel.size >= 2 ? "" : "disabled"}>
            ${conSel.size >= 2 ? "📄 Заключить контракт" : "Выбери минимум 2"}
          </button>
        </div>
        <div class="section-head"><h3 style="font-size:13px;color:var(--muted)">Твой инвентарь</h3></div>
        <div class="inv-grid picker" id="conPicker"></div>
      </div>`;

    renderPicker("conPicker",
      (id) => { conSel.has(id) ? conSel.delete(id) : conSel.add(id); CD.sound.play("click"); renderContract(); },
      (i) => conSel.has(i.id));
    const go = root.querySelector("#conGo");
    if (conSel.size >= 2) go.onclick = doContract;
  }

  async function doContract() {
    if (busy) return; busy = true;
    CD.sound.play("tick");
    let data;
    try { data = await API.contract([...conSel]); }
    catch (e) { CD.toast(e.message, "err"); busy = false; return; }

    const win = data.profit >= 0;
    CD.sound.play(win ? (data.result.rarity === "legendary" ? "jackpot" : "win") : "lose");
    if (win) CD.confetti(data.result.rarity === "legendary" ? 120 : 60);
    showGameResult(win ? "win" : "lose", data.result.emoji,
      `${data.result.name} · ⭐ ${fmt(data.result.stars)}`,
      `Вложено ⭐ ${fmt(data.input_value)} → получено ⭐ ${fmt(data.output_value)} (${data.profit >= 0 ? "+" : ""}${fmt(data.profit)})`,
      data.result.rarity, data.result);
    CD.patchBalance(data.new_balance);
    conSel.clear(); busy = false; CD.refreshUser();
  }

  // ============================ КОЛЕСО ФОРТУНЫ ============================
  // гармоничная прогрессия синий → фиолетовый → розовый → золото
  const WHEEL_COLORS = ["#3390ec", "#2f7fd6", "#6f72e8", "#8e6fe6", "#b065d8", "#d061b8", "#e07aa0", "#f5b544"];

  async function renderWheel() {
    root.innerHTML = `<div class="center" style="padding:20px"><div class="skeleton" style="height:160px"></div></div>`;
    let st;
    try { st = await API.wheelStatus(); } catch (e) { root.innerHTML = `<div class="empty">Ошибка</div>`; return; }
    const segs = st.segments;
    const n = segs.length, step = 360 / n;

    // тонкие разделители между секторами для аккуратного вида
    const grad = segs.map((v, i) => {
      const c = WHEEL_COLORS[i % WHEEL_COLORS.length];
      return `${c} ${i * step}deg ${(i + 1) * step - 0.6}deg, rgba(255,255,255,.14) ${(i + 1) * step - 0.6}deg ${(i + 1) * step}deg`;
    }).join(", ");

    root.innerHTML = `
      <div class="game-panel">
        <div class="card center" style="padding:16px">
          <div class="fortune">
            <div class="fortune-arrow"></div>
            <div class="fortune-wheel" id="fWheel" style="background:conic-gradient(${grad})"></div>
            <div class="fortune-cap">🎁</div>
          </div>
          <div id="wheelInfo" class="game-hint" style="margin-top:8px"></div>
          <button class="btn block gold" id="wheelGo" style="margin-top:10px">Крутить (бесплатно)</button>
        </div>
      </div>`;

    // метки раскладываем по пикселям — надёжно и ровно
    const wheel = root.querySelector("#fWheel");
    requestAnimationFrame(() => {
      const size = wheel.clientWidth, c = size / 2, r = c * 0.66;
      wheel.innerHTML = segs.map((v, i) => {
        const a = (i * step + step / 2) * Math.PI / 180;
        const x = c + r * Math.sin(a), y = c - r * Math.cos(a);
        return `<div class="fortune-seg-label" style="left:${x}px;top:${y}px">⭐${v}</div>`;
      }).join("");
    });

    const info = root.querySelector("#wheelInfo");
    const go = root.querySelector("#wheelGo");
    if (!st.available) setCooldown(st.cooldown_seconds, info, go);
    else { info.textContent = "Доступен бесплатный спин раз в 6 часов"; }
    go.onclick = () => doWheel(segs, step, info, go);
  }

  function setCooldown(sec, info, go) {
    go.disabled = true;
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    info.textContent = `Следующий спин через ${h}ч ${m}м`;
    go.textContent = "⏳ Недоступно";
  }

  async function doWheel(segs, step, info, go) {
    if (busy) return; busy = true; go.disabled = true;
    CD.sound.play("tick");
    let data;
    try { data = await API.wheelSpin(); }
    catch (e) { CD.toast(e.message, "err"); busy = false; go.disabled = false; return; }

    if (!data.spun) { setCooldown(data.cooldown_seconds, info, go); busy = false; return; }

    const wheel = root.querySelector("#fWheel");
    const target = 360 * 6 + (360 - (data.index * step + step / 2));
    wheel.style.transform = `rotate(${target}deg)`;

    // звук «тиканья» во время прокрутки
    let ticks = 0; const ti = setInterval(() => { CD.sound.play("tick"); if (++ticks > 18) clearInterval(ti); }, 230);

    setTimeout(() => {
      clearInterval(ti);
      CD.sound.play(data.reward >= 250 ? "jackpot" : "coin");
      CD.confetti(data.reward >= 250 ? 120 : 70);
      CD.patchBalance(data.new_balance);
      CD.toast(`🎡 Выпало ⭐ ${fmt(data.reward)}!`, "ok");
      info.textContent = `Выигрыш: ⭐ ${fmt(data.reward)} · следующий спин через 6ч`;
      go.textContent = "⏳ Недоступно";
      busy = false; CD.refreshUser();
    }, 5200);
  }

  // ============================ ОБЩЕЕ ============================
  function renderPicker(hostId, onToggle, isSel) {
    const host = root.querySelector("#" + hostId);
    if (!inventory.length) {
      host.outerHTML = `<div class="empty"><span class="e-emoji">🎒</span>Инвентарь пуст — открой кейсы!</div>`;
      return;
    }
    host.innerHTML = inventory.map((i) => `
      <div class="inv-item ${isSel(i) ? "sel" : ""}" data-pick="${i.id}" style="--rc:var(--r-${i.rarity})">
        <div class="iv-emoji">${CD.gift(i)}</div>
        <div class="iv-name">${i.name}</div>
        <div class="iv-stars">⭐ ${fmt(i.stars)}</div>
      </div>`).join("");
    host.querySelectorAll("[data-pick]").forEach((el) =>
      el.addEventListener("click", () => onToggle(+el.dataset.pick)));
  }

  function showGameResult(cls, emoji, title, sub, rarity, obj) {
    const icon = obj ? CD.gift(obj) : emoji;
    const card = document.createElement("div");
    card.className = "modal";
    card.innerHTML = `
      <div class="modal-card" style="max-width:360px;position:relative">
        <button class="modal-close" data-close type="button">×</button>
        <div class="game-result ${cls}" style="--glow:var(--r-${rarity || "common"})">
          <div class="gr-emoji">${icon}</div>
          <div class="gr-title">${title}</div>
          <div class="gr-sub">${sub}</div>
        </div>
        <button class="btn block" style="margin-top:14px" data-close type="button">Продолжить</button>
      </div>`;
    document.body.appendChild(card);
    let closed = false;
    const close = () => { if (closed) return; closed = true; card.remove(); render(); };
    card.querySelectorAll("[data-close]").forEach((b) =>
      b.addEventListener("click", (e) => { e.stopPropagation(); close(); }));
    card.addEventListener("click", (e) => { if (e.target === card) close(); });
  }

  render();
})();

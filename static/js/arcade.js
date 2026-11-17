/* Аркада: ракета (crash) · мины · кости.
   Каждая игра — функция (root) => cleanup, исход всегда считает сервер. */
(function () {
  "use strict";
  const CD = window.CD, API = CD.API, fmt = CD.fmt;

  const LIMITS = { min: 10, max: 10000 };
  const BET_KEY = "cd_bet";
  const GAME_LABEL = { crash: "🚀 Ракета", mines: "💣 Мины", dice: "🎲 Кости" };

  const balance = () => (CD.user && CD.user.stars_balance) || 0;
  const clampBet = (v) => Math.max(LIMITS.min, Math.min(LIMITS.max, Math.floor(Number(v) || 0)));
  const x2 = (m) => "×" + Number(m).toFixed(2);

  // ---------------------------------------------------------------- ставка
  function betControl() {
    const saved = clampBet(localStorage.getItem(BET_KEY) || 50);
    return `
      <div class="bet">
        <div class="bet-label">Ставка</div>
        <div class="bet-row">
          <button class="bet-step" data-bet="half" type="button">½</button>
          <div class="bet-input"><span>⭐</span><input type="number" inputmode="numeric" min="${LIMITS.min}" max="${LIMITS.max}" value="${saved}" data-bet-input></div>
          <button class="bet-step" data-bet="double" type="button">×2</button>
        </div>
        <div class="bet-presets">
          ${[10, 50, 100, 500].map((v) => `<button type="button" data-bet="${v}">${v}</button>`).join("")}
          <button type="button" data-bet="max">Макс</button>
        </div>
      </div>`;
  }

  function bindBet(root, onChange) {
    const input = root.querySelector("[data-bet-input]");
    const set = (v) => {
      input.value = clampBet(v);
      localStorage.setItem(BET_KEY, input.value);
      onChange && onChange(+input.value);
    };
    root.querySelectorAll("[data-bet]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.bet, cur = Number(input.value) || 0;
      CD.sound.play("click");
      if (k === "half") set(cur / 2);
      else if (k === "double") set(cur * 2);
      else if (k === "max") set(Math.min(balance(), LIMITS.max));
      else set(+k);
    }));
    input.addEventListener("change", () => set(input.value));
    input.addEventListener("input", () => onChange && onChange(clampBet(input.value)));
    return {
      get value() { return clampBet(input.value); },
      lock(on) {
        input.disabled = on;
        root.querySelectorAll("[data-bet]").forEach((b) => (b.disabled = on));
      },
    };
  }

  function afterRound(data) {
    CD.patchBalance(data.new_balance);
    CD.refreshUser();
  }

  // --------------------------------------------------------- история ставок
  function historyBlock() {
    return `<div class="section-head"><h3 style="font-size:13px;color:var(--muted)">Мои последние игры</h3></div>
            <div class="bets" data-history><div class="skeleton" style="height:40px"></div></div>`;
  }

  async function loadHistory(root, game) {
    const host = root.querySelector("[data-history]");
    if (!host) return;
    let rows = [];
    try { rows = await API.arcadeHistory(game, 8); } catch (e) {}
    if (!host.isConnected) return;
    if (!rows.length) { host.innerHTML = `<div class="empty" style="padding:14px">Ставок пока нет</div>`; return; }
    host.innerHTML = rows.map((r) => {
      const won = r.state === "won";
      return `<div class="bet-line ${won ? "won" : "lost"}">
        <span class="bl-game">${GAME_LABEL[r.game] || r.game}</span>
        <span class="bl-bet">⭐ ${fmt(r.bet)}</span>
        <span class="bl-mult">${won ? x2(r.multiplier) : (r.game === "crash" ? "💥 " + x2(r.multiplier) : "—")}</span>
        <span class="bl-profit">${r.profit >= 0 ? "+" : "−"}${fmt(Math.abs(r.profit))}</span>
      </div>`;
    }).join("");
  }

  // ================================================================ РАКЕТА
  function crash(root) {
    let round = null, t0 = 0, growth = 0.14, raf = 0, poll = 0, alive = true;
    let shown = 1, ended = null; // ended: {state, mult}

    root.innerHTML = `
      <div class="game-panel">
        <div class="card crash-card">
          <div class="crash-stage" id="crStage">
            <canvas id="crCanvas"></canvas>
            <div class="crash-mult" id="crMult">×1.00</div>
            <div class="crash-note" id="crNote">Забери выигрыш до взрыва ракеты</div>
          </div>
          ${betControl()}
          <label class="auto-row">
            <span>Авто-вывод на</span>
            <div class="bet-input sm"><span>×</span><input type="number" step="0.1" min="1.01" max="100" placeholder="выкл" id="crAuto"></div>
          </label>
          <button class="btn block gold" id="crGo" type="button">🚀 Запустить</button>
        </div>
        ${historyBlock()}
      </div>`;

    const stage = root.querySelector("#crStage");
    const canvas = root.querySelector("#crCanvas");
    const ctx = canvas.getContext("2d");
    const multEl = root.querySelector("#crMult");
    const note = root.querySelector("#crNote");
    const go = root.querySelector("#crGo");
    const autoEl = root.querySelector("#crAuto");
    const bet = bindBet(root);
    let W = 0, H = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = stage.clientWidth; H = stage.clientHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw(elapsed, mult, state) {
      ctx.clearRect(0, 0, W, H);
      const pad = 14, T = Math.max(6, elapsed * 1.2), top = Math.max(2, mult * 1.25);
      const px = (t) => pad + (t / T) * (W - pad * 2);
      const py = (m) => H - pad - ((m - 1) / (top - 1)) * (H - pad * 2);

      ctx.strokeStyle = "rgba(255,255,255,0.06)"; ctx.lineWidth = 1;
      for (let i = 1; i <= 3; i++) {
        const y = pad + (i / 4) * (H - pad * 2);
        ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(W - pad, y); ctx.stroke();
      }
      if (elapsed <= 0) return;

      const color = state === "lost" ? "#ec5f5f" : state === "won" ? "#30c48d" : "#f5b544";
      const steps = 60;
      ctx.beginPath(); ctx.moveTo(px(0), py(1));
      for (let i = 1; i <= steps; i++) {
        const t = (elapsed * i) / steps;
        ctx.lineTo(px(t), py(Math.min(mult, Math.exp(growth * t))));
      }
      ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.stroke();
      ctx.lineTo(px(elapsed), H - pad); ctx.lineTo(px(0), H - pad); ctx.closePath();
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, color + "55"); g.addColorStop(1, color + "00");
      ctx.fillStyle = g; ctx.fill();

      ctx.font = "26px serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(state === "lost" ? "💥" : "🚀", px(elapsed), py(mult));
    }

    function frame() {
      if (!alive || !round || ended) return;
      const elapsed = (performance.now() - t0) / 1000;
      shown = Math.floor(Math.exp(growth * elapsed) * 100) / 100;
      multEl.textContent = x2(shown);
      go.textContent = `💰 Забрать ⭐ ${fmt(Math.floor(round.bet * shown))}`;
      draw(elapsed, shown, "active");
      raf = requestAnimationFrame(frame);
    }

    function finish(data) {
      if (ended) return;
      const won = data.state === "won";
      ended = { state: data.state, mult: won ? data.multiplier : (data.crash_point || data.multiplier) };
      cancelAnimationFrame(raf); clearInterval(poll);
      const elapsed = Math.log(Math.max(1.0001, ended.mult)) / growth;
      draw(elapsed, ended.mult, data.state);
      multEl.textContent = x2(ended.mult);
      stage.classList.add(won ? "won" : "lost");
      if (won) {
        note.innerHTML = `Забрал на <b>${x2(data.multiplier)}</b> · +⭐ ${fmt(data.payout - data.bet)}`
          + (data.crash_point ? ` · взрыв был на ${x2(data.crash_point)}` : "");
        CD.sound.play(data.multiplier >= 5 ? "jackpot" : "win");
        CD.confetti(data.multiplier >= 5 ? 120 : 50);
        CD.toast(`🚀 +⭐ ${fmt(data.payout)}`, "ok");
      } else {
        note.innerHTML = `Ракета взорвалась на <b>${x2(ended.mult)}</b>`;
        CD.sound.play("lose"); CD.haptic("heavy");
      }
      afterRound(data);
      round = null;
      bet.lock(false); autoEl.disabled = false;
      go.disabled = false; go.className = "btn block gold"; go.textContent = "🚀 Ещё раз";
      loadHistory(root, "crash");
    }

    async function start() {
      go.disabled = true;
      const auto = parseFloat(autoEl.value);
      let data;
      try { data = await API.crashStart(bet.value, auto > 1 ? auto : null); }
      catch (e) { CD.toast(e.message, "err"); go.disabled = false; return; }
      if (!alive) return;
      round = data; ended = null; growth = data.growth; t0 = performance.now();
      stage.classList.remove("won", "lost");
      note.textContent = data.auto_cashout ? `Авто-вывод на ${x2(data.auto_cashout)}` : "Жми «Забрать», пока не взорвалась";
      CD.patchBalance(data.new_balance);
      bet.lock(true); autoEl.disabled = true;
      go.disabled = false; go.className = "btn block";
      CD.sound.play("tick");
      frame();
      poll = setInterval(async () => {
        if (!round || ended) return;
        try {
          const t = await API.crashTick(round.round_id);
          if (t.state !== "active") finish(t);
        } catch (e) {}
      }, 300);
    }

    async function cashout() {
      if (!round || ended) return;
      go.disabled = true;
      try { finish(await API.crashCashout(round.round_id)); }
      catch (e) { CD.toast(e.message, "err"); go.disabled = false; }
    }

    go.addEventListener("click", () => (round && !ended ? cashout() : start()));
    const onResize = () => { resize(); if (!round) draw(0, 1, "idle"); };
    window.addEventListener("resize", onResize);
    resize(); draw(0, 1, "idle");
    loadHistory(root, "crash");

    return () => {
      alive = false; cancelAnimationFrame(raf); clearInterval(poll);
      window.removeEventListener("resize", onResize);
      // раунд не бросаем: забираем по текущему множителю
      if (round && !ended) API.crashCashout(round.round_id).then(afterRound).catch(() => {});
    };
  }

  // ================================================================== МИНЫ
  const MINE_CHOICES = [1, 3, 5, 10, 15, 24];

  function mines(root) {
    let alive = true, playing = false, busy = false, mineCount = 3, state = null;

    root.innerHTML = `
      <div class="game-panel">
        <div class="card" style="padding:14px">
          <div class="mines-top">
            <div class="mt-cell"><span>Множитель</span><b id="mnCur">×1.00</b></div>
            <div class="mt-cell"><span>Следующая</span><b id="mnNext">—</b></div>
            <div class="mt-cell"><span>Мин</span><b id="mnCnt">3</b></div>
          </div>
          <div class="mines-grid" id="mnGrid">
            ${Array.from({ length: 25 }, (_, i) => `<button class="mine-cell" data-cell="${i}" type="button" disabled></button>`).join("")}
          </div>
          <div id="mnSetup">
            <div class="bet-label" style="margin-top:12px">Количество мин</div>
            <div class="mult-row" id="mnChoices">
              ${MINE_CHOICES.map((m) => `<button class="mult-btn ${m === mineCount ? "active" : ""}" data-mines="${m}" type="button">${m}</button>`).join("")}
            </div>
            ${betControl()}
          </div>
          <button class="btn block gold" id="mnGo" type="button" style="margin-top:12px">💣 Начать игру</button>
        </div>
        ${historyBlock()}
      </div>`;

    const grid = root.querySelector("#mnGrid");
    const cells = [...grid.querySelectorAll(".mine-cell")];
    const go = root.querySelector("#mnGo");
    const setup = root.querySelector("#mnSetup");
    const curEl = root.querySelector("#mnCur"), nextEl = root.querySelector("#mnNext"), cntEl = root.querySelector("#mnCnt");
    const bet = bindBet(root);

    root.querySelectorAll("[data-mines]").forEach((b) => b.addEventListener("click", () => {
      if (playing) return;
      mineCount = +b.dataset.mines; cntEl.textContent = mineCount;
      root.querySelectorAll("[data-mines]").forEach((x) => x.classList.toggle("active", x === b));
      CD.sound.play("click");
    }));

    function paint(view) {
      curEl.textContent = x2(view.current);
      nextEl.textContent = view.next ? x2(view.next) : "—";
      cntEl.textContent = view.mines_count;
      const opened = new Set(view.opened), bombs = new Set(view.mines || []);
      cells.forEach((c, i) => {
        c.className = "mine-cell";
        c.textContent = "";
        if (opened.has(i)) { c.classList.add("safe"); c.textContent = "💎"; }
        else if (bombs.has(i)) { c.classList.add("bomb"); c.textContent = "💣"; }
        c.disabled = !playing || opened.has(i);
      });
    }

    function setPlaying(on, view) {
      playing = on;
      setup.classList.toggle("hidden", on);
      if (on) {
        go.className = "btn block";
        go.disabled = !view.picks;
        go.textContent = view.picks ? `💰 Забрать ⭐ ${fmt(Math.floor(state.bet * view.current))}` : "Открой клетку";
      } else {
        go.className = "btn block gold"; go.disabled = false; go.textContent = "💣 Начать игру";
      }
    }

    function end(data) {
      playing = false;
      paint(data);
      setPlaying(false, data);
      if (data.state === "won") {
        CD.sound.play(data.multiplier >= 5 ? "jackpot" : "win");
        CD.confetti(data.multiplier >= 5 ? 120 : 50);
        CD.toast(`💎 ${x2(data.multiplier)} · +⭐ ${fmt(data.payout)}`, "ok");
      } else {
        const hit = cells[data.cell]; if (hit) hit.classList.add("boom");
        CD.sound.play("lose"); CD.haptic("heavy");
        CD.toast("💥 Мина! Ставка сгорела", "err");
      }
      afterRound(data);
      loadHistory(root, "mines");
    }

    async function start() {
      if (busy) return; busy = true; go.disabled = true;
      try {
        const data = await API.minesStart(bet.value, mineCount);
        state = { bet: data.bet };
        CD.patchBalance(data.new_balance);
        playing = true; paint(data); setPlaying(true, data);
        CD.sound.play("tick");
      } catch (e) { CD.toast(e.message, "err"); go.disabled = false; }
      busy = false;
    }

    async function cashout() {
      if (busy) return; busy = true; go.disabled = true;
      try { end(await API.minesCashout()); }
      catch (e) { CD.toast(e.message, "err"); go.disabled = false; }
      busy = false;
    }

    grid.addEventListener("click", async (e) => {
      const c = e.target.closest("[data-cell]");
      if (!c || !playing || busy || c.disabled) return;
      busy = true;
      try {
        const data = await API.minesReveal(+c.dataset.cell);
        if (!alive) return;
        if (data.state === "active") {
          paint(data); setPlaying(true, data);
          CD.sound.play("coin"); CD.haptic("light");
        } else end(data);
      } catch (err) { CD.toast(err.message, "err"); }
      busy = false;
    });

    go.addEventListener("click", () => (playing ? cashout() : start()));

    // продолжить незавершённую игру
    API.minesState().then((s) => {
      if (!alive || !s.active) return;
      state = { bet: s.bet }; playing = true; mineCount = s.mines_count;
      paint(s); setPlaying(true, s);
      CD.toast("Продолжаем незавершённую игру", "info");
    }).catch(() => {});
    loadHistory(root, "mines");

    return () => { alive = false; };
  }

  // ================================================================= КОСТИ
  function dice(root) {
    let alive = true, busy = false, chance = 50;
    const recent = [];

    root.innerHTML = `
      <div class="game-panel">
        <div class="card" style="padding:14px">
          <div class="dice-roll" id="dcRoll">50.00</div>
          <div class="dice-track">
            <div class="dice-zone" id="dcZone"></div>
            <div class="dice-marker hidden" id="dcMarker"></div>
          </div>
          <div class="dice-scale"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
          <input type="range" min="5" max="95" value="50" class="dice-slider" id="dcSlider">
          <div class="mines-top" style="margin-top:10px">
            <div class="mt-cell"><span>Шанс</span><b id="dcChance">50%</b></div>
            <div class="mt-cell"><span>Множитель</span><b id="dcMult">×1.92</b></div>
            <div class="mt-cell"><span>Выигрыш</span><b id="dcWin">⭐ 0</b></div>
          </div>
          ${betControl()}
          <button class="btn block gold" id="dcGo" type="button" style="margin-top:12px">🎲 Бросить</button>
          <div class="dice-recent" id="dcRecent"></div>
          <div class="game-hint" style="margin-top:8px">Победа, если выпало меньше выбранного шанса</div>
        </div>
        ${historyBlock()}
      </div>`;

    const slider = root.querySelector("#dcSlider");
    const zone = root.querySelector("#dcZone"), marker = root.querySelector("#dcMarker");
    const rollEl = root.querySelector("#dcRoll"), go = root.querySelector("#dcGo");
    const mult = () => Math.floor(96 / chance * 100) / 100;

    function update() {
      zone.style.width = chance + "%";
      root.querySelector("#dcChance").textContent = chance + "%";
      root.querySelector("#dcMult").textContent = x2(mult());
      root.querySelector("#dcWin").textContent = "⭐ " + fmt(Math.floor(bet.value * mult()));
    }
    const bet = bindBet(root, update);
    slider.addEventListener("input", () => { chance = +slider.value; update(); });
    update();

    go.addEventListener("click", async () => {
      if (busy) return; busy = true; go.disabled = true;
      let data;
      try { data = await API.dice(bet.value, chance); }
      catch (e) { CD.toast(e.message, "err"); busy = false; go.disabled = false; return; }
      if (!alive) return;
      CD.patchBalance(data.new_balance - data.payout);   // выигрыш покажем после анимации
      marker.classList.remove("hidden", "won", "lost");
      marker.style.left = data.roll + "%";
      rollEl.classList.remove("won", "lost");
      const from = parseFloat(rollEl.textContent) || 0, startT = performance.now();
      CD.sound.play("tick");
      (function spin(now) {
        const p = Math.min((now - startT) / 700, 1);
        rollEl.textContent = (from + (data.roll - from) * (1 - Math.pow(1 - p, 3))).toFixed(2);
        if (p < 1 && alive) return requestAnimationFrame(spin);
        rollEl.textContent = data.roll.toFixed(2);
        rollEl.classList.add(data.won ? "won" : "lost");
        marker.classList.add(data.won ? "won" : "lost");
        if (data.won) {
          CD.sound.play(data.win_multiplier >= 5 ? "jackpot" : "win");
          if (data.win_multiplier >= 3) CD.confetti(70);
          CD.toast(`🎲 ${data.roll.toFixed(2)} · +⭐ ${fmt(data.payout)}`, "ok");
        } else { CD.sound.play("lose"); CD.haptic("medium"); }
        recent.unshift(data); recent.splice(10);
        root.querySelector("#dcRecent").innerHTML = recent.map((r) =>
          `<span class="${r.won ? "won" : "lost"}">${r.roll.toFixed(2)}</span>`).join("");
        afterRound(data);
        loadHistory(root, "dice");
        busy = false; go.disabled = false;
      })(startT);
    });

    loadHistory(root, "dice");
    return () => { alive = false; };
  }

  window.CDArcade = { crash, mines, dice };
})();

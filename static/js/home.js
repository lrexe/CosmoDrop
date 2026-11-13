/* Главная: live-статистика, ежедневный бонус, популярные кейсы, лента выигрышей */
(function () {
  "use strict";
  const { API, CD } = { API: window.CD.API, CD: window.CD };
  const fmt = CD.fmt;

  function timeAgo(iso) {
    if (!iso) return "";
    const diff = (Date.now() - new Date(iso + "Z").getTime()) / 1000;
    if (diff < 60) return "только что";
    if (diff < 3600) return Math.floor(diff / 60) + " мин назад";
    if (diff < 86400) return Math.floor(diff / 3600) + " ч назад";
    return Math.floor(diff / 86400) + " дн назад";
  }

  // --- live stats ---
  API.stats().then((s) => {
    const row = document.getElementById("live-stats");
    const items = [
      [s.total_cases_opened, "Кейсов открыто"],
      [s.total_users, "Игроков"],
      [s.biggest_win, "Рекорд ⭐"],
    ];
    row.innerHTML = items.map(([v, l]) =>
      `<div class="stat"><div class="val" data-cv="${v}">0</div><div class="lbl">${l}</div></div>`).join("");
    row.querySelectorAll("[data-cv]").forEach((el) => CD.countUp(el, 0, +el.dataset.cv));
  }).catch(() => {});

  // --- daily bonus ---
  const dBtn = document.getElementById("daily-btn");
  const dSub = document.getElementById("daily-sub");
  function renderDaily(st) {
    if (st.available) {
      dSub.innerHTML = `Забери <b>⭐ ${fmt(st.next_reward)}</b> · серия <span class="streak">${st.streak} 🔥</span>`;
      dBtn.disabled = false; dBtn.textContent = "Забрать";
      dBtn.onclick = async () => {
        dBtn.disabled = true;
        try {
          const r = await CD.API.claimDaily();
          if (r.claimed) {
            CD.patchBalance(r.new_balance);
            CD.confetti(60);
            CD.toast(`+⭐ ${fmt(r.reward)} · серия ${r.streak} 🔥`, "ok");
            CD.haptic("medium");
            renderDaily({ available: false, cooldown_seconds: 86400, streak: r.streak, next_reward: r.reward });
          }
        } catch (e) { CD.toast(e.message, "err"); dBtn.disabled = false; }
      };
    } else {
      const h = Math.floor(st.cooldown_seconds / 3600);
      const m = Math.floor((st.cooldown_seconds % 3600) / 60);
      dSub.innerHTML = `Уже получен · серия <span class="streak">${st.streak} 🔥</span> · через ${h}ч ${m}м`;
      dBtn.disabled = true; dBtn.textContent = "✓";
    }
  }
  API.dailyStatus().then(renderDaily).catch(() => { dSub.textContent = "Недоступно"; });

  // --- daily quests ---
  function loadQuests() {
    API.quests().then(({ quests }) => {
      const box = document.getElementById("quests-list");
      box.innerHTML = quests.map(questRow).join("");
      box.querySelectorAll("[data-claim]").forEach((b) =>
        b.addEventListener("click", async () => {
          b.disabled = true;
          try {
            const r = await CD.API.claimQuest(b.dataset.claim);
            CD.patchBalance(r.new_balance);
            CD.confetti(50); CD.sound.play("coin");
            CD.toast(`Задание выполнено: +⭐ ${fmt(r.reward)}`, "ok");
            loadQuests();
          } catch (e) { CD.toast(e.message, "err"); b.disabled = false; }
        }));
    }).catch(() => {});
  }
  function questRow(q) {
    const pct = Math.min(100, Math.round((q.progress / q.goal) * 100));
    let action;
    if (q.claimed) action = `<span class="q-reward">✓</span>`;
    else if (q.completed) action = `<button class="btn gold sm" data-claim="${q.key}">+${q.reward}</button>`;
    else action = `<span class="q-reward">⭐ ${q.reward}</span>`;
    return `
      <div class="quest">
        <span class="q-ic">${q.emoji}</span>
        <div class="q-body">
          <div class="q-title">${q.title}</div>
          <div class="q-bar"><div class="q-fill" style="width:${pct}%"></div></div>
          <div class="q-prog">${fmt(q.progress)} / ${fmt(q.goal)}</div>
        </div>
        ${action}
      </div>`;
  }
  loadQuests();

  // --- featured cases ---
  API.cases().then((cases) => {
    const grid = document.getElementById("featured-cases");
    const top = cases.slice(0, 4);
    if (!top.length) { grid.innerHTML = `<div class="empty"><span class="e-emoji">📦</span>Кейсов пока нет</div>`; return; }
    grid.innerHTML = top.map((c) => caseCard(c)).join("");
    grid.querySelectorAll("[data-case]").forEach((el) =>
      el.addEventListener("click", () => (window.location = "/cases")));
  }).catch(() => {});

  function caseCard(c) {
    const rar = (c.rarity || "common");
    return `
      <div class="case-card rarity-ring-${rar}" data-case="${c.id}">
        <span class="rarity-badge r-${rar}">${(window.CD.RARITY[rar] || {}).label || rar}</span>
        <div class="c-emoji">${CD.gift(c)}</div>
        <div class="c-name">${c.name}</div>
        <div class="c-range">⭐ ${fmt(c.prize_min)}–${fmt(c.prize_max)}</div>
        <div class="c-price">⭐ ${fmt(c.price)}</div>
      </div>`;
  }

  // --- global win feed ---
  API.history("global", 12).then((rows) => {
    const feed = document.getElementById("win-feed");
    if (!rows.length) { feed.innerHTML = `<div class="empty"><span class="e-emoji">🌌</span>Пока никто не открывал кейсы</div>`; return; }
    feed.innerHTML = rows.map((r) => `
      <div class="feed-item">
        <span class="fi-emoji">${r.avatar || "🧑‍🚀"}</span>
        <div class="fi-main">
          <div class="fi-name">${r.username || "Космонавт"} · ${r.prize_name}</div>
          <div class="fi-sub">${r.case_name} · ${timeAgo(r.opened_at)}</div>
        </div>
        <div class="fi-win" style="color:var(--${rarColor(r.prize_rarity)})">+${fmt(r.prize_stars)} ⭐</div>
      </div>`).join("");
  }).catch(() => {});

  function rarColor(r) {
    return { common: "muted", rare: "blue", epic: "violet", legendary: "gold" }[r] || "muted";
  }
})();

/* Профиль: статистика, инвентарь (продажа), история */
(function () {
  "use strict";
  const CD = window.CD, API = CD.API, fmt = CD.fmt, RARITY = CD.RARITY;
  const rarLabel = (r) => (RARITY[r] || {}).label || r;

  function timeAgo(iso) {
    if (!iso) return "";
    const diff = (Date.now() - new Date(iso + "Z").getTime()) / 1000;
    if (diff < 60) return "только что";
    if (diff < 3600) return Math.floor(diff / 60) + " мин назад";
    if (diff < 86400) return Math.floor(diff / 3600) + " ч назад";
    return Math.floor(diff / 86400) + " дн назад";
  }

  // --- статистика из состояния пользователя ---
  CD.onUser((u) => {
    CD.countUp(document.getElementById("ps-balance"), 0, u.stars_balance);
    CD.countUp(document.getElementById("ps-cases"), 0, u.cases_opened);
    CD.countUp(document.getElementById("ps-earned"), 0, u.total_earned);
    CD.countUp(document.getElementById("ps-best"), 0, u.best_drop);
    document.getElementById("rank-tag").textContent =
      u.rank ? `🏆 Место в рейтинге: #${u.rank}` : "Космический игрок";

    const li = u.level_info || { level: u.level || 1, xp_into_level: 0, xp_for_level: 100, progress: 0 };
    document.getElementById("lt-lvl").textContent = `Уровень ${li.level}`;
    document.getElementById("lt-xp").textContent = `${fmt(li.xp_into_level)} / ${fmt(li.xp_for_level)} XP`;
    document.getElementById("lt-fill").style.width = Math.round((li.progress || 0) * 100) + "%";
  });

  // --- достижения ---
  function loadAchievements() {
    API.achievements().then(({ achievements }) => {
      const grid = document.getElementById("ach-grid");
      grid.innerHTML = achievements.map(achCard).join("");
      grid.querySelectorAll("[data-ach]").forEach((b) =>
        b.addEventListener("click", async () => {
          try {
            const r = await API.claimAchievement(b.dataset.ach);
            CD.patchBalance(r.new_balance);
            CD.confetti(60); CD.sound.play("coin");
            CD.toast(`Достижение получено: +⭐ ${fmt(r.reward)}`, "ok");
            loadAchievements();
          } catch (e) { CD.toast(e.message, "err"); }
        }));
    }).catch(() => {});
  }
  function achCard(a) {
    let foot;
    if (a.claimed) foot = `<div class="a-done">✓ Получено</div>`;
    else if (a.unlocked) foot = `<div class="a-claim" data-ach="${a.key}">Забрать +${a.reward}</div>`;
    else foot = `<div class="a-done">${fmt(a.progress)} / ${fmt(a.goal)}</div>`;
    return `
      <div class="ach ${a.unlocked ? "unlocked" : ""}">
        <span class="a-ic">${a.emoji}</span>
        <div><div class="a-title">${a.title}</div><div class="a-desc">${a.desc}</div>${foot}</div>
      </div>`;
  }
  loadAchievements();

  // --- промокод ---
  const promoBtn = document.getElementById("promo-btn");
  promoBtn.addEventListener("click", async () => {
    const input = document.getElementById("promo-input");
    const code = input.value.trim();
    if (!code) { CD.toast("Введи код", "err"); return; }
    promoBtn.disabled = true;
    try {
      const r = await API.redeemPromo(code);
      CD.patchBalance(r.new_balance);
      CD.confetti(60); CD.sound.play("coin");
      CD.toast(`Промокод активирован: +⭐ ${fmt(r.reward)}`, "ok");
      input.value = ""; CD.refreshUser();
    } catch (e) { CD.toast(e.message, "err"); }
    promoBtn.disabled = false;
  });

  // --- рефералы ---
  API.referral().then((r) => {
    document.getElementById("ref-code").textContent = r.code || "—";
    document.getElementById("ref-invited").textContent = fmt(r.invited);
    document.getElementById("ref-earned").textContent = fmt(r.earned);
    document.getElementById("ref-copy").onclick = () => {
      const text = r.link || r.code;
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => CD.toast("Ссылка скопирована", "ok")).catch(() => {});
      else CD.toast(r.code, "info");
      CD.sound.play("click");
    };
  }).catch(() => {});

  // --- настройки: звук ---
  const sw = document.getElementById("sound-switch");
  function syncSwitch() { sw.classList.toggle("on", !CD.sound.muted); }
  syncSwitch();
  sw.addEventListener("click", () => { CD.sound.toggle(); syncSwitch(); });

  // --- инвентарь ---
  function loadInventory() {
    API.inventory().then(({ items, total_value, count }) => {
      const grid = document.getElementById("inv-grid");
      document.getElementById("inv-count").textContent = count ? `(${count} · ⭐ ${fmt(total_value)})` : "";
      const sellAll = document.getElementById("sell-all");

      if (!count) {
        grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><span class="e-emoji">🎒</span>Инвентарь пуст — открой кейс!</div>`;
        sellAll.style.display = "none";
        return;
      }
      grid.innerHTML = items.map(invItem).join("");
      grid.querySelectorAll("[data-sell]").forEach((el) =>
        el.addEventListener("click", () => sellOne(+el.dataset.sell)));

      sellAll.style.display = "";
      sellAll.onclick = async () => {
        try {
          const r = await API.sellAll();
          CD.patchBalance(r.new_balance);
          CD.toast(`Продано ${r.sold} шт. за ⭐ ${fmt(r.gained)}`, "ok");
          CD.haptic("medium");
          loadInventory(); CD.refreshUser();
        } catch (e) { CD.toast(e.message, "err"); }
      };
    }).catch(() => {
      document.getElementById("inv-grid").innerHTML = `<div class="empty" style="grid-column:1/-1">Ошибка загрузки</div>`;
    });
  }

  function invItem(i) {
    return `
      <div class="inv-item" style="--rc:var(--r-${i.rarity})" title="${rarLabel(i.rarity)} · из «${i.case_name}»">
        <div class="iv-emoji">${i.emoji}</div>
        <div class="iv-name">${i.name}</div>
        <div class="iv-stars">⭐ ${fmt(i.stars)}</div>
        <div class="iv-sell" data-sell="${i.id}">Продать</div>
      </div>`;
  }

  async function sellOne(id) {
    try {
      const r = await API.sell(id);
      CD.patchBalance(r.new_balance);
      CD.toast(`Продано за ⭐ ${fmt(r.gained)}`, "ok");
      CD.haptic("light");
      loadInventory(); CD.refreshUser();
    } catch (e) { CD.toast(e.message, "err"); }
  }

  // --- история ---
  function loadHistory() {
    API.history("me", 25).then((rows) => {
      const list = document.getElementById("history-list");
      if (!rows.length) {
        list.innerHTML = `<div class="empty"><span class="e-emoji">📜</span>Пока нет открытий</div>`;
        return;
      }
      list.innerHTML = rows.map((r) => `
        <div class="feed-item">
          <span class="fi-emoji">🎁</span>
          <div class="fi-main">
            <div class="fi-name">${r.prize_name}</div>
            <div class="fi-sub">${r.case_name} · ${timeAgo(r.opened_at)}</div>
          </div>
          <div class="fi-win" style="color:var(--${rarColor(r.prize_rarity)})">⭐ ${fmt(r.prize_stars)}</div>
        </div>`).join("");
    }).catch(() => {});
  }

  function rarColor(r) { return { common: "muted", rare: "blue", epic: "violet", legendary: "gold" }[r] || "muted"; }

  loadInventory();
  loadHistory();
  // при пополнении баланса обновим цифры
  window.addEventListener("cd:balance", () => CD.refreshUser());
})();

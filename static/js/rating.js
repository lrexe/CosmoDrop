/* Рейтинг: подиум топ-3 + таблица + подсветка игрока */
(function () {
  "use strict";
  const CD = window.CD, API = CD.API, fmt = CD.fmt;

  API.rating().then(({ leaderboard, me }) => {
    renderPodium(leaderboard.slice(0, 3));
    renderList(leaderboard, me);
    renderMe(leaderboard, me);
  }).catch(() => {
    document.getElementById("rating-list").innerHTML = `<div class="empty">Ошибка загрузки рейтинга</div>`;
  });

  function pod(entry, cls, crown) {
    if (!entry) return `<div class="pod ${cls}"></div>`;
    return `
      <div class="pod ${cls}">
        ${crown ? `<div class="crown">${crown}</div>` : ""}
        <div class="pa">${entry.avatar || "🧑‍🚀"}</div>
        <div class="pname">${entry.name}</div>
        <div class="pscore">⭐ ${fmt(entry.score)}</div>
        <div class="pbar">${entry.place}</div>
      </div>`;
  }

  function renderPodium(top) {
    const wrap = document.getElementById("podium-wrap");
    if (!top.length) { wrap.innerHTML = ""; return; }
    // визуальный порядок: 2 — 1 — 3
    wrap.innerHTML = `<div class="podium">
      ${pod(top[1], "p2")}
      ${pod(top[0], "p1", "👑")}
      ${pod(top[2], "p3")}
    </div>`;
  }

  function renderList(leaderboard, me) {
    const list = document.getElementById("rating-list");
    const rest = leaderboard.slice(3);
    if (!rest.length) {
      list.innerHTML = leaderboard.length
        ? `<div class="empty">Весь топ уже на подиуме 🚀</div>`
        : `<div class="empty"><span class="e-emoji">🌌</span>Рейтинг пуст</div>`;
      return;
    }
    const myId = me && me.telegram_id;
    list.innerHTML = rest.map((e) => row(e, me && e.name === me.name && e.place === me.place)).join("");
  }

  function row(e, isMe) {
    return `
      <div class="rating-item ${isMe ? "me" : ""}">
        <span class="place">${medal(e.place)}</span>
        <span class="ri-av">${e.avatar || "🧑‍🚀"}</span>
        <span class="name">${e.name}</span>
        <span class="score">⭐ ${fmt(e.score)} <small>· ${fmt(e.cases_opened)}🎁</small></span>
      </div>`;
  }

  function medal(p) { return p; }

  function renderMe(leaderboard, me) {
    const box = document.getElementById("me-card");
    // показываем отдельную карточку «ты», только если игрок НЕ попал в видимый топ
    if (!me || me.place <= leaderboard.length) { box.innerHTML = ""; return; }
    box.innerHTML = `
      <div class="rating-item me">
        <span class="place">${me.place}</span>
        <span class="ri-av">${me.avatar || "🧑‍🚀"}</span>
        <span class="name">Ты · ${me.name}</span>
        <span class="score">⭐ ${fmt(me.score)} <small>· ${fmt(me.cases_opened)}🎁</small></span>
      </div>`;
  }
})();

const modal = document.getElementById("caseModal");
const resultBox = document.getElementById("result");
const roller = document.getElementById("rollerItems");
const closeBtn = document.getElementById("closeModal");
const casesGrid = document.querySelector(".cases-grid");
const balanceEl = document.getElementById("balance");
const earnedEl = document.getElementById("earned");

// ⚠️ временно, потом замени на Telegram WebApp
const telegramId = 111222333;

/* =========================
   ЗАГРУЗКА КЕЙСОВ
========================= */
async function loadCases() {
    const res = await fetch("/api/cases");
    const cases = await res.json();

    casesGrid.innerHTML = "";

    cases.forEach(c => {
        const card = document.createElement("div");
        card.className = "case-card";
        card.innerHTML = `
            <div class="case-label">🎁</div>
            <img src="${c.image}" alt="${c.name}">
            <div class="case-info">
                <h4>${c.name}</h4>
                <p>Кейс за ⭐ ${c.price}</p>
            </div>
            <div class="case-footer">
                <span class="case-stars">⭐ ${c.price}</span>
                <button class="open-btn" data-case-id="${c.id}">Открыть</button>
            </div>
        `;
        casesGrid.appendChild(card);
    });

    addOpenListeners();
}

/* =========================
   ОТКРЫТИЕ КЕЙСА
========================= */
function addOpenListeners() {
    document.querySelectorAll(".open-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const caseId = btn.dataset.caseId;

            modal.classList.remove("hidden");
            resultBox.classList.add("hidden");
            roller.innerHTML = "";

            // запрос к серверу
            const res = await fetch("/api/open-case", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({case_id: caseId, telegram_id: telegramId})
            });
            const data = await res.json();
            if (data.error) {
                alert(data.error);
                modal.classList.add("hidden");
                return;
            }

            const ITEM_WIDTH = 110.2;
            const container = document.querySelector(".roller-container");
            const containerCenter = container.offsetWidth / 2;
            const itemCenter = ITEM_WIDTH / 2;

            // строим длинную рулетку
            const rollerItems = [];
            const DUPLICATE = 5; // сколько раз дублируем список для длинной прокрутки
            for (let i = 0; i < DUPLICATE; i++) {
                data.roller.forEach(value => {
                    const div = document.createElement("div");
                    div.className = "roller-item";
                    div.innerText = `⭐ ${value}`;
                    roller.appendChild(div);
                    rollerItems.push(div);
                });
            }

            // выигрышный элемент ставим ближе к концу рулетки
            const WIN_INDEX = rollerItems.length - data.roller.length + data.center_index;
            const offset = WIN_INDEX * ITEM_WIDTH - containerCenter + itemCenter;

            // стартовая позиция
            roller.style.transition = "none";
            roller.style.transform = "translateX(0px)";

            // запускаем спин
            const SPIN_TIME = 10000; // 10 секунд
            setTimeout(() => {
                roller.style.transition = `transform ${SPIN_TIME}ms cubic-bezier(0.12, 0.8, 0.25, 1)`;
                roller.style.transform = `translateX(-${offset}px)`;
            }, 100);

            // показываем результат после окончания спина
            setTimeout(() => {
                resultBox.innerText = `🎉 Ты выиграл ⭐ ${data.win}`;
                resultBox.classList.remove("hidden");
                balanceEl.innerText = `⭐ ${data.new_balance}`;
            }, SPIN_TIME + 200);
        });
    });
}

/* =========================
   ЗАКРЫТИЕ МОДАЛКИ
========================= */
closeBtn.onclick = () => {
    modal.classList.add("hidden");
    roller.innerHTML = "";
};

/* =========================
   СТАРТ
========================= */
loadCases();

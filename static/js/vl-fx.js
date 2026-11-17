/* Vloody effects + gift pictures. No dependency on screen markup; load before vloody.js.

   Public API (globals):
     giftImg(item, cls?) -> string          also VLFx.giftImg
       item = {image: string|null, title: string, art: string}
       Returns an <img loading="lazy" decoding="async"> with a fixed 1:1 aspect-ratio. If the picture
       fails to load (or item.image is null) a fallback tile of the same box is shown instead:
       a gradient picked by a hash of the title (blues / cyans / teals / slate, one amber) + a monogram.
       `cls` is added to the <img> and to the fallback tile alike, so size them with that class.
     VLFx.tilt(root)               — 3D tilt (up to ±8°) + pointer sheen on every [data-tilt] inside root.
                                    Desktop only: (hover: hover) and (pointer: fine), width ≥ 861px,
                                    and never with prefers-reduced-motion: reduce (checked on every move).
                                    The element may hold a [data-tilt-sheen] child (sheen layer, gets
                                    --vl-mx / --vl-my) and [data-tilt-float] children are lifted with translateZ
                                    by CSS (the element gets transform-style: preserve-3d via CSS).
     VLFx.countUp(el, to, ms?)     — animates el's number to `to` (ru-RU grouping); instant with reduced motion.
     VLFx.stagger(container)       — children fade/slide in one after another (≤ 40ms step); off with reduced motion.
     VLFx.lottie(el, src, opts?) -> {destroy()}
                                   — plays the lottie JSON at `src` inside `el` (opts.loop, default true) on a layer
                                    (div.vl-anim) over the static picture already in `el`; `el` gets .vl-anim-on once the
                                    first frame is drawn (CSS fades the layer in). lottie-web 5.12.2 is loaded lazily, once,
                                    from cdnjs. Any failure (script blocked, 404, bad JSON) removes the layer and leaves the
                                    picture; it never throws. Reduced motion: first frame only, no autoplay.
                                    destroy() is idempotent and safe before the animation has loaded.
                                    A runtime switch of prefers-reduced-motion stops (first frame) or resumes live players.
     VLFx.transition(from, to)     — screen change: `from` loses .on, `to` gets .on at once (the class contract never waits
                                    for the animation), then `to` enters with a 200 ms shift + fade (Web Animations API, no
                                    fill, so nothing is left behind). A call during a running transition cancels it first.
                                    Reduced motion: plain swap. from === to (or no from): just makes sure `to` is .on.
     VLFx.confetti(kind)           — kind "win" | "jackpot": a short burst of particles on a fixed canvas over the page,
                                    colours from the theme tokens only (--accent, --accent-2, --accent-text, --warn: blues +
                                    amber). pointer-events: none, aria-hidden; the canvas is removed after the burst (timer
                                    fallback when frames do not run). Off with reduced motion. Never throws.
*/
(function () {
  "use strict";

  const mq = (q) => (window.matchMedia ? window.matchMedia(q).matches : false);
  const RM_QUERY = "(prefers-reduced-motion: reduce)";
  const reduced = () => mq(RM_QUERY);
  // one listener for the runtime change of the reduced-motion setting; parts that read it once subscribe here
  const rmSubs = new Set();
  try {
    const rmq = window.matchMedia && window.matchMedia(RM_QUERY);
    const onRm = () => { const r = reduced(); rmSubs.forEach((fn) => { try { fn(r); } catch (e) {} }); };
    if (rmq && rmq.addEventListener) rmq.addEventListener("change", onRm);
    else if (rmq && rmq.addListener) rmq.addListener(onRm);
  } catch (e) {}
  const canTilt = () => !reduced() && mq("(hover: hover) and (pointer: fine)") && mq("(min-width: 861px)");

  // ------------------------------------------------------------------ gift picture + fallback tile
  const escAttr = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // blues / cyans / teals / slate + one warm amber. No purple, no pink.
  const FB_PALETTE = [
    ["#2b90ff", "#0b4fae", "#ffffff"],
    ["#56b0ff", "#1f6fd1", "#ffffff"],
    ["#22b8cf", "#0b6f86", "#ffffff"],
    ["#2dd4bf", "#0f766e", "#ffffff"],
    ["#14b8a6", "#115e59", "#ffffff"],
    ["#64748b", "#1e293b", "#ffffff"],
    ["#38bdf8", "#075985", "#ffffff"],
    ["#f5b544", "#c27a0a", "#1d1405"],
  ];

  function hash(s) { // FNV-1a, 32 bit
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
    return h >>> 0;
  }
  function monogram(title) {
    const words = String(title || "").replace(/['’`]/g, "").split(/[\s\-_#.,]+/).filter((w) => /\p{L}/u.test(w));
    const letters = words.slice(0, 2).map((w) => w.match(/\p{L}/u)[0].toUpperCase()).join("");
    return letters || "?";
  }
  function fallbackHtml(title, cls) {
    const [a, b, ink] = FB_PALETTE[hash(String(title || "")) % FB_PALETTE.length];
    return `<span class="vl-gift-fb ${escAttr(cls || "")}" role="img" aria-label="${escAttr(title)}"`
      + ` style="aspect-ratio:1/1;background:linear-gradient(145deg,${a},${b});color:${ink}">`
      + `<span class="vl-gift-fb-mono" aria-hidden="true">${escAttr(monogram(title))}</span></span>`;
  }

  function giftImg(item, cls) {
    item = item || {};
    const title = item.title || "";
    if (!item.image) return fallbackHtml(title, cls);
    return `<img class="vl-gift-img ${escAttr(cls || "")}" src="${escAttr(item.image)}" alt="${escAttr(title)}"`
      + ` loading="lazy" decoding="async" width="320" height="320" style="aspect-ratio:1/1"`
      + ` onerror="VLFx.imgFail(this)">`;
  }

  // onerror: swap the <img> for the fallback tile with the same classes (same box, no layout jump)
  function imgFail(img) {
    if (!img || !img.parentNode) return;
    img.onerror = null;
    const extra = Array.from(img.classList).filter((c) => c !== "vl-gift-img").join(" ");
    const tmp = document.createElement("div");
    tmp.innerHTML = fallbackHtml(img.getAttribute("alt") || "", extra);
    img.replaceWith(tmp.firstChild);
  }

  // ------------------------------------------------------------------ 3D tilt
  const MAX_DEG = 8;
  function bindTilt(el) {
    if (el._vlTilt) return;
    el._vlTilt = true;
    let raf = 0, last = null;
    const sheen = el.querySelector("[data-tilt-sheen]");

    const apply = () => {
      raf = 0;
      if (!last) return;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const x = Math.min(1, Math.max(0, (last.x - r.left) / r.width));
      const y = Math.min(1, Math.max(0, (last.y - r.top) / r.height));
      // a long side tilts less around its axis so the far edge never swings out too much
      const degY = MAX_DEG * Math.min(1, 420 / r.width), degX = MAX_DEG * Math.min(1, 420 / r.height);
      const ry = (x - 0.5) * 2 * degY, rx = -(y - 0.5) * 2 * degX;
      el.style.transform = `perspective(1000px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`;
      el.classList.add("is-tilting");
      if (sheen) {
        sheen.style.setProperty("--vl-mx", (x * 100).toFixed(1) + "%");
        sheen.style.setProperty("--vl-my", (y * 100).toFixed(1) + "%");
      }
    };
    const reset = () => {
      last = null;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      el.style.transform = "";
      el.classList.remove("is-tilting");
    };
    const move = (e) => {
      if (e.pointerType && e.pointerType !== "mouse") return;
      if (!canTilt()) { if (el.style.transform) reset(); return; }
      last = { x: e.clientX, y: e.clientY };
      if (!raf) raf = requestAnimationFrame(apply);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", reset);
    el.addEventListener("blur", reset, true);
  }
  function tilt(root) {
    (root || document).querySelectorAll("[data-tilt]").forEach(bindTilt);
  }
  // reduced motion turned on while a card is tilted: drop the tilt now, not on the next pointer move
  rmSubs.add((r) => {
    if (!r) return;
    document.querySelectorAll("[data-tilt].is-tilting").forEach((el) => { el.style.transform = ""; el.classList.remove("is-tilting"); });
  });

  // ------------------------------------------------------------------ numbers
  const fmt = (n) => Math.round(n).toLocaleString("ru-RU");
  function countUp(el, to, ms) {
    if (!el) return;
    to = Number(to) || 0;
    if (el._vlCount) cancelAnimationFrame(el._vlCount);
    el._vlCount = 0;
    const from = Number(String(el.textContent).replace(/[^\d.-]/g, "")) || 0;
    // nothing to watch in a hidden tab (and frames do not run there): set the value at once
    if (reduced() || from === to || document.hidden) { el.textContent = fmt(to); return; }
    const dur = ms == null ? 700 : Math.max(0, ms);
    const t0 = performance.now();
    const step = (t) => {
      const k = dur ? Math.min(1, (t - t0) / dur) : 1;
      const e = 1 - Math.pow(1 - k, 3); // ease-out cubic
      el.textContent = fmt(from + (to - from) * e);
      el._vlCount = k < 1 ? requestAnimationFrame(step) : 0;
    };
    el._vlCount = requestAnimationFrame(step);
  }

  // ------------------------------------------------------------------ list entrance
  const STEP = 40, MAX_STAGGERED = 12;
  function stagger(container) {
    if (!container || reduced()) return;
    const kids = Array.from(container.children);
    kids.forEach((el, i) => {
      if (typeof el.animate !== "function") return;
      el.animate(
        [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }],
        { duration: 260, delay: Math.min(i, MAX_STAGGERED) * STEP, easing: "cubic-bezier(.2,.7,.2,1)", fill: "backwards" }
      );
    });
  }

  // ------------------------------------------------------------------ gift animation (lottie)
  const LOTTIE_URL = "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie_light.min.js";
  // SRI of the exact file (sha384): a changed or tampered build is refused and the static picture stays
  const LOTTIE_SRI = "sha384-Vtbz3QbtSBqleuQry6kQy5smig1gPZCXUoTFN7RmN9QW47xpEDsV/J1w0Pw0rDJu";
  let lottieLib = null; // Promise<lottie> — the script is requested once per page, a failure is remembered too
  function loadLottie() {
    if (!lottieLib) {
      lottieLib = new Promise((resolve, reject) => {
        if (window.lottie && window.lottie.loadAnimation) { resolve(window.lottie); return; }
        const s = document.createElement("script");
        s.src = LOTTIE_URL;
        s.integrity = LOTTIE_SRI;
        s.crossOrigin = "anonymous";
        s.async = true;
        s.onload = () => (window.lottie && window.lottie.loadAnimation ? resolve(window.lottie) : reject(new Error("lottie")));
        s.onerror = () => reject(new Error("lottie script"));
        document.head.appendChild(s);
      });
      lottieLib.catch(() => {}); // a rejected load is handled by every caller; never an unhandled rejection
    }
    return lottieLib;
  }

  function lottie(el, src, opts) {
    const handle = { destroyed: false, anim: null, layer: null };
    // reduced motion switched while playing: stop on the first frame / resume
    const onRm = (r) => {
      const a = handle.anim; if (!a) return;
      if (r) a.goToAndStop(0, true); else a.play();
    };
    const api = {
      destroy() {
        if (handle.destroyed) return;
        handle.destroyed = true;
        rmSubs.delete(onRm);
        try { if (handle.anim) handle.anim.destroy(); } catch (e) {}
        if (handle.layer && handle.layer.parentNode) handle.layer.remove();
        if (el && el.classList) el.classList.remove("vl-anim-on");
        handle.anim = handle.layer = null;
      },
    };
    if (!el || !src) return api;
    const loop = !opts || opts.loop !== false;
    const still = reduced();
    const fail = () => api.destroy(); // the static picture under the layer stays as it is

    // the JSON is fetched here (not by lottie) so a 404 / bad JSON is a clean rejection, not a lottie error event
    Promise.all([loadLottie(), fetch(src, { credentials: "same-origin" }).then((r) => {
      if (!r.ok) throw new Error("anim " + r.status);
      return r.json();
    })]).then(([lib, data]) => {
      if (handle.destroyed || !el.isConnected) return;
      if (!data || !Array.isArray(data.layers)) throw new Error("anim data");
      const layer = document.createElement("div");
      layer.className = "vl-anim";
      layer.setAttribute("aria-hidden", "true");
      el.appendChild(layer);
      handle.layer = layer;
      const anim = lib.loadAnimation({
        container: layer, renderer: "svg", loop, autoplay: !still, animationData: data,
        rendererSettings: { preserveAspectRatio: "xMidYMid slice", progressiveLoad: true },
      });
      handle.anim = anim;
      anim.addEventListener("data_failed", fail);
      anim.addEventListener("error", fail);
      anim.addEventListener("DOMLoaded", () => {
        if (handle.destroyed) return;
        if (reduced()) anim.goToAndStop(0, true);
        rmSubs.add(onRm);
        el.classList.add("vl-anim-on"); // CSS fades the layer in over the picture
      });
    }).catch(fail);
    return api;
  }

  // ------------------------------------------------------------------ screen transition
  const TR_MS = 200;
  const TR_EASE = "cubic-bezier(.2,.7,.2,1)";
  function stopTr(el) {
    if (!el || !el._vlTr) return;
    const t = el._vlTr; el._vlTr = null;
    clearTimeout(t.timer);
    try { t.anim.cancel(); } catch (e) {}
  }
  function transition(from, to) {
    try {
      if (!to) return;
      stopTr(from); stopTr(to);
      if (from && from !== to) from.classList.remove("on");
      to.classList.add("on");
      if (!from || from === to || reduced() || typeof to.animate !== "function") return;
      const anim = to.animate(
        [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }],
        { duration: TR_MS, easing: TR_EASE }
      );
      const t = { anim, timer: 0 };
      to._vlTr = t;
      const done = () => { if (to._vlTr === t) { clearTimeout(t.timer); to._vlTr = null; } };
      anim.onfinish = done; anim.oncancel = done;
      // frames may not run (background tab): never leave the screen half-faded
      t.timer = setTimeout(() => { if (to._vlTr === t) { try { anim.finish(); } catch (e) {} done(); } }, TR_MS + 120);
    } catch (e) {
      if (to) to.classList.add("on");
    }
  }

  // ------------------------------------------------------------------ confetti
  const CONFETTI = { win: { n: 70, ms: 1600 }, jackpot: { n: 140, ms: 2400 } };
  let confettiRun = null; // {canvas, raf, timer} — one burst at a time
  function confettiStop() {
    const c = confettiRun; confettiRun = null;
    if (!c) return;
    if (c.raf) cancelAnimationFrame(c.raf);
    clearTimeout(c.timer);
    if (c.canvas.parentNode) c.canvas.remove();
  }
  rmSubs.add((r) => { if (r) confettiStop(); });
  function confetti(kind) {
    try {
      if (reduced()) return;
      const cfg = CONFETTI[kind] || CONFETTI.win;
      confettiStop();
      const cs = getComputedStyle(document.documentElement);
      const pal = ["--accent", "--accent-2", "--accent-text", "--warn", "--warn"]
        .map((n) => cs.getPropertyValue(n).trim()).filter(Boolean);
      if (!pal.length) return;
      const canvas = document.createElement("canvas");
      canvas.className = "vl-confetti";
      canvas.setAttribute("aria-hidden", "true");
      const W = window.innerWidth, H = window.innerHeight, dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      document.body.appendChild(canvas);
      const ctx = canvas.getContext("2d");
      if (!ctx) { canvas.remove(); return; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // two cannons from the lower corners towards the centre top (jackpot adds a burst from the top centre)
      const parts = [];
      for (let i = 0; i < cfg.n; i++) {
        const src = kind === "jackpot" ? i % 3 : i % 2;
        const x = src === 0 ? W * 0.1 : src === 1 ? W * 0.9 : W * 0.5;
        const y = src === 2 ? H * 0.2 : H * 0.85;
        const ang = src === 2 ? Math.random() * Math.PI * 2
          : (src === 0 ? -Math.PI / 3 : -2 * Math.PI / 3) + (Math.random() - 0.5) * 0.7;
        const sp = (src === 2 ? 3 : 9) + Math.random() * 7;
        parts.push({ x, y, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, r: Math.random() * Math.PI,
          vr: (Math.random() - 0.5) * 0.3, w: 5 + Math.random() * 5, h: 3 + Math.random() * 4,
          c: pal[i % pal.length] });
      }
      const run = { canvas, raf: 0, timer: 0 };
      confettiRun = run;
      const t0 = performance.now();
      let last = t0;
      const frame = (now) => {
        if (confettiRun !== run) return;
        const k = Math.min(3, (now - last) / 16.7); last = now;
        const life = (now - t0) / cfg.ms;
        if (life >= 1) { confettiStop(); return; }
        ctx.clearRect(0, 0, W, H);
        ctx.globalAlpha = life > 0.7 ? (1 - life) / 0.3 : 1;
        for (const p of parts) {
          p.vy += 0.25 * k; p.vx *= Math.pow(0.985, k); p.vy *= Math.pow(0.985, k);
          p.x += p.vx * k; p.y += p.vy * k; p.r += p.vr * k;
          ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
          ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h * Math.abs(Math.cos(p.r * 2)) + 1);
          ctx.restore();
        }
        run.raf = requestAnimationFrame(frame);
      };
      run.raf = requestAnimationFrame(frame);
      run.timer = setTimeout(() => { if (confettiRun === run) confettiStop(); }, cfg.ms + 400);
    } catch (e) {
      try { confettiStop(); } catch (e2) {}
    }
  }

  window.VLFx = { tilt, countUp, stagger, giftImg, imgFail, lottie, transition, confetti };
  window.giftImg = giftImg;
})();

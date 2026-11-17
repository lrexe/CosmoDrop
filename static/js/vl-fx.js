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
*/
(function () {
  "use strict";

  const mq = (q) => (window.matchMedia ? window.matchMedia(q).matches : false);
  const reduced = () => mq("(prefers-reduced-motion: reduce)");
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

  // ------------------------------------------------------------------ numbers
  const fmt = (n) => Math.round(n).toLocaleString("ru-RU");
  function countUp(el, to, ms) {
    if (!el) return;
    to = Number(to) || 0;
    if (el._vlCount) cancelAnimationFrame(el._vlCount);
    el._vlCount = 0;
    const from = Number(String(el.textContent).replace(/[^\d.-]/g, "")) || 0;
    if (reduced() || from === to) { el.textContent = fmt(to); return; }
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
  const LOTTIE_URL = "https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js";
  let lottieLib = null; // Promise<lottie> — the script is requested once per page, a failure is remembered too
  function loadLottie() {
    if (!lottieLib) {
      lottieLib = new Promise((resolve, reject) => {
        if (window.lottie && window.lottie.loadAnimation) { resolve(window.lottie); return; }
        const s = document.createElement("script");
        s.src = LOTTIE_URL;
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
    const api = {
      destroy() {
        if (handle.destroyed) return;
        handle.destroyed = true;
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
        if (still) anim.goToAndStop(0, true);
        el.classList.add("vl-anim-on"); // CSS fades the layer in over the picture
      });
    }).catch(fail);
    return api;
  }

  window.VLFx = { tilt, countUp, stagger, giftImg, imgFail, lottie };
  window.giftImg = giftImg;
})();

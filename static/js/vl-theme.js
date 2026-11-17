/* Vloody theme switch. Load in <head> (after telegram-web-app.js, before <body>) so the right theme
   is on <html data-theme> before the first paint.
   API: window.VLTheme = { get(), set(theme), toggle() }; fires `vl:theme` on document ({detail:{theme}}).
   Choice order: saved choice (localStorage "vl_theme") → Telegram colorScheme → prefers-color-scheme → dark.
   localStorage may throw (Telegram WebView, private mode): every access is guarded, the theme then lives
   in memory for the session. */
(function () {
  "use strict";
  var KEY = "vl_theme";
  // Keep in sync with --bg in static/css/vl-tokens.css (tests/test_contrast.py checks it).
  var BG = { dark: "#070b14", light: "#f5f8fc" };
  var root = document.documentElement;
  var memory = null; // the user's explicit choice when storage is unavailable

  function valid(t) { return t === "dark" || t === "light"; }

  function readSaved() {
    try {
      var v = window.localStorage.getItem(KEY);
      if (valid(v)) return v;
    } catch (e) { /* storage blocked */ }
    return memory;
  }

  function save(t) {
    memory = t;
    try { window.localStorage.setItem(KEY, t); } catch (e) { /* keep in memory only */ }
  }

  function tg() {
    var w = window.Telegram && window.Telegram.WebApp;
    // Outside Telegram the SDK still exists but reports platform "unknown".
    return w && w.platform && w.platform !== "unknown" ? w : null;
  }

  function systemTheme() {
    var w = tg();
    if (w && valid(w.colorScheme)) return w.colorScheme;
    try {
      if (window.matchMedia) {
        if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
        if (window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
      }
    } catch (e) { /* old engines */ }
    return "dark";
  }

  function apply(t) {
    root.setAttribute("data-theme", t);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta && document.head) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      document.head.appendChild(meta);
    }
    if (meta) meta.setAttribute("content", BG[t]);
    var w = tg();
    if (w) {
      try { if (typeof w.setHeaderColor === "function") w.setHeaderColor(BG[t]); } catch (e) { /* old client */ }
      try { if (typeof w.setBackgroundColor === "function") w.setBackgroundColor(BG[t]); } catch (e) { /* old client */ }
    }
  }

  function emit(t) {
    var ev;
    try { ev = new CustomEvent("vl:theme", { detail: { theme: t } }); }
    catch (e) { ev = document.createEvent("CustomEvent"); ev.initCustomEvent("vl:theme", false, false, { theme: t }); }
    document.dispatchEvent(ev);
  }

  function get() {
    var t = root.getAttribute("data-theme");
    return valid(t) ? t : "dark";
  }

  function set(t) {
    if (!valid(t)) return;
    save(t);
    var changed = t !== get();
    apply(t);
    if (changed) emit(t);
  }

  function toggle() { set(get() === "dark" ? "light" : "dark"); }

  // Follow Telegram / OS changes only while the user has not picked a theme.
  function follow() {
    if (readSaved()) return;
    var t = systemTheme();
    if (t !== get()) { apply(t); emit(t); }
  }

  apply(readSaved() || systemTheme());

  try {
    var w = tg();
    if (w && typeof w.onEvent === "function") w.onEvent("themeChanged", follow);
  } catch (e) { /* ignore */ }
  try {
    var mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)");
    if (mq) {
      if (typeof mq.addEventListener === "function") mq.addEventListener("change", follow);
      else if (typeof mq.addListener === "function") mq.addListener(follow);
    }
  } catch (e) { /* ignore */ }

  window.VLTheme = { get: get, set: set, toggle: toggle };
})();

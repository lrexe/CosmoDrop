"""WCAG-контраст токенов дизайн-системы: парсит static/css/vl-tokens.css и проверяет пары текста в обеих темах."""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS = os.path.join(ROOT, "static", "css", "vl-tokens.css")
THEME_JS = os.path.join(ROOT, "static", "js", "vl-theme.js")
AA = 4.5
ok = True

# Пары (текст, фон). on-accent проверяется на обоих концах градиента кнопки: --accent (светлый) и --accent-2 (тёмный).
# Статусные цвета и accent-text стоят и на фоне страницы, и на --surface-2 (плашки, тосты, строки списков).
PAIRS = [
    ("text", "bg"), ("muted", "bg"),
    ("text", "surface"), ("muted", "surface"),
    ("text", "surface-2"), ("muted", "surface-2"),
    ("on-accent", "accent"), ("on-accent", "accent-2"),
    ("accent-text", "bg"), ("accent-text", "surface"), ("accent-text", "surface-2"),
    ("success", "bg"), ("success", "surface"), ("success", "surface-2"),
    ("warn", "bg"), ("warn", "surface"), ("warn", "surface-2"),
    ("danger", "bg"), ("danger", "surface"), ("danger", "surface-2"),
]
# Полупрозрачные фоны: (текст, фон, подложки, на которых этот фон встречается). --field — поле ввода,
# muted на нём — плейсхолдер; поле лежит на странице, на карточке и на --surface-2.
OVER_PAIRS = [
    ("muted", "field", ("bg", "surface", "surface-2")),
    ("text", "field", ("bg", "surface", "surface-2")),
]
REQUIRED = ["bg", "bg-glow", "surface", "surface-2", "vl-line", "text", "muted", "accent", "accent-2",
            "on-accent", "accent-text", "success", "warn", "danger", "shadow-1", "shadow-2", "shadow-cta",
            "focus", "field", "r-sm", "r-md", "r-lg", "font", "vl-mono"]


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def blocks(css):
    """[(selector_list, {var: value})] для каждого верхнеуровневого правила с custom properties."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = [s.strip() for s in m.group(1).split(",")]
        decls = {}
        for d in re.finditer(r"--([\w-]+)\s*:\s*([^;]+);?", m.group(2)):
            decls[d.group(1)] = d.group(2).strip()
        if decls:
            out.append((sel, decls))
    return out


def theme_vars(bl, theme):
    """Общий блок `:root { }` (только этот селектор) + блок темы; тема перекрывает общий."""
    want = ':root[data-theme="%s"]' % theme
    res = {}
    for sel, decls in bl:
        if sel == [":root"]:
            res.update(decls)
    for sel, decls in bl:
        if want in [s.replace("'", '"') for s in sel]:
            res.update(decls)
    return res


def hex_rgb(v):
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v.strip())
    if not m:
        return None
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgba(v):
    """#rrggbb или rgba(r, g, b, a) -> ((r, g, b) 0..1, alpha); иначе None."""
    c = hex_rgb(v)
    if c is not None:
        return c, 1.0
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", v.strip())
    if not m:
        return None
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return tuple(int(m.group(i)) / 255 for i in (1, 2, 3)), a


def over(top, base):
    """Цвет полупрозрачного top поверх непрозрачной подложки base."""
    (c, a) = top
    return tuple(c[i] * a + base[i] * (1 - a) for i in range(3))


def lum(rgb):
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main():
    check("vl-tokens.css exists", os.path.isfile(TOKENS), "static/css/vl-tokens.css")
    if not os.path.isfile(TOKENS):
        print("SOME FAILED")
        return 1
    with open(TOKENS, encoding="utf-8") as f:
        css = strip_comments(f.read())
    bl = blocks(css)
    # Без атрибута data-theme действуют все блоки с селектором `:root` (по порядку). Каждое значение тёмной темы
    # должно получиться и так: если кто-то разнесёт `:root` и `:root[data-theme="dark"]` и значения разойдутся — FAIL.
    plain = {}
    for sel, decls in bl:
        if ":root" in sel:
            plain.update(decls)
    dark = theme_vars(bl, "dark")
    diff = [k for k in dark if plain.get(k) != dark[k]]
    check("plain :root falls back to dark", dark and not diff,
          ", ".join(f"--{k}: {plain.get(k)!r} vs dark {dark[k]!r}" for k in diff))
    light = theme_vars(bl, "light")
    check("light theme differs from the plain-:root fallback", light.get("bg") and light.get("bg") != plain.get("bg"),
          f"{light.get('bg')} vs {plain.get('bg')}")
    for theme in ("dark", "light"):
        v = theme_vars(bl, theme)
        missing = [k for k in REQUIRED if k not in v]
        check(f"{theme}: all tokens defined", not missing, ",".join(missing))
        for fg, bg in PAIRS:
            a, b = hex_rgb(v.get(fg, "")), hex_rgb(v.get(bg, ""))
            if a is None or b is None:
                check(f"{theme}: {fg}/{bg} are #rrggbb", False, f"{v.get(fg)!r} / {v.get(bg)!r}")
                continue
            r = ratio(a, b)
            check(f"{theme}: {fg}/{bg} >= {AA}", r >= AA, f"{v[fg]} on {v[bg]} = {r:.2f}")
        for fg, bg, bases in OVER_PAIRS:
            a, top = hex_rgb(v.get(fg, "")), rgba(v.get(bg, ""))
            if a is None or top is None:
                check(f"{theme}: {fg}/{bg} parse", False, f"{v.get(fg)!r} / {v.get(bg)!r}")
                continue
            for base in bases:
                b = hex_rgb(v.get(base, ""))
                if b is None:
                    check(f"{theme}: {base} is #rrggbb", False, repr(v.get(base)))
                    continue
                r = ratio(a, over(top, b))
                check(f"{theme}: {fg}/{bg} (on {base}) >= {AA}", r >= AA, f"{v[fg]} on {v[bg]} over {v[base]} = {r:.2f}")
        # <meta name="theme-color"> / Telegram header colour in vl-theme.js must match --bg.
        js = ""
        if os.path.isfile(THEME_JS):
            with open(THEME_JS, encoding="utf-8") as f:
                js = f.read()
        m = re.search(r"\b%s\s*:\s*\"(#[0-9a-fA-F]{6})\"" % theme, js)
        check(f"{theme}: vl-theme.js header colour == --bg", m and m.group(1).lower() == v.get("bg", "").lower(),
              f"{m.group(1) if m else None} vs {v.get('bg')}")
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

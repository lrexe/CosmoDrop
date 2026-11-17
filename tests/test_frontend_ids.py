"""Static consistency of the front end (no browser): every id / data-act / sprite icon that the JS or the markup
refers to actually exists. Catches the typo class of bug (a renamed id, a deleted icon, an action without a handler)
that otherwise only shows up as a dead button in the Telegram client.

Usage: python tests/test_frontend_ids.py [repo_root]
"""
import collections
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


JS_FILES = ["static/js/vloody.js", "static/js/vl-fx.js", "static/js/vl-theme.js"]
js = {f: read(f) for f in JS_FILES}
vloody_html = read("templates/vloody.html")
admin_html = read("templates/admin.html")
icons_html = read("templates/_icons.html")
all_js = "\n".join(js.values())

# ---------------------------------------------------------------- (i) ids referenced from JS exist
# Only plain string literals are checked ($("x"), getElementById("x"), querySelector("#x ...")); computed ids
# ($("sc-" + screen), template strings) are out of reach of a static check.
refs = collections.defaultdict(set)   # id -> files
for fname, src in js.items():
    for m in re.finditer(r"""(?<![\w$])\$\(\s*["']([A-Za-z][\w-]*)["']\s*\)""", src):
        refs[m.group(1)].add(fname)
    for m in re.finditer(r"""getElementById\(\s*["']([A-Za-z][\w-]*)["']\s*\)""", src):
        refs[m.group(1)].add(fname)
    for m in re.finditer(r"""querySelector(?:All)?\(\s*(["'])(.*?)\1\s*\)""", src):
        for idm in re.finditer(r"#([A-Za-z][\w-]*)", m.group(2)):
            refs[idm.group(1)].add(fname)

html_ids = set(re.findall(r'\bid="([^"{}]+)"', vloody_html + "\n" + icons_html))

# Ids that exist only at run time (created by JS, so not in the markup). Keep this list as small as possible and
# say WHY each one is here.
JS_CREATED_IDS = set()  # none at the moment: every id the scripts look up is in templates/vloody.html or _icons.html
missing = sorted(i for i in refs if i not in html_ids and i not in JS_CREATED_IDS)
check("js references %d distinct ids; all exist in the markup (or the JS-created allow-list)" % len(refs),
      not missing, ["%s (in %s)" % (i, ", ".join(sorted(refs[i]))) for i in missing])
stale = sorted(JS_CREATED_IDS - set(refs))
check("allow-list has no stale entries", not stale, stale)
check("sanity: the scan actually found ids (> 100)", len(refs) > 100, len(refs))

# ---------------------------------------------------------------- (ii) duplicate ids
for name, src in (("templates/vloody.html", vloody_html), ("templates/admin.html", admin_html)):
    ids = re.findall(r'\bid="([^"{}]+)"', src)
    dup = sorted(i for i, n in collections.Counter(ids).items() if n > 1)
    check("no duplicate ids in %s (%d ids)" % (name, len(ids)), not dup, dup)

# ---------------------------------------------------------------- (iii) data-act <-> ACTIONS table
m = re.search(r"const ACTIONS = \{(.*?)\n  \};", js["static/js/vloody.js"], re.S)
check("ACTIONS table found in vloody.js", bool(m))
action_keys = set(re.findall(r'(?:^|[{,\s])"([a-z][a-z0-9-]*)"\s*:', m.group(1))) if m else set()
used_acts = set(re.findall(r'data-act="([A-Za-z][\w-]*)"', vloody_html)) | set(
    re.findall(r'data-act="([A-Za-z][\w-]*)"', all_js))
no_handler = sorted(used_acts - action_keys)
check("every data-act used in the markup / JS markup has an ACTIONS entry (%d used, %d handlers)"
      % (len(used_acts), len(action_keys)), not no_handler, no_handler)
# ACTIONS keys that are legitimately not referenced as a literal data-act anywhere (say why):
UNUSED_ACTIONS_OK = set()  # none at the moment
dead = sorted(action_keys - used_acts - UNUSED_ACTIONS_OK)
check("every ACTIONS key is used by some data-act (no dead handlers)", not dead, dead)

# ---------------------------------------------------------------- (iv) sprite icons
symbols = set(re.findall(r'<symbol\b[^>]*\bid="(i-[\w-]+)"', icons_html))
used_icons = set(re.findall(r'href="#(i-[\w-]+)"', vloody_html)) | set(re.findall(r'href="#(i-[\w-]+)"', all_js))
# icon("i-x") helper calls and "i-x" literals in maps / arrays inside the scripts
used_icons |= set(re.findall(r"""["'](i-[a-z][\w-]*)["']""", all_js))
bad_icons = sorted(used_icons - symbols)
check("every icon reference (<use href=\"#i-…\">, icon(\"i-…\"), \"i-…\" tables) has a <symbol> in _icons.html "
      "(%d used, %d symbols)" % (len(used_icons), len(symbols)), not bad_icons, bad_icons)
check("sanity: symbols were found", len(symbols) > 20, len(symbols))

# ---------------------------------------------------------------- (v) code swallowed by a trailing // comment
# Regression class: `a(); // note b = 1;` — the statement after the comment never runs. Conservative heuristic: find a
# `//` that is outside quotes/backticks and not part of a URL (`://`), and flag it only if an assignment-looking
# statement (`ident = value;`) follows on the same line.
def comment_start(line):
    q = None
    i = 0
    while i < len(line):
        ch = line[i]
        if q:
            if ch == "\\":
                i += 1
            elif ch == q:
                q = None
        elif ch in "\"'`":
            q = ch
        elif line.startswith("//", i) and not (i and line[i - 1] == ":"):
            return i
        i += 1
    return -1


swallowed = []
for fname, src in js.items():
    for n, line in enumerate(src.splitlines(), 1):
        i = comment_start(line)
        if i > 0 and line[:i].strip() and re.search(r"[A-Za-z_$][\w$.]*\s*=\s*[^=\s>][^;]*;\s*$", line[i + 2:]):
            swallowed.append("%s:%d: %s" % (fname, n, line.strip()[:110]))
check("no executable-looking assignment hides inside a trailing // comment", not swallowed, swallowed)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

"""Быстрая отдача фронтенда: один CSS и один JS вместо десяти файлов, сжатие gzip, долгий кэш.

Через туннель/мобильную сеть каждый запрос стоит сотни миллисекунд, поэтому главное — меньше запросов
и меньше байт. Бандлы собираются при старте из исходников в static/, имя файла содержит хэш содержимого,
поэтому их можно кэшировать «навсегда»: при любом изменении адрес меняется сам.
"""
import gzip
import hashlib
import os

from flask import abort, request

CSS = ["vl-tokens", "vl-base", "vl-shell", "vl-cards", "vl-rounds", "vl-screens", "vl-overlays"]
JS = ["vl-fx", "vloody"]
COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml")


def _read(base, sub, names, ext):
    parts = []
    for n in names:
        with open(os.path.join(base, "static", sub, n + ext), encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts).encode("utf-8")


def build(base):
    """-> (urls, files): urls = {'css': '/b/<хэш>.css', 'js': ...}, files = {имя: (сырой, gzip, mime)}."""
    files, urls = {}, {}
    for kind, names, sub, ext, mime in (("css", CSS, "css", ".css", "text/css; charset=utf-8"),
                                        ("js", JS, "js", ".js", "application/javascript; charset=utf-8")):
        raw = _read(base, sub, names, ext)
        name = hashlib.sha1(raw).hexdigest()[:12] + "." + kind
        files[name] = (raw, gzip.compress(raw, 9, mtime=0), mime)
        urls[kind] = "/b/" + name
    inline_theme = _read(base, "js", ["vl-theme"], ".js").decode("utf-8")
    return urls, files, inline_theme


def init_assets(app, base):
    urls, files, theme = build(base)

    @app.route("/b/<name>")
    def bundle(name):
        item = files.get(name)
        if not item:
            abort(404)
        raw, packed, mime = item
        use_gz = "gzip" in request.headers.get("Accept-Encoding", "")
        resp = app.response_class(packed if use_gz else raw, mimetype=mime.split(";")[0])
        resp.headers["Content-Type"] = mime
        resp.headers["Vary"] = "Accept-Encoding"
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        if use_gz:
            resp.headers["Content-Encoding"] = "gzip"
        return resp

    @app.context_processor
    def inject_assets():
        return {"BUNDLE_CSS": urls["css"], "BUNDLE_JS": urls["js"], "THEME_JS": theme}

    @app.after_request
    def compress(resp):
        # JSON и HTML сжимаем на лету; готовые бандлы и уже сжатое не трогаем
        if (resp.direct_passthrough or resp.status_code != 200 or "Content-Encoding" in resp.headers
                or "gzip" not in request.headers.get("Accept-Encoding", "")
                or not (resp.mimetype or "").startswith(COMPRESSIBLE)):
            return resp
        data = resp.get_data()
        if len(data) < 600:
            return resp
        resp.set_data(gzip.compress(data, 6, mtime=0))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
        return resp

    return urls

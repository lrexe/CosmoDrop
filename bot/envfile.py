"""Загрузка секретов из файла .env в корне проекта (без сторонних библиотек).

Формат: KEY=VALUE, по одной паре на строку; строки с # — комментарии.
Переменные, уже заданные в окружении, не перезаписываются.
"""

import os

LOADED = {}      # что именно взято из .env (а не задано снаружи)
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def load_env(path=ENV_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        key = key.strip()
        if key not in os.environ:
            LOADED[key] = value
        os.environ.setdefault(key, value)
    return True


def current(key, default=""):
    """Значение, взятое из .env, перечитывается на лету (сторож туннеля меняет PUBLIC_URL без перезапуска);
    заданное снаружи окружением не трогаем."""
    value = os.environ.get(key, default)
    if key in LOADED and value == LOADED[key]:
        try:
            with open(ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    if line.startswith(key + "="):
                        fresh = line.split("=", 1)[1].strip()
                        LOADED[key] = os.environ[key] = fresh
                        return fresh
        except OSError:
            pass
    return value

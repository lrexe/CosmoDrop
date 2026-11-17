"""Загрузка секретов из файла .env в корне проекта (без сторонних библиотек).

Формат: KEY=VALUE, по одной паре на строку; строки с # — комментарии.
Переменные, уже заданные в окружении, не перезаписываются.
"""

import os

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
        os.environ.setdefault(key.strip(), value)
    return True

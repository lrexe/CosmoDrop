"""Сторож временного туннеля (localhost.run): сам переподнимает его и перепривязывает бота.

Бесплатный туннель периодически падает и меняет адрес. Этот скрипт:
  1. открывает туннель на локальный сервер;
  2. ловит новый https-адрес и запускает `python -m bot.setup_main <адрес>` (вебхук, меню, PUBLIC_URL);
  3. каждые 20 секунд проверяет адрес снаружи; если не отвечает — всё повторяет.

Запуск:  python -m bot.tunnel_watch            (порт берётся из PORT, по умолчанию 5000)
Это временная мера для разработки: для боя нужен постоянный домен.
"""
import os
import re
import subprocess
import sys
import queue
import threading
import time
import urllib.request

PORT = os.getenv("PORT", "5000")
URL_RE = re.compile(r"https://[a-z0-9.]+\.lhr\.life")
CHECK_EVERY = 20
FAILS_TO_RESTART = 2


def alive(url):
    try:
        with urllib.request.urlopen(url + "/health", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def run_once():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=15",
           "-o", "ServerAliveCountMax=2", "-o", "ExitOnForwardFailure=yes",
           "-R", f"80:127.0.0.1:{PORT}", "nokey@localhost.run"]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    # вывод ssh читает отдельный поток: так ожидание адреса ограничено по времени (ssh может молчать),
    # а канал не забивается баннером/QR — иначе ssh встаёт и туннель «зависает»
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout], daemon=True).start()
    url = None
    deadline = time.time() + 40
    while url is None and time.time() < deadline and proc.poll() is None:
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            continue
        m = URL_RE.search(re.sub(r"\x1b\[[0-9;]*m", "", line))
        if m:
            url = m.group(0)
    if not url:
        log("адрес туннеля не получен за 40 с — новая попытка")
        proc.kill()
        return
    log(f"туннель: {url}")
    time.sleep(3)
    try:
        res = subprocess.run([sys.executable, "-m", "bot.setup_main", url], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        log("бот перепривязан" if res.returncode == 0 else "setup_main: " + (res.stdout + res.stderr)[-200:])
    except subprocess.TimeoutExpired:
        log("setup_main не ответил за 60 с — перепривяжу при следующем перезапуске")
    fails = 0
    while proc.poll() is None:
        time.sleep(CHECK_EVERY)
        fails = 0 if alive(url) else fails + 1
        if fails >= FAILS_TO_RESTART:
            log("туннель не отвечает — перезапуск")
            break
    proc.kill()


def main():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            return
        except Exception as e:                      # сторож не должен падать
            log(f"ошибка: {e}")
        time.sleep(3)


if __name__ == "__main__":
    main()

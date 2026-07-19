"""
NOTAM Watchdog — Vigila sync_daemon.py y lo reinicia si muere.
- Heartbeat: daemon escribe timestamp cada ciclo
- Si heartbeat > 5 min stale O proceso muere, reinicia
- Nunca muere: loop de monitoreo con timeout
"""

import os
import sys
import time
import subprocess
import logging

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_watchdog.log")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(SCRIPT_DIR, "sync_daemon.py")
HEARTBEAT = os.path.join(SCRIPT_DIR, "data", "heartbeat.txt")

RESTART_DELAY = 10
MAX_QUICK_RESTARTS = 5
QUICK_RESTART_WINDOW = 300
HEARTBEAT_TIMEOUT = 300
POLL_INTERVAL = 30

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("watchdog")


def write_heartbeat():
    try:
        os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
        with open(HEARTBEAT, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def heartbeat_age():
    try:
        with open(HEARTBEAT, "r") as f:
            return time.time() - float(f.read().strip())
    except Exception:
        return float("inf")


def start_daemon():
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", DAEMON],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            cwd=SCRIPT_DIR,
        )
        log.info("Daemon PID %d arrancado", proc.pid)
        return proc
    except Exception as e:
        log.error("No se pudo iniciar daemon: %s", e)
        return None


def main():
    log.info("=" * 50)
    log.info("NOTAM Watchdog iniciado")
    log.info("=" * 50)

    quick_restarts = []
    proc = start_daemon()
    if not proc:
        time.sleep(RESTART_DELAY)

    while True:
        time.sleep(POLL_INTERVAL)

        if proc is None:
            proc = start_daemon()
            if not proc:
                time.sleep(RESTART_DELAY)
                continue

        poll = proc.poll()

        if poll is not None:
            log.error("Daemon PID %d murio (exit %d). Reiniciando...", proc.pid, poll)
            quick_restarts.append(time.time())
            proc = None
            time.sleep(RESTART_DELAY)
            continue

        age = heartbeat_age()
        if age > HEARTBEAT_TIMEOUT:
            log.error("Heartbeat stale %.0fs (> %ds). Matando daemon...", age, HEARTBEAT_TIMEOUT)
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
            quick_restarts.append(time.time())
            proc = None
            time.sleep(RESTART_DELAY)
            continue

        now = time.time()
        quick_restarts = [t for t in quick_restarts if now - t < QUICK_RESTART_WINDOW]
        if len(quick_restarts) >= MAX_QUICK_RESTARTS:
            log.warning("Demasiados restarts. Pausa 5min.")
            time.sleep(300)
            quick_restarts.clear()


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log.error("Watchdog crash: %s — reiniciando en 10s", e)
            time.sleep(10)

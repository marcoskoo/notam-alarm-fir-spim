"""
NOTAM Watchdog — Vigila sync_daemon.py y lo reinicia si muere.
Nivel 1: sync_daemon.py ya maneja crashes del scraper (while True + try/except).
Nivel 2: Este watchdog maneja crashes del daemon mismo (OOM, segfault, Windows kill, etc.)

Se ejecuta como VBS en Startup. Nunca muere.
"""

import os
import sys
import time
import subprocess
import logging

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_watchdog.log")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(SCRIPT_DIR, "sync_daemon.py")

RESTART_DELAY = 10
MAX_QUICK_RESTARTS = 5
QUICK_RESTART_WINDOW = 300

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("watchdog")


def is_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def main():
    log.info("=" * 50)
    log.info("NOTAM Watchdog iniciado — vigila sync_daemon.py")
    log.info("=" * 50)

    quick_restarts = []
    proc = None

    while True:
        now = time.time()
        quick_restarts = [t for t in quick_restarts if now - t < QUICK_RESTART_WINDOW]

        if len(quick_restarts) >= MAX_QUICK_RESTARTS:
            wait = 300
            log.warning("Demasiados restarts rapidos (%d en %ds). Pausa %ds.",
                        len(quick_restarts), QUICK_RESTART_WINDOW, wait)
            time.sleep(wait)
            quick_restarts.clear()

        log.info("Iniciando sync_daemon.py...")

        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", DAEMON],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
                cwd=SCRIPT_DIR,
            )
            log.info("Daemon PID %d arrancado", proc.pid)
        except Exception as e:
            log.error("No se pudo iniciar daemon: %s", e)
            time.sleep(RESTART_DELAY)
            continue

        exit_code = proc.wait()

        if exit_code == 0:
            log.info("Daemon PID %d termino limpiamente (exit 0). Reiniciando...", proc.pid)
        else:
            log.error("Daemon PID %d murio con exit code %d. Reiniciando en %ds...",
                      proc.pid, exit_code, RESTART_DELAY)

        quick_restarts.append(time.time())
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()

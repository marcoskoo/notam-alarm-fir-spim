"""
NOTAM Watchdog — reinicia sync_daemon.py si muere.
Ejecutar con: python watchdog.py
"""

import os
import sys
import time
import subprocess
import logging

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_watchdog.log")
DAEMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_daemon.py")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("watchdog")

console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [WATCHDOG] %(message)s", "%H:%M:%S"))
log.addHandler(console)

MAX_RESTART_DELAY = 300


def start_daemon():
    """Inicia sync_daemon.py como subprocess."""
    log.info("Iniciando daemon: %s", DAEMON)
    proc = subprocess.Popen(
        [sys.executable, DAEMON],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info("Daemon PID: %d", proc.pid)
    return proc


def main():
    restart_count = 0
    proc = None

    while True:
        if proc is None or proc.poll() is not None:
            if proc:
                exit_code = proc.returncode
                log.warning("Daemon murio (exit code %d). Reiniciando...", exit_code)
            else:
                log.info("Iniciando daemon...")

            restart_count += 1
            proc = start_daemon()

            if restart_count > 1:
                delay = min(MAX_RESTART_DELAY, 10 * restart_count)
                log.info("Esperando %ds antes de monitorear...", delay)
                time.sleep(delay)
            else:
                time.sleep(5)
        else:
            time.sleep(10)


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("NOTAM Watchdog iniciado")
    log.info("Daemon: %s", DAEMON)
    log.info("=" * 50)
    main()

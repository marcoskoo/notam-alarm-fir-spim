"""
NOTAM Sync Daemon — proceso auto-renacente.
- Ejecuta scraper como SUBPROCESS con kill forzado por timer
- Si el subprocess muere, lo reinicia con backoff
- VBS en Startup lo arranca al login
"""

import os
import sys
import time
import signal
import threading
import subprocess
import logging

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_sync.log")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER = os.path.join(SCRIPT_DIR, "scraper.py")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("sync")

INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))
MAX_DELAY = 300
SCRAPER_TIMEOUT = 90


def _force_kill_pid(pid):
    """Mata un PID y sus hijos de forma agresiva."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=10,
            creationflags=0x08000000,
        )
    except Exception:
        pass


def _kill_chromium():
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chromium.exe"],
            capture_output=True, timeout=5,
            creationflags=0x08000000,
        )
    except Exception:
        pass


def run_scraper_subprocess():
    """Ejecuta scraper.py como subprocess con kill forzado por timer."""
    log.info("Ejecutando scraper...")

    proc = subprocess.Popen(
        [sys.executable, SCRAPER],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=0x08000000,
        cwd=SCRIPT_DIR,
    )

    killed = threading.Event()

    def timeout_kill():
        log.error("Scraper tardo %ds — matando PID %d", SCRAPER_TIMEOUT, proc.pid)
        killed.set()
        _force_kill_pid(proc.pid)
        _kill_chromium()

    timer = threading.Timer(SCRAPER_TIMEOUT, timeout_kill)
    timer.daemon = True
    timer.start()

    try:
        stdout, _ = proc.communicate()
    except Exception:
        pass
    finally:
        timer.cancel()

    if killed.is_set():
        return False

    if stdout:
        for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
            if line.strip():
                log.info("[scraper] %s", line.strip())

    if proc.returncode != 0:
        log.error("Scraper fallo exit code %d", proc.returncode)
        return False

    return True


def main():
    log.info("=" * 50)
    log.info("NOTAM Sync Daemon iniciado")
    log.info("Intervalo: %ds", INTERVAL)
    log.info("Timeout scraper: %ds", SCRAPER_TIMEOUT)
    log.info("=" * 50)

    consecutive_failures = 0

    while True:
        try:
            success = run_scraper_subprocess()

            if success:
                consecutive_failures = 0
                log.info("Proximo sync en %ds...", INTERVAL)
                time.sleep(INTERVAL)
            else:
                consecutive_failures += 1
                wait = min(MAX_DELAY, 10 * consecutive_failures)
                log.warning("Fallo #%d — reintentando en %ds", consecutive_failures, wait)
                time.sleep(wait)

        except KeyboardInterrupt:
            log.info("Saliendo.")
            break
        except Exception as e:
            log.error("Excepcion en daemon: %s", e)
            consecutive_failures += 1
            wait = min(MAX_DELAY, 10 * consecutive_failures)
            time.sleep(wait)


if __name__ == "__main__":
    main()

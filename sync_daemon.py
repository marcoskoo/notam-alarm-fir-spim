"""
NOTAM Sync Daemon — ultra-resiliente.
- Ejecuta scraper.py como subprocess con timeout del sistema
- Si se cuelga, taskkill mata todo el arbol
- Si el daemon muere, VBS lo revive al login
"""

import os
import sys
import time
import subprocess
import logging

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_sync.log")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER = os.path.join(SCRIPT_DIR, "scraper.py")
HEARTBEAT = os.path.join(SCRIPT_DIR, "data", "heartbeat.txt")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("sync")

INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))
MAX_DELAY = 300
SCRAPER_TIMEOUT = 120


def _kill_all_chromium():
    """Mata TODOS los procesos chromium en el sistema (seguro: solo chromium)."""
    subprocess.run(
        ["taskkill", "/F", "/IM", "chromium.exe"],
        capture_output=True, timeout=10,
        creationflags=0x08000000,
    )


def run_scraper_subprocess():
    """Ejecuta scraper.py y lo mata si excede timeout."""
    log.info("Ejecutando scraper...")
    proc = subprocess.Popen(
        [sys.executable, "-u", SCRAPER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
        cwd=SCRIPT_DIR,
    )

    deadline = time.time() + SCRAPER_TIMEOUT
    while time.time() < deadline:
        ret = proc.poll()
        if ret is not None:
            if ret != 0:
                log.error("Scraper exit code %d", ret)
                _kill_all_chromium()
                return False
            return True
        time.sleep(2)

    log.error("Scraper timeout (%ds) — matando PID %d", SCRAPER_TIMEOUT, proc.pid)
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    _kill_all_chromium()
    return False


def main():
    log.info("=" * 50)
    log.info("NOTAM Sync Daemon iniciado")
    log.info("Intervalo: %ds | Timeout: %ds", INTERVAL, SCRAPER_TIMEOUT)
    log.info("=" * 50)

    consecutive_failures = 0

    while True:
        try:
            success = run_scraper_subprocess()
            try:
                os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
                with open(HEARTBEAT, "w") as f:
                    f.write(str(time.time()))
            except Exception:
                pass
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
    while True:
        try:
            main()
        except Exception as e:
            log.error("Daemon crash fatal: %s — reiniciando en 10s", e)
            time.sleep(10)

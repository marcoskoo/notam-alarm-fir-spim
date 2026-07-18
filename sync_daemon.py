"""
NOTAM Sync Daemon — proceso auto-renacente.
- Ejecuta scraper como SUBPROCESS para aislar crashes de Playwright
- Si el subprocess muere, lo reinicia con backoff
- VBS en Startup lo arranca al login
"""

import os
import sys
import time
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


def _kill_chromium():
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                capture_output=True, timeout=5,
                creationflags=0x08000000,
            )
    except Exception:
        pass


def run_scraper_subprocess():
    """Ejecuta scraper.py como subprocess aislado."""
    log.info("Ejecutando scraper...")
    try:
        result = subprocess.run(
            [sys.executable, SCRAPER],
            capture_output=True, text=True, timeout=120,
            creationflags=0x08000000,
            cwd=SCRIPT_DIR,
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    log.info("[scraper] %s", line.strip())
        if result.returncode != 0:
            log.error("Scraper fallo con exit code %d", result.returncode)
            if result.stderr:
                log.error("stderr: %s", result.stderr[-500:])
            _kill_chromium()
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("Scraper tardo mas de 120s — matando chromium")
        _kill_chromium()
        return False
    except Exception as e:
        log.error("Error ejecutando scraper: %s", e)
        _kill_chromium()
        return False


def main():
    log.info("=" * 50)
    log.info("NOTAM Sync Daemon iniciado")
    log.info("Intervalo: %ds", INTERVAL)
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

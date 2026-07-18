"""
NOTAM Sync Daemon — proceso auto-renacente.
- Ejecuta scraper como SUBPROCESS con taskkill /T para matar arbol completo
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
SCRAPER_TIMEOUT = 90


def _kill_tree(pid):
    """Mata un proceso y todos sus hijos (chromium, etc)."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
                creationflags=0x08000000,
            )
        else:
            import os, signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


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
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, SCRAPER],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=0x08000000,
            cwd=SCRIPT_DIR,
        )
        try:
            stdout, _ = proc.communicate(timeout=SCRAPER_TIMEOUT)
        except subprocess.TimeoutExpired:
            log.error("Scraper tardo %ds — matando arbol de procesos PID %d", SCRAPER_TIMEOUT, proc.pid)
            _kill_tree(proc.pid)
            _kill_chromium()
            return False

        if stdout:
            for line in stdout.strip().split("\n"):
                if line.strip():
                    log.info("[scraper] %s", line.strip())

        if proc.returncode != 0:
            log.error("Scraper fallo con exit code %d", proc.returncode)
            return False
        return True

    except Exception as e:
        log.error("Error ejecutando scraper: %s", e)
        if proc and proc.poll() is None:
            _kill_tree(proc.pid)
        _kill_chromium()
        return False


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

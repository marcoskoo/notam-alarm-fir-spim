"""
NOTAM Sync Daemon — proceso auto-renacente.
- Scraping cada 60s con retry interno
- Si el loop muere (excepcion no capturada), se reinicia automaticamente
- Logging a archivo
- VBS en Startup lo arranca al login
"""

import os
import sys
import time
import json
import signal
import urllib.request
import logging
import traceback
import subprocess

LOG_FILE = os.path.join(os.environ.get("TEMP", "."), "notam_sync.log")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
log = logging.getLogger("sync")

console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
log.addHandler(console)

from scraper import run_scraper, upload_to_server

INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))
MAX_RESTART_DELAY = 300


def _kill_chromium():
    """Mata procesos Chromium zombie que Playwright dejo."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def sync_cycle():
    """Un ciclo: scrape + upload. Retorna True si exitoso."""
    try:
        log.info("Ejecutando scraper...")
        data = run_scraper(headless=True)
        notams = data.get("notams", [])
        log.info("Scraping OK — %d NOTAMs", len(notams))

        log.info("Subiendo a servidores...")
        upload_to_server(data)
        log.info("Upload completo")
        return True

    except Exception as e:
        log.error("Error en ciclo: %s", e)
        log.error(traceback.format_exc())
        _kill_chromium()
        return False


def sync_loop():
    """Loop principal: scrape cada 60s, auto-restart si algo explota."""
    consecutive_failures = 0

    while True:
        try:
            success = sync_cycle()

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                wait = min(30, 10 * consecutive_failures)
                log.warning("Fallos consecutivos: %d — esperando %ds", consecutive_failures, wait)
                time.sleep(wait)
                continue

            log.info("Proximo sync en %ds...", INTERVAL)
            time.sleep(INTERVAL)

        except KeyboardInterrupt:
            log.info("Interrupcion manual. Saliendo.")
            break
        except Exception as e:
            log.error("Excepcion no capturada en loop: %s", e)
            log.error(traceback.format_exc())
            _kill_chromium()
            consecutive_failures += 1
            wait = min(MAX_RESTART_DELAY, 10 * consecutive_failures)
            log.warning("Reintentando en %ds...", wait)
            time.sleep(wait)


def watchdog_loop():
    """Auto-restart: si sync_loop() muere, lo reinicia."""
    log.info("=" * 50)
    log.info("NOTAM Daemon (watchdog integrado) iniciado")
    log.info("Intervalo: %ds", INTERVAL)
    log.info("Servidores: %s", ", ".join([
        "https://notam-alarm1.up.railway.app",
        "https://notam-alarm.up.railway.app",
    ]))
    log.info("=" * 50)

    restart_count = 0

    while True:
        try:
            restart_count += 1
            if restart_count > 1:
                delay = min(MAX_RESTART_DELAY, 10 * restart_count)
                log.info("Daemon reiniciado (#%d). Esperando %ds...", restart_count, delay)
                time.sleep(delay)

            sync_loop()
            log.info("Loop terminado inesperadamente. Reiniciando...")

        except KeyboardInterrupt:
            log.info("Saliendo.")
            break
        except Exception as e:
            log.error("Watchdog error: %s", e)
            log.error(traceback.format_exc())
            _kill_chromium()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    watchdog_loop()

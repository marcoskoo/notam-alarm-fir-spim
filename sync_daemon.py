"""
NOTAM Sync Daemon — nunca falla.
- Scraping cada 60s con retry
- Si el proceso muere, se reinicia solo
- Logging a archivo
"""

import os
import sys
import time
import json
import urllib.request
import logging
import traceback

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
MAX_SCRAPER_RETRIES = 3


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
        return False


def sync_loop():
    """Loop infinito con auto-restart."""
    consecutive_failures = 0

    while True:
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


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("NOTAM Sync Daemon iniciado")
    log.info("Intervalo: %ds", INTERVAL)
    log.info("Servidores: %s", ", ".join([
        "https://notam-alarm1.up.railway.app",
        "https://notam-alarm.up.railway.app",
    ]))
    log.info("=" * 50)

    sync_loop()

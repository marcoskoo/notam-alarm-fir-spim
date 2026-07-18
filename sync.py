"""
NOTAM Sync — Ejecuta el scraper cada 60 segundos y sube los datos a Railway.
Ejecutar en la red de CORPAC (Perú).
"""

import os
import sys
import time
import json
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from scraper import run_scraper

INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))

REMOTE_URLS = [
    os.environ.get("NOTAM_API_URL", "https://notam-alarm1.up.railway.app"),
    "https://notam-alarm.up.railway.app",
]


def sync_loop():
    print(f"[sync] Iniciando — intervalo: {INTERVAL}s", flush=True)
    for url in REMOTE_URLS:
        print(f"[sync] Servidor: {url}", flush=True)
    print(flush=True)

    while True:
        try:
            print(f"[sync] {time.strftime('%H:%M:%S')} — Ejecutando scraper...", flush=True)
            data = run_scraper(headless=True)

            notams = data.get("notams", [])
            extraction_date = data.get("extraction_date", time.strftime("%Y-%m-%d %H:%M:%S"))
            payload = json.dumps({
                "notams": notams,
                "extraction_date": extraction_date,
            }).encode("utf-8")

            for url in REMOTE_URLS:
                req = urllib.request.Request(
                    url + "/upload",
                    data=payload,
                    headers={"Content-Type": "application/json", "X-Secret": "notam-spim-2026"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                        print(f"[upload] {url} OK — {result.get('total_received', '?')} NOTAMs", flush=True)
                except Exception as e:
                    print(f"[upload] {url} Error: {e}", flush=True)

            print(f"[sync] {len(notams)} NOTAMs extraídos y subidos", flush=True)

        except Exception as e:
            print(f"[sync] Error: {e}", flush=True)

        print(f"[sync] Próximo sync en {INTERVAL}s...\n", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sync_loop()

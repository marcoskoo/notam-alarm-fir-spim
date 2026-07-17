"""
NOTAM Sync — Ejecuta el scraper cada 60 segundos y sube los datos a Railway.
Ejecutar en la red de CORPAC (Perú).
"""

import os
import sys
import time

# Agregar directorio del script al path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from scraper import run_scraper, upload_to_server

INTERVAL = int(os.environ.get("SYNC_INTERVAL", "60"))

# Servidores Railway
REMOTE_URLS = [
    os.environ.get("NOTAM_API_URL", "https://notam-alarm-spim-production.up.railway.app"),
    "https://notam-alarm.up.railway.app",
]


def sync_loop():
    print(f"[sync] Iniciando — intervalo: {INTERVAL}s")
    for url in REMOTE_URLS:
        print(f"[sync] Servidor: {url}")
    print()

    while True:
        try:
            print(f"[sync] {time.strftime('%H:%M:%S')} — Ejecutando scraper...")
            data = run_scraper(headless=True)

            for url in REMOTE_URLS:
                print(f"[sync] Subiendo a {url}...")
                import urllib.request, json as _json
                payload = _json.dumps({
                    "notams": data.get("notams", []),
                    "extraction_date": data.get("extraction_date", time.strftime("%Y-%m-%d %H:%M:%S")),
                }).encode("utf-8")
                req = urllib.request.Request(
                    url + "/upload",
                    data=payload,
                    headers={"Content-Type": "application/json", "X-Secret": "notam-spim-2026"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        result = _json.loads(resp.read().decode("utf-8"))
                        print(f"[upload] {url} OK — {result.get('total_received', '?')} NOTAMs")
                except Exception as e:
                    print(f"[upload] {url} Error: {e}")

        except Exception as e:
            print(f"[sync] Error: {e}")

        print(f"[sync] Próximo sync en {INTERVAL}s...\n")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sync_loop()

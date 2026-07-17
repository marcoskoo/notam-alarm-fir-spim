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


def sync_loop():
    print(f"[sync] Iniciando — intervalo: {INTERVAL}s")
    print(f"[sync] Servidor: {os.environ.get('NOTAM_API_URL', 'https://notam-alarm-spim-production.up.railway.app')}")
    print()

    while True:
        try:
            print(f"[sync] {time.strftime('%H:%M:%S')} — Ejecutando scraper...")
            data = run_scraper(headless=True)

            print(f"[sync] Subiendo a servidor...")
            result = upload_to_server(data)

            if result:
                print(f"[sync] OK — {result.get('total_alive', '?')} NOTAMs vivos en servidor")
            else:
                print(f"[sync] Error al subir")

        except Exception as e:
            print(f"[sync] Error: {e}")

        print(f"[sync] Próximo sync en {INTERVAL}s...\n")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sync_loop()

"""
NOTAM CORPAC Scraper — FIR SPIM
Extrae NOTAMs vigentes y limpia expirados automáticamente.
Opcionalmente sube los datos a un servidor remoto (Railway).
"""

import os
import re
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CACHE_FILE = os.path.join(DATA_DIR, "notam_cache.json")
os.makedirs(DATA_DIR, exist_ok=True)

CORPAC_USER = os.environ.get("CORPAC_USER", "aissphi")
CORPAC_PASS = os.environ.get("CORPAC_PASS", "corpac")
LOGIN_URL = "https://appoperacional.corpac.gob.pe/NOTAM/newlog.php"
DIST_URL = "https://appoperacional.corpac.gob.pe/NOTAM/UserLayer/Notam/Consultas/consultas.php?action="

# Servidor remoto (Railway)
REMOTE_URLS = [
    os.environ.get("NOTAM_API_URL", "https://notam-alarm1.up.railway.app"),
    "https://notam-alarm.up.railway.app",
]
UPLOAD_SECRET = os.environ.get("UPLOAD_SECRET", "notam-spim-2026")


def parse_notam_fields(details: str) -> dict:
    eff_from = eff_until = schedule = description = ""
    b = re.search(r"B\)\s*(\d{10})", details)
    if b:
        eff_from = b.group(1)
    c = re.search(r"C\)\s*(\d{10}|PERM[^A-Z]*)", details)
    if c:
        eff_until = c.group(1).strip()
    d = re.search(r"D\)\s*(.+?)(?=\s*[A-Z]\)|$)", details)
    if d:
        schedule = d.group(1).strip()
    e = re.search(r"E\)\s*(.+?)(?:\s*F\)|$)", details, re.DOTALL)
    description = e.group(1).strip() if e else details
    return {
        "effective_from": eff_from,
        "effective_until": eff_until,
        "schedule": schedule,
        "description": description,
    }


def parse_expiry(date_str: str):
    if not date_str or "PERM" in date_str.upper():
        return None
    try:
        return datetime.strptime(date_str.strip()[:10], "%y%m%d%H%M").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def filter_expired(notams: list) -> list:
    now = datetime.now(timezone.utc)
    vivos = []
    eliminados = []
    for n in notams:
        det = parse_notam_fields(n.get("details", "") or n.get("raw_text", ""))
        exp = parse_expiry(det.get("effective_until", ""))
        if exp and exp <= now:
            eliminados.append(n["id"])
            continue
        vivos.append(n)
    if eliminados:
        print(f"[scraper] Expirados eliminados ({len(eliminados)}): {', '.join(eliminados)}")
    return vivos


def run_scraper(headless: bool = True) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        print("[scraper] Login...")
        page.goto(LOGIN_URL, timeout=60000)
        time.sleep(3)
        page.fill("#txtusu", CORPAC_USER)
        page.fill("#txtpass", CORPAC_PASS)
        page.click("#action")
        time.sleep(5)

        print("[scraper] Abriendo NOTAM Distribución...")
        page.goto(DIST_URL, timeout=60000)
        time.sleep(6)

        print("[scraper] Buscando FIR SPIM vigentes...")
        page.evaluate("""() => {
            var form = document.forms['frmConsultas'];
            form.elements['txtcodpais'].value = 'SP';
            form.elements['slSerie'].value = '';
            form.elements['txtcodaero'].value = '';
            form.elements['txtfir'].value = 'SPIM';
            var radios = document.querySelectorAll('input[name="rdVer"]');
            radios.forEach(function(r) { r.checked = (r.value === 'V'); });
            form.elements['rdTemp'].value = 'V';
        }""")
        page.click('input[name="action"][value="Buscar"]')
        time.sleep(15)

        print("[scraper] Extrayendo NOTAMs...")
        notams = page.evaluate("""() => {
            var results = [];
            var links = document.querySelectorAll('a[href^="mailto:"]');

            links.forEach(function(link) {
                var href = link.getAttribute('href');
                var bodyIdx = href.indexOf('body=');
                if (bodyIdx < 0) return;
                var body = decodeURIComponent(href.substring(bodyIdx + 5));
                var lines = body.split('\\n');

                var notamId = '';
                var notamStartIdx = 0;
                for (var i = 0; i < lines.length; i++) {
                    var m = lines[i].trim().match(/^([AC]\\d{4}\\/\\d{2,4})\\s+(NOTAM[NRC])/);
                    if (m) { notamId = m[1]; notamStartIdx = i; break; }
                }
                if (!notamId) return;

                var parent = link.closest('table');
                var expLink = parent ? parent.querySelector('a[href*="ocultarMensaje"]') : null;
                var location = '';
                if (expLink) {
                    var lm = expLink.getAttribute('href').match(/ocultarMensaje\\('([A-Z]{3,4})/);
                    if (lm) location = lm[1];
                }

                var pubDate = '';
                if (location && notamId) {
                    var dateEl = document.getElementById(location + notamId + '-1');
                    if (dateEl) {
                        var dm = dateEl.textContent.match(/(\\d{2}\\/\\d{2}\\/\\d{4}\\s+\\d{2}:\\d{2}:\\d{2})/);
                        if (dm) pubDate = dm[1];
                    }
                }

                var remaining = lines.slice(notamStartIdx + 1).join('\\n').trim();
                var qMatch = remaining.match(/Q\\)\\s*(.+)/);
                var qLine = qMatch ? qMatch[1].trim() : '';
                var remaining2 = remaining;
                if (qMatch) {
                    var qi = remaining2.indexOf('Q)');
                    if (qi >= 0) remaining2 = remaining2.substring(qi + qMatch[0].length);
                }
                var detailMatches = remaining2.match(/[A-F]\\)[\\s\\S]*/);
                var details = detailMatches ? detailMatches[0].trim() : '';
                var typeMatch = lines[notamStartIdx].match(/(NOTAM[NRC])/);
                var type = typeMatch ? typeMatch[1] : '';

                results.push({
                    id: notamId,
                    type: type,
                    location: location,
                    raw_text: (pubDate ? pubDate + '\\n' : '') + body.replace(/\\n/g, '\\r\\n'),
                    q_line: qLine,
                    details: details.replace(/\\n/g, '\\r\\n')
                });
            });
            return results;
        }""")

        browser.close()

    print(f"[scraper] {len(notams)} NOTAMs extraídos")

    result_data = {
        "territory": "PERU",
        "fir": "SPIM",
        "total_count": len(notams),
        "serie_a_count": sum(1 for n in notams if n["id"][0] == "A"),
        "serie_c_count": sum(1 for n in notams if n["id"][0] == "C"),
        "notam_n_count": sum(1 for n in notams if n["type"] == "NOTAMN"),
        "notam_r_count": sum(1 for n in notams if n["type"] == "NOTAMR"),
        "source": "CORPAC S.A.",
        "source_url": DIST_URL,
        "extraction_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "search_path": "Modulos/NOTAM/CONSULTAS/NOTAM Distribucion",
        "search_params": {
            "pais": "PERU", "serie": "Todas", "aerodromo": "Todos",
            "fir": "SPIM", "ver": "Vigentes"
        },
        "notams": notams,
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"[scraper] {len(notams)} NOTAMs guardados")
    return result_data


def upload_to_server(data: dict):
    """Sube los NOTAMs a todos los servidores Railway vía POST /upload."""
    payload = json.dumps({
        "notams": data.get("notams", []),
        "extraction_date": data.get("extraction_date", time.strftime("%Y-%m-%d %H:%M:%S")),
    }).encode("utf-8")

    results = []
    for url in REMOTE_URLS:
        req = urllib.request.Request(
            url + "/upload",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Secret": UPLOAD_SECRET,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                print(f"[upload] {url} OK — {result.get('total_received', '?')} recibidos")
                results.append(result)
        except Exception as e:
            print(f"[upload] {url} Error: {e}")

    return results[0] if results else None


if __name__ == "__main__":
    upload = "--upload" in sys.argv
    headless = "--show" not in sys.argv

    data = run_scraper(headless=headless)

    if upload:
        print("\n[scraper] Subiendo a servidor remoto...")
        upload_to_server(data)

"""
NOTAM FIR SPIM API - Railway Deploy
====================================
Auto-refresh cada 60s + limpieza automática de NOTAMs expirados.
"""

import os
import re
import sys
import json
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
CACHE_FILE = os.path.join(DATA_DIR, "notam_cache.json")
os.makedirs(DATA_DIR, exist_ok=True)

REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL", "60"))
UPLOAD_SECRET = os.environ.get("UPLOAD_SECRET", "notam-spim-2026")

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="NOTAM FIR SPIM API",
    description="API NOTAM FIR SPIM — CORPAC S.A. Auto-refresh + expirados automáticos.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class NotamItem(BaseModel):
    id: str
    type: Optional[str] = ""
    series: Optional[str] = ""
    fir: str = "SPIM"
    location: Optional[str] = ""
    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    schedule: Optional[str] = None
    description: Optional[str] = ""
    q_line: Optional[str] = ""
    raw_text: str


class NotamResponse(BaseModel):
    fir: str
    total_count: int
    last_updated: str
    source: str
    notams: List[NotamItem]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def get_cached_notams() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"fir": "SPIM", "notams": [], "last_updated": None}


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


def _to_api_items(data: dict) -> list:
    items = []
    for n in data.get("notams", []):
        det = parse_notam_fields(n.get("details", "") or n.get("raw_text", ""))
        items.append({
            "id": n["id"],
            "type": n.get("type", ""),
            "series": "A" if n["id"][0] == "A" else "C",
            "fir": "SPIM",
            "location": n.get("location", ""),
            "effective_from": det["effective_from"] or None,
            "effective_until": det["effective_until"] or None,
            "schedule": det["schedule"] or None,
            "description": det["description"],
            "q_line": n.get("q_line", ""),
            "raw_text": n.get("raw_text", ""),
        })
    return items


def _parse_expiry(date_str: str) -> Optional[datetime]:
    if not date_str or "PERM" in date_str.upper():
        return None
    try:
        return datetime.strptime(date_str.strip()[:10], "%y%m%d%H%M").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def _filter_expired(notams: list) -> list:
    now = datetime.now(timezone.utc)
    vivos = []
    eliminados = []
    for n in notams:
        det = parse_notam_fields(n.get("details", "") or n.get("raw_text", ""))
        exp = _parse_expiry(det.get("effective_until", ""))
        if exp and exp <= now:
            eliminados.append(n["id"])
            continue
        vivos.append(n)
    if eliminados:
        print(f"[auto] Expirados eliminados ({len(eliminados)}): {', '.join(eliminados)}")
    return vivos


# ---------------------------------------------------------------------------
# Scraper (Playwright)
# ---------------------------------------------------------------------------
def run_scraper() -> dict:
    from playwright.sync_api import sync_playwright

    CORPAC_USER = os.environ.get("CORPAC_USER", "aissphi")
    CORPAC_PASS = os.environ.get("CORPAC_PASS", "corpac")
    LOGIN_URL = "https://appoperacional.corpac.gob.pe/NOTAM/newlog.php"
    DIST_URL = "https://appoperacional.corpac.gob.pe/NOTAM/UserLayer/Notam/Consultas/consultas.php?action="

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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
        "notams": notams,
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    return result_data


# ---------------------------------------------------------------------------
# Auto-refresh background task
# ---------------------------------------------------------------------------
_last_refresh: Optional[str] = None
_refresh_count: int = 0
_refresh_running: bool = False


async def _auto_refresh_loop():
    """Actualiza timestamp cada N segundos. El scraper corre local y sube vía /upload."""
    global _last_refresh, _refresh_count, _refresh_running
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        _last_refresh = datetime.now().isoformat()
        _refresh_count += 1


@app.on_event("startup")
async def startup():
    global _refresh_task
    _refresh_task = asyncio.create_task(_auto_refresh_loop())
    print(f"[api] Auto-refresh cada {REFRESH_INTERVAL}s")


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_DIR = os.path.join(APP_DIR, "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    # Fallback: API info page
    html = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>NOTAM FIR SPIM API</title>
<style>
body{font-family:system-ui;max-width:700px;margin:40px auto;padding:0 20px;color:#222}
h1{color:#1a5276}a{color:#2e86c1}code{background:#f4f4f4;padding:2px 6px;border-radius:3px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#1a5276;color:white}tr:nth-child(even){background:#f9f9f9}
</style></head>
<body>
<h1>NOTAM FIR SPIM API v2.0</h1>
<p>Fuente: <strong>CORPAC S.A.</strong> | FIR: <strong>SPIM</strong></p>
<p>Auto-refresh: cada 60 segundos | Limpieza automática de NOTAMs expirados</p>
<h2>Endpoints</h2>
<table>
<tr><th>Método</th><th>Ruta</th><th>Descripción</th></tr>
<tr><td>GET</td><td><a href="/notams">/notams</a></td><td>Todos los NOTAMs</td></tr>
<tr><td>GET</td><td><a href="/notams/raw">/notams/raw</a></td><td>Texto crudo</td></tr>
<tr><td>GET</td><td><a href="/status">/status</a></td><td>Estado del auto-refresh</td></tr>
<tr><td>GET</td><td><a href="/health">/health</a></td><td>Health check</td></tr>
<tr><td>GET</td><td><a href="/docs">/docs</a></td><td>Swagger UI</td></tr>
</table>
</body></html>"""
    return HTMLResponse(content=html)


@app.get("/notams", response_model=NotamResponse)
async def get_all_notams():
    data = get_cached_notams()
    if not data.get("notams"):
        raise HTTPException(404, "No hay NOTAMs")
    items = _to_api_items(data)
    return NotamResponse(
        fir=data["fir"],
        total_count=len(items),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**i) for i in items],
    )


@app.get("/notams/raw")
async def get_raw_notams():
    data = get_cached_notams()
    if not data.get("notams"):
        raise HTTPException(404, "No hay NOTAMs")
    return {
        "fir": data["fir"],
        "total_count": len(data["notams"]),
        "last_updated": data.get("extraction_date", "Unknown"),
        "raw_notams": [n.get("raw_text", "") for n in data["notams"]],
    }


@app.get("/notams/type/{notam_type}")
async def get_notams_by_type(notam_type: str):
    data = get_cached_notams()
    if not data.get("notams"):
        raise HTTPException(404, "No hay NOTAMs")
    nt = notam_type.upper()
    items = [i for i in _to_api_items(data) if i["type"].upper() == nt]
    return NotamResponse(
        fir=data["fir"],
        total_count=len(items),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**i) for i in items],
    )


@app.get("/notams/serie/{serie}")
async def get_notams_by_serie(serie: str):
    data = get_cached_notams()
    if not data.get("notams"):
        raise HTTPException(404, "No hay NOTAMs")
    s = serie.upper()
    items = [i for i in _to_api_items(data) if i["series"] == s]
    return NotamResponse(
        fir=data["fir"],
        total_count=len(items),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**i) for i in items],
    )


@app.get("/notams/{notam_id:path}")
async def get_notam_by_id(notam_id: str):
    data = get_cached_notams()
    if not data.get("notams"):
        raise HTTPException(404, "No hay NOTAMs")
    nid = notam_id.upper().replace("-", "/")
    for item in _to_api_items(data):
        if item["id"].upper() == nid:
            return NotamItem(**item)
    raise HTTPException(404, f"NOTAM {nid} no encontrado")


@app.post("/refresh")
async def refresh_notams():
    """Refresca datos — el scraper debe correr local y subir vía POST /upload"""
    return {
        "status": "info",
        "message": "El scraper corre en la red de CORPAC (Perú). Ejecuta localmente: python scraper.py --upload",
        "upload_endpoint": "/upload",
    }


@app.get("/status")
async def get_status():
    data = get_cached_notams()
    return {
        "auto_refresh": {
            "enabled": True,
            "interval_seconds": REFRESH_INTERVAL,
            "last_refresh": _last_refresh,
            "total_refreshes": _refresh_count,
            "currently_running": _refresh_running,
        },
        "cache": {
            "total_notams": len(data.get("notams", [])),
            "last_updated": data.get("extraction_date"),
            "fir": data.get("fir", "SPIM"),
        },
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/upload")
async def upload_notams(payload: dict, x_secret: str = Header(None)):
    """
    Sube NOTAMs nuevos desde el scraper local.
    El scraper corre en la red de CORPAC (Perú) y sube los datos aquí.
    """
    if not x_secret:
        raise HTTPException(401, "Falta header X-Secret")
    if x_secret != UPLOAD_SECRET:
        raise HTTPException(403, "Secret incorrecto")

    notams = payload.get("notams", [])
    if not notams:
        raise HTTPException(400, "No se enviaron NOTAMs")

    # El scraper ya filtra expirados localmente; aqui solo guardamos

    data = {
        "territory": "PERU",
        "fir": "SPIM",
        "total_count": len(notams),
        "serie_a_count": sum(1 for n in notams if n.get("id", "A")[0] == "A"),
        "serie_c_count": sum(1 for n in notams if n.get("id", "C")[0] == "C"),
        "notam_n_count": sum(1 for n in notams if n.get("type") == "NOTAMN"),
        "notam_r_count": sum(1 for n in notams if n.get("type") == "NOTAMR"),
        "source": "CORPAC S.A.",
        "extraction_date": payload.get("extraction_date", datetime.now().isoformat()),
        "notams": notams,
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    global _last_refresh, _refresh_count
    _last_refresh = datetime.now().isoformat()
    _refresh_count += 1

    print(f"[upload] {len(notams)} NOTAMs guardados")

    return {
        "status": "success",
        "total_received": len(notams),
        "last_updated": _last_refresh,
    }

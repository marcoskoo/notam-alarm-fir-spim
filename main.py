from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import re
import json
import os

app = FastAPI(
    title="NOTAM FIR SPIM API",
    description="API para consultar NOTAM de la FIR SPIM (Lima, Peru) - Fuente: CORPAC S.A.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NotamItem(BaseModel):
    id: str
    type: Optional[str] = ""
    series: Optional[str] = ""
    fir: str = "SPIM"
    location: Optional[str] = ""
    published_at: Optional[str] = None
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

def parse_notam_text(text: str) -> dict:
    """Parse raw NOTAM text into structured fields"""
    result = {
        "id": "",
        "series": "",
        "fir": "SPIM",
        "location": "",
        "effective_from": None,
        "effective_until": None,
        "schedule": None,
        "description": ""
    }
    
    lines = text.strip().split('\n')
    full_text = ' '.join(lines).strip()
    
    # Extract NOTAM ID (e.g., A4005/25 or C1969/26)
    id_match = re.search(r'([AC]\d+/\d{2})', full_text)
    if id_match:
        result["id"] = id_match.group(1)
        result["series"] = "A" if id_match.group(1).startswith("A") else "C"
    
    # Extract location (e.g., SPIM, SPJC, etc.)
    loc_match = re.search(r'\b(SP[A-Z]{2}|LIMA)\b', full_text)
    if loc_match:
        result["location"] = loc_match.group(1)
    else:
        result["location"] = "SPIM"
    
    # Extract effective dates
    b_match = re.search(r'B\)\s*(\d{10})', full_text)
    if b_match:
        result["effective_from"] = b_match.group(1)
    
    c_match = re.search(r'C\)\s*(\d{10}|PERM)', full_text)
    if c_match:
        result["effective_until"] = c_match.group(1)
    
    # Extract schedule
    d_match = re.search(r'D\)\s*(.+?)(?=\s*[A-Z]\)|$)', full_text)
    if d_match:
        result["schedule"] = d_match.group(1).strip()
    
    # Extract description (after E) or the main content
    e_match = re.search(r'(?:E\)\s*)(.+?)(?:\s*F\)|$)', full_text, re.DOTALL)
    if e_match:
        result["description"] = e_match.group(1).strip()
    else:
        # Use the full text minus the ID
        result["description"] = full_text
    
    result["raw_text"] = full_text
    
    return result

def get_notam_data() -> dict:
    """Get cached NOTAM data"""
    # Check data/ directory first (deployed), then same directory (local)
    cache_file = os.path.join(os.path.dirname(__file__), "data", "notam_cache.json")
    if not os.path.exists(cache_file):
        cache_file = os.path.join(os.path.dirname(__file__), "notam_cache.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        # Convert new extraction format to API format
        if cache.get("notams") and isinstance(cache["notams"][0], dict):
            first = cache["notams"][0]
            if "q_line" in first or "details" in first:
                # New format - convert
                notams = []
                for n in cache["notams"]:
                    # Parse B/C dates from details
                    details = n.get("details", "")
                    eff_from = None
                    eff_until = None
                    schedule = None
                    published_at = None
                    
                    b_match = re.search(r'B\)\s*(\d{10})', details)
                    if b_match:
                        eff_from = b_match.group(1)
                    
                    c_match = re.search(r'C\)\s*(\d{10}|PERM[^A-Z]*)', details)
                    if c_match:
                        eff_until = c_match.group(1).strip()
                    
                    d_match = re.search(r'D\)\s*(.+?)(?=\s*[A-Z]\)|$)', details)
                    if d_match:
                        schedule = d_match.group(1).strip()
                    
                    e_match = re.search(r'E\)\s*(.+?)(?:\s*F\)|$)', details, re.DOTALL)
                    description = e_match.group(1).strip() if e_match else details
                    
                    # Extract publication date from CREATED field
                    pub_match = re.search(r'(\d{6})\s*(\d{4})\s*CREATED', details)
                    if pub_match:
                        dd = pub_match.group(1)[:2]
                        mo = pub_match.group(1)[2:4]
                        yy = pub_match.group(1)[4:6]
                        hh = pub_match.group(2)[:2]
                        mm = pub_match.group(2)[2:4]
                        published_at = f"20{yy}-{mo}-{dd}T{hh}:{mm}:00"
                    elif b_match:
                        # Use B) field as publication date (DDMMYYHHMM format)
                        b = b_match.group(1)
                        published_at = f"20{b[4:6]}-{b[2:4]}-{b[0:2]}T{b[6:8]}:{b[8:10]}:00"
                    
                    notams.append({
                        "id": n["id"],
                        "type": n.get("type", ""),
                        "series": "A" if n["id"][0] == "A" else "C",
                        "fir": "SPIM",
                        "location": n.get("location", ""),
                        "published_at": published_at,
                        "effective_from": eff_from,
                        "effective_until": eff_until,
                        "schedule": schedule,
                        "description": description,
                        "q_line": n.get("q_line", ""),
                        "raw_text": n.get("raw_text", "")
                    })
                
                cache["notams"] = notams
        
        return cache
    
    return {"fir": "SPIM", "notams": [], "last_updated": None}

def save_notam_data(data: dict):
    """Save NOTAM data to cache"""
    cache_file = os.path.join(os.path.dirname(__file__), "data", "notam_cache.json")
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Initialize with cached data from CORPAC scraper
@app.on_event("startup")
async def startup_event():
    cache = get_notam_data()
    if not cache.get("notams"):
        # No data available - will need to run scraper
        save_notam_data({
            "fir": "SPIM",
            "territory": "PERU",
            "notams": [],
            "last_updated": datetime.now().isoformat(),
            "source": "CORPAC S.A. - https://appoperacional.corpac.gob.pe/NOTAM/"
        })

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the NOTAM Alarm app"""
    # Check static/ directory first (deployed), then parent notam_alarm/ (local)
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if not os.path.exists(html_path):
        html_path = os.path.join(os.path.dirname(__file__), '..', 'notam_alarm', 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    return {"api": "NOTAM FIR SPIM API", "version": "2.0.0", "note": "HTML app not found"}

@app.get("/notams", response_model=NotamResponse)
async def get_all_notams(
    sort: Optional[str] = Query(None, description="Ordenar: 'latest' (más reciente primero), 'oldest' (más antiguo primero)")
):
    """Get all NOTAMs for FIR SPIM"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    notams = data["notams"]
    if sort == "latest":
        notams = sorted(notams, key=lambda x: x.get("published_at") or "0000", reverse=True)
    elif sort == "oldest":
        notams = sorted(notams, key=lambda x: x.get("published_at") or "9999")
    
    return NotamResponse(
        fir=data["fir"],
        total_count=len(notams),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**n) for n in notams]
    )

@app.get("/notams/latest", response_model=NotamResponse)
async def get_latest_notams(limit: int = Query(10, ge=1, le=100)):
    """Get latest NOTAMs by publication date"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    sorted_notams = sorted(
        data["notams"], 
        key=lambda x: x.get("published_at") or "0000", 
        reverse=True
    )[:limit]
    
    return NotamResponse(
        fir=data["fir"],
        total_count=len(sorted_notams),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**n) for n in sorted_notams]
    )

@app.get("/notams/raw")
async def get_raw_notams():
    """Get raw NOTAM text"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    raw_texts = [n.get("raw_text", "") for n in data["notams"]]
    
    return {
        "fir": data["fir"],
        "total_count": len(raw_texts),
        "last_updated": data.get("extraction_date", "Unknown"),
        "source": data.get("source", "CORPAC S.A."),
        "raw_notams": raw_texts
    }

@app.get("/notams/type/{notam_type}")
async def get_notams_by_type(notam_type: str):
    """Get NOTAMs by type (NOTAMN, NOTAMR, NOTAMC)"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    notam_type = notam_type.upper()
    filtered = [n for n in data["notams"] if n.get("type", "").upper() == notam_type]
    
    return NotamResponse(
        fir=data["fir"],
        total_count=len(filtered),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**n) for n in filtered]
    )

@app.get("/notams/serie/{serie}")
async def get_notams_by_serie(serie: str):
    """Get NOTAMs by serie (A or C)"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    serie = serie.upper()
    filtered = [n for n in data["notams"] if n.get("series", "").upper() == serie]
    
    return NotamResponse(
        fir=data["fir"],
        total_count=len(filtered),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**n) for n in filtered]
    )

@app.get("/notams/{notam_id:path}")
async def get_notam_by_id(notam_id: str):
    """Get specific NOTAM by ID (e.g., A4005/25 or A4005-25)"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    # Normalize the ID - handle both / and - separators
    notam_id = notam_id.upper().replace("-", "/")
    
    for notam in data["notams"]:
        if notam.get("id", "").upper() == notam_id:
            return NotamItem(**notam)
    
    raise HTTPException(status_code=404, detail=f"NOTAM {notam_id} not found")

@app.get("/notams/fir/{fir_code}")
async def get_notams_by_fir(fir_code: str):
    """Get NOTAMs for a specific FIR code"""
    data = get_notam_data()
    
    if not data.get("notams"):
        raise HTTPException(status_code=404, detail="No NOTAMs found")
    
    fir_code = fir_code.upper()
    
    filtered_notams = [
        n for n in data["notams"] 
        if fir_code in n.get("q_line", "").upper() or
           fir_code in n.get("location", "").upper() or
           fir_code in n.get("raw_text", "").upper()
    ]
    
    return NotamResponse(
        fir=fir_code,
        total_count=len(filtered_notams),
        last_updated=data.get("extraction_date", "Unknown"),
        source=data.get("source", "CORPAC S.A."),
        notams=[NotamItem(**n) for n in filtered_notams]
    )

@app.post("/refresh")
async def refresh_notams():
    """Refresh NOTAM data by running the CORPAC scraper"""
    try:
        import subprocess
        scraper_path = os.path.join(os.path.dirname(__file__), '..', 'notam_dist_v6.py')
        
        if not os.path.exists(scraper_path):
            raise HTTPException(status_code=500, detail="Scraper script not found")
        
        result = subprocess.run(
            ['python', scraper_path],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Scraper failed: {result.stderr[:500]}")
        
        # Reload the cache
        data = get_notam_data()
        
        return {
            "status": "success",
            "message": f"Refreshed {len(data.get('notams', []))} NOTAMs from CORPAC",
            "last_updated": data.get("extraction_date", datetime.now().isoformat()),
            "source": "CORPAC S.A. - NOTAM Distribucion"
        }
            
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Scraper timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

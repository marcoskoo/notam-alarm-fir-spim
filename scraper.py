from playwright.sync_api import sync_playwright
import time
import json
import re
import os
from urllib.parse import unquote, parse_qs

output_dir = "C:\\Users\\aissphi\\AppData\\Local\\Temp\\notam_api"
URL_DISTRIBUCION = 'https://appoperacional.corpac.gob.pe/NOTAM/UserLayer/Notam/Consultas/consultas.php?action='

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=200)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    
    print("1. Login...")
    page.goto('https://appoperacional.corpac.gob.pe/NOTAM/newlog.php', timeout=60000)
    time.sleep(3)
    page.fill('#txtusu', 'aissphi')
    page.fill('#txtpass', 'corpac')
    page.click('#action')
    time.sleep(5)
    
    print("2. NOTAM Distribucion...")
    page.goto(URL_DISTRIBUCION, timeout=60000)
    time.sleep(6)
    
    print("3. Buscar...")
    page.evaluate('''() => {
        var form = document.forms['frmConsultas'];
        form.elements['txtcodpais'].value = 'SP';
        form.elements['slSerie'].value = '';
        form.elements['txtcodaero'].value = '';
        form.elements['txtfir'].value = 'SPIM';
        var radios = document.querySelectorAll('input[name="rdVer"]');
        radios.forEach(function(r) { r.checked = (r.value === 'V'); });
        form.elements['rdTemp'].value = 'V';
    }''')
    page.click('input[name="action"][value="Buscar"]')
    time.sleep(15)
    
    print("4. Extrayendo NOTAMs...")
    notams = page.evaluate('''() => {
        var results = [];
        var links = document.querySelectorAll('a[href^="mailto:"]');
        
        links.forEach(function(link) {
            var href = link.getAttribute('href');
            
            // Extract body - everything after body=
            var bodyIdx = href.indexOf('body=');
            if (bodyIdx < 0) return;
            var bodyRaw = href.substring(bodyIdx + 5);
            var body = decodeURIComponent(bodyRaw);
            
            // Split by newlines
            var lines = body.split('\\n');
            
            // Find NOTAM ID line
            var notamId = '';
            var notamStartIdx = 0;
            
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                var idMatch = line.match(/^([AC]\\d{4}\\/\\d{2,4})\\s+(NOTAM[NRC])/);
                if (idMatch) {
                    notamId = idMatch[1];
                    notamStartIdx = i;
                    break;
                }
            }
            
            if (!notamId) return;
            
            // Extract publication date from the HTML table row (NOT from mailto body)
            // The date DD/MM/YYYY HH:MM:SS is in a table cell near the mailto link
            var publishedAt = '';
            var tableRow = link.closest('tr');
            if (tableRow) {
                var allText = tableRow.textContent;
                var dateMatch = allText.match(/(\\d{2}\\/\\d{2}\\/\\d{4}\\s+\\d{2}:\\d{2}:\\d{2})/);
                if (dateMatch) {
                    publishedAt = dateMatch[1];
                }
            }
            
            // Get remaining lines after NOTAM ID
            var remaining = lines.slice(notamStartIdx + 1).join('\\n').trim();
            
            // Extract Q line
            var qMatch = remaining.match(/Q\\)\\s*(.+)/);
            var qLine = qMatch ? qMatch[1].trim() : '';
            
            // Extract detail lines (A through E)
            var remaining2 = remaining;
            if (qMatch) {
                var qEndIdx = remaining2.indexOf('Q)');
                if (qEndIdx >= 0) {
                    remaining2 = remaining2.substring(qEndIdx + qMatch[0].length);
                }
            }
            var detailMatches = remaining2.match(/[A-F]\\)[\\s\\S]*/);
            var details = detailMatches ? detailMatches[0].trim() : '';
            
            // Get expand link for location
            var parent = link.closest('table');
            var expandLink = parent ? parent.querySelector('a[href*="ocultarMensaje"]') : null;
            var location = '';
            if (expandLink) {
                var ocultarHref = expandLink.getAttribute('href');
                var locMatch = ocultarHref.match(/ocultarMensaje\\('([A-Z]{3,4})/);
                if (locMatch) location = locMatch[1];
            }
            
            // Type
            var typeMatch = lines[notamStartIdx].match(/(NOTAM[NRC])/);
            var type = typeMatch ? typeMatch[1] : '';
            
            results.push({
                id: notamId,
                type: type,
                location: location,
                published_at: publishedAt,
                raw_text: body.replace(/\\n/g, '\\r\\n'),
                q_line: qLine,
                details: details.replace(/\\n/g, '\\r\\n')
            });
        });
        
        return results;
    }''')
    
    print(f"   NOTAMs: {len(notams)}")
    
    # Debug: print first 3
    for n in notams[:3]:
        print(f"\n  [{n['id']}] {n['type']}")
        print(f"  Q: {n['q_line']}")
        print(f"  Details: {n['details'][:300]}")
    
    result_data = {
        "territory": "PERU",
        "fir": "SPIM",
        "total_count": len(notams),
        "serie_a_count": sum(1 for n in notams if n['id'][0] == 'A'),
        "serie_c_count": sum(1 for n in notams if n['id'][0] == 'C'),
        "notam_n_count": sum(1 for n in notams if n['type'] == 'NOTAMN'),
        "notam_r_count": sum(1 for n in notams if n['type'] == 'NOTAMR'),
        "source": "CORPAC S.A.",
        "source_url": URL_DISTRIBUCION,
        "extraction_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "search_path": "Modulos/NOTAM/CONSULTAS/NOTAM Distribucion",
        "search_params": {
            "pais": "PERU", "serie": "Todas", "aerodromo": "Todos",
            "fir": "SPIM", "ver": "Vigentes"
        },
        "notams": notams
    }
    
    with open(os.path.join(output_dir, 'notam_peru_final.json'), 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    with open(os.path.join(output_dir, 'notam_cache.json'), 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    
    browser.close()
    print("\nListo!")

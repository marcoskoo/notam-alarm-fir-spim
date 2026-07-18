import re, json
from scraper import _scrape_once, filter_expired, parse_notam_fields, parse_expiry
from datetime import datetime, timezone

notams = _scrape_once(headless=True)
print(f"Before filter: {len(notams)}")

now = datetime.now(timezone.utc)
for n in notams:
    det = parse_notam_fields(n.get("details", "") or n.get("raw_text", ""))
    exp = parse_expiry(det.get("effective_until", ""))
    if exp and exp <= now:
        print(f"  EXPIRED: {n['id']}  C={det.get('effective_until','')}  exp={exp}  now={now}")

alive = filter_expired(notams)
print(f"After filter: {len(alive)}")
alive_ids = [n["id"] for n in alive]
removed = [n["id"] for n in notams if n["id"] not in alive_ids]
print(f"Removed: {removed}")

"""
GWP Water Notifier - GitHub Actions version.
- Multiple fallback fetch methods (ScraperAPI + direct + proxies)
- Saves current_alerts.json for bot (0 credits per new user)
- Saves streets_db.json (learning system)
- Bilingual notifications
"""
from __future__ import annotations
import os
import re
import json
import logging
import urllib.parse
import requests as http
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("water_notifier")

BOT_TOKEN       = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID   = os.environ.get("CHAT_ID", "").strip()
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

SEEN_FILE            = "seen.json"
SUBSCRIBERS_FILE     = "subscribers.json"
CURRENT_ALERTS_FILE  = "current_alerts.json"
STREETS_DB_FILE      = "streets_db.json"

API_DISCONNECT = "https://www.gwp.ge/api/Disconnect/ByCity?cityId=1"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8",
    "Referer": "https://www.gwp.ge/",
}

DISTRICT_KA_EN = {
    "გლდანი": "Gldani",   "დიდუბე": "Didube",
    "ვაკე": "Vake",       "ისანი": "Isani",
    "კრწანისი": "Krtsanisi", "მთაწმინდა": "Mtatsminda",
    "ნაძალადევი": "Nadzaladevi", "საბურთალო": "Saburtalo",
    "ჩუღურეთი": "Chugureti", "წყნეთი": "Tsqneti",
    "სამგორი": "Samgori", "დიღომი": "Dighomi",
}

DISTRICT_EN_KA = {v: k for k, v in DISTRICT_KA_EN.items()}


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(data)
            if isinstance(data, dict):
                return set(data.keys())
        except Exception:
            pass
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def load_subscribers() -> dict:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Load subs failed: %s", e)
    return {}


def save_current_alerts(alerts: list):
    try:
        enriched = []
        for item in alerts:
            ka = item.get("district", "")
            enriched.append({
                "id":          item.get("code", ""),
                "district_ka": ka,
                "district_en": DISTRICT_KA_EN.get(ka, ka),
                "address":     item.get("address", ""),
                "email_text":  item.get("emailText", ""),
                "type":        item.get("type", ""),
                "status":      item.get("status", ""),
            })

        payload = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "count":      len(enriched),
            "alerts":     enriched,
        }

        with open(CURRENT_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        log.info("Saved %d alerts to %s", len(enriched), CURRENT_ALERTS_FILE)
    except Exception as e:
        log.warning("Save current alerts failed: %s", e)


def save_empty_alerts_state():
    try:
        payload = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "count": 0,
            "alerts": [],
        }
        with open(CURRENT_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("Saved empty alerts state")
    except Exception as e:
        log.warning("Save empty failed: %s", e)


def save_streets_from_alerts(alerts: list):
    db = {}
    if os.path.exists(STREETS_DB_FILE):
        try:
            with open(STREETS_DB_FILE, "r", encoding="utf-8") as f:
                db = json.load(f)
        except Exception:
            pass

    def normalize(text):
        return re.sub(r'[^\w\s]', ' ', text.lower()).strip()

    new_count = 0
    for item in alerts:
        d_ka = item.get("district", "")
        d_en = DISTRICT_KA_EN.get(d_ka, d_ka)
        email = item.get("emailText", "") or ""
        address = item.get("address", "")

        for source in [address, email]:
            parts = re.split(r'[,;\n]', source)
            for part in parts:
                part = part.strip()
                part = re.sub(r'^\s*(ისანი|ვაკე|საბურთალო|გლდანი|დიდუბე|მთაწმინდა|კრწანისი|ჩუღურეთი|ნაძალადევი|სამგორი|დიღომი|წყნეთი),?\s*', '', part)
                part = re.sub(r'\s+', ' ', part).strip()

                if len(part) < 3 or len(part) > 100:
                    continue

                if any(w in part.lower() for w in [
                    'due to', 'გამო', 'დაზიან', 'network', 'ქსელ',
                    'water', 'წყალ', 'from', 'დან', 'until', 'მდე',
                    'restoration', 'აღდგენ', '2026', '2025', '2027',
                ]):
                    continue

                is_street = (
                    'ქუჩ' in part or 'street' in part.lower() or
                    'გამზ' in part or 'ave' in part.lower() or
                    'შესახვ' in part or 'ჩიხი' in part or 'ჩიხს' in part or
                    re.search(r'[ა-ჰ]{4,}', part) or
                    re.search(r'[a-zA-Z]{4,}', part)
                )

                if not is_street:
                    continue

                key = normalize(part)
                if key not in db:
                    db[key] = {
                        "name": part,
                        "district": d_en,
                        "seen_count": 1,
                    }
                    new_count += 1
                else:
                    db[key]["seen_count"] = db[key].get("seen_count", 0) + 1

    try:
        with open(STREETS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        log.info("Streets DB: %d total, %d new", len(db), new_count)
    except Exception as e:
        log.warning("Save streets DB failed: %s", e)


def fetch_alerts() -> list:
    """Try multiple methods with retries."""

    # Method 1: ScraperAPI standard - with 2 retries
    if SCRAPER_API_KEY:
        for attempt in range(2):
            try:
                log.info("Trying ScraperAPI standard (attempt %d)...", attempt + 1)
                r = http.get(
                    "http://api.scraperapi.com",
                    params={
                        "api_key": SCRAPER_API_KEY,
                        "url": API_DISCONNECT,
                        "render": "false",
                    },
                    timeout=60,
                )
                if r.status_code == 200:
                    data = r.json()
                    log.info("ScraperAPI standard OK (%d alerts)", len(data))
                    return data
                log.warning("ScraperAPI standard HTTP %s (attempt %d)",
                            r.status_code, attempt + 1)
            except Exception as e:
                log.warning("ScraperAPI standard error: %s", e)

    # Method 2: ScraperAPI premium
    if SCRAPER_API_KEY:
        try:
            log.info("Trying ScraperAPI premium...")
            r = http.get(
                "http://api.scraperapi.com",
                params={
                    "api_key": SCRAPER_API_KEY,
                    "url": API_DISCONNECT,
                    "render": "false",
                    "premium": "true",
                },
                timeout=60,
            )
            if r.status_code == 200:
                data = r.json()
                log.info("ScraperAPI premium OK (%d alerts)", len(data))
                return data
            log.warning("ScraperAPI premium HTTP %s", r.status_code)
        except Exception as e:
            log.warning("ScraperAPI premium error: %s", e)

    # Method 3: Direct request with browser headers
    try:
        log.info("Trying direct request...")
        r = http.get(API_DISCONNECT, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            log.info("Direct OK (%d alerts)", len(data))
            return data
        log.warning("Direct HTTP %s", r.status_code)
    except Exception as e:
        log.warning("Direct failed: %s", 

"""
GWP Water Notifier - GitHub Actions version.
Multiple fallback fetch methods.
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8",
    "Referer": "https://www.gwp.ge/",
}

DISTRICT_KA_EN = {
    "გლდანი": "Gldani",
    "დიდუბე": "Didube",
    "ვაკე": "Vake",
    "ისანი": "Isani",
    "კრწანისი": "Krtsanisi",
    "მთაწმინდა": "Mtatsminda",
    "ნაძალადევი": "Nadzaladevi",
    "საბურთალო": "Saburtalo",
    "ჩუღურეთი": "Chugureti",
    "წყნეთი": "Tsqneti",
    "სამგორი": "Samgori",
    "დიღომი": "Dighomi",
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
                "id": item.get("code", ""),
                "district_ka": ka,
                "district_en": DISTRICT_KA_EN.get(ka, ka),
                "address": item.get("address", ""),
                "email_text": item.get("emailText", ""),
                "type": item.get("type", ""),
                "status": item.get("status", ""),
            })

        payload = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "count": len(enriched),
            "alerts": enriched,
        }

        with open(CURRENT_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        log.info("Saved %d alerts", len(enriched))
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
        log.info("Saved empty state")
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

                if any(w in part.lower() for w in ['due to', 'გამო', 'დაზიან', 'network', 'ქსელ', 'water', 'წყალ', 'from', 'დან', 'until', 'მდე', 'restoration', 'აღდგენ', '2026', '2025', '2027']):
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


def try_scraperapi_standard():
    if not SCRAPER_API_KEY:
        return None
    try:
        log.info("Trying ScraperAPI standard...")
        r = http.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_API_KEY, "url": API_DISCONNECT, "render": "false"},
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("ScraperAPI standard OK (%d alerts)", len(data))
            return data
        log.warning("ScraperAPI standard HTTP %s", r.status_code)
    except Exception as e:
        log.warning("ScraperAPI standard error: %s", e)
    return None


def try_scraperapi_premium():
    if not SCRAPER_API_KEY:
        return None
    try:
        log.info("Trying ScraperAPI premium...")
        r = http.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_API_KEY, "url": API_DISCONNECT, "render": "false", "premium": "true"},
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("ScraperAPI premium OK (%d alerts)", len(data))
            return data
        log.warning("ScraperAPI premium HTTP %s", r.status_code)
    except Exception as e:
        log.warning("ScraperAPI premium error: %s", e)
    return None


def try_direct():
    try:
        log.info("Trying direct request...")
        r = http.get(API_DISCONNECT, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            log.info("Direct OK (%d alerts)", len(data))
            return data
        log.warning("Direct HTTP %s", r.status_code)
    except Exception as e:
        log.warning("Direct error: %s", e)
    return None


def try_allorigins():
    try:
        log.info("Trying allorigins...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get("https://api.allorigins.win/raw?url=" + encoded, timeout=45)
        if r.status_code == 200:
            data = r.json()
            log.info("AllOrigins OK (%d alerts)", len(data))
            return data
    except Exception as e:
        log.warning("AllOrigins error: %s", e)
    return None


def try_corsproxy():
    try:
        log.info("Trying corsproxy.io...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get("https://corsproxy.io/?" + encoded, timeout=30)
        if r.status_code == 200:
            data = r.json()
            log.info("corsproxy.io OK (%d alerts)", len(data))
            return data
    except Exception as e:
        log.warning("corsproxy.io error: %s", e)
    return None


def fetch_alerts() -> list:
    """Try multiple methods with retries."""
    for attempt in range(2):
        data = try_scraperapi_standard()
        if data is not None:
            return data

    data = try_scraperapi_premium()
    if data is not None:
        return data

    data = try_direct()
    if data is not None:
        return data

    data = try_allorigins()
    if data is not None:
        return data

    data = try_corsproxy()
    if data is not None:
        return data

    log.error("ALL methods failed")
    return []


def build_message(item: dict, lang: str = "en") -> str:
    district_ka = item.get("district", "")
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    address = item.get("address", "")
    email_text = item.get("emailText", "") or ""
    code = item.get("code", "")
    wtype = item.get("type", "") or ""

    is_emergency = "არაგეგმ" in wtype

    if lang == "ka":
        title = "🚰 <b>წყალმომარაგების შეწყვეტა</b>"
        status = "🚨 ავარიული" if is_emergency else "📋 დაგეგმილი"
        d_label = "📍 <b>რაიონი:</b>"
        a_label = "🏠 <b>მისამართი:</b>"
        det_lbl = "📝 <b>დეტალები:</b>"
        aff_lbl = "🏘️ <b>დაზარალებული ქუჩები:</b>"
        note = ""
        district_display = district_ka
    else:
        title = "🚰 <b>WATER SUPPLY INTERRUPTION</b>"
        status = "🚨 Emergency" if is_emergency else "📋 Planned"
        d_label = "📍 <b>District:</b>"
        a_label = "🏠 <b>Address:</b>"
        det_lbl = "📝 <b>Details (original from GWP):</b>"
        aff_lbl = "🏘️ <b>Affected streets:</b>"
        note = "\nℹ️ <i>Content is from GWP in Georgian.</i>\n"
        district_display = district_en

    affected = ""
    for marker in ["შეუწყდება:", "შეუწყდა:", "შეეზღუდება:"]:
        if marker in email_text:
            affected = email_text.split(marker, 1)[1].strip()
            break

    msg = title + "\n" + status + "\n\n"
    msg += d_label + " " + district_display + "\n"
    msg += a_label + " " + address + "\n\n"

    if affected:
        msg += aff_lbl + "\n" + affected + "\n\n"

    msg += det_lbl + "\n" + email_text + "\n"

    if note:
        msg += note

    msg += "\n🆔 <code>" + code + "</code>"

    if len(msg) > 4000:
        msg = msg[:3900] + "\n\n... (truncated)"

    return msg


def send(chat_id: str, message: str) -> bool:
    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
    try:
        r = http.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code == 200:
            return True
        if r.status_code == 403:
            log.info("User %s blocked bot", chat_id)
        else:
            log.warning("TG %s for %s: %s", r.status_code, chat_id, r.text[:200])
        return False
    except Exception as e:
        log.warning("Send error: %s", e)
        return False


def alert_matches_user(item: dict, user: dict) -> bool:
    districts = user.get("districts", [])
    streets = user.get("streets", [])

    if not districts:
        return False

    district_ka = item.get("district", "")
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    if district_en not in districts:
        return False

    if streets:
        searchable = (item.get("address", "") + " " + item.get("emailText", "")).lower()
        if not any(s.lower() in searchable for s in streets):
            return False

    return True


def main():
    log.info("=== Water Notifier Started ===")
    seen = load_seen()
    subs = load_subscribers()
    alerts = fetch_alerts()

    log.info("Loaded %d subs, %d alerts, %d seen", len(subs), len(alerts), len(seen))

    if not alerts:
        log.warning("No alerts - saving empty state")
        save_empty_alerts_state()
        return

    save_current_alerts(alerts)
    save_streets_from_alerts(alerts)

    new_ids = set()
    total_sent = 0
    admin_sent = 0

    for item in alerts:
        code = item.get("code", "")
        if not code or code in seen:
            continue

        new_ids.add(code)
        log.info("New alert: %s (%s)", code, item.get("district", ""))

        if ADMIN_CHAT_ID:
            admin_msg = build_message(item, lang="en")
            if send(ADMIN_CHAT_ID, admin_msg):
                admin_sent += 1

        for uid, user in subs.items():
            if not user.get("active", True):
                continue
            if alert_matches_user(item, user):
                user_lang = user.get("lang", "en")
                user_msg = build_message(item, lang=user_lang)
                if send(uid, user_msg):
                    total_sent += 1
                    log.info("  -> sent to %s", uid)

    save_seen(seen | new_ids)
    log.info("=== Done: %d new, %d admin, %d subs ===", len(new_ids), admin_sent, total_sent)


if __name__ == "__main__":
    main()

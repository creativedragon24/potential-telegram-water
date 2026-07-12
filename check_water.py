"""
GWP Water Notifier - GitHub Actions version.
- Multiple fallback fetch methods
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
    """Save empty state when no alerts fetched, so file always exists."""
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
    """Extract and save all streets to streets_db.json (learning system)."""
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
    if not SCRAPER_API_KEY:
        log.error("SCRAPER_API_KEY missing!")
        return []

    try:
        log.info("Trying standard...")
        r = http.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_API_KEY, "url": API_DISCONNECT, "render": "false"},
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("Standard OK (%d alerts)", len(data))
            return data
        log.warning("Standard HTTP %s", r.status_code)
    except Exception as e:
        log.warning("Standard failed: %s", e)

    try:
        log.info("Trying premium...")
        r = http.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_API_KEY, "url": API_DISCONNECT,
                    "render": "false", "premium": "true"},
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("Premium OK (%d alerts)", len(data))
            return data
    except Exception as e:
        log.warning("Premium failed: %s", e)

    try:
        log.info("Trying allorigins...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get(f"https://api.allorigins.win/raw?url={encoded}", timeout=45)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("AllOrigins failed: %s", e)

    log.error("ALL methods failed")
    return []


def build_message(item: dict, lang: str = "en") -> str:
    district_ka = item.get("district", "")
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    address     = item.get("address", "")
    email_text  = item.get("emailText", "") or ""
    code        = item.get("code", "")
    wtype       = item.get("type", "") or ""

    is_emergency = "არაგეგმ" in wtype

    if lang == "ka":
        title    = "🚰 <b>წყალმომარაგების შეწყვეტა</b>"
        status   = "🚨 ავარიული" if is_emergency else "📋 დაგეგმილი"
        d_label  = "📍 <b>რაიონი:</b>"
        a_label  = "🏠 <b>მისამართი:</b>"
        det_lbl  = "📝 <b>დეტალები:</b>"
        aff_lbl  = "🏘️ <b>დაზარალებული ქუჩები:</b>"
        note     = ""
        district_display = district_ka
    else:
        title    = "🚰 <b>WATER SUPPLY INTERRUPTION</b>"
        status   = "🚨 Emergency" if is_emergency else "📋 Planned"
        d_label  = "📍 <b>District:</b>"
        a_label  = "🏠 <b>Address:</b>"
        det_lbl  = "📝 <b>Details (original from GWP):</b>"
        aff_lbl  = "🏘️ <b>Affected streets:</b>"
        note     = "\nℹ️ <i>Content is from GWP in Georgian.</i>\n"
        district_display = district_en

    affected = ""
    for marker in ["შეუწყდება:", "შეუწყდა:", "შეეზღუდება:"]:
        if marker in email_text:
            affected = email_text.split(marker, 1)[1].strip()
            break

    msg = f"{title}\n{status}\n\n"
    msg += f"{d_label} {district_display}\n"
    msg += f"{a_label} {address}\n\n"

    if affected:
        msg += f"{aff_lbl}\n{affected}\n\n"

    msg += f"{det_lbl}\n{email_text}\n"

    if note:
        msg += note

    msg += f"\n🆔 <code>{code}</code>"

    if len(msg) > 4000:
        msg = msg[:3900] + "\n\n... (truncated)"

    return msg


def send(chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, json={
            "chat_id":                 chat_id,
            "text":                    message,
            "parse_mode":              "HTML",
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
    streets   = user.get("streets", [])

    if not districts:
        return False

    district_ka = item.get("district", "")
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    if district_en not in districts:
        return False

    if streets:
        searchable = (item.get("address", "") + " " +
                      item.get("emailText", "")).lower()
        if not any(s.lower() in searchable for s in streets):
            return False

    return True


def main():
    log.info("=== Water Notifier Started ===")
    seen   = load_seen()
    subs   = load_subscribers()
    alerts = fetch_alerts()

    log.info("Loaded %d subscribers, %d alerts, %d seen IDs",
             len(subs), len(alerts), len(seen))

    if not alerts:
        log.warning("No alerts fetched - saving empty state")
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
                user_msg  = build_message(item, lang=user_lang)
                if send(uid, user_msg):
                    total_sent += 1
                    log.info("  -> sent to %s (lang=%s)", uid, user_lang)

    save_seen(seen | new_ids)
    log.info("=== Done: %d new, %d to admin, %d to subs ===",
             len(new_ids), admin_sent, total_sent)


if __name__ == "__main__":
    main()

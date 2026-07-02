"""
GWP Water Notifier — GitHub Actions version.
Multiple fallback methods for API access.
"""
from __future__ import annotations
import os, json, logging, urllib.parse
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

SEEN_FILE        = "seen.json"
SUBSCRIBERS_FILE = "subscribers.json"

API_DISCONNECT = "https://www.gwp.ge/api/Disconnect/ByCity?cityId=1"

DISTRICT_KA_EN = {
    "გლდანი": "Gldani", "დიდუბე": "Didube", "ვაკე": "Vake",
    "ისანი": "Isani", "კრწანისი": "Krtsanisi", "მთაწმინდა": "Mtatsminda",
    "ნაძალადევი": "Nadzaladevi", "საბურთალო": "Saburtalo",
    "ჩუღურეთი": "Chugureti", "წყნეთი": "Tsqneti",
    "სამგორი": "Samgori", "დიღომი": "Dighomi",
}


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list): return set(data)
            if isinstance(data, dict): return set(data.keys())
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


def fetch_alerts() -> list:
    """Try multiple methods to fetch GWP alerts."""
    if not SCRAPER_API_KEY:
        log.error("SCRAPER_API_KEY missing!")
        return []

    # Method 1: Standard
    try:
        log.info("Trying standard...")
        r = http.get(
            "http://api.scraperapi.com",
            params={
                "api_key": SCRAPER_API_KEY,
                "url":     API_DISCONNECT,
                "render":  "false",
            },
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("Standard OK (%d alerts)", len(data))
            return data
        log.warning("Standard HTTP %s", r.status_code)
    except Exception as e:
        log.warning("Standard failed: %s", e)

    # Method 2: Premium
    try:
        log.info("Trying premium...")
        r = http.get(
            "http://api.scraperapi.com",
            params={
                "api_key": SCRAPER_API_KEY,
                "url":     API_DISCONNECT,
                "render":  "false",
                "premium": "true",
            },
            timeout=60,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("Premium OK (%d alerts)", len(data))
            return data
        log.warning("Premium HTTP %s", r.status_code)
    except Exception as e:
        log.warning("Premium failed: %s", e)

    # Method 3: AllOrigins (free)
    try:
        log.info("Trying allorigins...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get(
            f"https://api.allorigins.win/raw?url={encoded}",
            timeout=45,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("AllOrigins OK (%d alerts)", len(data))
            return data
    except Exception as e:
        log.warning("AllOrigins failed: %s", e)

    log.error("ALL methods failed")
    return []


def build_message(item: dict) -> str:
    district_ka = item.get("district", "")
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    address     = item.get("address", "")
    email_text  = item.get("emailText", "") or ""
    code        = item.get("code", "")
    wtype       = item.get("type", "") or ""
    status      = "🚨 Emergency" if "არაგეგმ" in wtype else "📋 Planned"

    if len(email_text) > 500:
        email_text = email_text[:500] + "..."

    return (
        f"🚰 <b>WATER SUPPLY INTERRUPTION</b>\n"
        f"{status}\n\n"
        f"📍 <b>District:</b> {district_en}\n"
        f"🏠 <b>Address:</b> {address}\n\n"
        f"📝 {email_text}\n\n"
        f"🆔 <code>{code}</code>"
    )


def send(chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, json={
            "chat_id": chat_id,
            "text":    message,
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
        log.warning("No alerts fetched — skipping")
        return

    new_ids = set()
    total_sent = 0
    admin_sent = 0

    for item in alerts:
        code = item.get("code", "")
        if not code:
            continue
        if code in seen:
            continue

        new_ids.add(code)
        msg = build_message(item)
        log.info("New alert: %s (%s)", code, item.get("district", ""))

        if ADMIN_CHAT_ID:
            if send(ADMIN_CHAT_ID, msg):
                admin_sent += 1

        for uid, user in subs.items():
            if not user.get("active", True):
                continue
            if alert_matches_user(item, user):
                if send(uid, msg):
                    total_sent += 1
                    log.info("  → sent to subscriber %s", uid)

    save_seen(seen | new_ids)
    log.info("=== Done: %d new, %d to admin, %d to subs ===",
             len(new_ids), admin_sent, total_sent)


if __name__ == "__main__":
    main()

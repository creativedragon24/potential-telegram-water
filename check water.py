"""
check_water.py — GitHub Actions entry point
Scrapes GWP, matches subscriptions stored in seen.json, sends Telegram alerts.
Runs every 15 minutes via GitHub Actions cron.
"""
from __future__ import annotations
import os
import json
import logging
import hashlib
import re
import requests as http
from datetime import datetime

# ── Logging ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("check_water")

# ── Config from GitHub Secrets ────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
CHAT_ID    = os.environ["CHAT_ID"]
DISTRICT   = os.environ.get("DISTRICT", "").strip()   # e.g. "Vake"
STREET     = os.environ.get("STREET",   "").strip()   # e.g. "Nutsubidze"

SEEN_FILE  = "seen.json"
GWP_EN     = "https://www.gwp.ge/en/news/nonscheduled-works"
GWP_KA     = "https://www.gwp.ge/ka/news/nonscheduled-works"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer":         "https://www.gwp.ge/",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
}

# ── District detection ────────────────────────
DISTRICT_FORMS = {
    "Vake":         ["ვაკე", "ვაკის", "ვაკეში"],
    "Saburtalo":    ["საბურთალო", "საბურთალოს", "საბურთალოში"],
    "Isani":        ["ისანი", "ისანის", "ისანში"],
    "Samgori":      ["სამგორი", "სამგორის", "სამგორში"],
    "Didube":       ["დიდუბე", "დიდუბის", "დიდუბეში"],
    "Chugureti":    ["ჩუღურეთი", "ჩუღურეთის", "ჩუღურეთში"],
    "Gldani":       ["გლდანი", "გლდანის", "გლდანში"],
    "Nadzaladevi":  ["ნაძალადევი", "ნაძალადევის", "ნაძალადევში"],
    "Mtatsminda":   ["მთაწმინდა", "მთაწმინდის", "მთაწმინდაზე"],
    "Krtsanisi":    ["კრწანისი", "კრწანისის", "კრწანისში"],
    "Dighomi":      ["დიღომი", "დიღომის", "დიღომში"],
}

# Noise phrases that mean the text is navigation/menu garbage
NAV_NOISE = [
    "chven shesakheb", "kompania", "menejmenti", "sms servisi",
    "onlain gadakhda", "*303#", "distantsiuri", "litsenzirebuli",
    "sajaro dadgenilebebi", "kariera", "etika da politika",
    "chemi kabineti", "meniu", "airchiet district",
    "tbilisi media", "dagegmili works", "mimdinare works",
    "tenderebi", "dokumentebi", "online@gwp.ge", "dzebna",
    "nakhva servi", "siakhleebi",
]

WATER_KEYWORDS_KA = ["შეუწყდება", "შეეზღუდება", "წყალმომარაგება", "წყლის"]
WATER_KEYWORDS_EN = ["water supply", "will be cut", "interruption", "water cut"]


# ── Seen list helpers ─────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # handle both list and dict formats
                if isinstance(data, list):
                    return set(data)
                if isinstance(data, dict):
                    return set(data.keys())
        except Exception:
            pass
    return set()


def save_seen(seen: set) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def make_id(text: str) -> str:
    """Stable hash of the first 200 chars of cleaned text."""
    clean = re.sub(r"\s+", " ", text[:200]).strip()
    return hashlib.md5(clean.encode("utf-8")).hexdigest()[:12]


# ── Scraper ───────────────────────────────────

def _is_noise(text: str) -> bool:
    """Return True if text block is nav/menu garbage."""
    tl = text.lower()
    noise_hits = sum(1 for p in NAV_NOISE if p in tl)
    if noise_hits >= 3:
        return True
    has_water = (
        any(k in text for k in WATER_KEYWORDS_KA) or
        any(k in tl    for k in WATER_KEYWORDS_EN)
    )
    return not has_water


def _clean_line(line: str) -> bool:
    """Return False for lines that are pure nav/phone/footer garbage."""
    l = line.strip()
    if not l:
        return False
    ll = l.lower()
    if any(p in ll for p in NAV_NOISE):
        return False
    # phone numbers
    if re.match(r"^[\d\s\-+()]{7,}$", l):
        return False
    return True


def _clean_text(raw: str) -> str:
    """Remove nav/menu lines and collapse whitespace."""
    lines = [ln.strip() for ln in raw.splitlines()]
    good  = [ln for ln in lines if _clean_line(ln)]
    result = " ".join(good)
    return re.sub(r"\s+", " ", result).strip()


def _detect_districts(text: str) -> list[str]:
    found = []
    for eng, forms in DISTRICT_FORMS.items():
        if any(f in text for f in forms):
            found.append(eng)
    return found


def _extract_time(text: str) -> str:
    m = re.search(
        r"(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})",
        text
    )
    if m:
        return f"{m.group(1).replace('.', ':')} – {m.group(2).replace('.', ':')}"
    return ""


def _extract_date(text: str) -> str:
    m = re.search(r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", text)
    return m.group(1) if m else datetime.now().strftime("%-m/%-d")


def scrape_alerts() -> list[dict]:
    """
    Pure requests + BeautifulSoup scraper.
    No Selenium needed — works perfectly on GitHub Actions.
    """
    from bs4 import BeautifulSoup

    raw_blocks = []

    for url in [GWP_EN, GWP_KA]:
        try:
            resp = http.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Step 1: Remove nav/header/footer noise from DOM
            for tag in soup.select(
                "nav, header, footer, .navbar, .menu, .sidebar, "
                ".breadcrumb, #navigation, .nav-menu, .top-menu, "
                ".header-menu, .footer-links, script, style, "
                "[class*='contact'], [class*='footer']"
            ):
                tag.decompose()

            # Step 2: Try known card selectors first
            card_selectors = [
                ".gadaudebeli-item", ".news-item", ".alert-card",
                ".nonscheduled-item", "article.news", ".news-body",
                "[class*='news-card']", "[class*='alert']",
                "article", ".card",
            ]

            cards = []
            for sel in card_selectors:
                found = soup.select(sel)
                if found:
                    log.info("Found %d cards with selector: %s", len(found), sel)
                    cards = found
                    break

            if cards:
                for card in cards:
                    text = card.get_text(separator=" ", strip=True)
                    if len(text) > 60:
                        raw_blocks.append(text)
            else:
                # Fallback: grab divs/sections with water keywords only
                log.warning("No cards found for %s — using keyword fallback", url)
                for el in soup.find_all(["div", "section", "p"]):
                    children = el.find_all(["div", "article", "section"])
                    if len(children) > 3:
                        continue
                    text = el.get_text(separator=" ", strip=True)
                    if len(text) < 80:
                        continue
                    has_water = (
                        any(k in text for k in WATER_KEYWORDS_KA) or
                        any(k in text.lower() for k in WATER_KEYWORDS_EN)
                    )
                    if has_water:
                        raw_blocks.append(text)

            log.info("Got %d raw blocks from %s", len(raw_blocks), url)

            # If we got results from EN, no need to try KA
            if raw_blocks:
                break

        except Exception as e:
            log.warning("Scrape failed for %s: %s", url, e)
            continue

    # Step 3: Clean and filter
    cleaned = []
    for raw in raw_blocks:
        clean = _clean_text(raw)
        if clean and len(clean) > 60 and not _is_noise(clean):
            cleaned.append(clean)

    # Step 4: Deduplicate by (time + district) signature
    groups: dict[str, str] = {}
    for text in cleaned:
        time_sig     = _extract_time(text)
        districts    = _detect_districts(text)
        district_sig = ",".join(sorted(districts)) if districts else "unknown"
        sig          = f"{time_sig}|{district_sig}"

        if sig not in groups or len(text) > len(groups[sig]):
            groups[sig] = text

    # Step 5: Remove substrings
    unique = list(groups.values())
    final  = []
    for t1 in unique:
        is_sub = any(
            t1 != t2 and t1 in t2 and len(t1) < len(t2) - 20
            for t2 in unique
        )
        if not is_sub:
            final.append(t1)

    log.info("Dedup: %d raw → %d final", len(raw_blocks), len(final))
    return [
        {
            "id":        make_id(t),
            "text":      t,
            "districts": _detect_districts(t),
            "time":      _extract_time(t),
            "date":      _extract_date(t),
        }
        for t in final
    ]


# ── Notification builder ──────────────────────

def build_message(alert: dict) -> str:
    """Build a clean Telegram message — same style as your laptop bot."""
    districts = alert["districts"]
    district_str = ", ".join(districts) if districts else "Unknown"
    time_str     = alert["time"]  or "Unknown"
    date_str     = alert["date"]  or datetime.now().strftime("%-m/%-d")
    text         = alert["text"]

    # Trim the affected area text
    area = text
    if len(area) > 400:
        area = area[:400].rsplit(" ", 1)[0] + "..."

    msg = (
        f"🚰 <b>WATER SUPPLY INTERRUPTION</b>\n"
        f"📍 <b>District:</b> {district_str}\n"
        f"⏱ <b>Time:</b> {time_str}\n"
        f"📅 <b>Date:</b> {date_str}\n"
        f"\n"
        f"📝 <b>Affected area:</b>\n"
        f"{area}\n"
        f"\n"
        f"🔗 {GWP_EN}"
    )
    return msg


# ── Telegram sender ───────────────────────────

def send_telegram(chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = http.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=15)
        if resp.status_code == 200:
            log.info("✅ Sent to %s", chat_id)
            return True
        else:
            log.warning("Telegram error %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


# ── District/street matching ──────────────────

def matches(alert: dict) -> bool:
    """Check if alert matches the configured DISTRICT and STREET."""
    # If no filter set → notify for everything
    if not DISTRICT:
        return True

    # District match
    if DISTRICT not in alert["districts"]:
        # Also try case-insensitive
        if not any(
            DISTRICT.lower() == d.lower()
            for d in alert["districts"]
        ):
            return False

    # Street match (optional)
    if STREET:
        if STREET.lower() not in alert["text"].lower():
            return False

    return True


# ── Main ──────────────────────────────────────

def main():
    log.info("=== GWP Water Check Started ===")
    log.info("Filter → District: '%s'  Street: '%s'", DISTRICT, STREET)

    seen    = load_seen()
    alerts  = scrape_alerts()
    new_ids = set()
    sent    = 0

    log.info("Found %d total alerts", len(alerts))

    for alert in alerts:
        aid = alert["id"]

        if aid in seen:
            log.info("Already seen: %s", aid)
            continue

        log.info(
            "New alert [%s] districts=%s time=%s",
            aid, alert["districts"], alert["time"]
        )

        if matches(alert):
            msg = build_message(alert)
            ok  = send_telegram(CHAT_ID, msg)
            if ok:
                sent += 1
        else:
            log.info("Does not match filter — skipping notification")

        # Mark seen regardless of match so we don't re-process
        new_ids.add(aid)

    # Save updated seen list
    updated_seen = seen | new_ids
    save_seen(updated_seen)
    log.info("=== Done: %d sent, %d new IDs saved ===", sent, len(new_ids))


if __name__ == "__main__":
    main()

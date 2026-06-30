"""
GWP Water Cut Telegram Bot
Uses GWP JSON API via ScraperAPI proxy (1 credit per call).
"""
from __future__ import annotations
import os, json, logging, re, urllib.parse
import requests as http
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("water_bot")

# ── Config from GitHub Secrets ───────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
DISTRICT        = os.environ.get("DISTRICT", "").strip()
STREET          = os.environ.get("STREET",   "").strip()
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

SEEN_FILE = "seen.json"

# ── GWP API ───────────────────────────────────
API_DISCONNECT = "https://www.gwp.ge/api/Disconnect/ByCity?cityId=1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8",
    "Referer":         "https://www.gwp.ge/",
}

# ── District mapping ──────────────────────────
DISTRICT_KA_EN = {
    "გლდანი":     "Gldani",
    "დიდუბე":     "Didube",
    "ვაკე":       "Vake",
    "ისანი":      "Isani",
    "კრწანისი":   "Krtsanisi",
    "მთაწმინდა":  "Mtatsminda",
    "ნაძალადევი": "Nadzaladevi",
    "საბურთალო":  "Saburtalo",
    "ჩუღურეთი":   "Chugureti",
    "წყნეთი":     "Tsqneti",
    "სამგორი":    "Samgori",
    "დიღომი":     "Dighomi",
}
DISTRICT_EN_KA = {v.lower(): k for k, v in DISTRICT_KA_EN.items()}

# ── Translation dictionary ────────────────────
KA_EN = {
    "მოქალაქის კუთვნილ წყალსადენის ქსელზე დაზიანების აღდგენითი სამუშაოების ჩატარების მიზნით":
        "to repair damage on citizen-owned water pipeline",
    "წყალმომარაგების აღდგენის დროს შეგატყობინებთ მოგვიანებით":
        "restoration time will be announced later",
    "წყალმომარაგების ქსელზე დაზიანების გამო":
        "due to water supply network damage",
    "წყალსადენის ქსელზე დაზიანების გამო":
        "due to water pipeline damage",
    "წყალმომარაგება შეუწყდა":     "water supply was cut off",
    "წყალმომარაგება შეუწყდება":   "water supply will be cut off",
    "წყალმომარაგება შეუწყდათ ავარიულად": "water supply was emergency-cut at",
    "სატუმბო სადგურს შეუწყდა ელ.ენერგიის მიწოდება": "pumping station lost electricity",
    "საათამდე": "until", "დან": "from", "მდე": "to",
    "ჩათვლით": "inclusive", "კენტები": "odd numbers", "ლუწები": "even numbers",
    "ქუჩას": "St.", "ქუჩა": "St.", "ქუჩის": "St.",
    "ქუჩები": "Streets", "ქუჩებს": "Streets",
    "გამზ.": "Ave.", "გამზ": "Ave.", "გამზირი": "Ave.", "გამზირის": "Ave.",
    "შესახვევი": "Lane", "შესახვევს": "Lane",
    "შესახვევებს": "Lanes", "შესახვევებით": "with lanes",
    "ჩიხი": "Dead End", "ჩიხს": "Dead End",
    "მიკრო": "microdistrict", "მიკროს": "microdistrict", "მ/რ": "microdistrict",
    "კვარტალი": "block", "კვ.": "block", "კვ": "block",
    "სოფ.": "village", "სოფელ": "village",
    "მასივი": "settlement", "მასივის": "settlement",
    "დასახლება": "settlement", "დასახლებას": "settlement",
    "უბანი": "area", "უბანს": "area",
    "ეკლესიის": "church", "სატუმბო": "pumping", "სადგურს": "station",
    "ელ.ენერგიის": "electricity", "მიწოდება": "supply",
    "ავარიულად": "emergency", "და": "and", "თან": "at",
}
KA_EN_SORTED = sorted(KA_EN.items(), key=lambda x: len(x[0]), reverse=True)

KA_LATIN = {
    "ა":"a","ბ":"b","გ":"g","დ":"d","ე":"e","ვ":"v","ზ":"z",
    "თ":"t","ი":"i","კ":"k","ლ":"l","მ":"m","ნ":"n","ო":"o",
    "პ":"p","ჟ":"zh","რ":"r","ს":"s","ტ":"t","უ":"u","ფ":"p",
    "ქ":"k","ღ":"gh","ყ":"q","შ":"sh","ჩ":"ch","ც":"ts",
    "ძ":"dz","წ":"ts","ჭ":"ch","ხ":"kh","ჯ":"j","ჰ":"h",
}


# ── Seen helpers ──────────────────────────────

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


# ── Translation ───────────────────────────────

def _strip_genitive(word: str) -> str:
    w = word.rstrip(",.;:!)")
    if w.endswith("ის") and len(w) > 4: return w[:-2]
    if w.endswith("ში") and len(w) > 4: return w[:-2]
    if w.endswith("ს")  and len(w) > 3: return w[:-1]
    return w


def _transliterate(text: str) -> str:
    result = "".join(KA_LATIN.get(ch, ch) for ch in text)
    return " ".join(w.capitalize() for w in result.split() if w)


def translate(text: str) -> str:
    if not text: return ""
    result = text
    for ka, en in KA_EN_SORTED:
        result = result.replace(ka, en)
    out = []
    for word in result.split():
        if any("\u10d0" <= ch <= "\u10fa" for ch in word):
            out.append(_transliterate(_strip_genitive(word)))
        else:
            out.append(word)
    result = " ".join(out)
    result = re.sub(r"\b(St\.|Ave\.|and|at|from|to)\s+\1\b", r"\1", result)
    return re.sub(r"\s{2,}", " ", result).strip()


# ── Time/Date extraction ──────────────────────

_DATETIME_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\s+"
    r"(?:დან|from)\s+"
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\s+"
    r"(?:საათამდე|until)"
)
_UNTIL_ONLY_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\s+(?:საათამდე|until)"
)


def extract_time_date(text: str) -> tuple[str, str]:
    m = _DATETIME_RE.search(text)
    if m:
        d1, t1, d2, t2 = m.groups()
        time_range = f"{t1} – {t2}"
        date_range = d1 if d1 == d2 else f"{d1} → {d2}"
        return time_range, date_range
    m = _UNTIL_ONLY_RE.search(text)
    if m:
        d, t = m.groups()
        return f"until {t}", d
    return "See message", datetime.now().strftime("%-m/%-d/%Y")


def extract_streets(text: str) -> str:
    if "შეუწყდება:" in text:
        part = text.split("შეუწყდება:", 1)[1]
    elif "შეუწყდა:" in text:
        part = text.split("შეუწყდა:", 1)[1]
    elif ":" in text:
        part = text.split(":", 1)[1]
    else:
        part = text
    return translate(part.strip())


# ── Fetch alerts — MULTIPLE METHODS ──────────

def fetch_alerts() -> list:
    """Try ScraperAPI first, fallback to free proxies, then direct."""

    # ── Method 1: ScraperAPI (1 credit per call) ──
    if SCRAPER_API_KEY:
        try:
            log.info("Trying ScraperAPI (1 credit)...")
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
                log.info("ScraperAPI SUCCESS — %d alerts", len(data))
                return data
            log.warning("ScraperAPI HTTP %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("ScraperAPI error: %s", e)
    else:
        log.warning("SCRAPER_API_KEY secret is missing!")

    # ── Method 2: AllOrigins (free unlimited) ──
    try:
        log.info("Trying AllOrigins proxy...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get(
            f"https://api.allorigins.win/raw?url={encoded}",
            timeout=45,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("AllOrigins SUCCESS — %d alerts", len(data))
            return data
    except Exception as e:
        log.warning("AllOrigins error: %s", e)

    # ── Method 3: corsproxy.io (free unlimited) ──
    try:
        log.info("Trying corsproxy.io...")
        encoded = urllib.parse.quote(API_DISCONNECT, safe="")
        r = http.get(
            f"https://corsproxy.io/?{encoded}",
            timeout=45,
        )
        if r.status_code == 200:
            data = r.json()
            log.info("corsproxy.io SUCCESS — %d alerts", len(data))
            return data
    except Exception as e:
        log.warning("corsproxy.io error: %s", e)

    # ── Method 4: Direct (fails on GitHub Actions) ──
    try:
        log.info("Trying direct request...")
        r = http.get(API_DISCONNECT, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        log.info("Direct SUCCESS — %d alerts", len(data))
        return data
    except Exception as e:
        log.warning("Direct error: %s", e)

    log.error("ALL methods failed — no data this cycle")
    return []


# ── Message builder ───────────────────────────

def build_message(item: dict) -> str:
    district_ka = item.get("district", "").strip()
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    address_en  = translate(item.get("address", "").strip())
    email_text  = item.get("emailText", "") or ""
    time_str, date_str = extract_time_date(email_text)
    streets     = extract_streets(email_text)
    code        = item.get("code", "")
    wtype       = item.get("type", "")
    status_en   = "🚨 Emergency" if "არაგეგმ" in wtype else "📋 Planned"

    if len(streets) > 600:
        streets = streets[:600].rsplit(" ", 1)[0] + "..."

    return (
        f"🚰 <b>WATER SUPPLY INTERRUPTION</b>\n"
        f"{status_en}\n"
        f"\n"
        f"📍 <b>District:</b> {district_en}\n"
        f"🏠 <b>Address:</b> {address_en}\n"
        f"⏱ <b>Time:</b> {time_str}\n"
        f"📅 <b>Date:</b> {date_str}\n"
        f"\n"
        f"📝 <b>Affected streets:</b>\n"
        f"{streets}\n"
        f"\n"
        f"🆔 <code>{code}</code>\n"
        f"🔗 https://www.gwp.ge/en/news/nonscheduled-works"
    )


# ── Telegram sender ───────────────────────────

def send_telegram(chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, json={
            "chat_id":                 chat_id,
            "text":                    message,
            "parse_mode":              "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code == 200:
            log.info("Telegram OK → %s", chat_id)
            return True
        log.warning("Telegram %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        log.warning("Telegram error: %s", e)
        return False


# ── Filter matching ───────────────────────────

def matches_filter(item: dict) -> bool:
    if not DISTRICT:
        return True
    district_ka = item.get("district", "").strip()
    district_en = DISTRICT_KA_EN.get(district_ka, district_ka)
    d_in = DISTRICT.lower()
    if (d_in != district_en.lower() and
        d_in != district_ka.lower() and
        DISTRICT_EN_KA.get(d_in, "") != district_ka):
        return False
    if STREET:
        searchable = (
            item.get("address", "") + " " +
            item.get("emailText", "") + " " +
            translate(item.get("address", "")) + " " +
            translate(item.get("emailText", ""))
        ).lower()
        if STREET.lower() not in searchable:
            return False
    return True


# ── Main ──────────────────────────────────────

def main():
    log.info("=== GWP Water Bot Started ===")
    log.info("Filter → District:'%s'  Street:'%s'", DISTRICT, STREET)
    log.info("ScraperAPI key present: %s", "YES" if SCRAPER_API_KEY else "NO")

    seen    = load_seen()
    alerts  = fetch_alerts()
    new_ids = set()
    sent    = 0

    log.info("Processing %d alerts (seen so far: %d)", len(alerts), len(seen))

    for item in alerts:
        code = item.get("code", "")
        if not code: continue
        if code in seen: continue

        district = item.get("district", "")
        log.info("New alert: %s (%s)", code, district)

        if matches_filter(item):
            if send_telegram(CHAT_ID, build_message(item)):
                sent += 1
        else:
            log.info("  → skipped (filter does not match)")

        new_ids.add(code)

    save_seen(seen | new_ids)
    log.info("=== Done: %d sent, %d new IDs saved ===", sent, len(new_ids))


if __name__ == "__main__":
    main()

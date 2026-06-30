from __future__ import annotations
import os, json, logging, hashlib, re, requests as http
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("check_water")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
DISTRICT  = os.environ.get("DISTRICT", "").strip()
STREET    = os.environ.get("STREET",   "").strip()

SEEN_FILE = "seen.json"
GWP_EN    = "https://www.gwp.ge/en/news/nonscheduled-works"
GWP_KA    = "https://www.gwp.ge/ka/news/nonscheduled-works"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer":         "https://www.gwp.ge/",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
}

DISTRICT_FORMS = {
    "Vake":        ["ვაკე","ვაკის","ვაკეში"],
    "Saburtalo":   ["საბურთალო","საბურთალოს","საბურთალოში"],
    "Isani":       ["ისანი","ისანის","ისანში"],
    "Samgori":     ["სამგორი","სამგორის","სამგორში"],
    "Didube":      ["დიდუბე","დიდუბის","დიდუბეში"],
    "Chugureti":   ["ჩუღურეთი","ჩუღურეთის","ჩუღურეთში"],
    "Gldani":      ["გლდანი","გლდანის","გლდანში"],
    "Nadzaladevi": ["ნაძალადევი","ნაძალადევის","ნაძალადევში"],
    "Mtatsminda":  ["მთაწმინდა","მთაწმინდის","მთაწმინდაზე"],
    "Krtsanisi":   ["კრწანისი","კრწანისის","კრწანისში"],
    "Dighomi":     ["დიღომი","დიღომის","დიღომში"],
}

NAV_NOISE = [
    "chven shesakheb","kompania","menejmenti","sms servisi",
    "onlain gadakhda","*303#","distantsiuri","litsenzirebuli",
    "sajaro dadgenilebebi","kariera","etika da politika",
    "chemi kabineti","meniu","airchiet district",
    "tbilisi media","dagegmili works","mimdinare works",
    "tenderebi","dokumentebi","online@gwp.ge","dzebna",
    "nakhva servi","siakhleebi",
]

WATER_KA = ["შეუწყდება","შეეზღუდება","წყალმომარაგება","წყლის"]
WATER_EN = ["water supply","will be cut","interruption","water cut"]


# ── Seen helpers ──────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE,"r",encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list): return set(data)
            if isinstance(data, dict): return set(data.keys())
        except Exception:
            pass
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE,"w",encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)

def make_id(text: str) -> str:
    clean = re.sub(r"\s+"," ", text[:200]).strip()
    return hashlib.md5(clean.encode("utf-8")).hexdigest()[:12]


# ── Text helpers ──────────────────────────────

def is_noise(text: str) -> bool:
    tl = text.lower()
    if sum(1 for p in NAV_NOISE if p in tl) >= 3:
        return True
    has_water = any(k in text for k in WATER_KA) or any(k in tl for k in WATER_EN)
    return not has_water

def clean_line(line: str) -> bool:
    l = line.strip()
    if not l: return False
    if any(p in l.lower() for p in NAV_NOISE): return False
    if re.match(r"^[\d\s\-+()]{7,}$", l): return False
    return True

def clean_text(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines()]
    good  = [ln for ln in lines if clean_line(ln)]
    return re.sub(r"\s+"," "," ".join(good)).strip()

def detect_districts(text: str) -> list:
    return [eng for eng,forms in DISTRICT_FORMS.items()
            if any(f in text for f in forms)]

def extract_time(text: str) -> str:
    m = re.search(r"(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})", text)
    if m:
        return (f"{m.group(1).replace('.', ':')} – "
                f"{m.group(2).replace('.', ':')}")
    return ""

def extract_date(text: str) -> str:
    m = re.search(r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", text)
    return m.group(1) if m else datetime.now().strftime("%-m/%-d")


# ── HTTP fetch with multiple bypass methods ───

def _fetch_html(target_url: str) -> str | None:
    """
    Try multiple methods to get the HTML.
    Method 1: ScraperAPI free tier  (1000 free requests/month)
    Method 2: Scrape.do free tier   (1000 free requests/month)
    Method 3: AllOrigins CORS proxy (unlimited but slow)
    Method 4: Direct request        (works if GWP unblocks GitHub)
    """

    # ── Method 1: ScraperAPI ──────────────────
    # Sign up free at https://www.scraperapi.com
    # Get your API key and add it as GitHub Secret: SCRAPER_API_KEY
    scraper_api_key = os.environ.get("SCRAPER_API_KEY", "").strip()
    if scraper_api_key:
        try:
            log.info("Trying ScraperAPI...")
            r = http.get(
                "http://api.scraperapi.com",
                params={
                    "api_key": scraper_api_key,
                    "url":     target_url,
                    "render":  "false",
                },
                timeout=60,
            )
            if r.status_code == 200 and len(r.text) > 500:
                log.info("ScraperAPI success (%d bytes)", len(r.text))
                return r.text
            log.warning("ScraperAPI returned %s", r.status_code)
        except Exception as e:
            log.warning("ScraperAPI failed: %s", e)

    # ── Method 2: Scrape.do ───────────────────
    # Sign up free at https://scrape.do
    # Add token as GitHub Secret: SCRAPEDO_TOKEN
    scrapedo_token = os.environ.get("SCRAPEDO_TOKEN", "").strip()
    if scrapedo_token:
        try:
            log.info("Trying Scrape.do...")
            import urllib.parse
            encoded = urllib.parse.quote(target_url)
            r = http.get(
                f"https://api.scrape.do?token={scrapedo_token}&url={encoded}",
                timeout=60,
            )
            if r.status_code == 200 and len(r.text) > 500:
                log.info("Scrape.do success (%d bytes)", len(r.text))
                return r.text
            log.warning("Scrape.do returned %s", r.status_code)
        except Exception as e:
            log.warning("Scrape.do failed: %s", e)

    # ── Method 3: AllOrigins (no signup needed) ──
    try:
        log.info("Trying AllOrigins proxy...")
        import urllib.parse
        encoded = urllib.parse.quote(target_url)
        r = http.get(
            f"https://api.allorigins.win/get?url={encoded}",
            timeout=45,
        )
        if r.status_code == 200:
            data = r.json()
            html = data.get("contents", "")
            if html and len(html) > 500:
                log.info("AllOrigins success (%d bytes)", len(html))
                return html
        log.warning("AllOrigins returned empty or %s", r.status_code)
    except Exception as e:
        log.warning("AllOrigins failed: %s", e)

    # ── Method 4: Direct (fallback) ──────────
    try:
        log.info("Trying direct request...")
        r = http.get(target_url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.text) > 500:
            log.info("Direct request success (%d bytes)", len(r.text))
            return r.text
        log.warning("Direct returned %s", r.status_code)
    except Exception as e:
        log.warning("Direct failed: %s", e)

    return None


# ── Scraper ───────────────────────────────────

def _parse_html(html: str, url: str) -> list:
    """Parse HTML and extract water alert text blocks."""
    raw_blocks = []

    try:
        soup = BeautifulSoup(html, "lxml")

        # Remove nav/header/footer noise
        for tag in soup.select(
            "nav,header,footer,.navbar,.menu,.sidebar,"
            ".breadcrumb,#navigation,.nav-menu,.top-menu,"
            ".header-menu,.footer-links,script,style"
        ):
            tag.decompose()

        # Try known card selectors first
        card_selectors = [
            ".gadaudebeli-item",".news-item",".alert-card",
            ".nonscheduled-item","article.news",".news-body",
            "[class*='news-card']","[class*='alert']",
            "article",".card",
        ]

        cards = []
        for sel in card_selectors:
            found = soup.select(sel)
            if found:
                log.info("Cards found: %s (%d)", sel, len(found))
                cards = found
                break

        if cards:
            for card in cards:
                t = card.get_text(separator=" ", strip=True)
                if len(t) > 60:
                    raw_blocks.append(t)
        else:
            # Keyword fallback
            log.warning("No card selector matched — keyword fallback")
            for el in soup.find_all(["div","section","p"]):
                if len(el.find_all(["div","article","section"])) > 3:
                    continue
                t = el.get_text(separator=" ", strip=True)
                if len(t) < 80:
                    continue
                has_water = (
                    any(k in t for k in WATER_KA) or
                    any(k in t.lower() for k in WATER_EN)
                )
                if has_water:
                    raw_blocks.append(t)

        log.info("%d raw blocks from %s", len(raw_blocks), url)

    except Exception as e:
        log.warning("HTML parse error: %s", e)

    return raw_blocks


def scrape_alerts() -> list:
    raw_blocks = []

    for url in [GWP_EN, GWP_KA]:
        html = _fetch_html(url)
        if html:
            raw_blocks = _parse_html(html, url)
            if raw_blocks:
                break
        else:
            log.warning("Could not fetch %s", url)

    # Clean
    cleaned = []
    for raw in raw_blocks:
        c = clean_text(raw)
        if c and len(c) > 60 and not is_noise(c):
            cleaned.append(c)

    # Deduplicate by (time + district)
    groups: dict = {}
    for text in cleaned:
        sig = f"{extract_time(text)}|{','.join(sorted(detect_districts(text)))}"
        if sig not in groups or len(text) > len(groups[sig]):
            groups[sig] = text

    unique = list(groups.values())
    final  = [
        t1 for t1 in unique
        if not any(
            t1 != t2 and t1 in t2 and len(t1) < len(t2) - 20
            for t2 in unique
        )
    ]

    log.info("Dedup: %d raw → %d final", len(raw_blocks), len(final))

    return [{
        "id":        make_id(t),
        "text":      t,
        "districts": detect_districts(t),
        "time":      extract_time(t),
        "date":      extract_date(t),
    } for t in final]


# ── Message builder ───────────────────────────

def build_message(alert: dict) -> str:
    districts = ", ".join(alert["districts"]) if alert["districts"] else "Unknown"
    time_str  = alert["time"] or "See details"
    date_str  = alert["date"] or datetime.now().strftime("%-m/%-d")
    area      = alert["text"]
    if len(area) > 400:
        area  = area[:400].rsplit(" ", 1)[0] + "..."

    return (
        f"🚰 <b>WATER SUPPLY INTERRUPTION</b>\n"
        f"📍 <b>District:</b> {districts}\n"
        f"⏱ <b>Time:</b> {time_str}\n"
        f"📅 <b>Date:</b> {date_str}\n"
        f"\n"
        f"📝 <b>Affected area:</b>\n"
        f"{area}\n"
        f"\n"
        f"🔗 {GWP_EN}"
    )


# ── Telegram ──────────────────────────────────

def send_telegram(chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = http.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=15)
        if r.status_code == 200:
            log.info("Sent to %s", chat_id)
            return True
        log.warning("Telegram error %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        log.warning("Send failed: %s", e)
        return False


# ── Matching ──────────────────────────────────

def matches(alert: dict) -> bool:
    if not DISTRICT:
        return True
    if not any(DISTRICT.lower() == d.lower() for d in alert["districts"]):
        return False
    if STREET and STREET.lower() not in alert["text"].lower():
        return False
    return True


# ── Main ──────────────────────────────────────

def main():
    log.info("=== GWP Water Check Started ===")
    log.info("Filter → District:'%s'  Street:'%s'", DISTRICT, STREET)

    seen    = load_seen()
    alerts  = scrape_alerts()
    new_ids: set = set()
    sent    = 0

    log.info("Total alerts found: %d", len(alerts))

    for alert in alerts:
        aid = alert["id"]
        if aid in seen:
            log.info("Already seen: %s", aid)
            continue

        log.info("New alert [%s] districts=%s time=%s",
                 aid, alert["districts"], alert["time"])

        if matches(alert):
            if send_telegram(CHAT_ID, build_message(alert)):
                sent += 1
        else:
            log.info("No match for filter — skip")

        new_ids.add(aid)

    save_seen(seen | new_ids)
    log.info("=== Done: %d sent, %d new IDs saved ===", sent, len(new_ids))


if __name__ == "__main__":
    main()

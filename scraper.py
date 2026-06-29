"""
GWP Water-Cut Scraper — v6 FIXED
- Removes nav/menu text contamination
- Targets ONLY alert card content
- Works on GitHub Actions (headless Chrome)
- Falls back to requests+BS4 if Selenium fails
"""

import time
import re
import logging
import hashlib
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config

log = logging.getLogger("scraper")

GWP_URL_KA = "https://www.gwp.ge/ka/news/nonscheduled-works"
GWP_URL_EN = "https://www.gwp.ge/en/news/nonscheduled-works"

# ─────────────────────────────────────────────
# NOISE FILTER — These are nav/footer/menu strings
# that contaminate the scraped output
# ─────────────────────────────────────────────
NAV_NOISE_PHRASES = [
    "chven shesakheb", "kompania", "menejmenti", "khariskhi",
    "istoria", "obiektebi", "csr", "taripi", "servisebi",
    "khshirad dasmuli kitkhvebi", "gantskhadebi", "pormebi",
    "sms servisi", "onlain gadakhda", "*303#", "distantsiuri",
    "litsenzirebuli", "sajaro dadgenilebebi", "kariera",
    "etika da politika", "etikisa da ktsevi", "kodeksi",
    "politika etiki", "arkhi", "kontakti", "geo eng",
    "chemi kabineti", "meniu", "airchiet district",
    "tbilisi media", "mzia", "nakhva servi tsentrebi",
    "onlain gantskhadebebi", "online@gwp.ge",
    "dagegmili works", "mimdinare works", "tenderebi",
    "dokumentebi", "siakhleebi", "dzebna"
]

# Georgian nav phrases
NAV_NOISE_KA = [
    "ჩვენ შესახებ", "კომპანია", "მენეჯმენტი", "ხარისხი",
    "ისტორია", "ობიექტები", "ტარიფი", "ხშირად დასმული",
    "განცხადებები", "ფორმები", "დისტანციური სერვისი",
    "ლიცენზირებული", "საჯარო", "კარიერა", "ეთიკა",
    "კონტაქტი", "ჩემი კაბინეტი", "მენიუ", "სიახლეები",
    "დაგეგმილი", "მიმდინარე", "ტენდერები", "დოკუმენტები"
]

DISTRICT_FORMS = {
    "Vake": ["ვაკე", "ვაკის", "ვაკეში", "ვაკის რაიონში"],
    "Saburtalo": ["საბურთალო", "საბურთალოს", "საბურთალოში"],
    "Isani": ["ისანი", "ისანის", "ისანში"],
    "Samgori": ["სამგორი", "სამგორის", "სამგორში"],
    "Didube": ["დიდუბე", "დიდუბის", "დიდუბეში"],
    "Chugureti": ["ჩუღურეთი", "ჩუღურეთის", "ჩუღურეთში"],
    "Gldani": ["გლდანი", "გლდანის", "გლდანში"],
    "Nadzaladevi": ["ნაძალადევი", "ნაძალადევის", "ნაძალადევში"],
    "Mtatsminda": ["მთაწმინდა", "მთაწმინდის", "მთაწმინდაზე"],
    "Krtsanisi": ["კრწანისი", "კრწანისის", "კრწანისში"],
    "Dighomi": ["დიღომი", "დიღომის", "დიღომში"],
    "Gldani-Nadzaladevi": ["გლდანი-ნაძალადევი"],
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _detect_districts(text: str) -> list[str]:
    found = []
    for eng, forms in DISTRICT_FORMS.items():
        for form in forms:
            if form in text:
                found.append(eng)
                break
    return found


def _extract_time(text: str) -> str:
    match = re.search(r'(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})', text)
    if match:
        t1 = match.group(1).replace('.', ':')
        t2 = match.group(2).replace('.', ':')
        return f"{t1}–{t2}"
    return ""


def _is_nav_noise(text: str) -> bool:
    """Return True if this text block is navigation/menu garbage."""
    text_lower = text.lower()

    # Count how many nav phrases appear
    noise_count = sum(1 for phrase in NAV_NOISE_PHRASES if phrase in text_lower)
    ka_noise_count = sum(1 for phrase in NAV_NOISE_KA if phrase in text)

    # If more than 3 nav phrases → it's a nav block
    if noise_count >= 3 or ka_noise_count >= 3:
        return True

    # If it does NOT contain any water-related keywords → skip
    water_keywords_ka = ["წყალმომარაგება", "შეუწყდება", "შეეზღუდება", "წყლის"]
    water_keywords_en = ["water supply", "water cut", "interruption", "will be cut"]

    has_water_keyword = any(k in text for k in water_keywords_ka + water_keywords_en)
    if not has_water_keyword:
        return True

    return False


def _clean_text(text: str) -> str:
    """Remove nav/menu contamination from beginning and end of text."""
    lines = text.split('\n')
    clean_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line_lower = line.lower()

        # Skip nav/menu lines
        is_noise = any(phrase in line_lower for phrase in NAV_NOISE_PHRASES)
        is_ka_noise = any(phrase in line for phrase in NAV_NOISE_KA)

        if is_noise or is_ka_noise:
            continue

        # Skip phone numbers that appear in footer
        if re.match(r'^\d{3}\s+\d{3}\s+\d{2}\s+\d{2}$', line):
            continue
        if re.match(r'^0\d{9,10}$', line):
            continue

        clean_lines.append(line)

    result = ' '.join(clean_lines)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def _deduplicate_alerts(raw_texts: list) -> list:
    """Group by (time + district), keep the longest/cleanest version."""
    cleaned = []
    for t in raw_texts:
        c = _clean_text(t)
        if c and len(c) > 60:
            cleaned.append(c)

    # Remove nav noise blocks
    water_only = [t for t in cleaned if not _is_nav_noise(t)]

    # Group by signature
    groups = {}
    for text in water_only:
        time_sig = _extract_time(text)
        districts = _detect_districts(text)
        district_sig = ",".join(sorted(districts)) if districts else "unknown"

        # Use first 60 chars as fallback for grouping
        if not time_sig and district_sig == "unknown":
            sig_key = hashlib.md5(text[:60].encode()).hexdigest()[:8]
        else:
            sig_key = f"{time_sig}|{district_sig}"

        if sig_key not in groups or len(text) > len(groups[sig_key]):
            groups[sig_key] = text

    # Final substring dedup
    unique = list(groups.values())
    final = []
    for t1 in unique:
        if not any(t1 != t2 and t1 in t2 and len(t1) < len(t2) - 20 for t2 in unique):
            final.append(t1)

    log.info(f"Dedup: raw={len(raw_texts)} → clean={len(water_only)} → final={len(final)}")
    return final


# ─────────────────────────────────────────────
# METHOD 1: requests + BeautifulSoup (FAST, preferred)
# ─────────────────────────────────────────────

def _fetch_with_requests() -> list:
    """Fast scraper using requests. No Selenium needed."""
    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/124.0.0.0 Safari/537.36'),
        'Referer': 'https://www.gwp.ge/',
        'Accept-Language': 'ka-GE,ka;q=0.9,en-US;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    results = []

    for url in [GWP_URL_EN, GWP_URL_KA]:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'lxml')

            # ── Remove nav, header, footer FIRST ──
            for tag in soup.select('nav, header, footer, .navbar, .menu, '
                                   '.sidebar, .breadcrumb, #navigation, '
                                   '.nav-menu, .top-menu, .header-menu, '
                                   '.footer-links, .contact-info, script, style'):
                tag.decompose()

            # ── Try known GWP card selectors ──
            card_selectors = [
                '.gadaudebeli-item', '.news-item', '.alert-card',
                '.nonscheduled-item', 'article', '.card',
                '.news-body', '.announcement', '.region-card',
                '[class*="news"]', '[class*="alert"]', '[class*="card"]'
            ]

            found_cards = []
            for selector in card_selectors:
                cards = soup.select(selector)
                if cards:
                    log.info(f"Found {len(cards)} cards with selector: {selector}")
                    found_cards = cards
                    break

            if found_cards:
                for card in found_cards:
                    text = card.get_text(separator=' ', strip=True)
                    if len(text) > 60:
                        results.append(text)
            else:
                # Fallback: grab all divs with water keywords
                log.warning(f"No cards found for {url}, using keyword fallback")
                all_divs = soup.find_all(['div', 'p', 'section'], recursive=True)
                for div in all_divs:
                    # Only leaf-ish nodes
                    child_blocks = div.find_all(['div', 'article', 'section'])
                    if len(child_blocks) > 2:
                        continue
                    text = div.get_text(separator=' ', strip=True)
                    water_ka = any(k in text for k in ["შეუწყდება", "შეეზღუდება", "წყალმომარაგება"])
                    water_en = any(k in text.lower() for k in ["water supply", "will be cut", "interruption"])
                    if (water_ka or water_en) and len(text) > 80:
                        results.append(text)

            log.info(f"requests: got {len(results)} raw blocks from {url}")
            break  # Stop after first successful URL

        except Exception as e:
            log.warning(f"requests failed for {url}: {e}")
            continue

    return results


# ─────────────────────────────────────────────
# METHOD 2: Selenium (fallback, slower)
# ─────────────────────────────────────────────

def _fetch_with_selenium() -> list:
    """Selenium fallback scraper — FIXED to avoid nav contamination."""
    driver = None
    results = []

    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument(
            'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(40)
        driver.get(GWP_URL_EN)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )
        time.sleep(4)

        # ── Remove nav/header/footer from DOM FIRST ──
        driver.execute_script("""
            var remove_selectors = [
                'nav', 'header', 'footer', '.navbar', '.menu',
                '.sidebar', '.breadcrumb', '#navigation',
                '.nav-menu', '.top-menu', '.header-menu',
                '.footer-links', '.contact-info'
            ];
            remove_selectors.forEach(function(sel) {
                document.querySelectorAll(sel).forEach(function(el) {
                    el.remove();
                });
            });
        """)

        # ── Click expand buttons ──
        read_more_xpaths = [
            "//button[contains(text(),'სრულად')]",
            "//a[contains(text(),'სრულად')]",
            "//span[contains(text(),'სრულად')]",
            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'read more')]",
        ]
        for xpath in read_more_xpaths:
            try:
                btns = driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.3)
                    except:
                        pass
            except:
                pass

        time.sleep(2)

        # ── Remove CSS truncation ──
        driver.execute_script("""
            document.querySelectorAll('*').forEach(function(el) {
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el.style.textOverflow = 'clip';
                el.style.webkitLineClamp = 'unset';
                el.style.display = el.style.display === 'none' ? 'block' : el.style.display;
            });
        """)
        time.sleep(1)

        # ── Extract text from card-like elements only ──
        card_texts = driver.execute_script("""
            var results = [];
            var water_ka = ['შეუწყდება', 'შეეზღუდება', 'წყალმომარაგება'];
            var water_en = ['water supply', 'will be cut', 'interruption'];
            
            // Try card selectors first
            var card_sels = [
                '.gadaudebeli-item', '.news-item', '.alert-card',
                'article', '.card', '[class*="news"]', '[class*="alert"]'
            ];
            
            var found = false;
            for (var s = 0; s < card_sels.length; s++) {
                var cards = document.querySelectorAll(card_sels[s]);
                if (cards.length > 0) {
                    cards.forEach(function(card) {
                        var text = (card.innerText || '').trim();
                        if (text.length > 60) results.push(text);
                    });
                    found = true;
                    break;
                }
            }
            
            // Fallback: leaf nodes with water keywords
            if (!found) {
                var allEls = document.querySelectorAll('div, p, span');
                allEls.forEach(function(el) {
                    var text = (el.innerText || '').trim();
                    var childBlocks = el.querySelectorAll('div, p, article, section').length;
                    if (childBlocks > 2) return;
                    if (text.length < 80) return;
                    
                    var hasWater = false;
                    for (var k = 0; k < water_ka.length; k++) {
                        if (text.indexOf(water_ka[k]) !== -1) { hasWater = true; break; }
                    }
                    if (!hasWater) {
                        var tl = text.toLowerCase();
                        for (var k = 0; k < water_en.length; k++) {
                            if (tl.indexOf(water_en[k]) !== -1) { hasWater = true; break; }
                        }
                    }
                    
                    if (hasWater) results.push(text);
                });
            }
            
            return results;
        """)

        results = card_texts or []
        log.info(f"Selenium: got {len(results)} raw blocks")

    except Exception as e:
        log.error(f"Selenium error: {str(e)[:200]}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return results


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def fetch_live_alerts(alert_type: str = "emergency") -> list:
    """
    Main entry point.
    Tries requests first (fast), falls back to Selenium if needed.
    Returns list of dicts: {text, districts, url, time_range}
    """
    raw_texts = []

    # Try fast method first
    log.info("Trying requests method...")
    raw_texts = _fetch_with_requests()

    if not raw_texts:
        log.warning("requests method got nothing, falling back to Selenium...")
        raw_texts = _fetch_with_selenium()

    if not raw_texts:
        log.error("Both methods returned nothing")
        return []

    unique_texts = _deduplicate_alerts(raw_texts)

    results = []
    for text in unique_texts:
        districts = _detect_districts(text)
        time_range = _extract_time(text)
        results.append({
            'text': text,
            'districts': districts,
            'url': GWP_URL_EN,
            'time_range': time_range
        })

    log.info(f"Final: {len(results)} clean unique alerts")
    return results


def get_announcement_links(limit=None) -> list:
    """Compatibility wrapper — keeps notifier.py working unchanged."""
    alerts = fetch_live_alerts("emergency")
    formatted = []
    for a in alerts:
        text_hash = hashlib.md5(a["text"][:200].encode('utf-8')).hexdigest()[:8]
        formatted.append({
            "url": a["url"] + "#" + text_hash,
            "text": a["text"],
            "districts": a["districts"],
            "time_range": a.get("time_range", "")
        })
    if limit:
        formatted = formatted[:limit]
    return formatted


def shutdown():
    pass

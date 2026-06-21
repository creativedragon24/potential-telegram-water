"""
Advanced Scraper for GWP website.

Extracts alert text directly from the DOM elements on the listing page.
This is much more reliable than searching for href links in Angular SPAs.
"""
import time
import re
import logging
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import config

log = logging.getLogger("scraper")

GWP_EMERGENCY = "https://www.gwp.ge/ka/news/nonscheduled-works"
GWP_PLANNED = "https://www.gwp.ge/ka/news/scheduled-works"

# Georgian district forms for detection
DISTRICT_FORMS = {
    "Vake": ["ვაკე", "ვაკის", "ვაკეში", "ვაკის რაიონში"],
    "Saburtalo": ["საბურთალო", "საბურთალოს", "საბურთალოში", "საბურთალოს რაიონში"],
    "Isani": ["ისანი", "ისანის", "ისანში", "ისანის რაიონში"],
    "Samgori": ["სამგორი", "სამგორის", "სამგორში", "სამგორის რაიონში"],
    "Didube": ["დიდუბე", "დიდუბის", "დიდუბეში", "დიდუბის რაიონში"],
    "Chugureti": ["ჩუღურეთი", "ჩუღურეთის", "ჩუღურეთში", "ჩუღურეთის რაიონში"],
    "Gldani": ["გლდანი", "გლდანის", "გლდანში", "გლდანის რაიონში"],
    "Nadzaladevi": ["ნაძალადევი", "ნაძალადევის", "ნაძალადევში", "ნაძალადევის რაიონში"],
    "Mtatsminda": ["მთაწმინდა", "მთაწმინდის", "მთაწმინდაზე", "მთაწმინდის რაიონში"],
    "Krtsanisi": ["კრწანისი", "კრწანისის", "კრწანისში", "კრწანისის რაიონში"],
}

def _detect_districts(text):
    text_lower = text.lower()
    found = []
    for eng, forms in DISTRICT_FORMS.items():
        for form in forms:
            if form.lower() in text_lower:
                found.append(eng)
                break
    return found

def _remove_css_truncation(driver):
    """Remove CSS-based text truncation (max-height, overflow:hidden)."""
    driver.execute_script("""
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var style = window.getComputedStyle(el);
            if (style.maxHeight && style.maxHeight !== 'none' && style.maxHeight !== '') {
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
            }
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp) {
                el.style.textOverflow = 'clip';
                el.style.webkitLineClamp = 'unset';
                el.style.display = 'block';
                el.style.overflow = 'visible';
            }
        }
    """)
    time.sleep(1)

def _click_read_more(driver):
    """Find and click all 'Read More' / 'სრულად' buttons to expand cards."""
    read_more_texts = [
        "სრულად", "წაიკითხეთ სრულად", "მეტის ნახვა", "გაგრძელება",
        "სრულად წაკითხვა", "მეტი", "read more", "more"
    ]
    clicked = 0
    for text in read_more_texts:
        try:
            buttons = driver.find_elements(
                By.XPATH,
                f"//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
            )
            for btn in buttons:
                try:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        clicked += 1
                        time.sleep(0.3)
                except Exception:
                    continue
        except Exception:
            continue

    expand_selectors = [
        ".read-more", ".readmore", ".show-more", ".expand",
        "[data-toggle]", "[aria-expanded='false']",
        ".more-link", ".btn-more", ".card-link"
    ]
    for selector in expand_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                try:
                    if el.is_displayed():
                        driver.execute_script("arguments[0].click();", el)
                        clicked += 1
                        time.sleep(0.3)
                except Exception:
                    continue
        except Exception:
            continue

    if clicked > 0:
        log.info(f"Clicked {clicked} 'Read More' buttons to expand text")
        time.sleep(2)

def fetch_live_alerts(alert_type="emergency"):
    """Scrape alerts from GWP website by extracting DOM text."""
    url = GWP_EMERGENCY if alert_type == "emergency" else GWP_PLANNED
    results = []
    driver = None
    
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.get(url)
        
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
        except Exception:
            pass
            
        time.sleep(5)  # Wait for Angular to render
        
        # 1. Click all "Read More" buttons to reveal hidden text
        _click_read_more(driver)
        
        # 2. Expand any CSS truncation
        _remove_css_truncation(driver)

        # Use JavaScript to extract text from all news cards/items
        # Looks for common container classes used by GWP
        card_texts = driver.execute_script("""
            var selectors = ['.region-card', '.news-card', '.card', 'article', '.item'];
            var texts = [];
            
            for (var s = 0; s < selectors.length; s++) {
                var cards = document.querySelectorAll(selectors[s]);
                if (cards.length > 0) {
                    cards.forEach(function(card) {
                        var text = (card.innerText || card.textContent || '').trim();
                        if (text.length > 30 && text.includes('წყალმომარაგება')) {
                            texts.push(text);
                        }
                    });
                    if (texts.length > 0) return texts; // Stop if we found cards
                }
            }
            
            // Fallback: find ANY div that looks like an alert
            var allDivs = document.querySelectorAll('div, p, span');
            allDivs.forEach(function(el) {
                var text = (el.innerText || '').trim();
                var childNodes = el.querySelectorAll('*');
                // Only get leaf nodes (no children) to avoid duplicates
                if (text.length > 50 && text.length < 2000 && childNodes.length === 0) {
                    if (text.includes('შეუწყდება') || text.includes('შეეზღუდება')) {
                        if (texts.indexOf(text) === -1) texts.push(text);
                    }
                }
            });
            
            return texts;
        """)

        if card_texts:
            log.info(f"Found {len(card_texts)} {alert_type} alerts via DOM extraction")
            for text in card_texts:
                districts = _detect_districts(text)
                results.append({
                    'text': text,
                    'districts': districts,
                    'url': url
                })
        else:
            log.warning(f"No {alert_type} alerts found in DOM. Page source size: {len(driver.page_source)}")
                
    except Exception as e:
        log.error(f"Error fetching {alert_type}: {str(e)[:100]}")
    finally:
        if driver:
            driver.quit()
            
    return results

# ---- Compatibility wrappers for the rest of the bot ----
def get_announcement_links(limit: int | None = None):
    """Fetch live data and return formatted list."""
    alerts = fetch_live_alerts("emergency")
    formatted = []
    for a in alerts:
        formatted.append({
            "url": a["url"] + "#" + str(hash(a["text"])), # unique url
            "text": a["text"],
            "districts": a["districts"]
        })
    return formatted

def fetch_announcement_text(url: str) -> str:
    return "" 

def shutdown():
    pass

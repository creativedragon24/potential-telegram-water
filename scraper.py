import time
import re
import logging
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import config

log = logging.getLogger("scraper")
logging.basicConfig(level=logging.INFO)

GWP_EMERGENCY = "https://www.gwp.ge/ka/news/nonscheduled-works"
GWP_PLANNED = "https://www.gwp.ge/ka/news/scheduled-works"

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

def fetch_live_alerts(alert_type="emergency"):
    url = GWP_EMERGENCY if alert_type == "emergency" else GWP_PLANNED
    results = []
    driver = None
    
    try:
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        
        log.info(f"Launching undetected Chrome for {url}")
        driver = uc.Chrome(options=options, headless=True, version_main=None)
        driver.set_page_load_timeout(30)
        driver.get(url)
        
        time.sleep(8)  # Wait for Angular to render
        
        # Expand text
        driver.execute_script("""
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el.style.textOverflow = 'clip';
                el.style.webkitLineClamp = 'unset';
            }
        """)
        time.sleep(1)

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
                    if (texts.length > 0) return texts;
                }
            }
            
            var allDivs = document.querySelectorAll('div, p, span');
            allDivs.forEach(function(el) {
                var text = (el.innerText || '').trim();
                var childNodes = el.querySelectorAll('*');
                if (text.length > 50 && text.length < 2000 && childNodes.length === 0) {
                    if (text.includes('შეუწყდება') || text.includes('შეეზღუდება')) {
                        if (texts.indexOf(text) === -1) texts.push(text);
                    }
                }
            });
            
            return texts;
        """)

        if card_texts:
            log.info(f"Found {len(card_texts)} {alert_type} alerts")
            for text in card_texts:
                districts = _detect_districts(text)
                results.append({
                    'text': text,
                    'districts': districts,
                    'url': url
                })
        else:
            log.warning(f"No {alert_type} alerts found")
                
    except Exception as e:
        log.error(f"Error fetching {alert_type}: {str(e)[:100]}")
    finally:
        if driver:
            driver.quit()
            
    return results

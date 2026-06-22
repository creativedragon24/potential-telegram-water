import os
import re
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("scraper")
logging.basicConfig(level=logging.INFO)

# We are now targeting the NEW GWP website
GWP_URL = "https://www.gwp.ge/ka/news/nonscheduled-works"

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
    results = []
    api_key = os.getenv("SCRAPER_API_KEY")
    
    if not api_key:
        log.error("SCRAPER_API_KEY missing from environment variables!")
        return []

    try:
        log.info(f"Fetching live HTML via ScraperAPI (Rendering JS)...")
        
        # ScraperAPI endpoint
        payload = {
            'api_key': api_key,
            'url': GWP_URL,
            'render': 'true', # THIS IS THE MAGIC WORD! It tells ScraperAPI to run the JavaScript!
            'country_code': 'ge' # Use a Georgian IP address
        }
        
        response = requests.get('https://api.scraperapi.com/', params=payload, timeout=90)
        
        if response.status_code == 200:
            log.info("Successfully fetched HTML! Parsing...")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            cards = soup.find_all(['table', 'div', 'p', 'span'])
            
            for card in cards:
                text = card.get_text(separator=" ", strip=True)
                if text and len(text) > 50 and ("შეუწყდება" in text or "შეეზღუდება" in text):
                    text = re.sub(r'\s+', ' ', text).strip()
                    
                    districts = _detect_districts(text)
                    if districts:
                        results.append({
                            'text': text,
                            'districts': districts,
                            'url': GWP_URL
                        })
            
            # Remove duplicates
            unique_results = []
            seen_texts = set()
            for res in results:
                if res['text'] not in seen_texts:
                    seen_texts.add(res['text'])
                    unique_results.append(res)
                    
            log.info(f"Found {len(unique_results)} alerts using ScraperAPI!")
            return unique_results
        else:
            log.error(f"ScraperAPI failed. HTTP Status: {response.status_code}")
            
    except Exception as e:
        log.error(f"Error fetching alerts: {str(e)[:100]}")
        
    return []

import re
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("scraper")
logging.basicConfig(level=logging.INFO)

# The OLD website - pure HTML, no JavaScript required!
GWP_URL = "https://www.georgianwater.com/en/gadaudebeli"

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
    try:
        log.info(f"Fetching live HTML from {GWP_URL}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(GWP_URL, headers=headers, timeout=20)
        
        if response.status_code == 200:
            log.info("Successfully connected! Parsing HTML...")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all tables or divs that contain the alerts
            # The old site uses tables for layout
            cards = soup.find_all(['table', 'div', 'p', 'span'])
            
            for card in cards:
                text = card.get_text(separator=" ", strip=True)
                # Check if the text block is an actual water cut alert
                if text and len(text) > 50 and ("შეუწყდება" in text or "შეეზღუდება" in text):
                    # Clean up extra whitespace
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
                    
            log.info(f"Found {len(unique_results)} alerts using requests!")
            return unique_results
        else:
            log.error(f"Failed to fetch. HTTP Status: {response.status_code}")
            
    except Exception as e:
        log.error(f"Error fetching alerts: {str(e)[:100]}")
        
    return []

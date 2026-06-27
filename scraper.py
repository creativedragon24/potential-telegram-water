import os
import re
import logging
import requests
import time
from bs4 import BeautifulSoup

log = logging.getLogger("scraper")
logging.basicConfig(level=logging.INFO)

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

def _extract_time(text):
    match = re.search(r'(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})', text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return ""

def _deduplicate_alerts(raw_texts):
    cleaned = []
    for t in raw_texts:
        clean = t.replace("სრულად", "").replace("...", "").strip()
        clean = re.sub(r'\s+', ' ', clean).strip()
        if clean and len(clean) > 50:
            cleaned.append(clean)

    groups = {}
    for i, text in enumerate(cleaned):
        time_sig = _extract_time(text)
        districts = _detect_districts(text)
        district_sig = ",".join(sorted(districts)) if districts else "unknown"
        signature = f"{time_sig}|{district_sig}"

        if signature not in groups:
            groups[signature] = (i, text, len(text))
        else:
            if len(text) > groups[signature][2]:
                groups[signature] = (i, text, len(text))

    unique_items = sorted(groups.values(), key=lambda x: x[0])
    unique_texts = [item[1] for item in unique_items]

    final = []
    for t1 in unique_texts:
        is_partial = False
        for t2 in unique_texts:
            if t1 != t2 and t1 in t2 and len(t1) < len(t2) - 20:
                is_partial = True
                break
        if not is_partial and t1 not in final:
            final.append(t1)

    log.info(f"Deduplication: {len(cleaned)} raw -> {len(final)} unique")
    return final

def fetch_live_alerts(alert_type="emergency"):
    results = []
    api_key = os.getenv("SCRAPER_API_KEY")
    
    if not api_key:
        log.error("SCRAPER_API_KEY missing from environment variables!")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    payload = {
        'api_key': api_key,
        'url': GWP_URL,
        'render': 'true'
    }

    # 🚀 AUTOMATIC RETRY LOGIC
    max_retries = 3
    for attempt in range(max_retries):
        try:
            log.info(f"Fetching live HTML via ScraperAPI (Attempt {attempt + 1}/{max_retries})...")
            response = requests.get('https://api.scraperapi.com/', headers=headers, params=payload, timeout=90)
            
            if response.status_code == 200:
                log.info("Successfully fetched HTML! Parsing...")
                soup = BeautifulSoup(response.text, 'html.parser')
                cards = soup.find_all(['table', 'div', 'p', 'span'])
                raw_texts = []
                
                for card in cards:
                    text = card.get_text(separator=" ", strip=True)
                    if text and len(text) > 50 and ("შეუწყდება" in text or "შეეზღუდება" in text):
                        text = re.sub(r'\s+', ' ', text).strip()
                        raw_texts.append(text)
                
                unique_texts = _deduplicate_alerts(raw_texts)
                
                log.info(f"Found {len(unique_texts)} unique alerts!")
                for text in unique_texts:
                    districts = _detect_districts(text)
                    results.append({
                        'text': text,
                        'districts': districts,
                        'url': GWP_URL
                    })
                return results
                
            elif response.status_code in [500, 502, 503, 429]:
                log.warning(f"ScraperAPI returned {response.status_code}. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                log.error(f"ScraperAPI failed. HTTP Status: {response.status_code}")
                break # Don't retry on 400/403 errors
                
        except Exception as e:
            log.warning(f"Network error on attempt {attempt + 1}: {str(e)[:50]}. Retrying in 5 seconds...")
            time.sleep(5)
            
    log.error("Failed to fetch alerts after multiple retries.")
    return []

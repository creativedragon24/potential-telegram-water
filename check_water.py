"""
Cloud version of the GWP Water Bot.
Designed to run once on GitHub Actions, check the website, send messages, and exit.
"""
import os
import json
import requests
import time
import scraper
import parser

SEEN_FILE = "seen.json"

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
        print("  [NOTIFY] Sent Telegram message!")
    except Exception as e:
        print(f"  [NOTIFY] Failed to send message: {e}")

def main():
    print("🤖 Starting Water Bot Cloud Check...")
    
    # Get secrets from GitHub
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    district = os.getenv("DISTRICT", "").lower()
    street = os.getenv("STREET", "").lower()

    if not bot_token or not chat_id:
        print("❌ Error: BOT_TOKEN or CHAT_ID missing.")
        return

    # 1. Scrape live alerts
    print("🔍 Fetching live alerts from GWP...")
    alerts = scraper.fetch_live_alerts("emergency")
    
    if not alerts:
        print("No alerts found.")
        return

    # 2. Load memory (what we already sent)
    seen = load_seen()
    new_count = 0

    # 3. Process each alert
    for alert in alerts:
        text = alert.get("text", "")
        url = alert.get("url", "") + "#" + str(hash(text)) # unique id
        
        if url in seen:
            continue # Already sent this one
            
        # Parse the alert to find districts and streets
        pa = parser.parse_announcement(text, url=url, lang="en")
        
        # 4. Check if it matches user's subscription
        is_all_districts = (district == "all")
        matched = False
        target_district = ""

        if is_all_districts:
            # If user wants ALL districts, match as long as the alert has at least one district
            if pa.districts:
                matched = True
                target_district = list(pa.districts.keys())[0] # Pick the first one for the title
        else:
            # Specific district matching
            if district in pa.districts:
                target_district = district
                matched = True
                # If user specified a street, check if it matches
                if street:
                    matched = parser.matches_subscription(pa, district, street)
        
        if matched:
            print(f"✅ Found new matching alert for {target_district}!")
            msg = parser.build_notification(pa, target_district, street if street else parser.ALL_STREETS_MARKER, "en")
            send_telegram_message(bot_token, chat_id, msg)
            time.sleep(2) # Telegram rate limit safety
            new_count += 1
        
        # Mark as seen so we don't send it again
        seen[url] = True

    # 5. Save memory for next run
    save_seen(seen)
    print(f"✅ Done! Sent {new_count} new notifications.")

if __name__ == "__main__":
    main()

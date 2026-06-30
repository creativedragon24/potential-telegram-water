"""
Run this ONCE to dump the GWP HTML so we can find the real CSS selectors.
python debug_html.py
"""
import os, requests, re
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

GWP_EN = "https://www.gwp.ge/en/news/nonscheduled-works"

def fetch_html(url):
    if SCRAPER_API_KEY:
        print("Using ScraperAPI...")
        r = requests.get(
            "http://api.scraperapi.com",
            params={"api_key": SCRAPER_API_KEY, "url": url, "render": "false"},
            timeout=60,
        )
        if r.status_code == 200:
            return r.text
    print("Using direct...")
    r = requests.get(url, timeout=30)
    return r.text


def send_telegram(message):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message},
        timeout=15,
    )


def analyze(html):
    soup = BeautifulSoup(html, "lxml")

    # Save full HTML to file for inspection
    with open("gwp_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Full HTML saved to gwp_debug.html ({len(html)} bytes)")

    # ── Find ALL unique class names in the page ──
    all_classes = set()
    for tag in soup.find_all(True):
        for cls in tag.get("class", []):
            all_classes.add(cls)

    # Filter classes that look like content (not utility)
    interesting = [
        c for c in sorted(all_classes)
        if any(word in c.lower() for word in [
            "news","card","item","article","alert","content",
            "post","entry","block","list","row","result",
            "announce","water","gadau","nonsch","cut"
        ])
    ]

    print("\n=== INTERESTING CSS CLASSES ===")
    for c in interesting:
        print(f"  .{c}")

    # ── Find elements containing water keywords ──
    water_kw_ka = ["შეუწყდება", "შეეზღუდება", "წყალმომარაგება"]
    water_kw_en = ["water supply", "will be cut", "interruption"]

    print("\n=== ELEMENTS WITH WATER KEYWORDS ===")
    found_elements = []
    for tag in soup.find_all(True):
        text = tag.get_text(" ", strip=True)
        has_water = (
            any(k in text for k in water_kw_ka) or
            any(k in text.lower() for k in water_kw_en)
        )
        if not has_water:
            continue
        # Only look at reasonably sized elements
        if len(text) < 50 or len(text) > 5000:
            continue

        tag_name  = tag.name
        classes   = " ".join(tag.get("class", []))
        tag_id    = tag.get("id", "")
        parent    = tag.parent
        p_classes = " ".join(parent.get("class", [])) if parent else ""

        info = {
            "tag":      tag_name,
            "class":    classes,
            "id":       tag_id,
            "parent":   f"{parent.name}.{p_classes}" if parent else "",
            "text_len": len(text),
            "preview":  text[:120],
        }
        found_elements.append(info)

    # Deduplicate by class
    seen_classes = set()
    unique_elements = []
    for el in found_elements:
        key = el["class"] or el["tag"]
        if key not in seen_classes:
            seen_classes.add(key)
            unique_elements.append(el)

    for el in unique_elements[:20]:
        print(f"\n  TAG:    <{el['tag']}>")
        print(f"  CLASS:  {el['class'] or '(none)'}")
        print(f"  ID:     {el['id'] or '(none)'}")
        print(f"  PARENT: {el['parent']}")
        print(f"  LEN:    {el['text_len']} chars")
        print(f"  TEXT:   {el['preview']}")

    # ── Send summary to Telegram ──
    msg = "🔍 GWP HTML Debug\n\n"
    msg += f"Total HTML size: {len(html)} bytes\n\n"

    if interesting:
        msg += "📌 Interesting CSS classes:\n"
        msg += "\n".join(f"  .{c}" for c in interesting[:15])
        msg += "\n\n"

    if unique_elements:
        msg += "💧 Elements with water keywords:\n"
        for el in unique_elements[:5]:
            msg += (
                f"\n<{el['tag']}> class='{el['class']}'\n"
                f"  parent: {el['parent']}\n"
                f"  preview: {el['preview'][:80]}\n"
            )
    else:
        msg += "❌ NO elements with water keywords found!\n"
        msg += "The page might need JavaScript to render.\n"

    send_telegram(msg)
    print("\n=== Telegram message sent ===")
    return unique_elements


def main():
    print(f"Fetching {GWP_EN}...")
    html = fetch_html(GWP_EN)
    print(f"Got {len(html)} bytes")
    elements = analyze(html)

    if not elements:
        print("\n⚠️  NO WATER ELEMENTS FOUND")
        print("This means the page requires JavaScript rendering.")
        print("We need ScraperAPI with render=true")


if __name__ == "__main__":
    main()

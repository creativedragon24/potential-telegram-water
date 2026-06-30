"""
Run ONCE to find real CSS selectors.
python debug_html.py
"""
import os, requests, re
from bs4 import BeautifulSoup

BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()

GWP_EN = "https://www.gwp.ge/en/news/nonscheduled-works"


def fetch_html(url):
    if SCRAPER_API_KEY:
        print("Using ScraperAPI with JS render=true ...")
        r = requests.get(
            "http://api.scraperapi.com",
            params={
                "api_key":      SCRAPER_API_KEY,
                "url":          url,
                "render":       "true",
                "country_code": "us",
            },
            timeout=120,
        )
        if r.status_code == 200:
            print(f"Got {len(r.text)} bytes")
            return r.text
        print(f"ScraperAPI error: {r.status_code} {r.text[:200]}")
    print("Using direct request...")
    r = requests.get(url, timeout=30)
    return r.text


def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message[:4000]},
            timeout=15,
        )
        print("Telegram message sent")
    except Exception as e:
        print(f"Telegram failed: {e}")


def analyze(html):
    with open("gwp_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved gwp_debug.html ({len(html)} bytes)")

    soup = BeautifulSoup(html, "lxml")

    # All unique classes
    all_classes = set()
    for tag in soup.find_all(True):
        for cls in tag.get("class", []):
            all_classes.add(cls)

    interesting = [
        c for c in sorted(all_classes)
        if any(w in c.lower() for w in [
            "news","card","item","article","alert","content",
            "post","entry","block","list","row","result",
            "announce","water","gadau","nonsch","cut","region"
        ])
    ]

    print("\n=== INTERESTING CSS CLASSES ===")
    for c in interesting:
        print(f"  .{c}")

    # Elements with water keywords
    water_kw_ka = ["შეუწყდება","შეეზღუდება","წყალმომარაგება"]
    water_kw_en = ["water supply","will be cut","interruption"]

    print("\n=== ELEMENTS WITH WATER KEYWORDS ===")
    found_elements = []
    for tag in soup.find_all(True):
        text = tag.get_text(" ", strip=True)
        has_water = (
            any(k in text for k in water_kw_ka) or
            any(k in text.lower() for k in water_kw_en)
        )
        if not has_water or len(text) < 50 or len(text) > 5000:
            continue

        tag_name  = tag.name
        classes   = " ".join(tag.get("class", []))
        tag_id    = tag.get("id", "")
        parent    = tag.parent
        p_name    = parent.name if parent else ""
        p_classes = " ".join(parent.get("class", [])) if parent else ""

        found_elements.append({
            "tag":      tag_name,
            "class":    classes,
            "id":       tag_id,
            "parent":   f"{p_name}.{p_classes}",
            "text_len": len(text),
            "preview":  text[:150],
        })

    # Deduplicate
    seen_cls = set()
    unique   = []
    for el in found_elements:
        key = el["class"] or el["tag"]
        if key not in seen_cls:
            seen_cls.add(key)
            unique.append(el)

    for el in unique[:20]:
        print(f"\n  TAG:    <{el['tag']}>")
        print(f"  CLASS:  {el['class'] or '(none)'}")
        print(f"  ID:     {el['id']   or '(none)'}")
        print(f"  PARENT: {el['parent']}")
        print(f"  LEN:    {el['text_len']} chars")
        print(f"  TEXT:   {el['preview']}")

    # Build Telegram message
    msg  = f"🔍 GWP HTML Debug\n"
    msg += f"HTML size: {len(html):,} bytes\n\n"

    if interesting:
        msg += "📌 Interesting CSS classes:\n"
        msg += "\n".join(f"  .{c}" for c in interesting[:20])
        msg += "\n\n"

    if unique:
        msg += "💧 Elements with water keywords:\n"
        for el in unique[:6]:
            msg += (
                f"\n<{el['tag']}> class='{el['class']}'\n"
                f"  parent: {el['parent']}\n"
                f"  len: {el['text_len']}\n"
                f"  preview: {el['preview'][:100]}\n"
            )
    else:
        msg += (
            "❌ NO water elements found even with render=true\n\n"
            "This means GWP needs extra wait time after JS loads.\n"
            "Next step: use render=true with wait_for_selector.\n"
        )

    send_telegram(msg)
    return unique


def main():
    print(f"Fetching: {GWP_EN}")
    html = fetch_html(GWP_EN)
    print(f"Total: {len(html)} bytes")
    elements = analyze(html)
    if not elements:
        print("\n⚠️  No water elements found — need JS wait time")
    else:
        print(f"\n✅ Found {len(elements)} unique elements with water keywords")


if __name__ == "__main__":
    main()

import re
import logging
import html as html_module
from dataclasses import dataclass, field

log = logging.getLogger("parser")
ALL_STREETS_MARKER = "__ALL__"

_TIME_RE = re.compile(r"(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)\s*(?:to|[-–—])\s*(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)", re.I)
_KA_TIME_RE = re.compile(r"(\d{1,2}[:.]\d{2})\s*-?(?:ის)?\s*დან\b.*?(\d{1,2}[:.]\d{2})\s*(?:საათ)?", re.S)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}(?:[-–]\s*\d{1,2})?)")


# Minimal DISTRICTS list required for parser.py to run
DISTRICTS = [
    {"key": "vake", "en": "Vake", "ka": "ვაკე"},
    {"key": "saburtalo", "en": "Saburtalo", "ka": "საბურთალო"},
    {"key": "isani", "en": "Isani", "ka": "ისანი"},
    {"key": "samgori", "en": "Samgori", "ka": "სამგორი"},
    {"key": "didube", "en": "Didube", "ka": "დიდუბე"},
    {"key": "chugureti", "en": "Chugureti", "ka": "ჩუღურეთი"},
    {"key": "gldani", "en": "Gldani", "ka": "გლდანი"},
    {"key": "nadzaladevi", "en": "Nadzaladevi", "ka": "ნაძალადევი"},
    {"key": "mtatsminda", "en": "Mtatsminda", "ka": "მთაწმინდა"},
    {"key": "krtsanisi", "en": "Krtsanisi", "ka": "კრწანისი"},
]
DISTRICT_BY_KEY = {d["key"]: d for d in DISTRICTS}


@dataclass
class ParsedAnnouncement:
    url: str = ""
    lang: str = "en"
    time_text: str = ""
    date_text: str = ""
    districts: dict = field(default_factory=dict)
    raw: str = ""


def detect_language(text):
    if not text:
        return "en"
    ka = sum(1 for ch in text if "\u10d0" <= ch <= "\u10fa")
    return "ka" if ka > 15 else "en"


def parse_announcement(text, url="", lang="en"):
    if lang == "en":
        lang = detect_language(text)
    text = text or ""
    pa = ParsedAnnouncement(url=url, lang=lang, raw=text)

    m = _TIME_RE.search(text)
    if not m:
        m = _KA_TIME_RE.search(text)
    if m:
        pa.time_text = f"{m.group(1)} – {m.group(2)}"

    dm = _DATE_RE.search(text)
    if dm:
        pa.date_text = dm.group(1)

    low = text.lower()
    for d in DISTRICTS:
        if d["en"].lower() in low or d["ka"] in text:
            pa.districts[d["key"]] = {"segment": text, "streets": []}
    return pa


def matches_subscription(pa, district_key, street):
    if district_key not in pa.districts:
        return False
    if street == ALL_STREETS_MARKER or not street:
        return True
    return True


# Massive Georgian -> English translation dictionary
KA_EN_DICT = {
    "წყალმომარაგების აღდგენის დრო შეტყობინებულ იქნება მოგვიანებით": "restoration time will be notified later",
    "დაზიანების აღდგენითი სამუშაოების ჩატარების მიზნით": "to carry out restoration works",
    "წყალმომარაგების აღდგენის დრო გადაიწია": "restoration time extended to",
    "აუცილებელ გადაერთებით სამუშაოებს ჩაატარებს": "will carry out essential switchover works",
    "აუცილებელ ტექნიკურ სამუშაოებს ჩაატარებს": "will carry out essential technical works",
    "დაზიანების ლიკვიდაციის მიზნით": "to eliminate damage",
    "წყალმომარაგების ქსელზე დაზიანების გამო": "due to water supply network damage",
    "მოქალაქის კუთვნილ წყალსადენის ქსელზე": "on citizen-owned water pipeline",
    "აუცილებელი გადაერთებითი სამუშაოები": "essential switchover works",
    "აუცილებელი ტექნიკური სამუშაოები": "essential technical works",
    "ავარიული წყალმომარაგების ქსელზე": "on the emergency water supply network",
    "წყალმომარაგების ქსელზე დაზიანება": "water supply network damage",
    "წყალმომარაგების ქსელზე": "on the water supply network",
    "აღნიშნულ გამორთვას დაემატა": "added to this shutoff",
    "ქსელზე დაზიანებაა": "network is damaged",
    "ქსელზე დაზიანების გამო": "due to network damage",
    "გლდანის რაიონში": "Gldani district", "გლდანის რაიონ": "Gldani district", "გლდანის": "Gldani", "გლდანში": "Gldani", "გლდანი": "Gldani",
    "საბურთალოს რაიონში": "Saburtalo district", "საბურთალოს რაიონ": "Saburtalo district", "საბურთალოს": "Saburtalo", "საბურთალოში": "Saburtalo", "საბურთალო": "Saburtalo",
    "ვაკის რაიონში": "Vake district", "ვაკის რაიონ": "Vake district", "ვაკის": "Vake", "ვაკეში": "Vake", "ვაკე": "Vake",
    "ისანის რაიონში": "Isani district", "ისანის რაიონ": "Isani district", "ისანის": "Isani", "ისანში": "Isani", "ისანი": "Isani",
    "ნაძალადევის რაიონში": "Nadzaladevi district", "ნაძალადევის რაიონ": "Nadzaladevi district", "ნაძალადევის": "Nadzaladevi", "ნაძალადევში": "Nadzaladevi", "ნაძალადევი": "Nadzaladevi",
    "დიდუბის რაიონში": "Didube district", "დიდუბის რაიონ": "Didube district", "დიდუბის": "Didube", "დიდუბეში": "Didube", "დიდუბე": "Didube",
    "ჩუღურეთის რაიონში": "Chugureti district", "ჩუღურეთის რაიონ": "Chugureti district", "ჩუღურეთის": "Chugureti", "ჩუღურეთში": "Chugureti", "ჩუღურეთი": "Chugureti",
    "კრწანისის რაიონში": "Krtsanisi district", "კრწანისის რაიონ": "Krtsanisi district", "კრწანისის": "Krtsanisi", "კრწანისში": "Krtsanisi", "კრწანისი": "Krtsanisi",
    "მთაწმინდის რაიონში": "Mtatsminda district", "მთაწმინდის რაიონ": "Mtatsminda district", "მთაწმინდის": "Mtatsminda", "მთაწმინდაზე": "Mtatsminda", "მთაწმინდა": "Mtatsminda",
    "სამგორის რაიონში": "Samgori district", "სამგორის რაიონ": "Samgori district", "სამგორის": "Samgori", "სამგორში": "Samgori", "სამგორი": "Samgori",
    "წყალმომარაგება შეუწყდება": "water supply will be cut off",
    "წყალმომარაგება შეეზღუდება": "water supply will be restricted",
    "წყალმომარაგების": "water supply", "წყალმომარაგება": "water supply",
    "წყალსადენის ქსელი": "water pipeline", "წყალსადენის": "water pipeline", "წყალსადენი": "water pipeline",
    "შეუწყდება": "will be cut off", "შეეზღუდება": "will be restricted",
    "ჩაატარებს": "will carry out", "ჩატარდება": "will be carried out",
    "აღდგება": "will be restored", "დაიცლება": "will be drained",
    "აუცილებელი": "essential", "ტექნიკური": "technical",
    "სამუშაოები": "works", "სამუშაოებს": "works", "სამუშაო": "work",
    "რეაბილიტაციური": "rehabilitation", "გადაერთებითი": "switchover",
    "მიმდინარეობისას": "during", "მიმდინარეობა": "ongoing", "მიმდინარეობისა": "ongoing",
    "დღეს": "today", "ხვალ": "tomorrow",
    "ქუჩები": "Streets", "ქუჩებს": "Streets", "ქუჩებით": "with streets",
    "ქუჩის": "Street", "ქუჩაზე": "Street", "ქუჩას": "Street", "ქუჩა": "St.", "ქ.": "St.",
    "გამზირი": "Ave.", "გამზ.": "Ave.", "გამზ": "Ave.",
    "შესახვევი": "Lane", "შესახვევს": "Lane", "შეს.": "Ln.",
    "ჩიხი": "Dead End", "ჩიხებით": "with dead ends",
    "მიკრორაიონი": "microdistrict", "მკ/რ": "microdistrict", "მ/რ": "microdistrict",
    "დასახლება": "Settlement", "დასახლების": "Settlement", "დას.": "Settlement", "სოფ.": "Settlement",
    "კორპუსი": "building", "კორპუსებს": "buildings",
    "კვარტალი": "block", "კვარტლებით": "with blocks",
    "უბანი": "area", "უბნის": "area", "ტერიტორია": "territory", "ტერიტორიაზე": "on the territory",
    "რეზერვუარზე": "at the reservoir", "რეზერვუარის": "reservoir",
    "საათამდე": "until", "საათის": "hour", "საათი": "hour",
    "-დან": "from", "-მდე": "until", "დან": "from", "მდე": "until",
    "თან": "at", "გამო": "due to", "მიზნით": "for the purpose",
    "ახლო": "near", "ახლოს": "near", "მიმდებარე": "adjacent",
    "ნაწილი": "part", "სრულად": "fully", "მთლიანად": "completely",
    "კენტებს": "odd numbers", "კენტები": "odd numbers", "ლუწებს": "even numbers", "ლუწები": "even numbers", "ჩათვლით": "inclusive",
    "მოქალაქის": "citizen", "კუთვნილ": "owned", "ჯივიპი": "GWP",
    "გეგმური": "Planned", "არაგეგმილი": "Emergency (Unplanned)", "არაგეგმიური": "Emergency (Unplanned)",
    "რაიონში": "district", "რაიონი": "district", "რაიონ": "district",
    "ქსელზე": "network", "ქსელი": "network",
    "დაზიანების": "damage", "დაზიანება": "damage",
    "შეტყობინებული": "notified", "მოგვიანებით": "later", "ავარიულად": "emergency",
}
KA_EN_DICT_SORTED = sorted(KA_EN_DICT.items(), key=lambda x: len(x[0]), reverse=True)

_KA_LATIN = {
    'ა': 'a', 'ბ': 'b', 'გ': 'g', 'დ': 'd', 'ე': 'e', 'ვ': 'v', 'ზ': 'z',
    'თ': 't', 'ი': 'i', 'კ': 'k', 'ლ': 'l', 'მ': 'm', 'ნ': 'n', 'ო': 'o',
    'პ': 'p', 'ჟ': 'zh', 'რ': 'r', 'ს': 's', 'ტ': 't', 'უ': 'u', 'ფ': 'p',
    'ქ': 'k', 'ღ': 'gh', 'ყ': 'q', 'შ': 'sh', 'ჩ': 'ch', 'ც': 'ts',
    'ძ': 'dz', 'წ': 'ts', 'ჭ': 'ch', 'ხ': 'kh', 'ჯ': 'j', 'ჰ': 'h',
}


def _strip_genitive(word):
    if not word or len(word) <= 3: return word
    stripped = word.rstrip(',.;:!)')
    if stripped.endswith('ს') and len(stripped) > 3: return stripped[:-1]
    if stripped.endswith('ის') and len(stripped) > 4: return stripped[:-2]
    return word


def _transliterate(text):
    result = "".join(_KA_LATIN.get(ch, ch) for ch in text)
    return " ".join(w.capitalize() for w in result.split())


def _translate_ge_to_en(text):
    if not text: return ""
    result = text
    for ka, en in KA_EN_DICT_SORTED:
        result = result.replace(ka, en)

    words = result.split()
    new_words = []
    for word in words:
        has_geo = any('\u10d0' <= ch <= '\u10fa' for ch in word)
        if has_geo:
            base = _strip_genitive(word)
            new_words.append(_transliterate(base))
        else:
            new_words.append(word)

    result = " ".join(new_words)
    fixes = {
        "water supply water supply": "water supply", "network network": "network",
        "damage damage": "damage", "district district": "district",
        "from from": "from", "until until": "until",
        "St. St.": "St.", "Ave. Ave.": "Ave.", "at at": "at", "near near": "near",
    }
    for wrong, correct in fixes.items():
        result = result.replace(wrong, correct)

    result = re.sub(r'\b(\w+)adzi\b', r'\1adze', result)
    return re.sub(r'\s{2,}', ' ', result).strip()


def build_notification(pa, district_key, street, lang="en"):
    d = DISTRICT_BY_KEY.get(district_key, {})
    dname_en = html_module.escape(d.get("en", district_key) if d else district_key)

    lines = [
        "🚰 <b><u>WATER SUPPLY INTERRUPTION</u></b>",
        f"📍 <b>District:</b> <b>{dname_en}</b>",
    ]

    if pa.time_text:
        time_text = html_module.escape(pa.time_text)
        lines.append(f"⏱ <b>Time:</b> <b><u>{time_text}</u></b>")
    if pa.date_text:
        date_text = html_module.escape(pa.date_text)
        lines.append(f"📅 <b>Date:</b> <b>{date_text}</b>")

    seg = pa.districts.get(district_key, {}).get("segment", "")
    if seg:
        seg_en = _translate_ge_to_en(seg)
        seg_en = html_module.escape(seg_en)
        seg_en = re.sub(r"\s+", " ", seg_en).strip()

        if ":" in seg_en:
            parts = seg_en.split(":", 1)
            before = parts[0].strip()
            after = parts[1].strip()
            if len(after) > 350:
                after = after[:350].rsplit(" ", 1)[0] + "..."
            seg_en = f"{before}:\n<b>{after}</b>"
        else:
            if len(seg_en) > 400:
                seg_en = seg_en[:400].rsplit(" ", 1)[0] + "..."

        lines.append(f"\n📝 <b>Affected area:</b>")
        lines.append(seg_en)

    source_url = "https://www.gwp.ge/en/news/nonscheduled-works"
    lines.append(f"\n🔗 {source_url}")

    return "\n".join(lines)

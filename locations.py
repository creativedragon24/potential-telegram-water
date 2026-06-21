"""
Tbilisi districts + Georgian/Latin transliteration helpers.
"""
import re
import unicodedata

DISTRICTS = [
    {"key": "mtatsminda",  "en": "Mtatsminda",  "ka": "მთაწმინდა", "alt": ["sololaki", "vera"]},
    {"key": "vake",        "en": "Vake",        "ka": "ვაკე", "alt": ["vake-saburtalo"]},
    {"key": "saburtalo",   "en": "Saburtalo",   "ka": "საბურთალო", "alt": ["saburtalos"]},
    {"key": "didube",      "en": "Didube",      "ka": "დიდუბე", "alt": []},
    {"key": "nadzaladevi", "en": "Nadzaladevi", "ka": "ნაძალადევი", "alt": []},
    {"key": "gldani",      "en": "Gldani",      "ka": "გლდანი", "alt": ["mukhiani", "zahesi"]},
    {"key": "krtsanisi",   "en": "Krtsanisi",   "ka": "კრწანისი", "alt": ["ponichala", "ortachala"]},
    {"key": "isani",       "en": "Isani",       "ka": "ისანი", "alt": ["isani-samgori"]},
    {"key": "samgori",     "en": "Samgori",     "ka": "სამგორი", "alt": ["varketili"]},
    {"key": "chugureti",   "en": "Chugureti",   "ka": "ჩუღურეთი", "alt": ["kukia"]},
    {"key": "didgori",     "en": "Didgori",     "ka": "დიდგორი", "alt": []},
    {"key": "dighomi",     "en": "Dighomi",     "ka": "დიღომი", "alt": ["digomi"]},
    {"key": "vazisubani",  "en": "Vazisubani",  "ka": "ვაზისუბანი", "alt": []},
    {"key": "zahesi",      "en": "Zahesi",      "ka": "ზაჰესი", "alt": []},
    {"key": "orkhevi",     "en": "Orkhevi",     "ka": "ორხევი", "alt": []},
]

DISTRICT_BY_KEY = {d["key"]: d for d in DISTRICTS}

KA2LAT = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z",
    "თ": "t", "ი": "i", "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o",
    "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s", "ტ": "t", "უ": "u", "ფ": "p",
    "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}

def georgian_to_latin(text: str) -> str:
    return "".join(KA2LAT.get(ch, ch) for ch in text)

def has_georgian(text: str) -> bool:
    return any("\u10d0" <= ch <= "\u10fa" for ch in text)

def normalize_name(text: str) -> str:
    if not text: return ""
    t = unicodedata.normalize("NFC", text).strip().lower()
    t = re.sub(r"^\s*(n\.?\s*)?\d+\s*", "", t)
    t = re.sub(r"^\s*(i{2,3}|iv|v|vi)\b\.?\s*", "", t)
    return t

def normalize_for_match(text: str) -> str:
    base = normalize_name(text)
    if has_georgian(text):
        return (base + " " + normalize_name(georgian_to_latin(text))).strip()
    return base

def variants(text: str) -> list[str]:
    base = normalize_name(text)
    out = [base] if base else []
    if has_georgian(text):
        lat = normalize_name(georgian_to_latin(text))
        if lat and lat != base:
            out.append(lat)
    return [v for v in out if v] or [""]

def district_name(d: dict, lang: str) -> str:
    return d.get(lang) or d.get("en") or ""

def display_street(name: str, lang: str) -> str:
    n = name.strip()
    if not n: return n
    if has_georgian(n):
        return georgian_to_latin(n)
    if not re.search(r"(street|avenue|road|alley|highway|m/r|district)$", n, re.I):
        return n.rstrip(",;.") + " Street"
    return n

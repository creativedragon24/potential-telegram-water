"""
Rule-based parser for GWP supply-interruption announcements.

Splits text by district headers and extracts street names. The scraper's
body extraction (scraper.py) is responsible for stripping nav menus, so the
parser can trust its input here.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field

import locations
from locations import DISTRICTS

log = logging.getLogger("parser")

ALL_STREETS_MARKER = "__ALL__"   # subscription covers the whole district

_TIME_RE = re.compile(
    r"(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)\s*(?:to|[-–—])\s*(\d{1,2}[:.]\d{2}\s*(?:am|pm)?)",
    re.I,
)
_DATE_RE = re.compile(
    r"(today|tomorrow|(?:on\s+)?\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December))",
    re.I,
)
_KA_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}(?:[-–]\s*\d{1,2})?)")
_KA_TIME_RE = re.compile(
    r"(\d{1,2}[:.]\d{2})\s*-?(?:ის)?\s*დან\b.*?(\d{1,2}[:.]\d{2})\s*(?:საათ)?", re.S
)

_STREET_SUFFIX_EN = (
    r"Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Alley|Highway|Hwy|Lane|"
    r"Square|Sq\.?|micro\s?-?district|m/r"
)
_STREET_EN_A = re.compile(
    r"([A-Z][\w''-]+(?:\s+[A-Z][\w''-]+){0,3})\s+(?:" + _STREET_SUFFIX_EN + r")\b"
)
_STREET_EN_B = re.compile(r"([A-Z][\w''-]+)\s+(?:I{1,3}|IV|V|VI)\b")

_KA_SUFFIX = r"ქუჩა|ქ\.|ქუჩები|ქუჩებს|ქუჩას|გამზირი|გამზ\.|ჩიხი|შესახვევი|მიკრორაიონი|მ/რ|დასახლება"
_STREET_KA = re.compile(r"([ა-ჰ0-9]+(?:\s+[ა-ჰ0-9]+){0,3})\s+(?:" + _KA_SUFFIX + r")")


@dataclass
class ParsedAnnouncement:
    url: str = ""
    lang: str = "en"
    time_text: str = ""
    date_text: str = ""
    districts: dict[str, dict] = field(default_factory=dict)
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url, "lang": self.lang, "time_text": self.time_text,
            "date_text": self.date_text, "districts": self.districts, "raw": self.raw,
        }


def _district_alternation(lang: str) -> str:
    names = set()
    for d in DISTRICTS:
        for fld in (lang, "en", "alt"):
            val = d.get(fld)
            if isinstance(val, str) and val:
                names.add(re.escape(val.strip()))
            elif isinstance(val, list):
                names.update(re.escape(v.strip()) for v in val if v)
    return "|".join(sorted(names, key=len, reverse=True))


def _ka_genitive_variants(name: str) -> list[str]:
    out = [name]
    if name.endswith("ე"):
        out += [name[:-1] + "ის", name[:-1] + "ს", name + "ს"]
    elif name.endswith("ი"):
        out += [name + "ს", name[:-1] + "ის"]
    else:
        out += [name + "ს"]
    return out


def _split_by_district(text: str, lang: str) -> dict[str, str]:
    """Return {district_key: segment_text} by splitting on district headers."""
    segments: dict[str, str] = {}
    alt = _district_alternation("en")
    en_header = re.compile(
        r"(?im)\b(" + alt + r")\b"
        r"(?:\s*[-–]\s*(" + alt + r"))?"
        r"\s*(?:district|region|m\s?/\s?r|micro\s?-?district|residential area)?\s*:"
    )
    ka_headers = []
    for d in DISTRICTS:
        for nm in _ka_genitive_variants(d["ka"]):
            ka_headers.append((re.escape(nm), d["key"]))
    ka_header_re = re.compile(
        r"(?P<phrase>(" + "|".join(h for h, _ in ka_headers) + r"))\s*"
        r"(?:რაიონი|რაიონ|უბანი|უბან|მიკრორაიონი|მიკრორაიონ|დასახლება)ში"
    )

    spans: list[tuple[int, int, set[str]]] = []
    for m in en_header.finditer(text):
        keys = set()
        for g in (m.group(1), m.group(2)):
            if g:
                ks = _key_from_name(g)
                if ks:
                    keys.update(ks)
        if keys:
            spans.append((m.start(), m.end(), keys))
    for m in ka_header_re.finditer(text):
        keys = set()
        for nm, k in ka_headers:
            if nm == m.group("phrase"):
                keys.add(k)
        ks = _key_from_name(m.group("phrase"))
        if ks:
            keys.update(ks)
        if keys:
            spans.append((m.start(), m.end(), keys))

    if not spans:
        return segments
    spans.sort()
    for i, (s, e, keys) in enumerate(spans):
        seg_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        segment = text[e:seg_end].strip(" \t:;")
        for k in keys:
            segments[k] = (segments.get(k, "") + "\n" + segment).strip()
    return segments


def _key_from_name(name: str):
    if not name:
        return None
    norm = locations.normalize_name(name)
    hits = []
    for d in DISTRICTS:
        cands = [locations.normalize_name(x) for x in (d["en"], d["ka"])] + \
                [locations.normalize_name(x) for x in d["alt"]]
        if norm and norm in cands:
            hits.append(d["key"])
    for d in DISTRICTS:
        if d["key"] in hits:
            continue
        if norm and (norm in locations.normalize_name(d["en"])
                     or norm in locations.normalize_name(d["ka"])):
            hits.append(d["key"])
    return hits or None


def extract_streets(segment: str, lang: str) -> list[str]:
    found: list[str] = []
    if not segment:
        return found
    if lang == "ka":
        for m in _STREET_KA.finditer(segment):
            found.append(m.group(1).strip())
    else:
        for m in _STREET_EN_A.finditer(segment):
            found.append(m.group(1).strip())
        for m in _STREET_EN_B.finditer(segment):
            cand = m.group(1).strip()
            if cand and cand not in ("Part", "Water", "Supply"):
                found.append(cand)
    cleaned: list[str] = []
    seen = set()
    for s in found:
        s = re.sub(r"\s+", " ", s).strip(" .,;")
        if len(s) < 3:
            continue
        key = locations.normalize_name(s)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


def detect_language(text: str) -> str:
    if not text:
        return "en"
    ka = sum(1 for ch in text if "\u10d0" <= ch <= "\u10fa")
    return "ka" if ka > 15 else "en"


def parse_announcement(text: str, url: str = "", lang: str = "en") -> ParsedAnnouncement:
    if lang == "en":
        lang = detect_language(text)
    text = text or ""
    pa = ParsedAnnouncement(url=url, lang=lang, raw=text)

    m = _TIME_RE.search(text)
    if not m:
        m = _KA_TIME_RE.search(text)
    if m:
        pa.time_text = f"{m.group(1)} – {m.group(2)}"
    dm = _DATE_RE.search(text) or _KA_DATE_RE.search(text)
    if dm:
        pa.date_text = dm.group(1)

    segs = _split_by_district(text, lang)
    for key, seg in segs.items():
        pa.districts[key] = {
            "segment": seg,
            "streets": extract_streets(seg, lang),
        }

    if not pa.districts:
        low = text.lower()
        for d in DISTRICTS:
            if d["en"].lower() in low or d["ka"] in text:
                pa.districts[d["key"]] = {"segment": text, "streets": []}
    return pa


def _norm_variants(text: str) -> list[str]:
    return locations.variants(text)


def _street_in_segment(street: str, segment: str) -> bool:
    if not street or not segment:
        return False
    q_variants = _norm_variants(street)
    seg_variants = _norm_variants(segment)
    if not q_variants:
        return False
    for q in q_variants:
        for seg in seg_variants:
            if q and q in seg:
                return True
    for q in q_variants:
        qtoks = set(q.split())
        if len(qtoks) >= 2:
            for seg in seg_variants:
                if qtoks.issubset(set(seg.split())):
                    return True
    return False


def matches_subscription(pa: ParsedAnnouncement, district_key: str,
                         street: str) -> bool:
    seg = pa.districts.get(district_key)
    if not seg:
        return False
    if street == ALL_STREETS_MARKER or not street:
        return True
    if _street_in_segment(street, seg["segment"]):
        return True
    for cand in seg.get("streets", []):
        if _street_in_segment(street, cand):
            return True
    return False


def affected_streets_for(pa: ParsedAnnouncement, district_key: str) -> list[str]:
    seg = pa.districts.get(district_key)
    return seg["streets"] if seg else []


# Massive Georgian -> English dictionary for accurate translation
# (Street names are transliterated, common terms are translated)
KA_EN_DICT = {
    "წყალმომარაგება": "water supply", "წყალსადენის ქსელი": "water pipeline",
    "წყალმომარაგების ქსელზე": "on the water supply network",
    "არაგეგმილი": "Emergency (Unplanned)", "არაგეგმიური": "Emergency (Unplanned)",
    "დაზიანების აღდგენითი სამუშაოების ჩატარების მიზნით": "to carry out repair works",
    "დაზიანების ლიკვიდაციის მიზნით": "to eliminate damage",
    "დაზიანების გამო": "due to damage", "დაზიანების": "damage",
    "აუცილებელი ტექნიკური სამუშაოები": "essential technical works",
    "აუცილებელ ტექნიკურ სამუშაოებს": "essential technical works",
    "აუცილებელი გადაერთებითი სამუშაოები": "essential switchover works",
    "ჩაატარებს": "will carry out", "ჩატარდება": "will be carried out",
    "შეუწყდება": "will be cut off", "შეეზღუდება": "will be limited",
    "ქუჩა": "St.", "ქუჩას": "St.", "ქუჩებს": "Streets", "ქუჩები": "Streets",
    "გამზირი": "Ave.", "გამზ.": "Ave.", "შესახვევი": "Lane",
    "საათამდე": "until", "დან": "from", "რაიონში": "district",
    "მოქალაქის კუთვნილ": "citizen-owned", "აღდგენის დრო გადაიწია": "restoration time extended to",
    "თან": "at", "N": "No.", "ჯივიპი": "GWP",
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
    if stripped.endswith('ს') and len(stripped) > 3:
        return stripped[:-1]
    return word

def _translate_ge_to_en(text):
    if not text: return ""
    result = text
    for ka, en in KA_EN_DICT_SORTED:
        result = result.replace(ka, en)
    
    words = result.split()
    new_words = []
    for word in words:
        if any('\u10d0' <= ch <= '\u10fa' for ch in word):
            base = _strip_genitive(word)
            trans = "".join(_KA_LATIN.get(ch, ch) for ch in base)
            new_words.append(trans.capitalize())
        else:
            new_words.append(word)
    return " ".join(new_words)

def build_notification(pa: ParsedAnnouncement, district_key: str,
                       street: str, lang: str = "en") -> str:
    """Compose the Telegram alert. Always in English with transliterated area."""
    d = locations.DISTRICT_BY_KEY.get(district_key, {})
    dname_en = d.get("en", district_key) if d else district_key
    icon = "\U0001f6b0"

    lines = [
        f"{icon} <b><u>WATER SUPPLY INTERRUPTION</u></b>",
        f"\U0001f4cd <b>District:</b> <b>{dname_en}</b>",
    ]

    if street != ALL_STREETS_MARKER and street:
        street_display = locations.display_street(street, "en")
        lines.append(f"\U0001f5fa <b>Street:</b> <b>{street_display}</b>")

    if pa.time_text:
        lines.append(f"\u23f1 <b>Time:</b> <b><u>{pa.time_text}</u></b>")
    if pa.date_text:
        lines.append(f"\U0001f4c5 <b>Date:</b> <b>{pa.date_text}</b>")

    seg = pa.districts.get(district_key, {}).get("segment", "")
    if seg:
        seg_en = _translate_ge_to_en(seg)
        snippet = re.sub(r"\s+", " ", seg_en).strip()
        if len(snippet) > 400:
            snippet = snippet[:400].rsplit(" ", 1)[0] + "..."
        lines.append(f"\n\U0001f4dd <b><u>Affected area:</u></b>")
        lines.append(f"<i>{snippet}</i>")

    if pa.url:
        lines.append(f"\n\U0001f517 <a href=\"{pa.url}\">View source</a>")
    return "\n".join(lines)


_GEO_EN_DICT = {
    "tsqalmomarageba": "water supply", "tsqalmomaragebis": "water supply",
    "tsqalmomaragebas": "water supply",
    "sheutsqdeba": "will be cut", "sheezghudeba": "will be restricted", "tsqalsadenis": "water pipeline",
    "kselze": "network", "dazianebis": "damage", "gamo": "due to",
    "likvidatsiis": "elimination", "miznit": "for the purpose of",
    "gadaertebiti": "switching", "samushaoebi": "works", "samushaoebs": "works",
    "chatardeba": "will be carried out", "chaatarebs": "will carry out",
    "autsilebeli": "necessary", "teknikur": "technical",
    "saatamde": "until", "dan": "from", "raionshi": "district",
    "raioni": "district", "kucha": "street", "kuchas": "street",
    "kuchaze": "street", "kuchebs": "streets", "gamziri": "avenue",
    "gamz": "ave", "mikroraioni": "microdistrict", "dasaxleba": "settlement",
    "natsili": "part", "aghmdgeniti": "restoration", "avarialad": "emergency",
    "aghdgeba": "will be restored", "etapobrivad": "gradually",
    "korpusi": "building", "shesakhvevi": "lane", "chikhi": "dead end",
    "moedani": "square", "khidi": "bridge", "gzatqetsili": "highway",
}


def _translate_georgian_area(text):
    if not text:
        return ""
    result = []
    for word in text.split():
        clean = word.strip(".,;:!?()[]\"'-")
        lat = locations.georgian_to_latin(clean).lower()
        suffix = word[len(clean):]
        # Exact match
        if lat in _GEO_EN_DICT:
            result.append(_GEO_EN_DICT[lat] + suffix)
        # Stem match: handle Georgian case endings (-is, -s, -ze, -sh)
        else:
            matched = False
            for trim in range(1, min(5, len(lat))):
                stem = lat[:-trim]
                if stem in _GEO_EN_DICT:
                    result.append(_GEO_EN_DICT[stem] + suffix)
                    matched = True
                    break
            if not matched:
                if locations.has_georgian(clean):
                    result.append(locations.georgian_to_latin(clean) + suffix)
                else:
                    result.append(word)
    return " ".join(result)

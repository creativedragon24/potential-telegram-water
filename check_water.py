from __future__ import annotations
import os, json, logging, hashlib, re, requests as http
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("check_water")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
DISTRICT  = os.environ.get("DISTRICT", "").strip()
STREET    = os.environ.get("STREET",   "").strip()

SEEN_FILE = "seen.json"
GWP_EN    = "https://www.gwp.ge/en/news/nonscheduled-works"
GWP_KA    = "https://www.gwp.ge/ka/news/nonscheduled-works"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer":         "https://www.gwp.ge/",
    "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
}

DISTRICT_FORMS = {
    "Vake":        ["ვაკე","ვაკის","ვაკეში"],
    "Saburtalo":   ["საბურთალო","საბურთალოს","საბურთალოში"],
    "Isani":       ["ისანი","ისანის","ისანში"],
    "Samgori":     ["სამგორი","სამგორის","სამგორში"],
    "Didube":      ["დიდუბე","დიდუბის","დიდუბეში"],
    "Chugureti":   ["ჩუღურეთი","ჩუღურეთის","ჩუღურეთში"],
    "Gldani":      ["გლდანი","გლდანის","გლდანში"],
    "Nadzaladevi": ["ნაძალადევი","ნაძალადევის","ნაძალადევში"],
    "Mtatsminda":  ["მთაწმინდა","მთაწმინდის","მთაწმინდაზე"],
    "Krtsanisi":   ["კრწანისი","კრწანისის","კრწანისში"],
    "Dighomi":     ["დიღომი","დიღომის","დიღომში"],
}

NAV_NOISE = [
    "chven shesakheb","kompania","menejmenti","sms servisi",
    "onlain gadakhda","*303#","distantsiuri","litsenzirebuli",
    "sajaro dadgenilebebi","kariera","etika da politika",
    "chemi kabineti","meniu","airchiet district",
    "tbilisi media","dagegmili works","mimdinare works",
    "tenderebi","dokumentebi","online@gwp.ge","dzebna",
    "nakhva servi","siakhleebi",
]

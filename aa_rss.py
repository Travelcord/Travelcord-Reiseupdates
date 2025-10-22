import os, json, time, pathlib, re, urllib.parse
from datetime import datetime
import requests, feedparser
from bs4 import BeautifulSoup
import country_converter as coco
import xml.etree.ElementTree as ET

# ----- Konfiguration -----
FEED_URL = "https://www.auswaertiges-amt.de/de/ReiseUndSicherheit/-/RSS"
STATE_PATH = pathlib.Path("state.json")
MAX_POSTS_PER_RUN = 10
WARM_START = False

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
FORUM_IDS = {
    "Europe":              "1430673385855385703",
    "Africa":              "1430673454457290863",
    "Asia":                "1430673642949181501",
    "NorthAmerica":        "1430673563160940644",
    "CentralSouthAmerica": "1430673715598721197",
    "Oceania":             "1430673765855002714",
}

cc = coco.CountryConverter(include_obsolete=True)

MANUAL_MAP = {
    "UK": "Europe", "Großbritannien": "Europe", "Vereinigtes Königreich": "Europe",
    "Kosovo": "Europe", "Palästinensische Gebiete": "Asia", "Hongkong": "Asia",
    "Macao": "Asia", "Taiwan": "Asia", "Grönland": "Americas",
    "Französisch-Polynesien": "Oceania", "Réunion": "Africa",
    "Kanaren": "Africa", "Azoren": "Europe", "Madeira": "Europe",
}
NORTH_AMERICA_SET = {
    "usa","vereinigte staaten","united states","us",
    "kanada","canada","mexiko","méxico","mexico",
    "grönland","greenland","bermuda"
}

# ----- Helferfunktionen -----
def clean_text(html, limit=550):
    if not html: return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return (text[:limit] + " …") if len(text) > limit else text

def load_seen():
    if STATE_PATH.exists():
        try:
            return set(json.loads(STATE_PATH.read_text()))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    STATE_PATH.write_text(json.dumps(list(seen))[:200000])

def extract_country(title: str, link: str) -> str | None:
    m = re.match(r"^\s*([^:\-–—]+)", title or "", re.I)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"/ReiseUndSicherheit/([^/\s]+)", link or "", re.I)
    return m2.group(1).replace("-", " ") if m2 else None

def to_continent(name: str | None) -> str | None:
    if not name:
        return None
    if name in MANUAL_MAP:
        return MANUAL_MAP[name]
    cont = cc.convert(names=name, to="continent", not_found=None)
    if cont in {"Europe", "Asia", "Africa", "Americas", "Oceania"}:
        return cont
    en = cc.convert(names=name, to="name_short", not_found=None)
    cont = cc.convert(names=en, to="continent", not_found=None) if en else None
    return cont if cont in {"Europe", "Asia", "Africa", "Americas", "Oceania"} else None

def split_americas(country: str | None) -> str:
    if not country:
        return "CentralSouthAmerica"
    c = country.lower()
    return "NorthAmerica" if any(tok in c for tok in NORTH_AMERICA_SET) else "CentralSouthAmerica"

def forum_post(channel_id: str, title: str, content: str):
    url = f"https://discord.com/api/v10/channels/{channel_id}/threads"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "name": title[:95],
        "auto_archive_duration": 10080,
        "message": {"content": content}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord API error {r.status_code}: {r.text}")

# ----- Feed & Sitemap-Fallback -----
def load_entries():
    # 1) RSS prüfen
    f = feedparser.parse(FEED_URL)
    n = len(f.entries or [])
    print(f"RSS entries: {n}")
    if n > 0:
        return list(reversed(f.entries))

    # 2) Sitemap-Fallback (prüft mehrere mögliche URLs)
    base = "https://www.auswaertiges-amt.de"
    sitemap_candidates = [
        f"{base}/de/sitemap.xml",
        f"{base}/sitemap.xml",
        f"{base}/de/ReiseUndSicherheit/sitemap.xml"
    ]
    hdr = {"User-Agent": "TravelcordBot", "Accept-Language": "de-DE,de;q=0.9"}

    def get(url):
        r = requests.get(url, headers=hdr, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    xml_text = None
    used = None
    for sm in sitemap_candidates:
        xml_text = get(sm)
        if xml_text:
            used = sm
            break

    if not xml_text:
        print("Keine Sitemap gefunden.")
        return []

    print(f"Using sitemap: {used}")
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [
        loc.text for loc in root.findall(".//sm:loc", ns)
        if loc is not None and "/de/ReiseUndSicherheit/" in loc.text
    ]

    urls = list(dict.fromkeys(urls))[:200]
    print(f"Sitemap URLs (R+S): {len(urls)}")

    entries = []
    for u in urls:
        title = u.rsplit("/", 1)[-1].replace("-", " ").title()
        e = type("E", (), {})()
        e.title = title
        e.link = u
        e.summary = ""
        e.id = u
        entries.append(e)

    return entries

# ----- Hauptablauf -----
def main():
    seen = load_seen()
    entries = load_entries()
    print(f"Entries total: {len(entries)}")

    if WARM_START and not seen:
        ids = [getattr(e, "id", getattr(e, "link", "")) for e in entries]
        save_seen(set(ids))
        return

    posted = 0
    for e in entries:
        id_ = getattr(e, "id", getattr(e, "link", ""))
        if id_ in seen:
            continue

        title = getattr(e, "title", "Reisehinweis")
        link = getattr(e, "link", "")
        summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", ""))

        country = extract_country(title, link)
        continent = to_continent(country)
        if continent == "Americas":
            continent = split_americas(country)

        forum_id = FORUM_IDS.get(continent)
        if not forum_id:
            seen.add(id_)
            continue

        content = f"**{title}**\n{link}\n\n{summary}"
        print(f"Posting: {title} → {continent} ({country})")
        forum_post(forum_id, title, content)

        seen.add(id_)
        posted += 1
        if posted >= MAX_POSTS_PER_RUN:
            break
        time.sleep(1.2)

    if posted:
        save_seen(seen)

if __name__ == "__main__":
    main()


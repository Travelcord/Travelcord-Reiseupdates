import os, json, time, pathlib, re
import requests, feedparser
from bs4 import BeautifulSoup
import country_converter as coco

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

# ----- Hilfsfunktionen -----
def clean_text(html, limit=550):
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return (text[:limit] + " …") if len(text) > limit else text

def load_seen():
    if STATE_PATH.exists():
        try:
            return set(json.loads(STATE_PATH.read_text()))
        except:
            return set()
    return set()

def save_seen(seen):
    STATE_PATH.write_text(json.dumps(list(seen))[:200000])

def to_continent(name):
    if not name:
        return None
    if name in MANUAL_MAP:
        return MANUAL_MAP[name]
    cont = cc.convert(names=name, to="continent", not_found=None)
    if cont == "Americas":
        c = name.lower()
        return "NorthAmerica" if any(tok in c for tok in NORTH_AMERICA_SET) else "CentralSouthAmerica"
    return cont if cont in {"Europe", "Asia", "Africa", "Oceania"} else None

def forum_post(channel_id, title, content):
    url = f"https://discord.com/api/v10/channels/{channel_id}/threads"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    payload = {"name": title[:95], "auto_archive_duration": 10080, "message": {"content": content}}
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code >= 300:
        print(f"Discord error {r.status_code}: {r.text}")
    else:
        print(f"→ Thread erstellt in Kanal {channel_id}")

# ----- RSS + Dummy -----
def load_entries():
    feed = feedparser.parse(FEED_URL)
    entries = list(reversed(feed.entries or []))
    print(f"RSS entries: {len(entries)}")

    if entries:
        return entries

    # Dummy erzeugen, falls RSS leer
    print("Feed leer → Dummy-Eintrag für Testzwecke erstellt.")
    e = type("E", (), {})()
    e.title = "TESTBEITRAG: RSS-Feed leer (Beispielmeldung)"
    e.link = "https://www.auswaertiges-amt.de/de/ReiseUndSicherheit"
    e.summary = "Dies ist ein automatischer Testeintrag, um die Bot-Integration zu prüfen."
    e.id = "dummy-test"
    return [e]

# ----- Hauptablauf -----
def main():
    seen = load_seen()
    entries = load_entries()
    print(f"Entries total: {len(entries)}")

    posted = 0
    for e in entries:
        id_ = getattr(e, "id", getattr(e, "link", ""))
        if id_ in seen:
            continue

        title = getattr(e, "title", "Reisehinweis")
        link = getattr(e, "link", "")
        summary = clean_text(getattr(e, "summary", ""))

        # Dummy → nach Europa
        continent = "Europe" if "TESTBEITRAG" in title else to_continent(title)
        forum_id = FORUM_IDS.get(continent)
        if not forum_id:
            continue

        content = f"**{title}**\n{link}\n\n{summary}"
        print(f"Posting: {title} → {continent}")
        forum_post(forum_id, title, content)
        seen.add(id_)
        posted += 1

        if posted >= MAX_POSTS_PER_RUN:
            break
        time.sleep(1)

    if posted:
        save_seen(seen)
        print(f"Fertig: {posted} Beitrag(e) erstellt.")
    else:
        print("Keine neuen Beiträge erstellt.")

if __name__ == "__main__":
    main()



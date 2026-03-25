import os
import re
import datetime as dt
import requests
from bs4 import BeautifulSoup
import spotipy
from spotipy.oauth2 import SpotifyOAuth

PLAYLIST_NAME = "KINK – nieuw (<12m) – rolling 7d"

NLBE_BOOST = 2
NON_EN_BOOST = 1
MAX_TRACKS = 150
MAX_PER_ARTIST = 2

def scrape_day(date):
    url = f"https://kink.nl/gedraaid/kink/{date}"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    pairs = []
    for h2 in soup.find_all("h2"):
        artist = h2.get_text(strip=True)
        nxt = h2.find_next("p")
        if nxt:
            title = nxt.get_text(strip=True)
            pairs.append((artist, title))
    return pairs

def looks_non_english(s):
    return bool(re.search(r"[áéíóúàèëïöüçñ]| de | het | la | le ", s.lower()))

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    scope="playlist-modify-private playlist-modify-public"
))

user = sp.current_user()["id"]

# find playlist
playlist_id = None
for pl in sp.current_user_playlists()["items"]:
    if pl["name"] == PLAYLIST_NAME:
        playlist_id = pl["id"]

if not playlist_id:
    playlist_id = sp.user_playlist_create(user, PLAYLIST_NAME)["id"]

# clear playlist
tracks = sp.playlist_items(playlist_id)["items"]
uris = [t["track"]["uri"] for t in tracks if t["track"]]
if uris:
    sp.playlist_remove_all_occurrences_of_items(playlist_id, uris)

# scrape 7 dagen
counts = {}
today = dt.date.today()
for i in range(7):
    d = today - dt.timedelta(days=i)
    for a,t in scrape_day(d):
        counts[(a,t)] = counts.get((a,t),0)+1

rows = []

for (artist,title),plays in counts.items():
    q = f"{artist} {title}"
    res = sp.search(q=q, type="track", limit=1)
    items = res["tracks"]["items"]
    if not items:
        continue

    tr = items[0]

    # release filter
    rd = tr["album"]["release_date"]
    year = int(rd[:4])
    if year < today.year-1:
        continue

    boost = 0
    isrc = sp.track(tr["id"])["external_ids"].get("isrc","")

    if isrc.startswith("NL") or isrc.startswith("BE"):
        boost += NLBE_BOOST

    if looks_non_english(artist + " " + title):
        boost += NON_EN_BOOST

    score = plays + boost
    rows.append((score, plays, tr))

rows.sort(reverse=True)

added = []
artist_count = {}

for score, plays, tr in rows:
    name = tr["artists"][0]["name"]
    artist_count[name] = artist_count.get(name,0)+1
    if artist_count[name] > MAX_PER_ARTIST:
        continue
    added.append(tr["uri"])
    if len(added) >= MAX_TRACKS:
        break

if added:
    sp.playlist_add_items(playlist_id, added)

print("done")

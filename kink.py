import base64
import datetime as dt
import os
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

PLAYLIST_NAME = "KINK – nieuw (<12m) – rolling 7d"

DAYS_BACK = 7
LOOKBACK_DAYS = 365
MAX_TRACKS = 150
MAX_PER_ARTIST = 2

NLBE_BOOST = 2.0
NON_EN_BOOST = 1.0

SPOTIFY_API = "https://api.spotify.com/v1"
KINK_BASE = "https://kink.nl/gedraaid/kink"


def spotify_access_token():
    client_id = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    refresh_token = os.environ["SPOTIFY_REFRESH_TOKEN"]

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def sp_get(token, path, params=None):
    resp = requests.get(
        f"{SPOTIFY_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def sp_post(token, path, json=None):
    resp = requests.post(
        f"{SPOTIFY_API}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json,
        timeout=30,
    )
    resp.raise_for_status()
    if resp.text:
        return resp.json()
    return None


def sp_put(token, path, json=None):
    resp = requests.put(
        f"{SPOTIFY_API}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json,
        timeout=30,
    )
    resp.raise_for_status()
    if resp.text:
        return resp.json()
    return None


def sp_delete(token, path, json=None):
    resp = requests.delete(
        f"{SPOTIFY_API}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json,
        timeout=30,
    )
    resp.raise_for_status()
    if resp.text:
        return resp.json()
    return None


def normalize(text):
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def looks_non_english(text):
    s = f" {normalize(text)} "
    hints = [
        " de ", " het ", " een ", " ik ", " jij ", " je ", " niet ",
        " le ", " la ", " les ", " une ", " un ", " tu ", " pas ",
        " der ", " die ", " das ",
        " el ", " una ", " que ",
    ]
    if any(h in s for h in hints):
        return True
    return bool(re.search(r"[áàäâãåæçéèëêíìïîñóòöôõøœúùüûýÿß]", s))


def release_date_to_date(release_date):
    if not release_date:
        return None
    parts = release_date.split("-")
    try:
        if len(parts) == 3:
            return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return dt.date(int(parts[0]), int(parts[1]), 1)
        if len(parts) == 1:
            return dt.date(int(parts[0]), 1, 1)
    except Exception:
        return None
    return None


def scrape_kink_day(day):
    url = f"{KINK_BASE}/{day.isoformat()}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    pairs = []

    for h2 in soup.find_all("h2"):
        artist = h2.get_text(" ", strip=True)
        nxt = h2.find_next(["p", "h3"])
        if not artist or nxt is None:
            continue
        title = nxt.get_text(" ", strip=True)
        if not title:
            continue
        pairs.append((artist, title))

    return pairs


def current_user(token):
    return sp_get(token, "/me")


def find_playlist(token, user_id, playlist_name):
    offset = 0
    while True:
        data = sp_get(token, "/me/playlists", params={"limit": 50, "offset": offset})
        for item in data.get("items", []):
            if item["name"] == playlist_name and item["owner"]["id"] == user_id:
                return item
        if not data.get("next"):
            return None
        offset += 50


def create_playlist(token, user_id, playlist_name):
    return sp_post(
        token,
        f"/users/{urllib.parse.quote(user_id)}/playlists",
        json={
            "name": playlist_name,
            "public": False,
            "description": "KINK airplay, rolling 7 days, releases <12 months, with NL/BE and non-English bias.",
        },
    )


def clear_playlist(token, playlist_id):
    offset = 0
    uris = []

    while True:
        data = sp_get(
            token,
            f"/playlists/{playlist_id}/tracks",
            params={"limit": 100, "offset": offset},
        )
        items = data.get("items", [])
        for item in items:
            track = item.get("track") or {}
            uri = track.get("uri")
            if uri:
                uris.append(uri)
        if not data.get("next"):
            break
        offset += 100

    unique_uris = list(dict.fromkeys(uris))
    for i in range(0, len(unique_uris), 100):
        batch = unique_uris[i:i+100]
        sp_delete(
            token,
            f"/playlists/{playlist_id}/tracks",
            json={"tracks": [{"uri": u} for u in batch]},
        )


def add_tracks(token, playlist_id, uris):
    for i in range(0, len(uris), 100):
        batch = uris[i:i+100]
        sp_post(
            token,
            f"/playlists/{playlist_id}/tracks",
            json={"uris": batch},
        )


def search_track(token, artist, title):
    q = f'track:"{title}" artist:"{artist}"'
    data = sp_get(token, "/search", params={"q": q, "type": "track", "limit": 5})
    items = data.get("tracks", {}).get("items", [])
    if items:
        return items[0]

    q2 = f"{artist} {title}"
    data = sp_get(token, "/search", params={"q": q2, "type": "track", "limit": 5})
    items = data.get("tracks", {}).get("items", [])
    return items[0] if items else None


def track_details(token, track_id):
    return sp_get(token, f"/tracks/{track_id}")


def update_playlist_details(token, playlist_id, text):
    sp_put(
        token,
        f"/playlists/{playlist_id}",
        json={"description": text[:300], "public": False},
    )


def main():
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=LOOKBACK_DAYS)

    token = spotify_access_token()
    me = current_user(token)
    user_id = me["id"]

    playlist = find_playlist(token, user_id, PLAYLIST_NAME)
    if not playlist:
        playlist = create_playlist(token, user_id, PLAYLIST_NAME)
    playlist_id = playlist["id"]

    counts = {}
    for i in range(DAYS_BACK):
        day = today - dt.timedelta(days=i)
        for artist, title in scrape_kink_day(day):
            key = (artist.strip(), title.strip())
            counts[key] = counts.get(key, 0) + 1

    ranked = []
    for (artist, title), plays in counts.items():
        track = search_track(token, artist, title)
        if not track:
            continue

        full = track_details(token, track["id"])
        album = full.get("album", {})
        rd = release_date_to_date(album.get("release_date"))
        if not rd or rd < cutoff:
            continue

        boost = 0.0
        isrc = (full.get("external_ids") or {}).get("isrc", "")
        if isrc[:2].upper() in {"NL", "BE"}:
            boost += NLBE_BOOST

        joined = f"{artist} {title}"
        if looks_non_english(joined):
            boost += NON_EN_BOOST

        score = plays + boost
        ranked.append({
            "score": score,
            "plays": plays,
            "boost": boost,
            "uri": full["uri"],
            "artist": full["artists"][0]["name"],
            "title": full["name"],
        })

    ranked.sort(key=lambda x: (x["score"], x["plays"]), reverse=True)

    chosen = []
    artist_counts = {}
    for row in ranked:
        artist = row["artist"]
        artist_counts[artist] = artist_counts.get(artist, 0)
        if artist_counts[artist] >= MAX_PER_ARTIST:
            continue
        chosen.append(row["uri"])
        artist_counts[artist] += 1
        if len(chosen) >= MAX_TRACKS:
            break

    clear_playlist(token, playlist_id)
    if chosen:
        add_tracks(token, playlist_id, chosen)

    date_range = f"{(today - dt.timedelta(days=DAYS_BACK-1)).isoformat()} t/m {today.isoformat()}"
    desc = f"KINK laatste 7 dagen ({date_range}), releases sinds {cutoff.isoformat()}, medium bias NL/BE + niet-Engelstalig."
    update_playlist_details(token, playlist_id, desc)

    print(f"Klaar. {len(chosen)} tracks toegevoegd.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Fetch public-domain, safe-for-work demo media for the screenshot/recording Stash instance (stash-demo).

    python3 dev/demo_media.py [folder]     default: ~/.imaglr-dev/demo-media

Films: Prelinger Archives titles on archive.org marked public domain (Creative Commons Public Domain Mark).
Images: NASA image library (US government work, public domain). Every file is written with its source so the
README can credit them. Standard library only; skips files already present.
"""

import json
import os
import sys
import urllib.request

FILMS = [  # archive.org identifier, file, folder name
    ("NorelcoSpeed", "NorelcoSpeed_512kb.mp4", "Norelco Speedshaver Commercial (1960s)"),
    ("Westinghouse_2", "Westinghouse_2_512kb.mp4", "Westinghouse Air Conditioners Commercial (1950s)"),
    ("MidwestH1952", "MidwestH1952_512kb.mp4", "Midwest Holiday, Part I (1952)"),
    ("WheelsAc1936_3", "WheelsAc1936_3_512kb.mp4", "Wheels Across Africa, Part III (1936)"),
    ("1965Para1965", "1965Para1965_512kb.mp4", "The 1965 Parade of Homes, Part I (1965)"),
]
NASA_SEARCHES = [("nebula", 4), ("earth from orbit", 4), ("saturn rings", 3), ("mars rover", 3)]


def fetch(url, dest):
    if os.path.exists(dest):
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "stash-imaglr-integration demo media fetch"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest + ".part", "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(dest + ".part", dest)
    return True


def main(folder):
    credits = []
    films = os.path.join(folder, "films")
    os.makedirs(films, exist_ok=True)
    for ident, name, title in FILMS:
        dest = os.path.join(films, f"{title}.mp4")
        print(("fetched " if fetch(f"https://archive.org/download/{ident}/{name}", dest) else "have    ") + title)
        credits.append(f"{title} — Prelinger Archives via archive.org/details/{ident} (public domain)")
    images = os.path.join(folder, "nasa")
    os.makedirs(images, exist_ok=True)
    for query, count in NASA_SEARCHES:
        url = f"https://images-api.nasa.gov/search?q={urllib.request.quote(query)}&media_type=image&page_size={count * 2}"
        items = json.load(urllib.request.urlopen(url, timeout=60))["collection"]["items"]
        taken = 0
        seen = set()
        for item in items:
            meta = item["data"][0]
            nasa_id, title = meta["nasa_id"], meta["title"]
            safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()[:60] or nasa_id
            dest = os.path.join(images, f"{safe}.jpg")
            if dest in seen:
                continue
            seen.add(dest)
            try:
                # the item's manifest lists the renditions that actually exist
                renditions = json.load(urllib.request.urlopen(item["href"], timeout=60))
                url = next((u for u in renditions if "~medium" in u or "~large" in u), None) \
                    or next((u for u in renditions if "~orig" in u and u.lower().endswith((".jpg", ".jpeg", ".png"))), None)
                if not url:
                    raise ValueError("no usable rendition")
                fetched = fetch(url.replace("http://", "https://"), dest)
            except Exception as e:
                print(f"skip    {title}: {e}")
                continue
            print(("fetched " if fetched else "have    ") + title)
            credits.append(f"{title} — NASA ({nasa_id}, public domain)")
            taken += 1
            if taken >= count:
                break
    with open(os.path.join(folder, "CREDITS.txt"), "w") as f:
        f.write("Demo media used for the plugin's screenshots. All public domain.\n\n" + "\n".join(credits) + "\n")
    print(f"\n{len(credits)} files in {folder} (credits in CREDITS.txt)")


if __name__ == "__main__":
    main(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/.imaglr-dev/demo-media"))

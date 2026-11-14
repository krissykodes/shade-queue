"""Address → lon/lat via NYC Planning GeoSearch (public, no key), with an on-disk cache.

Used for ForMS planting spaces whose `location` is the placeholder point in Pennsylvania
(-77.52, 40.11): 39% of empty street pits citywide (finding from Shade First NYC).
Only public pit addresses (house number + street) are sent.
"""
from __future__ import annotations

import json
import time

import requests

from pipeline.aoi import DATA

URL = "https://geosearch.planninglabs.nyc/v2/search"
BORO = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
NYC_BBOX = (-74.27, 40.47, -73.68, 40.93)
CACHE = DATA / "raw" / "_geocode_cache.json"


def is_placeholder(lon: float, lat: float) -> bool:
    w, s, e, n = NYC_BBOX
    return not (w <= lon <= e and s <= lat <= n)


def borough_from_cb(cb) -> str:
    try:
        return BORO.get(str(int(float(cb)))[0], "")
    except (TypeError, ValueError):
        return ""


def geocode(addr: str, borough: str, zipcode: str) -> tuple[float, float] | None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    q = f"{addr}, {borough}, NY {zipcode}".strip()
    if q not in cache:
        try:
            g = requests.get(URL, params={"text": q, "size": 1}, timeout=30).json()
            f = (g.get("features") or [None])[0]
            # only accept a hit in the same ZIP, else it's probably a different street of that name
            cache[q] = f["geometry"]["coordinates"] if f and f["properties"].get("postalcode") == zipcode else None
        except Exception as ex:  # noqa: BLE001
            print(f"[geocode] error for {q!r}: {ex}")
            cache[q] = None
        CACHE.write_text(json.dumps(cache))
        time.sleep(0.05)
    hit = cache[q]
    return tuple(hit) if hit else None

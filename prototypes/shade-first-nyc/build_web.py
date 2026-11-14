"""Pack data/ outputs into small files for the map (web/data/*.json).
Run after fetch_data.py and shade_score.py.  Usage: python build_web.py [ZIP ...]
"""
import json, os, sys, math
import numpy as np, shapely
from shapely.geometry import shape, mapping

ZIPS = sys.argv[1:] or ["10026", "11429"]
os.makedirs("web/data", exist_ok=True)


def rnd(geom, nd=5):
    g = shapely.set_precision(shape(geom), 10 ** -nd)
    return json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), nd))


def dump(name, obj):
    p = f"web/data/{name}"
    json.dump(obj, open(p, "w"), separators=(",", ":"))
    print(f"{p}: {os.path.getsize(p) / 1e6:.2f} MB")


# citywide pits -> flat array [lon, lat, hvi, ...]
pits = json.load(open("data/empty_pits.geojson"))["features"]
flat = []
for f in pits:
    lon, lat = f["geometry"]["coordinates"]
    flat += [round(lon, 5), round(lat, 5), f["properties"]["hvi"] or 0]
dump("pits.json", flat)

# HVI polygons, simplified ~10 m
z = json.load(open("data/hvi_zcta.geojson"))
for f in z["features"]:
    f["geometry"] = rnd(mapping(shapely.simplify(shape(f["geometry"]), 0.0001)), 5)
dump("hvi.json", z)

# ranked ZIPs
zstats = {}
for ZIP in ZIPS:
    sh = json.load(open(f"data/shade_{ZIP}.geojson"))
    for f in sh["features"]:
        f["properties"].pop("id", None)
        f["geometry"]["coordinates"] = [round(c, 6) for c in f["geometry"]["coordinates"]]
    dump(f"shade_{ZIP}.json", sh)
    b = json.load(open(f"data/buildings_{ZIP}.geojson"))
    for f in b["features"]:
        f["geometry"] = rnd(mapping(shapely.simplify(shape(f["geometry"]), 0.000005)), 6)
    dump(f"buildings_{ZIP}.json", b)
    sw = json.load(open(f"data/sidewalks_{ZIP}.geojson"))
    for f in sw["features"]:
        f["geometry"] = rnd(mapping(shapely.simplify(shape(f["geometry"]), 0.000004)), 6)
    dump(f"sidewalks_{ZIP}.json", sw)
    zstats[ZIP] = json.load(open(f"data/shade_{ZIP}_stats.json"))

summary = json.load(open("data/summary.json"))
dump("stats.json", {"zips": zstats, "city": summary, "tree_sizes": json.load(open("data/tree_sizes.json"))})

# web/page.src.html is the source. build -> web/page.html (published artifact, no doctype; the
# artifact host wraps it) and web/index.html (local copy with a document skeleton).
page = open("web/page.src.html").read().replace("/*MAPLIBRE_CSS*/", open("web/vendor/maplibre-gl.css").read())
open("web/page.html", "w").write(page)
open("web/index.html", "w").write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<style>body{margin:0}[hidden]{display:none!important}</style>\n' + page + '\n</html>\n')
print("web/page.html + web/index.html built from web/page.src.html")

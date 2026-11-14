"""Fetch empty street-tree pits + HVI by ZCTA from NYC Open Data.

Outputs:
  data/empty_pits.geojson  all Street pits with psstatus='Empty' inside NYC bbox
  data/hvi_zcta.geojson    MODZCTA polygons with HVI (1-5)
  data/summary.json        counts by HVI / ZIP, for checking against slide numbers
"""
import json, os, collections, requests
import ssl
_ca = ssl.get_default_verify_paths().cafile  # requests' bundled certifi can be stale
if _ca and os.path.exists(_ca):
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)

BASE = "https://data.cityofnewyork.us/resource/"
NYC_BBOX = (-74.27, 40.47, -73.68, 40.93)  # lon_min, lat_min, lon_max, lat_max
os.makedirs("data", exist_ok=True)


def soql(ds, params, page=50000, order=":id"):
    out, off = [], 0
    while True:
        p = dict(params, **{"$limit": page, "$offset": off, "$order": order})
        r = requests.get(BASE + ds + ".json", params=p, timeout=120)
        r.raise_for_status()
        rows = r.json()
        out += rows
        print(f"  {ds}: {len(out):,}")
        if len(rows) < page:
            return out
        off += page


def in_nyc(lon, lat):
    return NYC_BBOX[0] <= lon <= NYC_BBOX[2] and NYC_BBOX[1] <= lat <= NYC_BBOX[3]


print("HVI by ZCTA")
hvi = {r["zcta20"]: int(r["hvi"]) for r in soql("4mhf-duep", {})}

print("MODZCTA polygons")
zfeat = []
for r in soql("pri4-ifjk", {}):
    z = r["modzcta"]
    # MODZCTA can merge several ZCTAs; take the max HVI of its members
    members = [s.strip() for s in r.get("zcta", z).split(",")]
    h = max([hvi[m] for m in members if m in hvi] or [None], key=lambda x: x or 0)
    zfeat.append({"type": "Feature", "geometry": r["the_geom"],
                  "properties": {"zip": z, "label": r.get("label", z), "hvi": h,
                                 "pop": int(float(r.get("pop_est") or 0))}})

print("Empty street pits")
rows = soql("82zj-84is", {
    "$select": "globalid,zipcode,nta,communityboard,width,length,location",
    "$where": "psstatus='Empty' AND pssite='Street'"})

pits, bad = [], 0
for r in rows:
    loc = r.get("location")
    if not loc:
        bad += 1; continue
    lon, lat = loc["coordinates"]
    if not in_nyc(lon, lat):  # ~placeholder coords in Pennsylvania
        bad += 1; continue
    z = str(int(float(r["zipcode"]))) if r.get("zipcode") else None
    pits.append({"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                 "properties": {"id": r["globalid"], "zip": z, "hvi": hvi.get(z)}})

# Vacancy rate needs populated count by ZIP too
print("Populated street pits by ZIP")
pop = collections.Counter()
for r in soql("82zj-84is", {"$select": "zipcode,count(*) as n",
                            "$where": "psstatus='Populated' AND pssite='Street'",
                            "$group": "zipcode"}, order="zipcode"):
    if r.get("zipcode"):
        pop[str(int(float(r["zipcode"])))] += int(r["n"])

empty_by_zip = collections.Counter(p["properties"]["zip"] for p in pits)
by_hvi = collections.Counter(p["properties"]["hvi"] for p in pits)
for f in zfeat:
    z = f["properties"]["zip"]
    e, p = empty_by_zip.get(z, 0), pop.get(z, 0)
    f["properties"].update(empty=e, populated=p,
                           vacancy=round(e / (e + p), 3) if e + p else None)

json.dump({"type": "FeatureCollection", "features": pits}, open("data/empty_pits.geojson", "w"))
json.dump({"type": "FeatureCollection", "features": zfeat}, open("data/hvi_zcta.geojson", "w"))
summary = {
    "empty_street_raw": len(rows), "dropped_bad_coords": bad, "empty_street_in_nyc": len(pits),
    "by_hvi": {str(k): v for k, v in sorted(by_hvi.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
    "top_zips": [{"zip": z, "empty": n, "hvi": hvi.get(z),
                  "vacancy": round(n / (n + pop[z]), 3) if n + pop[z] else None}
                 for z, n in empty_by_zip.most_common(40)],
}
json.dump(summary, open("data/summary.json", "w"), indent=1)
print(json.dumps({k: summary[k] for k in ("empty_street_raw", "dropped_bad_coords",
                                          "empty_street_in_nyc", "by_hvi")}, indent=1))

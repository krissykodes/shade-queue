"""Per-pit "shade yield if planted" for one ZIP.

Question it answers: if Parks plants this empty pit, how much of the new tree's
afternoon shadow (14:00-16:00 EDT, July 15) lands on ground that is sunny today?

Model (deliberately simple):
  * Tree size by years after planting (5, 10, 15, 25) from the USDA Urban Tree Database,
    Northeast region = Queens (see tree_sizes.py -> data/tree_sizes.json).
  * At each half-hour step the sun position (NOAA formulas) moves the crown's
    shadow crown_center/tan(elevation) m away from the sun. The shadow disc is sampled
    at its centre plus two 8-point rings (at 50% and 95% of crown radius) = 17 points.
  * Pits with placeholder coordinates are geocoded from their address (NYC GeoSearch)
    and snapped to the nearest sidewalk.
  * A sample counts as NEW pedestrian shade only if it lands on SIDEWALK (NYC
    Planimetric sidewalk polygons) and is sunny today: not in a building shadow (ray-cast toward the sun against extruded
    NYC Building Footprints, heightroof), and not inside the shadow of an existing
    street tree (size from its inventory DBH via the same database).
  * shade_yield = share of samples that are new shade (0-1);
    new_shade_m2h = shade_yield * pi * crown_radius^2 * 2 h.
  * Robustness checks (default age): 49 vs 17 samples, 12-18h vs 14-16h window,
    and top-N overlap between ages -> data/checks_<ZIP>.json.
No demographic inputs; HVI is used only as the published ZIP score.

Usage: python shade_score.py [ZIP] [TOP_N] [DEFAULT_AGE]
"""
import json, math, os, ssl, sys, time, datetime as dt
import numpy as np, requests, shapely
from shapely.geometry import shape

_ca = ssl.get_default_verify_paths().cafile
if _ca and os.path.exists(_ca):
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)

ZIP = sys.argv[1] if len(sys.argv) > 1 else "11429"
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
BASE = "https://data.cityofnewyork.us/resource/"
BOROUGH = {"100": "Manhattan", "103": "Staten Island", "104": "Bronx", "112": "Brooklyn"}
DEFAULT_AGE = sys.argv[3] if len(sys.argv) > 3 else "10"
SIZES = json.load(open("data/tree_sizes.json"))  # run tree_sizes.py first
AGES = list(SIZES["by_age"])
TIMES = [(14, 0), (14, 30), (15, 0), (15, 30), (16, 0)]  # EDT, July 15
WIDE_TIMES = [(h, m) for h in range(12, 18) for m in (0, 30)] + [(18, 0)]
DATE = dt.date(2026, 7, 15)
os.makedirs("data", exist_ok=True)


def soql(ds, params, page=50000):
    out, off = [], 0
    while True:
        r = requests.get(BASE + ds + ".json", timeout=180,
                         params=dict(params, **{"$limit": page, "$offset": off, "$order": ":id"}))
        r.raise_for_status()
        rows = r.json(); out += rows
        if len(rows) < page:
            return out
        off += page


def sun_position(lat, lon, when_utc):
    """NOAA solar position. Returns (azimuth deg clockwise from N, elevation deg)."""
    jd = when_utc.timestamp() / 86400 + 2440587.5
    T = (jd - 2451545) / 36525
    L0 = (280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = (math.sin(Mr) * (1.914602 - T * (0.004817 + 0.000014 * T))
         + math.sin(2 * Mr) * (0.019993 - 0.000101 * T) + math.sin(3 * Mr) * 0.000289)
    omega = 125.04 - 1934.136 * T
    lam = L0 + C - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(math.radians(omega)))
    decl = math.asin(math.sin(eps) * math.sin(math.radians(lam)))
    y = math.tan(eps / 2) ** 2
    L0r = math.radians(L0)
    eqt = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * e * math.sin(Mr)
                           + 4 * e * y * math.sin(Mr) * math.cos(2 * L0r)
                           - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * e * e * math.sin(2 * Mr))
    mins = when_utc.hour * 60 + when_utc.minute + when_utc.second / 60
    ha = math.radians(((mins + eqt + 4 * lon) / 4) - 180)
    latr = math.radians(lat)
    cosz = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1, min(1, cosz)))
    az = math.degrees(math.atan2(math.sin(ha),
                                 math.cos(ha) * math.sin(latr) - math.tan(decl) * math.cos(latr))) + 180
    return az % 360, 90 - math.degrees(zen)


# ---------------------------------------------------------------- pits
print(f"Empty street pits in {ZIP}")
rows = soql("82zj-84is", {
    "$select": "globalid,buildingnumber,streetname,crossstreet1,crossstreet2,communityboard,location",
    "$where": f"psstatus='Empty' AND pssite='Street' AND starts_with(zipcode,'{ZIP}')"})
print(f"  {len(rows)} records")

cache_f = f"data/geocode_cache_{ZIP}.json"
cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
boro = BOROUGH.get(str(int(float(rows[0].get("communityboard") or 400)))[:1] + "00", "Queens") if rows else "Queens"
boro = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}.get(
    str(int(float(rows[0].get("communityboard") or 400)))[0], "Queens")

pits, n_geo, n_fail = [], 0, 0
for r in rows:
    lon, lat = r["location"]["coordinates"] if r.get("location") else (0, 0)
    addr = f'{r.get("buildingnumber", "")} {r.get("streetname", "")}'.strip()
    geocoded = False
    if not (-74.27 <= lon <= -73.68 and 40.47 <= lat <= 40.93):
        q = f"{addr}, {boro}, NY {ZIP}"
        if q not in cache:
            try:
                g = requests.get("https://geosearch.planninglabs.nyc/v2/search",
                                 params={"text": q, "size": 1}, timeout=30).json()
                f = g["features"][0] if g.get("features") else None
                cache[q] = f["geometry"]["coordinates"] if f and f["properties"].get("postalcode") == ZIP else None
            except Exception as ex:
                print("  geocode error", q, ex); cache[q] = None
            time.sleep(0.05)
        if not cache[q]:
            n_fail += 1; continue
        lon, lat = cache[q]; geocoded = True; n_geo += 1
    pits.append(dict(id=r["globalid"], lon=lon, lat=lat, addr=addr.title(),
                     on=f'{r.get("crossstreet1", "")} & {r.get("crossstreet2", "")}'.title(),
                     geocoded=geocoded))
json.dump(cache, open(cache_f, "w"))
print(f"  {len(pits)} located ({n_geo} geocoded from address, {n_fail} unresolvable)")

lon0 = float(np.mean([p["lon"] for p in pits])); lat0 = float(np.mean([p["lat"] for p in pits]))
KX, KY = 111320 * math.cos(math.radians(lat0)), 110540


def to_xy(lon, lat):
    return (np.asarray(lon) - lon0) * KX, (np.asarray(lat) - lat0) * KY


px, py = to_xy([p["lon"] for p in pits], [p["lat"] for p in pits])
pad = 250 / KY
lo_min, lo_max = min(p["lon"] for p in pits) - pad * 1.3, max(p["lon"] for p in pits) + pad * 1.3
la_min, la_max = min(p["lat"] for p in pits) - pad, max(p["lat"] for p in pits) + pad
box = f"{la_max}, {lo_min}, {la_min}, {lo_max}"

# ---------------------------------------------------------------- buildings
print("Building footprints")
brows = soql("5zhs-2jue", {"$select": "bin,height_roof,the_geom",
                           "$where": f"within_box(the_geom, {box})"})
bgeo, bh, bfeat = [], [], []
for b in brows:
    if not b.get("the_geom"):
        continue
    g = shape(b["the_geom"])
    h = float(b.get("height_roof") or 0) * 0.3048
    if h <= 0:
        h = 8.0  # missing height -> typical 2-storey
    coords = shapely.get_coordinates(g)
    x, y = to_xy(coords[:, 0], coords[:, 1])
    bgeo.append(shapely.set_coordinates(g, np.c_[x, y])); bh.append(h)
    bfeat.append({"type": "Feature", "geometry": b["the_geom"], "properties": {"h": round(h, 1)}})
bgeo, bh = np.array(bgeo, dtype=object), np.array(bh)
btree = shapely.STRtree(bgeo)
print(f"  {len(bgeo)} buildings, max height {bh.max():.0f} m")

# ---------------------------------------------------------------- existing trees
print("Existing street trees")
trows = soql("hn5i-inap", {"$select": "dbh,location",
                           "$where": f"tpstructure='Full' AND within_box(location, {box})"})
tx, ty, tdbh = [], [], []
for t in trows:
    if not t.get("location"):
        continue
    x, y = to_xy(*t["location"]["coordinates"])
    tx.append(float(x)); ty.append(float(y)); tdbh.append(float(t.get("dbh") or 0) * 2.54)  # in -> cm
grid = SIZES["by_dbh"]
gd = [g["dbh_cm"] for g in grid]
tr = np.interp(tdbh, gd, [g["crown_radius_m"] for g in grid])   # crown radius, m
tc = np.interp(tdbh, gd, [g["crown_center_m"] for g in grid])   # crown centre height, m
tx, ty = np.array(tx), np.array(ty)
print(f"  {len(tx)} trees")

# ---------------------------------------------------------------- sidewalks
print("Sidewalk polygons")
srows = soql("52n9-sdep", {"$select": "the_geom", "$where": f"within_box(the_geom, {box})"})
sgeo = []
for srow in srows:
    if srow.get("the_geom"):
        g = shape(srow["the_geom"]); c = shapely.get_coordinates(g)
        x, y = to_xy(c[:, 0], c[:, 1])
        sgeo.append(shapely.buffer(shapely.set_coordinates(g, np.c_[x, y]), 0.3))
sgeo = np.array(sgeo, dtype=object)
json.dump({"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {}, "geometry": srow["the_geom"]} for srow in srows if srow.get("the_geom")]},
    open(f"data/sidewalks_{ZIP}.geojson", "w"))
stree = shapely.STRtree(sgeo)
print(f"  {len(sgeo)} polygons")

# snap geocoded (address-point) pits onto the nearest sidewalk
gi = [i for i, p in enumerate(pits) if p["geocoded"]]
if gi:
    gp = shapely.points(px[gi], py[gi])
    near = stree.nearest(gp)
    snapped = shapely.get_coordinates(shapely.shortest_line(gp, sgeo[near]))[1::2]
    moved = np.hypot(snapped[:, 0] - px[gi], snapped[:, 1] - py[gi])
    px[gi], py[gi] = snapped[:, 0], snapped[:, 1]
    for k, i in enumerate(gi):
        pits[i]["lon"] = round(float(lon0 + px[i] / KX), 6); pits[i]["lat"] = round(float(lat0 + py[i] / KY), 6)
    print(f"  snapped {len(gi)} geocoded pits to sidewalk (median move {np.median(moved):.1f} m)")

# ---------------------------------------------------------------- scoring
def sun_at(hh, mm):
    when = dt.datetime(DATE.year, DATE.month, DATE.day, hh, mm, tzinfo=dt.timezone.utc) + dt.timedelta(hours=4)
    return sun_position(lat0, lon0, when)


def make_ring(radius, rings=(0.5, 0.95), per=8):
    pts = [(0.0, 0.0)]
    for k, f in enumerate(rings):
        for a in np.linspace(0, 2 * math.pi, per, endpoint=False):
            a += k * math.pi / per
            pts.append((f * radius * math.cos(a), f * radius * math.sin(a)))
    return pts


def score_pits(size, times, ring):
    """Returns (yield 0-1 per pit, per-time yield matrix)."""
    per_time = np.zeros((len(pits), len(times)))
    for ti, (hh, mm) in enumerate(times):
        az, el = sun_at(hh, mm)
        if el <= 2:
            continue
        sx, sy = math.sin(math.radians(az)), math.cos(math.radians(az))  # unit vector toward sun
        tanel = math.tan(math.radians(el))
        off = size["crown_center_m"] / tanel
        ray_len = min(bh.max() / tanel, 400)
        etx, ety = tx - sx * tc / tanel, ty - sy * tc / tanel           # existing trees' shadow centres
        for ox, oy in ring:
            qx, qy = px - sx * off + ox, py - sy * off + oy             # sample in new tree's shadow
            pts = shapely.points(qx, qy)
            on_sw = np.zeros(len(pits), bool)                          # 1) lands on sidewalk
            ii, _ = stree.query(pts, predicate="intersects")
            on_sw[ii] = True
            rays = shapely.linestrings(np.stack([np.c_[qx, qy], np.c_[qx + sx * ray_len, qy + sy * ray_len]], 1))
            ri, bj = btree.query(rays, predicate="intersects")         # 2) building shadow
            shaded = np.zeros(len(pits), bool)
            if len(ri):
                d = shapely.distance(pts[ri], shapely.intersection(rays[ri], bgeo[bj]))
                shaded[ri[bh[bj] > d * tanel]] = True
            if len(tx):                                                # 3) existing tree shadow
                dx = qx[:, None] - etx[None, :]; dy = qy[:, None] - ety[None, :]
                shaded |= ((dx * dx + dy * dy) < (tr * tr)[None, :]).any(1)
            per_time[:, ti] += on_sw & ~shaded
    per_time /= len(ring)
    return per_time.mean(1), per_time


def ranks(score):
    order = np.argsort(-score, kind="stable")
    r = np.empty(len(score), int); r[order] = np.arange(1, len(score) + 1)
    return r


def spearman(a, b):
    ra, rb = ranks(a).astype(float), ranks(b).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def top_overlap(a, b, n):
    return len(set(np.argsort(-a, kind="stable")[:n]) & set(np.argsort(-b, kind="stable")[:n])) / n


hours = (TIMES[-1][0] * 60 + TIMES[-1][1] - TIMES[0][0] * 60 - TIMES[0][1]) / 60
sun_log = [dict(time=f"{h:02d}:{m:02d}", azimuth=round(a, 1), elevation=round(e, 1))
           for (h, m), (a, e) in ((t, sun_at(*t)) for t in TIMES)]
res = {}
for age in AGES:
    size = SIZES["by_age"][age]
    sc, pt = score_pits(size, TIMES, make_ring(size["crown_radius_m"]))
    res[age] = dict(score=sc, per_time=pt, rank=ranks(sc), area_h=math.pi * size["crown_radius_m"] ** 2 * hours)
    print(f"  age {age:>2} yr: mean yield {sc.mean():.3f}, zero-yield pits {(sc == 0).sum()}")

# ---------------------------------------------------------------- robustness checks (default age)
base = res[DEFAULT_AGE]["score"]
size = SIZES["by_age"][DEFAULT_AGE]
dense, _ = score_pits(size, TIMES, make_ring(size["crown_radius_m"], rings=(0.33, 0.66, 0.95), per=16))
wide, _ = score_pits(size, WIDE_TIMES, make_ring(size["crown_radius_m"]))
checks = {
    "default_age": DEFAULT_AGE, "top_n": TOP_N,
    "samples_49_vs_17": {"spearman": round(spearman(base, dense), 3), "top_n_overlap": round(top_overlap(base, dense, TOP_N), 3)},
    "window_12_18_vs_14_16": {"spearman": round(spearman(base, wide), 3), "top_n_overlap": round(top_overlap(base, wide, TOP_N), 3)},
    "ages_vs_default": {a: {"spearman": round(spearman(base, res[a]["score"]), 3),
                            "top_n_overlap": round(top_overlap(base, res[a]["score"], TOP_N), 3)} for a in AGES},
}
json.dump(checks, open(f"data/checks_{ZIP}.json", "w"), indent=1)
print(json.dumps(checks, indent=1))

# ---------------------------------------------------------------- outputs
feats = []
for i, p in enumerate(pits):
    props = {"id": p["id"], "addr": p["addr"], "on": p["on"], "geocoded": p["geocoded"]}
    for a in AGES:
        r = res[a]
        props[f"s{a}"] = round(float(r["score"][i]), 3)
        props[f"r{a}"] = int(r["rank"][i])
        props[f"m{a}"] = round(float(r["score"][i] * r["area_h"]), 1)
        props[f"t{a}"] = [round(float(v), 2) for v in r["per_time"][i]]
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}, "properties": props})
json.dump({"type": "FeatureCollection", "features": feats}, open(f"data/shade_{ZIP}.geojson", "w"))
json.dump({"type": "FeatureCollection", "features": bfeat}, open(f"data/buildings_{ZIP}.geojson", "w"))

by_age = {}
for a in AGES:
    sc = res[a]["score"]; order = np.argsort(-sc, kind="stable"); top = sc[order[:TOP_N]]
    by_age[a] = {**SIZES["by_age"][a], "mean_yield": round(float(sc.mean()), 3),
                 "share_top_n": round(float(top.sum() / sc.sum()), 3) if sc.sum() else 0,
                 "m2h_top_n": round(float(top.sum() * res[a]["area_h"])),
                 "m2h_all": round(float(sc.sum() * res[a]["area_h"])), "zero_yield": int((sc == 0).sum())}
stats = {
    "zip": ZIP, "records": len(rows), "located": len(pits), "geocoded": n_geo, "unresolved": n_fail,
    "buildings": int(len(bgeo)), "max_building_m": round(float(bh.max()), 1), "sidewalk_polys": int(len(sgeo)),
    "existing_trees": int(len(tx)), "sun": sun_log, "hours": hours, "top_n": TOP_N,
    "default_age": DEFAULT_AGE, "by_age": by_age, "checks": checks,
}
json.dump(stats, open(f"data/shade_{ZIP}_stats.json", "w"), indent=1)
print(json.dumps(by_age, indent=1))

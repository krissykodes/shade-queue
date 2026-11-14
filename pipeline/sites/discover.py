"""Empty street planting sites (ForMS Planting Spaces, psstatus == "Empty") → PlantingSite records.

Two sources of pits:
1. pits whose `location` falls in the AOI (bbox query), and
2. pits in the AOI's ZIP codes whose `location` is the Pennsylvania placeholder (-77.52, 40.11).
   These are geocoded from their address (NYC GeoSearch), snapped to the nearest sidewalk, and kept
   if they land in the AOI. (Method from Shade First NYC; placeholders are 39% of empty pits citywide.)
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from pipeline.aoi import AOI, METRIC, WGS84, to_lonlat
from pipeline.contracts import PlantingSite
from pipeline.ingest import socrata
from pipeline.ingest.geocode import borough_from_cb, geocode, is_placeholder

NEARBY_BUILDING_M = 30.0
FIELDS = "globalid,psstatus,pssite,buildingnumber,streetname,zipcode,communityboard,overheadutilities,location"


def _placeholder_pits(aoi: AOI, zips: list[str]) -> pd.DataFrame:
    out = aoi.dir("raw") / "forms_planting_spaces_placeholder.json"
    if not out.exists():
        rows = []
        for z in zips:
            rows += socrata.query("82zj-84is", f"psstatus='Empty' AND pssite='Street' AND starts_with(zipcode,'{z}') "
                                               f"AND NOT within_box(location,40.93,-74.27,40.47,-73.68)", FIELDS)
        out.write_text(json.dumps(rows))
    return pd.DataFrame(json.loads(out.read_text()))


def discover(aoi: AOI) -> gpd.GeoDataFrame:
    rows = json.loads(socrata.fetch(aoi, "forms_planting_spaces").read_text())
    df = pd.DataFrame(rows)
    df = df[(df["psstatus"] == "Empty") & (df["pssite"] == "Street")].copy()
    df["lon"] = df["location"].map(lambda p: p["coordinates"][0])
    df["lat"] = df["location"].map(lambda p: p["coordinates"][1])
    df["geocoded"] = False

    d = aoi.dir("interim")
    sidewalks = gpd.read_parquet(d / "sidewalks.parquet")
    sw_geoms = sidewalks.geometry.values
    sw_tree = shapely.STRtree(sw_geoms)

    # --- recover placeholder-coordinate pits in this AOI's ZIP codes
    all_rows = pd.DataFrame(rows)
    zips = sorted({str(z).split(".")[0] for z in all_rows.get("zipcode", pd.Series(dtype=str)).dropna()})
    ph = _placeholder_pits(aoi, zips) if zips else pd.DataFrame()
    n_ph = len(ph)
    rec = []
    for r in ph.to_dict("records"):
        z = str(r.get("zipcode", "")).split(".")[0]
        addr = f'{r.get("buildingnumber", "")} {r.get("streetname", "")}'.strip()
        hit = geocode(addr, borough_from_cb(r.get("communityboard")), z) if addr else None
        if not hit:
            continue
        # snap the address point (building frontage) onto the nearest sidewalk
        x, y = gpd.GeoSeries(gpd.points_from_xy([hit[0]], [hit[1]]), crs=WGS84).to_crs(METRIC).iloc[0].coords[0]
        pt = shapely.Point(x, y)
        near = sw_geoms[sw_tree.nearest(pt)]
        sx, sy = shapely.get_coordinates(shapely.shortest_line(pt, near))[1]
        lon, lat = to_lonlat(sx, sy)
        if aoi.west <= lon <= aoi.east and aoi.south <= lat <= aoi.north:
            rec.append({**r, "lon": lon, "lat": lat, "geocoded": True})
    if rec:
        df = pd.concat([df, pd.DataFrame(rec)], ignore_index=True)
    print(f"[sites] {int((~df.geocoded).sum())} empty pits with real coordinates + {len(rec)} recovered from "
          f"{n_ph} placeholder records in ZIPs {zips}")

    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=WGS84).to_crs(METRIC)
    streets = gpd.read_parquet(d / "streets.parquet")
    bldg = gpd.read_parquet(d / "buildings.parquet")
    hvi = gpd.read_parquet(d / "hvi_nta.parquet").to_crs(METRIC)

    near = gpd.sjoin_nearest(g[["geometry"]], streets[["street_width_m", "orientation_deg", "geometry"]],
                             how="left", max_distance=40)
    near = near[~near.index.duplicated()]
    g["street_width_m"] = near["street_width_m"]
    g["orientation_deg"] = near["orientation_deg"]
    hj = gpd.sjoin(g[["geometry"]], hvi[["hvi_quintile", "ntaname", "geometry"]], how="left", predicate="within")
    hj = hj[~hj.index.duplicated()]
    g["hvi_quintile"] = hj["hvi_quintile"]
    g["ntaname"] = hj["ntaname"]
    sidx = bldg.sindex
    heights = []
    for p in g.geometry:
        idx = sidx.query(p.buffer(NEARBY_BUILDING_M), predicate="intersects")
        heights.append(sorted(np.round(bldg.iloc[idx]["height_m"].to_numpy(), 1).tolist(), reverse=True)[:6])
    g["nearby_building_heights"] = heights

    sites = [PlantingSite(site_id=r.globalid, lon=r.lon, lat=r.lat, status=r.psstatus,
                          street_width_m=None if pd.isna(r.street_width_m) else round(float(r.street_width_m), 1),
                          orientation_deg=None if pd.isna(r.orientation_deg) else round(float(r.orientation_deg), 1) % 180,
                          nearby_building_heights=r.nearby_building_heights,
                          hvi_quintile=None if pd.isna(r.hvi_quintile) else int(r.hvi_quintile))
             for r in g.itertuples()]
    out = pd.DataFrame([s.model_dump() for s in sites])
    out["address"] = [f'{a or ""} {b or ""}'.strip().title() for a, b in zip(g.get("buildingnumber", [None] * len(g)), g["streetname"])]
    out["streetname"] = g["streetname"].fillna("").str.title().values
    out["ntaname"] = g["ntaname"].values
    out["overheadutilities"] = g["overheadutilities"].values
    out["geocoded"] = g["geocoded"].astype(bool).values
    return gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out.lon, out.lat), crs=WGS84)

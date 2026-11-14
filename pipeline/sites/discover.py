"""Empty planting sites (ForMS Planting Spaces, psstatus == "Empty") → PlantingSite records.

v1 will fill shade_deficit_score in sites/score.py; for now discovery + context enrichment is real.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline.aoi import AOI, METRIC, WGS84
from pipeline.contracts import PlantingSite
from pipeline.ingest import socrata

NEARBY_BUILDING_M = 30.0


def discover(aoi: AOI) -> gpd.GeoDataFrame:
    rows = json.loads(socrata.fetch(aoi, "forms_planting_spaces").read_text())
    df = pd.DataFrame(rows)
    df = df[(df["psstatus"] == "Empty") & (df["pssite"] == "Street")].copy()
    lon = pd.to_numeric(df["longitude"]); lat = pd.to_numeric(df["latitude"])
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(lon, lat), crs=WGS84).to_crs(METRIC)
    g["lon"], g["lat"] = lon.values, lat.values

    d = aoi.dir("interim")
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
    out["streetname"] = g["streetname"].values
    out["ntaname"] = g["ntaname"].values
    out["overheadutilities"] = g["overheadutilities"].values
    return gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out.lon, out.lat), crs=WGS84)

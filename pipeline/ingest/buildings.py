"""Building footprints (5zhs-2jue) → interim GeoParquet in metres with height_m."""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from pipeline.aoi import AOI, FT, METRIC
from pipeline.ingest import socrata


def build(aoi: AOI) -> gpd.GeoDataFrame:
    rows = json.loads(socrata.fetch(aoi, "buildings").read_text())
    df = pd.DataFrame(rows)
    df = df[df["the_geom"].notna()]
    g = gpd.GeoDataFrame(df.drop(columns="the_geom"), geometry=[shape(x) for x in df["the_geom"]], crs=4326)
    g["height_m"] = pd.to_numeric(g["height_roof"], errors="coerce") * FT
    g = g[(g["height_m"] > 2) & (g["last_status_type"].fillna("") != "Demolition")]
    g = g.to_crs(METRIC)
    g["geometry"] = g.geometry.buffer(0)
    g = g[["bin", "height_m", "feature_code", "construction_year", "geometry"]].reset_index(drop=True)
    g.to_parquet(aoi.dir("interim") / "buildings.parquet")
    return g

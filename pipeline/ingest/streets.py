"""Street centerlines (inkn-q76z) → street segments with width/orientation, plus a v0 sidewalk band.

v0 sidewalk = band from curb (centerline ± streetwidth/2) out to curb + SIDEWALK_M, minus building
footprints. Swap for the NYC planimetric sidewalk layer later behind `sidewalks()`.
"""
from __future__ import annotations

import json
import math

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import shape

from pipeline.aoi import AOI, FT, METRIC
from pipeline.ingest import socrata

SIDEWALK_M = 4.5
SURFACE_STREET_RW = {"1"}  # rw_type 1 = street; excludes highways, bridges, ramps, paths


def bearing_deg(line) -> float:
    """Undirected bearing of the segment's end-to-end chord, 0–180°, clockwise from north."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 180


def build(aoi: AOI) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    rows = json.loads(socrata.fetch(aoi, "centerline").read_text())
    df = pd.DataFrame(rows)
    g = gpd.GeoDataFrame(df.drop(columns="the_geom"), geometry=[shape(x) for x in df["the_geom"]], crs=4326)
    g = g[g["rw_type"].astype(str).isin(SURFACE_STREET_RW)].to_crs(METRIC)
    g = g.explode(index_parts=False).reset_index(drop=True)
    g["street_width_m"] = pd.to_numeric(g["streetwidth"], errors="coerce").fillna(30) * FT
    g["orientation_deg"] = g.geometry.apply(bearing_deg)
    streets = g[["physicalid", "full_street_name", "street_width_m", "orientation_deg", "geometry"]]

    half = streets["street_width_m"] / 2
    road = shapely.union_all(streets.geometry.buffer(half, cap_style="flat").values)
    outer = shapely.union_all(streets.geometry.buffer(half + SIDEWALK_M, cap_style="flat").values)
    bldg = gpd.read_parquet(aoi.dir("interim") / "buildings.parquet")
    walk = outer.difference(road).difference(shapely.union_all(bldg.geometry.values))
    sidewalks = gpd.GeoDataFrame(geometry=[walk], crs=METRIC).explode(index_parts=False).reset_index(drop=True)

    d = aoi.dir("interim")
    streets.to_parquet(d / "streets.parquet")
    sidewalks.to_parquet(d / "sidewalks.parquet")
    gpd.GeoDataFrame(geometry=[road], crs=METRIC).to_parquet(d / "roadbed.parquet")
    return streets, sidewalks

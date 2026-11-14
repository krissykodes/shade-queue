"""Street centerlines (inkn-q76z) → street segments with width/orientation, plus sidewalk polygons.

Sidewalks come from the NYC Planimetric Sidewalk layer (52n9-sdep), buffered 0.3 m to close slivers
(as in Shade First NYC), minus building footprints. Fallback if that fetch fails: a SIDEWALK_M band from
the curb (centerline ± streetwidth/2).
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
    bldg_u = shapely.union_all(bldg.geometry.values)
    try:
        sw = pd.DataFrame(json.loads(socrata.fetch(aoi, "sidewalks").read_text()))
        sw = gpd.GeoDataFrame(geometry=[shape(x) for x in sw["the_geom"] if x], crs=4326).to_crs(METRIC)
        walk = shapely.union_all(sw.geometry.buffer(0.3).values).difference(bldg_u)
        print(f"[streets] planimetric sidewalks: {len(sw)} polygons, {walk.area:,.0f} m²")
    except Exception as ex:  # noqa: BLE001 - fall back to the curb band
        print(f"[streets] planimetric sidewalks unavailable ({ex}); using {SIDEWALK_M} m curb band")
        walk = outer.difference(road).difference(bldg_u)
    sidewalks = gpd.GeoDataFrame(geometry=[walk], crs=METRIC).explode(index_parts=False).reset_index(drop=True)

    d = aoi.dir("interim")
    streets.to_parquet(d / "streets.parquet")
    sidewalks.to_parquet(d / "sidewalks.parquet")
    gpd.GeoDataFrame(geometry=[road], crs=METRIC).to_parquet(d / "roadbed.parquet")
    return streets, sidewalks

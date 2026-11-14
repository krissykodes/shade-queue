"""ForMS tree points (hn5i-inap) → live inventory trees in the AOI (the canonical tree IDs)."""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd

from pipeline.aoi import AOI, METRIC
from pipeline.growth.allometry import normalise_species
from pipeline.ingest import socrata

LIVE_STRUCTURE = {"Full"}
DEAD_CONDITION = {"Dead"}
IN_TO_CM = 2.54


def build(aoi: AOI) -> gpd.GeoDataFrame:
    rows = json.loads(socrata.fetch(aoi, "forms_trees").read_text())
    df = pd.DataFrame(rows)
    df = df[df["tpstructure"].isin(LIVE_STRUCTURE) & ~df["tpcondition"].isin(DEAD_CONDITION)].copy()
    lon = df["location"].map(lambda p: p["coordinates"][0])
    lat = df["location"].map(lambda p: p["coordinates"][1])
    g = gpd.GeoDataFrame(df.drop(columns="location"), geometry=gpd.points_from_xy(lon, lat), crs=4326)
    g["lon"], g["lat"] = lon.values, lat.values
    g["tree_id"] = g["globalid"]
    g["dbh_cm"] = pd.to_numeric(g["dbh"], errors="coerce") * IN_TO_CM
    g["species"] = g["genusspecies"].map(normalise_species)
    g["species_label"] = g["genusspecies"].str.split(" - ").str[-1]
    g = g[["tree_id", "objectid", "species", "species_label", "dbh_cm", "tpcondition", "planteddate",
           "plantingspaceglobalid", "lon", "lat", "geometry"]].to_crs(METRIC).reset_index(drop=True)
    g.to_parquet(aoi.dir("interim") / "trees.parquet")
    return g

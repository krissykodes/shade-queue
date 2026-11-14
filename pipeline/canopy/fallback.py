"""Allometric crowns: inventory DBH + species → CrownModel(source="allometric") via UTD equations.

Used for every tree when LiDAR is unavailable, and for trees LiDAR could not segment.
"""
from __future__ import annotations

import geopandas as gpd

from pipeline.contracts import CrownModel
from pipeline.growth.allometry import dims_from_dbh

EVERGREEN_GENERA = {"Pinus", "Picea", "Abies", "Thuja", "Juniperus", "Ilex", "Magnolia grandiflora", "Taxus", "Tsuga"}
FLAT_TOP_GENERA = {"Gleditsia", "Albizia"}  # wide, open umbrella crowns
CONICAL_GENERA = {"Pinus", "Picea", "Abies", "Thuja", "Tsuga", "Liquidambar", "Metasequoia", "Taxodium"}

MATCH_CONFIDENCE = {"species": 0.6, "genus": 0.45, "generic": 0.3}


def shape_for(species: str | None) -> str:
    genus = (species or "").split(" ")[0]
    if genus in CONICAL_GENERA:
        return "cone"
    if genus in FLAT_TOP_GENERA:
        return "umbrella"
    return "ellipsoid"


def leaf_on_for(species: str | None) -> tuple[int, int]:
    genus = (species or "").split(" ")[0]
    return (1, 12) if genus in EVERGREEN_GENERA else (5, 10)


def crown_for(tree_id: str, lon: float, lat: float, species: str | None, dbh_cm: float | None,
              as_of_year: int) -> CrownModel:
    species = species if isinstance(species, str) and species else None
    dbh_cm = None if dbh_cm is None or dbh_cm != dbh_cm else dbh_cm  # NaN → None
    d = dims_from_dbh(species, dbh_cm if dbh_cm and dbh_cm > 0 else 10.0)
    return CrownModel(tree_id=tree_id, lon=lon, lat=lat, height_m=round(d.height_m, 2),
                      crown_radius_m=round(d.crown_radius_m, 2), crown_base_m=round(d.crown_base_m, 2),
                      shape=shape_for(species), species=species, source="allometric", as_of_year=as_of_year,
                      confidence=MATCH_CONFIDENCE[d.match] * (1.0 if dbh_cm else 0.5),
                      leaf_on_months=leaf_on_for(species))


def crowns_from_inventory(trees: gpd.GeoDataFrame, as_of_year: int = 2026) -> list[CrownModel]:
    return [crown_for(r.tree_id, r.lon, r.lat, r.species, r.dbh_cm, as_of_year) for r in trees.itertuples()]

"""Predicted crowns for hypothetical plantings (v2). Same CrownModel → same shade simulator.

predict_crown(species, stock_caliper_in, years, lon, lat):
  caliper (≈ DBH at planting) → UTD "age" equivalent → + years → UTD DBH → dimensions.
v2 TODO: site-condition modifiers (pit size, overhead wires, street width) and growth uncertainty bands.
"""
from __future__ import annotations

from datetime import date

from pipeline.canopy.fallback import leaf_on_for, shape_for
from pipeline.contracts import CrownModel
from pipeline.growth.allometry import age_at_dbh, dbh_at_age, dims_from_dbh, normalise_species

IN_TO_CM = 2.54


def predict_crown(species: str, stock_caliper_in: float, years: int, lon: float, lat: float,
                  site_id: str | None = None) -> CrownModel:
    sp = normalise_species(species) or species
    dbh0 = stock_caliper_in * IN_TO_CM
    age0 = age_at_dbh(sp, dbh0)
    dbh = max(dbh_at_age(sp, age0 + years), dbh0)
    d = dims_from_dbh(sp, dbh)
    return CrownModel(tree_id=site_id or f"predicted:{lon:.6f},{lat:.6f}:{years}y", lon=lon, lat=lat,
                      height_m=round(d.height_m, 2), crown_radius_m=round(d.crown_radius_m, 2),
                      crown_base_m=round(d.crown_base_m, 2), shape=shape_for(sp), species=sp,
                      source="predicted", as_of_year=date.today().year + years,
                      confidence={"species": 0.6, "genus": 0.45, "generic": 0.3}[d.match],
                      leaf_on_months=leaf_on_for(sp))

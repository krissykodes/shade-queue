"""v1 (stub): shade_deficit_score for empty planting sites.

Planned definition (0–1, higher = plant here first):
    existing_shade = fraction of leaf-on daytime samples on scenario days in which the site's
                     sidewalk frontage (≈ 10 m × 4.5 m) is already shaded by buildings or trees
                     (reuse data/processed/{aoi}/shade.parquet + building_shadows.parquet)
    potential      = mean sidewalk_shade_m2 of predict_crown(best species, 2.5" caliper, 15 yr)
                     through shade.simulate.simulate (same simulator as existing trees)
    score          = norm(potential × (1 − existing_shade)) × hvi_weight[hvi_quintile]
Inputs: PlantingSite list + ShadeContext. Output: same PlantingSites with shade_deficit_score set.
"""
from __future__ import annotations

from pipeline.contracts import PlantingSite


def score(sites: list[PlantingSite], **_) -> list[PlantingSite]:
    raise NotImplementedError("v1: see module docstring for the agreed definition")

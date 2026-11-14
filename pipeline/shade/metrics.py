"""Per-hour ShadeResult rows → per-tree-per-day ShadeSummary."""
from __future__ import annotations

import pandas as pd

USABLE_SIDEWALK_M2 = 5.0  # a sidewalk shade patch smaller than this is not "usable" (≈ one bench)


def summarise(df: pd.DataFrame, step_hours: float = 1.0) -> pd.DataFrame:
    d = pd.DataFrame(df.drop(columns="geometry", errors="ignore"))
    d["day"] = d["timestamp"].astype(str).str[:10]  # local date; mixed EST/EDT offsets
    d["usable"] = (d["sidewalk_shade_m2"] >= USABLE_SIDEWALK_M2) & d["leaf_on"]
    g = d.groupby(["tree_id", "day"])
    out = pd.DataFrame({
        "usable_sidewalk_shade_hours": g["usable"].sum() * step_hours,
        "mean_ground_shade_m2": g["ground_shade_m2"].mean().round(2),
        "mean_sidewalk_shade_m2": g["sidewalk_shade_m2"].mean().round(2),
        "public_ground_fraction": (g["public_ground_m2"].sum() / g["total_shadow_m2"].sum().clip(lower=1e-9)).clip(0, 1).round(3),
        "mean_self_shaded_fraction": g["self_shaded_fraction"].mean().round(3),
        "leaf_on": g["leaf_on"].all(),
    }).reset_index()
    return out

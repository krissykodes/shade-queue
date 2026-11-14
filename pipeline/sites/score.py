"""v1: score empty planting pits by NEW sidewalk shade (ported from Shade First NYC, shade_score.py).

The question: if Parks plants this pit, how much of the new tree's shadow lands on sidewalk that is
sunny today, meaning not already shaded by a building and not by an existing street tree?

Shade First NYC (first version)                Shade Queue port
- one generic crown, 8 m up, 4 m radius     → species × age crown from the UTD growth curves (predict_crown)
- 17 sample points of a shadow disc          → full shadow polygon from the shared simulator
- existing trees: radius ≈ 0.27 m × DBH      → existing crowns from LiDAR (or UTD allometry)
- ray-cast building shadow                   → swept building prisms (same simulator)
- Planimetric sidewalk 52n9-sdep             → same layer
- July 15, 14:00–16:00 EDT every 30 min      → same scoring window (plus a full-day hourly profile for charts)

Outputs per pit (default species, default age):
    new_shade_m2h  = mean new sidewalk shade (m²) over the window × 2 h
    shade_yield    = new sidewalk shade ÷ the tree's whole shadow (0–1); the share of its shade that is new
    shade_deficit_score = shade_yield (contract field, 0–1)
    rank           = 1 = most new shade
HVI is reported as published, never blended into the score (Shade First NYC guardrail): Parks already
orders ZIPs/NTAs by HVI; this ranks pits within them.
"""
from __future__ import annotations

from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd

from pipeline import publish
from pipeline.aoi import AOI
from pipeline.growth.predict import predict_crown
from pipeline.shade import simulate as sim
from pipeline.shade.sun import TZ, sun_positions

SCORE_DAY = date(2026, 7, 15)
WINDOW = ("14:00", "16:00")  # EDT, Shade First NYC's afternoon window
WINDOW_HOURS = 2.0
DEFAULT_SPECIES = "Platanus x acerifolia"
DEFAULT_YEARS = 10
STOCK_CALIPER_IN = 2.5
SPECIES = {  # common NYC street-tree palette; all have Queens (UTD Northeast) equations
    "Platanus x acerifolia": "London planetree",
    "Gleditsia triacanthos": "Thornless honeylocust",
    "Quercus palustris": "Pin oak",
    "Tilia cordata": "Littleleaf linden",
    "Zelkova serrata": "Japanese zelkova",
    "Ginkgo biloba": "Ginkgo",
}
YEARS = (5, 10, 15)


def day_profile_samples():
    hourly = pd.date_range(f"{SCORE_DAY} 07:00", f"{SCORE_DAY} 19:00", freq="60min", tz=TZ)
    window = pd.date_range(f"{SCORE_DAY} {WINDOW[0]}", f"{SCORE_DAY} {WINDOW[1]}", freq="30min", tz=TZ)
    return sun_positions(hourly.union(window))  # hourly profile + half-hourly scoring window


def _in_window(ts) -> bool:
    hm = ts.strftime("%H:%M")
    return WINDOW[0] <= hm <= WINDOW[1]


def run_scenarios(aoi: AOI, sites: gpd.GeoDataFrame, species=SPECIES, years=YEARS) -> pd.DataFrame:
    """One row per (site, species, years): crown dims, window metrics, half-hourly new-shade profile."""
    ctx = sim.ShadeContext.from_interim(aoi)
    existing = publish.crowns_from_frame(gpd.read_parquet(aoi.dir("processed") / "crowns.parquet"))
    samples = day_profile_samples()
    rows = []
    for sp in species:
        for y in years:
            crowns = [predict_crown(sp, STOCK_CALIPER_IN, y, r.lon, r.lat, site_id=r.site_id) for r in sites.itertuples()]
            df = sim.simulate(crowns, ctx, samples, keep_geometry=False, existing=existing)
            df["in_window"] = df["timestamp"].map(_in_window)
            w = df[df["in_window"]].groupby("tree_id")
            prof = df.groupby("tree_id")["new_sidewalk_shade_m2"].apply(lambda s: [round(v, 1) for v in s])
            agg = pd.DataFrame({
                "new_shade_m2": w["new_sidewalk_shade_m2"].mean(),
                "shadow_m2": w["total_shadow_m2"].mean(),
                "sidewalk_shade_m2": w["sidewalk_shade_m2"].mean(),
            })
            agg["new_shade_m2h"] = (agg["new_shade_m2"] * WINDOW_HOURS).round(1)
            agg["shade_yield"] = (agg["new_shade_m2"] / agg["shadow_m2"].clip(lower=1e-9)).clip(0, 1).round(3)
            agg["profile"] = prof
            cdim = {c.tree_id: c for c in crowns}
            for sid, r in agg.iterrows():
                c = cdim[sid]
                rows.append(dict(site_id=sid, species=sp, years=y, height_m=c.height_m, crown_radius_m=c.crown_radius_m,
                                 crown_base_m=c.crown_base_m, shape=c.shape, new_shade_m2h=r.new_shade_m2h,
                                 shade_yield=r.shade_yield, sidewalk_shade_m2=round(r.sidewalk_shade_m2, 1),
                                 profile=r.profile))
            print(f"[score] {sp} @ {y} yr: {len(crowns)} pits, mean new shade {agg['new_shade_m2h'].mean():.0f} m²·h")
    out = pd.DataFrame(rows)
    out.attrs["profile_times"] = [s.timestamp.strftime("%H:%M") for s in samples]
    return out


def score(aoi: AOI, sites: gpd.GeoDataFrame, scen: pd.DataFrame) -> gpd.GeoDataFrame:
    d = scen[(scen.species == DEFAULT_SPECIES) & (scen.years == DEFAULT_YEARS)].set_index("site_id")
    s = sites.copy()
    s["new_shade_m2h"] = s["site_id"].map(d["new_shade_m2h"]).fillna(0.0)
    s["shade_yield"] = s["site_id"].map(d["shade_yield"]).fillna(0.0)
    s["shade_deficit_score"] = s["shade_yield"]
    s["rank"] = s["new_shade_m2h"].rank(ascending=False, method="first").astype(int)
    return s.sort_values("rank")


def summary(sites: gpd.GeoDataFrame, top_n: int = 50) -> dict:
    v = sites.sort_values("rank")["new_shade_m2h"].to_numpy()
    n = len(v)
    top_n = min(top_n, n)
    rng = np.random.default_rng(0)
    unranked = np.mean([v[rng.permutation(n)[:top_n]].sum() for _ in range(200)]) if n else 0
    return dict(pits=n, geocoded=int(sites["geocoded"].sum()) if "geocoded" in sites else 0, top_n=top_n,
                top_m2h=round(float(v[:top_n].sum())), all_m2h=round(float(v.sum())),
                share_top=round(float(v[:top_n].sum() / max(v.sum(), 1e-9)), 3),
                gain_vs_unranked=round(float(v[:top_n].sum() / max(unranked, 1e-9)), 2),
                zero_pits=int((v == 0).sum()), default_species=DEFAULT_SPECIES, default_years=DEFAULT_YEARS,
                window=f"{SCORE_DAY:%b %d} {WINDOW[0]}–{WINDOW[1]}")

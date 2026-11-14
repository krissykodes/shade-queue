"""python -m pipeline run --aoi mott_haven [--steps ingest,canopy,shade,sites] [--refresh]"""
from __future__ import annotations

import argparse
import time

import geopandas as gpd
import pandas as pd

from pipeline import publish
from pipeline.aoi import AOI
from pipeline.contracts import CrownModel

STEPS = ["ingest", "canopy", "shade", "sites"]


def step_ingest(aoi: AOI, refresh: bool) -> None:
    from pipeline.ingest import buildings, hvi, socrata, streets, trees
    socrata.fetch_all(aoi, refresh)
    b = buildings.build(aoi)
    s, sw = streets.build(aoi)
    t = trees.build(aoi)
    hvi.build(aoi)
    publish.write(aoi, "buildings", b)
    publish.write(aoi, "sidewalks", sw)
    print(f"[ingest] {len(t)} live inventory trees, {len(b)} buildings, {len(s)} street segments")


def step_canopy(aoi: AOI, use_lidar: bool = True) -> None:
    from pipeline.canopy import fallback
    trees = gpd.read_parquet(aoi.dir("interim") / "trees.parquet")
    crowns = {c.tree_id: c for c in fallback.crowns_from_inventory(trees)}
    lidar_path = aoi.dir("interim") / "lidar_crowns.parquet"
    if use_lidar and lidar_path.exists():
        lid = pd.read_parquet(lidar_path)
        for r in lid.to_dict("records"):
            crowns[r["tree_id"]] = CrownModel(**{k: r[k] for k in CrownModel.model_fields if k in r and k != "leaf_on_months"},
                                              leaf_on_months=crowns[r["tree_id"]].leaf_on_months
                                              if r["tree_id"] in crowns else (5, 10))
        print(f"[canopy] {len(lid)} LiDAR crowns merged; {sum(c.source == 'allometric' for c in crowns.values())} allometric")
    extra = trees[["tree_id", "species_label", "dbh_cm", "tpcondition"]]
    publish.write(aoi, "crowns", publish.crowns_gdf(list(crowns.values()), extra))


def step_shade(aoi: AOI) -> None:
    from pipeline.shade import metrics, simulate, sun
    cr = gpd.read_parquet(aoi.dir("processed") / "crowns.parquet")
    crowns = publish.crowns_from_frame(cr)
    ctx = simulate.ShadeContext.from_interim(aoi)
    samples = sun.scenario_samples()
    t0 = time.time()
    df = simulate.simulate(crowns, ctx, samples)
    print(f"[shade] {len(crowns)} crowns × {len(samples)} sun samples in {time.time() - t0:.0f}s")
    bsh = df.attrs.pop("building_shadows")
    df["timestamp"] = df["timestamp"].astype(str)
    publish.write(aoi, "shade", df)
    bsh["timestamp"] = bsh["timestamp"].astype(str)
    publish.write(aoi, "building_shadows", bsh)
    summ = metrics.summarise(df)
    publish.write(aoi, "shade_summary", summ)


def step_sites(aoi: AOI) -> None:
    from pipeline.sites import discover
    publish.write(aoi, "sites", discover.discover(aoi))


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m pipeline")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--aoi", default="mott_haven")
    ap.add_argument("--steps", default=",".join(STEPS))
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-lidar", action="store_true", help="force allometric crowns")
    a = ap.parse_args()
    aoi = AOI.load(a.aoi)
    for s in a.steps.split(","):
        t0 = time.time()
        if s == "ingest":
            step_ingest(aoi, a.refresh)
        elif s == "canopy":
            step_canopy(aoi, not a.no_lidar)
        elif s == "shade":
            step_shade(aoi)
        elif s == "sites":
            step_sites(aoi)
        elif s == "lidar":
            from pipeline.canopy import extract
            extract.run(aoi)
        else:
            raise SystemExit(f"unknown step {s}")
        print(f"== {s} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

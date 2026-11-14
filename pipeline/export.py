"""Static site export: processed GeoParquet → site/ (plain files for GitHub Pages; no server needed).

    python -m pipeline export --aoi harlem_116 [--aoi mott_haven] [--out site]

site/
  index.html, main.js, style.css         copied from web/
  data/aois.json                         list of exported AOIs (first = default)
  data/{aoi}/meta.json                   label, bbox, timestamps + sun position, summary, species palette
  data/{aoi}/trees.json                  crowns + per-day summaries + hourly sidewalk-shade arrays
  data/{aoi}/buildings.json, hvi.json, sites.json   GeoJSON
  data/{aoi}/scenarios.json              pit × species × years → crown dims, new shade, half-hourly profile
  data/{aoi}/shadows/{i}.json            tree + building shadows for timestamp i, quantised (0.1 m ints)

Shadow rings are stored as integer decimetres relative to meta.origin (lon0, lat0) with metres-per-degree
factors kx, ky. That makes the files ~5× smaller than GeoJSON; main.js decodes them.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from pipeline.aoi import AOI, ROOT
from pipeline.sites.score import SPECIES

ROUND = 6


def _gj(gdf: gpd.GeoDataFrame, cols: list[str]) -> dict:
    g = gdf[cols + ["geometry"]].copy()
    g["geometry"] = shapely.set_precision(g.geometry.values, 1e-6)
    return json.loads(g.to_json(drop_id=True))


def _num(v):
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else round(float(v), 3)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


class Quant:
    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = 111_320 * math.cos(math.radians(lat0))
        self.ky = 110_540

    def rings(self, geom, tol_m: float = 0.25) -> list[list[int]]:
        """Polygon/MultiPolygon → list of exterior rings, each flat [x0,y0,x1,y1,...] in int decimetres."""
        if geom is None or geom.is_empty:
            return []
        out = []
        geom = geom.simplify(tol_m / self.ky, preserve_topology=False)
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type != "Polygon" or poly.area <= 0:
                continue
            c = np.asarray(poly.exterior.coords)[:-1]
            x = np.round((c[:, 0] - self.lon0) * self.kx * 10).astype(int)
            y = np.round((c[:, 1] - self.lat0) * self.ky * 10).astype(int)
            out.append(np.column_stack([x, y]).ravel().tolist())
        return out

    def meta(self) -> dict:
        return {"lon0": self.lon0, "lat0": self.lat0, "kx": self.kx, "ky": self.ky}


def export_aoi(aoi: AOI, out: Path) -> dict:
    P = aoi.dir("processed")
    d = out / "data" / aoi.name
    (d / "shadows").mkdir(parents=True, exist_ok=True)
    lon0, lat0 = (aoi.west + aoi.east) / 2, (aoi.south + aoi.north) / 2
    q = Quant(lon0, lat0)

    # --- timestamps + sun position (from the simulator output)
    shade = gpd.read_parquet(P / "shade.parquet")
    sun = (shade.groupby("timestamp")[["sun_altitude_deg", "sun_azimuth_deg"]].first().reset_index()
           .sort_values("timestamp"))
    stamps = sun["timestamp"].tolist()

    # --- trees + summaries + hourly sidewalk arrays per day
    crowns = gpd.read_parquet(P / "crowns.parquet")
    summ = pd.read_parquet(P / "shade_summary.parquet")
    shade["day"] = shade["timestamp"].str[:10]
    hourly = shade.sort_values("timestamp").groupby(["tree_id", "day"])["sidewalk_shade_m2"].apply(
        lambda s: [round(v, 1) for v in s])
    sdict: dict[str, dict] = {}
    for r in summ.to_dict("records"):
        sdict.setdefault(r["tree_id"], {})[r["day"]] = {
            "h": r["usable_sidewalk_shade_hours"], "sw": r["mean_sidewalk_shade_m2"],
            "pub": r["public_ground_fraction"], "self": r["mean_self_shaded_fraction"], "leaf": bool(r["leaf_on"])}
    cols = ["tree_id", "lon", "lat", "height_m", "crown_radius_m", "crown_base_m", "shape", "species",
            "species_label", "source", "as_of_year", "confidence", "dbh_cm", "tpcondition"]
    trees = []
    for r in crowns[cols].to_dict("records"):
        t = {k: _num(v) for k, v in r.items()}
        t["lon"], t["lat"] = round(r["lon"], ROUND), round(r["lat"], ROUND)
        t["days"] = sdict.get(r["tree_id"], {})
        t["hourly"] = {day: hourly.get((r["tree_id"], day), []) for day in t["days"]}
        trees.append(t)
    (d / "trees.json").write_text(json.dumps(trees, separators=(",", ":")))

    # --- shadows per timestamp (tree ground shadows + dissolved building shadow)
    bsh = gpd.read_parquet(P / "building_shadows.parquet").set_index("timestamp")
    for i, ts in enumerate(stamps):
        sub = shade[(shade["timestamp"] == ts) & (shade["ground_shade_m2"] > 0)]
        tre = [{"r": q.rings(g), "l": int(bool(lf))} for g, lf in zip(sub.geometry.values, sub["leaf_on"]) if g is not None]
        b = bsh.loc[ts, "geometry"] if ts in bsh.index else None
        (d / "shadows" / f"{i}.json").write_text(json.dumps({"t": tre, "b": q.rings(b, 0.5)}, separators=(",", ":")))

    # --- buildings, hvi, sites
    b = gpd.read_parquet(P / "buildings.parquet")
    b["height_m"] = b["height_m"].round(1)
    (d / "buildings.json").write_text(json.dumps(_gj(b, ["height_m"]), separators=(",", ":")))
    h = gpd.read_parquet(P / "hvi_nta.parquet")
    (d / "hvi.json").write_text(json.dumps(_gj(h, ["ntaname", "hvi_quintile"]), separators=(",", ":")))
    s = gpd.read_parquet(P / "sites.parquet")
    scols = ["site_id", "address", "streetname", "ntaname", "hvi_quintile", "street_width_m", "orientation_deg",
             "nearby_building_heights", "overheadutilities", "geocoded", "new_shade_m2h", "shade_yield", "rank"]
    s["nearby_building_heights"] = s["nearby_building_heights"].map(lambda a: [float(x) for x in a])
    (d / "sites.json").write_text(json.dumps(_gj(s, [c for c in scols if c in s.columns]), separators=(",", ":")))

    # --- planting scenarios (compact: site → species → years → [h, r, base, m2h, yield, profile])
    sc = pd.read_parquet(P / "site_scenarios.parquet")
    scen: dict = {}
    for r in sc.to_dict("records"):
        scen.setdefault(r["site_id"], {}).setdefault(r["species"], {})[str(r["years"])] = [
            r["height_m"], r["crown_radius_m"], r["crown_base_m"], r["shape"], r["new_shade_m2h"], r["shade_yield"],
            [float(v) for v in r["profile"]]]
    (d / "scenarios.json").write_text(json.dumps(scen, separators=(",", ":")))

    site_summary = json.loads((P / "sites_summary.json").read_text())
    meta = {
        "name": aoi.name, "label": aoi.label, "focus": aoi.focus, "bbox": list(aoi.bbox), "center": [lon0, lat0], "origin": q.meta(),
        "timestamps": stamps,
        "sun": [[round(a, 2), round(z, 2)] for a, z in zip(sun["sun_altitude_deg"], sun["sun_azimuth_deg"])],
        "sites_summary": site_summary, "species": SPECIES,
        "counts": {"trees": len(trees), "lidar": int((crowns["source"] == "lidar").sum()), "pits": len(s)},
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
    print(f"[export] {aoi.name}: {len(trees)} trees, {len(s)} pits, {len(stamps)} time steps → {d} ({size:.1f} MB)")
    return {"name": aoi.name, "label": aoi.label}


def export(aoi_names: list[str], out: Path = ROOT / "site") -> None:
    out.mkdir(exist_ok=True)
    for f in (ROOT / "web").iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    (out / ".nojekyll").write_text("")
    entries = [export_aoi(AOI.load(n), out) for n in aoi_names]
    (out / "data" / "aois.json").write_text(json.dumps(entries, indent=1))

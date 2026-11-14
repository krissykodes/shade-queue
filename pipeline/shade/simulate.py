"""Shade simulator: list[CrownModel] × building/sidewalk context × sun samples → ShadeResult rows.

It only accepts CrownModel. LiDAR, allometric and predicted crowns all go through this one path.
"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from pipeline.aoi import METRIC, AOI, to_metric
from pipeline.contracts import CrownModel, ShadeResult
from pipeline.shade.geometry import building_shadows, crown_shadows
from pipeline.shade.sun import SunSample

GRID_M = 40.0  # sidewalk/road unions are cut into tiles so local intersections stay cheap


def _tile(geoms: gpd.GeoSeries, size: float = GRID_M) -> np.ndarray:
    u = shapely.union_all(geoms.values)
    x0, y0, x1, y1 = u.bounds
    xs, ys = np.arange(x0, x1 + size, size), np.arange(y0, y1 + size, size)
    cells = [shapely.box(x, y, x + size, y + size) for x in xs[:-1] for y in ys[:-1]]
    parts = shapely.intersection(np.array(cells, dtype=object), u)
    return parts[~shapely.is_empty(parts)]


@dataclass
class ShadeContext:
    footprints: np.ndarray
    heights: np.ndarray
    sidewalks: np.ndarray
    roadbed: np.ndarray

    def __post_init__(self):
        self.fp_tree = STRtree(self.footprints)
        self.sw_tree = STRtree(self.sidewalks)
        self.rd_tree = STRtree(self.roadbed)

    @classmethod
    def from_interim(cls, aoi: AOI) -> "ShadeContext":
        d = aoi.dir("interim")
        b = gpd.read_parquet(d / "buildings.parquet").to_crs(METRIC)
        sw = gpd.read_parquet(d / "sidewalks.parquet").to_crs(METRIC)
        rd = gpd.read_parquet(d / "roadbed.parquet").to_crs(METRIC)
        return cls(b.geometry.values, b["height_m"].to_numpy(), _tile(sw.geometry), _tile(rd.geometry))


def _local_union(tree: STRtree, geoms: np.ndarray, g):
    idx = tree.query(g, predicate="intersects")
    if len(idx) == 0:
        return None
    return geoms[idx[0]] if len(idx) == 1 else shapely.union_all(geoms[idx])


def _area_inter(a, b) -> float:
    return 0.0 if b is None or a.is_empty else float(shapely.intersection(a, b).area)


def simulate(crowns: list[CrownModel], ctx: ShadeContext, samples: list[SunSample],
             keep_geometry: bool = True) -> pd.DataFrame:
    """One row per (tree, sample). Columns = ShadeResult fields + public_ground_m2 + total_shadow_m2 (+ geometry)."""
    lon = np.array([c.lon for c in crowns]); lat = np.array([c.lat for c in crowns])
    x, y = to_metric(lon, lat)
    x, y = np.asarray(x), np.asarray(y)
    base = np.array([c.crown_base_m for c in crowns]); top = np.array([c.height_m for c in crowns])
    rad = np.array([c.crown_radius_m for c in crowns]); shapes = np.array([c.shape for c in crowns])
    ids = [c.tree_id for c in crowns]

    rows, building_rows = [], []
    for s in samples:
        tsh = crown_shadows(x, y, base, top, rad, shapes, s.altitude_deg, s.azimuth_deg)
        # only buildings whose shadow can reach a tree shadow need projecting
        reach_m = min(ctx.heights.max() / np.tan(np.radians(s.altitude_deg)), 300.0) + 5
        bx0, by0, bx1, by1 = shapely.total_bounds(tsh)
        reach = ctx.fp_tree.query(shapely.box(bx0 - reach_m, by0 - reach_m, bx1 + reach_m, by1 + reach_m))
        bsh_all = np.empty(len(ctx.footprints), dtype=object)
        bsh_all[:] = None
        bsh_all[reach] = building_shadows(ctx.footprints[reach], ctx.heights[reach], s.altitude_deg, s.azimuth_deg)
        valid = np.array([g is not None for g in bsh_all])
        bs_geoms = bsh_all[valid]
        bs_tree = STRtree(bs_geoms)
        building_rows.append((s.timestamp, shapely.union_all(bs_geoms)))

        for i, S in enumerate(tsh):
            B = _local_union(ctx.fp_tree, ctx.footprints, S)
            ground = S if B is None else shapely.difference(S, B)
            facade = 0.0 if B is None else float(shapely.intersection(S, B).area)
            ga = float(ground.area)
            BS = _local_union(bs_tree, bs_geoms, ground)
            in_bldg_shadow = _area_inter(ground, BS)
            SW = _local_union(ctx.sw_tree, ctx.sidewalks, ground)
            RD = _local_union(ctx.rd_tree, ctx.roadbed, ground)
            if SW is not None:
                sw_g = shapely.intersection(ground, SW)
                sidewalk = float((sw_g if BS is None else shapely.difference(sw_g, BS)).area)
                sw_area_raw = float(sw_g.area)
            else:
                sidewalk, sw_area_raw = 0.0, 0.0
            public = sw_area_raw + _area_inter(ground, RD)
            c = crowns[i]
            row = dict(tree_id=ids[i], timestamp=s.timestamp, sun_altitude_deg=round(s.altitude_deg, 2),
                       sun_azimuth_deg=round(s.azimuth_deg, 2), ground_shade_m2=round(ga, 2),
                       facade_shade_m2=round(facade, 2),
                       self_shaded_fraction=round(min(in_bldg_shadow / ga, 1.0), 4) if ga > 0 else 0.0,
                       sidewalk_shade_m2=round(sidewalk, 2), leaf_on=c.leaf_on(s.timestamp.month),
                       public_ground_m2=round(min(public, ga), 2), total_shadow_m2=round(float(S.area), 2))
            if keep_geometry:
                row["geometry"] = ground
            rows.append(row)

    df = pd.DataFrame(rows)
    if keep_geometry:
        df = gpd.GeoDataFrame(df, geometry="geometry", crs=METRIC)
    df.attrs["building_shadows"] = gpd.GeoDataFrame(
        {"timestamp": [t for t, _ in building_rows]}, geometry=[g for _, g in building_rows], crs=METRIC)
    return df


def to_results(df: pd.DataFrame) -> list[ShadeResult]:
    fields = list(ShadeResult.model_fields)
    return [ShadeResult(**{k: r[k] for k in fields}) for r in df[fields].to_dict("records")]

"""LiDAR → per-tree CrownModel(source="lidar").  (ARCHITECTURE.md §4 canopy/, ADR-0003)

1. ground.py-equivalent: rasterise class-2 ground → DTM; class 3/4/5 vegetation max-z → DSM; CHM = DSM − DTM.
2. Canopy mask: CHM ≥ 3 m, outside building footprints.
3. Inventory-seeded marker watershed: ForMS tree points are the seeds (snapped to the local CHM peak
   within 2.5 m); extra CHM local maxima ≥ 3.5 m from any seed are added as unlinked crowns.
4. Per crown: height = p99 CHM, radius = √(area/π), base = p10 of vegetation-return heights,
   centre = crown centroid. Linked crowns keep the ForMS tree_id; unlinked → lidar_unlinked.parquet.

The 2021 NYC tiles are EPSG:6539 (ftUS) + NAVD88 ftUS heights; everything is converted to metres/UTM 18N.
"""
from __future__ import annotations

import glob
import time

import geopandas as gpd
import laspy
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy import ndimage as ndi
from skimage.draw import polygon as draw_polygon
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

from pipeline.aoi import AOI, FT, METRIC, to_lonlat
from pipeline.canopy.fallback import crown_for, leaf_on_for, shape_for

RES = 0.5            # m per CHM pixel
MIN_CANOPY_M = 3.0
SEED_SNAP_M = 2.5
EXTRA_PEAK_SEP_M = 3.5
MIN_CROWN_AREA_M2 = 4.0
GROUND, VEG, BLDG = {2}, {3, 4, 5}, {6}

_ft_to_utm = Transformer.from_crs(6539, METRIC, always_xy=True)
_utm_to_ft = Transformer.from_crs(METRIC, 6539, always_xy=True)


def read_points(aoi: AOI, buffer_m: float = 25.0) -> dict[str, np.ndarray]:
    files = sorted(glob.glob(str(aoi.dir("raw") / f"lidar_{aoi.lidar_year}" / "*.las")))
    if not files:
        raise FileNotFoundError("no LAS tiles; run `python -m pipeline.ingest.lidar --allow-large` first")
    b = aoi.buffered(buffer_m)
    xs, ys = _utm_to_ft.transform(*Transformer.from_crs(4326, METRIC, always_xy=True).transform(
        [b.west, b.east, b.east, b.west], [b.south, b.south, b.north, b.north]))
    fx0, fx1, fy0, fy1 = min(xs), max(xs), min(ys), max(ys)
    keep = {"x": [], "y": [], "z": [], "c": []}
    for f in files:
        with laspy.open(f) as r:
            h = r.header
            if h.maxs[0] < fx0 or h.mins[0] > fx1 or h.maxs[1] < fy0 or h.mins[1] > fy1:
                continue
            for pts in r.chunk_iterator(4_000_000):
                x, y = np.asarray(pts.x), np.asarray(pts.y)
                c = np.asarray(pts.classification)
                m = (x >= fx0) & (x <= fx1) & (y >= fy0) & (y <= fy1) & np.isin(c, list(GROUND | VEG | BLDG))
                if m.any():
                    keep["x"].append(x[m]); keep["y"].append(y[m]); keep["z"].append(np.asarray(pts.z)[m]); keep["c"].append(c[m])
    x, y = np.concatenate(keep["x"]), np.concatenate(keep["y"])
    ux, uy = _ft_to_utm.transform(x, y)
    return {"x": np.asarray(ux), "y": np.asarray(uy), "z": np.concatenate(keep["z"]) * FT, "c": np.concatenate(keep["c"])}


def rasterise(p: dict[str, np.ndarray]):
    x0, y1 = p["x"].min(), p["y"].max()
    W = int(np.ceil((p["x"].max() - x0) / RES)) + 1
    H = int(np.ceil((y1 - p["y"].min()) / RES)) + 1
    col = ((p["x"] - x0) / RES).astype(int)
    row = ((y1 - p["y"]) / RES).astype(int)

    g = np.isin(p["c"], list(GROUND))
    dtm = np.full((H, W), np.nan)
    # lowest ground return per cell, then fill gaps (under buildings/canopy) by nearest neighbour
    order = np.argsort(-p["z"][g])
    dtm[row[g][order], col[g][order]] = p["z"][g][order]
    holes = np.isnan(dtm)
    if holes.any():
        idx = ndi.distance_transform_edt(holes, return_distances=False, return_indices=True)
        dtm = dtm[tuple(idx)]
    dtm = ndi.median_filter(dtm, size=5)

    v = np.isin(p["c"], list(VEG))
    dsm = np.full((H, W), np.nan)
    order = np.argsort(p["z"][v])
    dsm[row[v][order], col[v][order]] = p["z"][v][order]  # max veg z wins
    chm = np.nan_to_num(dsm - dtm, nan=0.0).clip(0, 60)
    chm = ndi.grey_closing(chm, size=3)  # fill pits between returns
    veg_h = p["z"][v] - dtm[row[v], col[v]]
    transform = (x0, y1)
    return chm, dtm, transform, (row[v], col[v], veg_h)


def to_pixel(transform, x, y):
    x0, y1 = transform
    return ((y1 - np.asarray(y)) / RES).astype(int), ((np.asarray(x) - x0) / RES).astype(int)


def building_mask(shape, transform, bldg: gpd.GeoDataFrame) -> np.ndarray:
    m = np.zeros(shape, bool)
    for geom in bldg.geometry.buffer(0.5):
        for poly in getattr(geom, "geoms", [geom]):
            xs, ys = poly.exterior.coords.xy
            r, c = to_pixel(transform, xs, ys)
            rr, cc = draw_polygon(r, c, shape)
            m[rr, cc] = True
    return m


def segment(chm, transform, trees: gpd.GeoDataFrame, bmask):
    smooth = ndi.gaussian_filter(chm, 1.0)
    canopy = (smooth >= MIN_CANOPY_M) & ~bmask
    H, W = chm.shape
    markers = np.zeros(chm.shape, np.int32)
    seed_ids: dict[int, str] = {}
    r, c = to_pixel(transform, trees.geometry.x, trees.geometry.y)
    snap = int(SEED_SNAP_M / RES)
    seeds_rc = []
    for k, (rr, cc, tid) in enumerate(zip(r, c, trees["tree_id"]), start=1):
        if not (snap <= rr < H - snap and snap <= cc < W - snap):
            continue
        win = np.where(canopy[rr - snap:rr + snap + 1, cc - snap:cc + snap + 1],
                       smooth[rr - snap:rr + snap + 1, cc - snap:cc + snap + 1], -1)
        if win.max() < MIN_CANOPY_M:
            continue  # small/young tree below canopy threshold → stays allometric
        dr, dc = np.unravel_index(np.argmax(win), win.shape)
        pr, pc = rr - snap + dr, cc - snap + dc
        if markers[pr, pc]:
            continue  # two inventory points on one peak: keep the first
        markers[pr, pc] = k
        seed_ids[k] = tid
        seeds_rc.append((pr, pc))
    # unlinked crowns: CHM peaks well away from any inventory seed (park/yard trees)
    peaks = peak_local_max(np.where(canopy, smooth, 0), min_distance=int(3 / RES), threshold_abs=4.0, labels=canopy.astype(int))
    nxt = len(trees) + 1
    if seeds_rc:
        sr = np.array(seeds_rc)
        from scipy.spatial import cKDTree
        far = cKDTree(sr).query(peaks)[0] > EXTRA_PEAK_SEP_M / RES
    else:
        far = np.ones(len(peaks), bool)
    for pr, pc in peaks[far]:
        markers[pr, pc] = nxt
        nxt += 1
    labels = watershed(-smooth, markers, mask=canopy)
    return labels, seed_ids, smooth


def fit_crowns(labels, seed_ids, chm, transform, veg_pts, trees, year: int):
    x0, y1 = transform
    vr, vc, vh = veg_pts
    inside = (vr >= 0) & (vr < labels.shape[0]) & (vc >= 0) & (vc < labels.shape[1])
    vlab = np.zeros(len(vh), np.int32)
    vlab[inside] = labels[vr[inside], vc[inside]]
    base_by = pd.Series(vh[vlab > 0]).groupby(vlab[vlab > 0]).quantile(0.10)
    ids = np.unique(labels[labels > 0])
    area = ndi.sum(np.ones_like(chm), labels, ids) * RES**2
    hmax = ndi.labeled_comprehension(chm, labels, ids, lambda a: np.percentile(a, 99), float, 0)
    com = ndi.center_of_mass(np.ones_like(chm), labels, ids)
    tinfo = trees.set_index("tree_id")
    linked, unlinked = [], []
    for lab, a, h, (rr, cc) in zip(ids, area, hmax, com):
        if a < MIN_CROWN_AREA_M2 or h < MIN_CANOPY_M:
            continue
        x, y = x0 + (cc + 0.5) * RES, y1 - (rr + 0.5) * RES
        lon, lat = to_lonlat(x, y)
        radius = float(np.sqrt(a / np.pi))
        base = float(np.clip(base_by.get(lab, h * 0.3), 0.5, h * 0.8))
        tid = seed_ids.get(int(lab))
        if tid is not None:
            t = tinfo.loc[tid]
            sp = t.species if isinstance(t.species, str) else None
            allo = crown_for(tid, t.lon, t.lat, sp, t.dbh_cm, year)
            # confidence: agreement between LiDAR height and DBH-allometric height
            conf = float(np.clip(1 - abs(h - allo.height_m) / max(allo.height_m, h), 0.3, 1.0))
            linked.append(dict(tree_id=tid, lon=lon, lat=lat, height_m=round(float(h), 2), crown_radius_m=round(radius, 2),
                               crown_base_m=round(base, 2), shape=shape_for(sp), species=sp,
                               source="lidar", as_of_year=year, confidence=round(conf, 2),
                               leaf_on_start=leaf_on_for(sp)[0], leaf_on_end=leaf_on_for(sp)[1],
                               allometric_height_m=allo.height_m, allometric_radius_m=allo.crown_radius_m))
        else:
            unlinked.append(dict(tree_id=f"lidar:{lab}", lon=lon, lat=lat, height_m=round(float(h), 2),
                                 crown_radius_m=round(radius, 2), crown_base_m=round(base, 2), source="lidar",
                                 as_of_year=year))
    return pd.DataFrame(linked), pd.DataFrame(unlinked)


def run(aoi: AOI) -> pd.DataFrame:
    t0 = time.time()
    p = read_points(aoi)
    print(f"[lidar] {len(p['z']):,} points in AOI ({time.time() - t0:.0f}s)")
    chm, dtm, transform, veg = rasterise(p)
    del p
    d = aoi.dir("interim")
    trees = gpd.read_parquet(d / "trees.parquet")
    bldg = gpd.read_parquet(d / "buildings.parquet")
    bmask = building_mask(chm.shape, transform, bldg)
    labels, seed_ids, smooth = segment(chm, transform, trees, bmask)
    linked, unlinked = fit_crowns(labels, seed_ids, chm, transform, veg, trees, aoi.lidar_year)
    np.savez_compressed(d / "chm.npz", chm=chm.astype(np.float32), labels=labels, x0=transform[0], y1=transform[1], res=RES)
    linked.to_parquet(d / "lidar_crowns.parquet")
    unlinked.to_parquet(d / "lidar_unlinked.parquet")
    print(f"[lidar] CHM {chm.shape}, {len(linked)} crowns linked to ForMS trees of {len(trees)}, "
          f"{len(unlinked)} unlinked crowns ({time.time() - t0:.0f}s)")
    return linked

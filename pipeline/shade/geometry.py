"""2.5-D shadow geometry in a metric CRS (ADR-0002).

Crowns: a crown is a convex solid of revolution, sliced into horizontal discs. A disc at height z
projects to a circle shifted by z / tan(altitude) away from the sun. The projection of a convex body
is convex, so the ground shadow is exactly the convex hull of the projected discs.

Buildings: flat-roofed prisms. Shadow = footprint ∪ roof translated by the offset ∪ the quads swept by
each wall edge (Minkowski sum of footprint and the offset segment). Convex footprints shortcut to a hull.
Ignored: terrain slope, leaf porosity, grid convergence (<1° in the Bronx).
"""
from __future__ import annotations

import math

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import Polygon

N_SLICES = 7
N_CIRCLE = 16
_THETA = np.linspace(0, 2 * np.pi, N_CIRCLE, endpoint=False)
_COS, _SIN = np.cos(_THETA), np.sin(_THETA)


def crown_profile(shape: str, base: float, top: float, radius: float, n: int = N_SLICES) -> tuple[np.ndarray, np.ndarray]:
    """Heights z and radii r of horizontal crown slices, base → top."""
    z = np.linspace(base, top, n)
    t = (z - base) / max(top - base, 1e-6)  # 0 at base, 1 at top
    if shape == "cone":
        r = radius * (1 - t)
    elif shape == "cylinder":
        r = np.full_like(z, radius)
    elif shape == "umbrella":  # widest at 65% of crown depth, flat-ish top
        u = (t - 0.65) / np.where(t < 0.65, 0.65, 0.35)
        r = radius * np.sqrt(np.clip(1 - u**2, 0, 1))
    else:  # ellipsoid
        r = radius * np.sqrt(np.clip(1 - (2 * t - 1) ** 2, 0, 1))
    r = np.maximum(r, 0.15 * radius)  # keep the tip/base slices from degenerating
    return z, r


def sun_offset(altitude_deg: float, azimuth_deg: float) -> tuple[float, float]:
    """Ground offset (dx, dy) per metre of height, pointing away from the sun."""
    k = 1.0 / math.tan(math.radians(altitude_deg))
    az = math.radians(azimuth_deg)
    return -k * math.sin(az), -k * math.cos(az)


def crown_shadows(x: np.ndarray, y: np.ndarray, base: np.ndarray, top: np.ndarray, radius: np.ndarray,
                  shapes: np.ndarray, altitude_deg: float, azimuth_deg: float) -> np.ndarray:
    """Vectorised: shadow polygons (shapely array) for N crowns at one sun position."""
    ox, oy = sun_offset(altitude_deg, azimuth_deg)
    n = len(x)
    pts = np.empty((n, N_SLICES * N_CIRCLE, 2))
    for shp in np.unique(shapes):
        idx = np.nonzero(shapes == shp)[0]
        for i in idx:  # profile per tree (cheap: 7 values)
            z, r = crown_profile(shp, base[i], top[i], radius[i])
            cx = x[i] + z * ox
            cy = y[i] + z * oy
            pts[i, :, 0] = (cx[:, None] + r[:, None] * _COS[None, :]).ravel()
            pts[i, :, 1] = (cy[:, None] + r[:, None] * _SIN[None, :]).ravel()
    return shapely.convex_hull(shapely.multipoints(pts))


def crown_footprints(x, y, radius) -> np.ndarray:
    return shapely.buffer(shapely.points(x, y), radius, quad_segs=4)


def _is_convex(poly: Polygon, tol: float = 0.995) -> bool:
    hull = poly.convex_hull
    return hull.area > 0 and poly.area / hull.area >= tol


def building_shadow(footprint, height_m: float, altitude_deg: float, azimuth_deg: float):
    ox, oy = sun_offset(altitude_deg, azimuth_deg)
    dx, dy = ox * height_m, oy * height_m
    parts = []
    for poly in getattr(footprint, "geoms", [footprint]):
        moved = shapely.affinity.translate(poly, dx, dy)
        if _is_convex(poly):
            parts.append(shapely.union_all([poly, moved]).convex_hull)
            continue
        ring = np.asarray(poly.exterior.coords)
        p1, p2 = ring[:-1], ring[1:]
        quads = np.stack([p1, p2, p2 + (dx, dy), p1 + (dx, dy), p1], axis=1)
        parts.append(shapely.union_all(np.concatenate([[poly, moved], shapely.polygons(quads)])))
    return shapely.make_valid(shapely.union_all(parts))


def building_shadows(footprints: np.ndarray, heights: np.ndarray, altitude_deg: float, azimuth_deg: float) -> np.ndarray:
    return np.array([building_shadow(f, h, altitude_deg, azimuth_deg) for f, h in zip(footprints, heights)], dtype=object)

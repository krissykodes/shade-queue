import math
from datetime import datetime

import numpy as np
import pytest
import shapely

from pipeline.contracts import CrownModel, ShadeResult
from pipeline.shade.geometry import building_shadow, crown_profile, crown_shadows, sun_offset
from pipeline.shade.simulate import ShadeContext, simulate, to_results
from pipeline.shade.sun import SunSample, day_samples
from pipeline.aoi import to_lonlat, to_metric


def test_sun_offset_points_away_from_sun():
    # Azimuth 180 = sun due south at 45°: shadow falls 1 m NORTH (+y) per metre of height.
    dx, dy = sun_offset(45, 180)
    assert dx == pytest.approx(0, abs=1e-9) and dy == pytest.approx(1.0)
    dx, dy = sun_offset(45, 90)  # sun in the east → shadow to the west
    assert dx == pytest.approx(-1.0) and dy == pytest.approx(0, abs=1e-9)


def test_sphere_shadow_offset_at_45deg():
    # Sphere centred 10 m up: at 45° altitude its shadow centroid is 10 m from the trunk.
    x, y = np.array([0.0]), np.array([0.0])
    sh = crown_shadows(x, y, np.array([7.0]), np.array([13.0]), np.array([3.0]), np.array(["ellipsoid"]), 45, 180)[0]
    c = sh.centroid
    assert c.x == pytest.approx(0, abs=0.05)
    assert c.y == pytest.approx(10.0, abs=0.3)
    # elongated along the shadow direction (projection of a sphere at 45° is an ellipse)
    minx, miny, maxx, maxy = sh.bounds
    assert (maxy - miny) > (maxx - minx)


def test_building_shadow_rect():
    fp = shapely.box(0, 0, 10, 10)
    sh = building_shadow(fp, 10, 45, 180)
    assert sh.area == pytest.approx(200, rel=0.01)  # 10×10 footprint swept 10 m north


def test_crown_profile_shapes():
    for s in ("ellipsoid", "cone", "cylinder", "umbrella"):
        z, r = crown_profile(s, 2, 10, 4)
        assert z[0] == 2 and z[-1] == 10 and (r > 0).all() and r.max() <= 4 + 1e-9


def test_contract_rejects_bad_crown():
    with pytest.raises(ValueError):
        CrownModel(tree_id="t", lon=-73.92, lat=40.81, height_m=5, crown_radius_m=2, crown_base_m=6,
                   source="allometric", as_of_year=2026)


def test_simulate_end_to_end_with_wall():
    """A tree south of a tall building at noon in June: part of its shadow hits the façade."""
    x0, y0 = to_metric(-73.92, 40.81)
    tree = CrownModel(tree_id="t1", lon=-73.92, lat=40.81, height_m=12, crown_radius_m=4, crown_base_m=4,
                      source="predicted", as_of_year=2036)
    bldg = shapely.box(x0 - 20, y0 + 6, x0 + 20, y0 + 30)
    walk = shapely.box(x0 - 30, y0 - 2, x0 + 30, y0 + 6)
    road = shapely.box(x0 - 30, y0 - 20, x0 + 30, y0 - 2)
    ctx = ShadeContext(np.array([bldg], dtype=object), np.array([30.0]), np.array([walk], dtype=object),
                       np.array([road], dtype=object))
    samples = [s for s in day_samples(datetime(2026, 6, 21).date()) if s.timestamp.hour == 13]
    df = simulate([tree], ctx, samples)
    r = to_results(df)[0]
    assert isinstance(r, ShadeResult)
    assert r.ground_shade_m2 > 0 and r.sidewalk_shade_m2 > 0
    assert r.facade_shade_m2 > 0  # shadow reaches the wall 6 m north
    assert 0 <= r.self_shaded_fraction <= 1

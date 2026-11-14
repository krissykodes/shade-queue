from pathlib import Path

import pytest

from pipeline.growth.allometry import dims_from_dbh, normalise_species, resolve
from pipeline.growth.predict import predict_crown

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed" / "mott_haven"


def test_normalise_species():
    assert normalise_species("Gleditsia triacanthos var. inermis 'Skyline' - 'Skyline' Thornless honeylocust") == "Gleditsia triacanthos"
    assert normalise_species("Unknown - Unknown") is None
    assert normalise_species(float("nan")) is None


def test_resolve_levels():
    assert resolve("Platanus x acerifolia")[1] == "species"
    assert resolve("Acer campestre")[1] == "genus"
    assert resolve("Celtis occidentalis")[1] == "generic"


def test_dims_monotonic_in_dbh():
    small, big = dims_from_dbh("Platanus x acerifolia", 10), dims_from_dbh("Platanus x acerifolia", 60)
    assert big.height_m > small.height_m and big.crown_radius_m > small.crown_radius_m
    assert small.crown_base_m < small.height_m


def test_predicted_crown_grows():
    c = [predict_crown("Quercus palustris", 2.5, y, -73.92, 40.81) for y in (5, 10, 15)]
    assert all(x.source == "predicted" for x in c)
    assert c[0].height_m < c[1].height_m < c[2].height_m
    assert c[0].crown_radius_m < c[2].crown_radius_m


@pytest.mark.skipif(not (PROCESSED / "crowns.parquet").exists(), reason="pipeline not built (make data)")
def test_api_smoke():
    from fastapi.testclient import TestClient
    from api.main import app
    c = TestClient(app)
    trees = c.get("/trees").json()["features"]
    assert len(trees) > 100
    ts = c.get("/timestamps").json()
    assert c.get("/shadows", params={"timestamp": ts[0]}).status_code == 200
    site = c.get("/sites").json()["features"][0]["geometry"]["coordinates"]
    r = c.post("/simulate", json={"species": "Platanus x acerifolia", "lon": site[0], "lat": site[1], "years": [5, 15]}).json()
    assert r["scenarios"][1]["crown"]["height_m"] > r["scenarios"][0]["crown"]["height_m"]

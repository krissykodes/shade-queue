"""Shade Queue API: read-only over data/processed/{aoi}/*.parquet via DuckDB spatial.

Run:  make api   (uvicorn api.main:app --reload --port 8811)
Docs: http://localhost:8811/docs
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline.aoi import DATA, ROOT

AOI_NAME = os.environ.get("SHADE_AOI", "mott_haven")
P = DATA / "processed" / AOI_NAME

app = FastAPI(title="Shade Queue API", version="0.1.0",
              description="Per-tree crown + shade simulation for NYC street trees. All geometry EPSG:4326.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_local = threading.local()


def db() -> duckdb.DuckDBPyConnection:
    if not hasattr(_local, "con"):
        con = duckdb.connect()
        con.execute("INSTALL spatial; LOAD spatial;")
        _local.con = con
    return _local.con


def pq(name: str) -> str:
    f = P / f"{name}.parquet"
    if not f.exists():
        raise HTTPException(404, f"{name} not built yet: run `python -m pipeline run --aoi {AOI_NAME}`")
    return f"read_parquet('{f}')"


def bbox_where(bbox: str | None) -> str:
    if not bbox:
        return "TRUE"
    w, s, e, n = (float(v) for v in bbox.split(","))
    return f"ST_Intersects(geometry, ST_MakeEnvelope({w},{s},{e},{n}))"


def feature_collection(sql: str, params: list | None = None) -> dict:
    cur = db().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    feats = []
    for row in cur.fetchall():
        props = dict(zip(cols, row))
        geom = props.pop("geojson")
        feats.append({"type": "Feature", "geometry": json.loads(geom), "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def props_sql(name: str) -> str:
    cols = [r[0] for r in db().execute(f"DESCRIBE SELECT * FROM {pq(name)}").fetchall() if r[0] != "geometry"]
    return ", ".join(f'"{c}"' for c in cols)


@app.get("/health")
def health():
    return {"aoi": AOI_NAME, "built": sorted(p.stem for p in P.glob("*.parquet"))}


@app.get("/trees")
def trees(bbox: str | None = None):
    """All crowns (CrownModel fields + species_label, dbh_cm), with summer-solstice summary metrics."""
    return feature_collection(f"""
        SELECT c.* EXCLUDE (geometry), ST_AsGeoJSON(c.geometry) AS geojson,
               s.usable_sidewalk_shade_hours AS summer_shade_hours, s.mean_sidewalk_shade_m2 AS summer_sidewalk_m2,
               s.public_ground_fraction AS summer_public_fraction
        FROM {pq('crowns')} c
        LEFT JOIN (SELECT * FROM {pq('shade_summary')} WHERE day = '2026-06-21') s USING (tree_id)
        WHERE {bbox_where(bbox).replace('geometry', 'c.geometry')}""")


@app.get("/trees/{tree_id}")
def tree(tree_id: str):
    fc = feature_collection(f"SELECT * EXCLUDE (geometry), ST_AsGeoJSON(geometry) AS geojson FROM {pq('crowns')} WHERE tree_id = ?", [tree_id])
    if not fc["features"]:
        raise HTTPException(404, "unknown tree_id")
    cur = db().execute(f"SELECT * FROM {pq('shade_summary')} WHERE tree_id = ? ORDER BY day", [tree_id])
    cols = [d[0] for d in cur.description]
    return {"crown": fc["features"][0], "summary": [dict(zip(cols, r)) for r in cur.fetchall()]}


@app.get("/trees/{tree_id}/shade")
def tree_shade(tree_id: str, date: date = Query(date(2026, 6, 21), description="a scenario day")):
    """Hourly ShadeResults (+ shadow polygon) for one tree on one scenario day."""
    return feature_collection(f"""
        SELECT {props_sql('shade')}, ST_AsGeoJSON(geometry) AS geojson FROM {pq('shade')}
        WHERE tree_id = ? AND starts_with(timestamp, ?) ORDER BY timestamp""", [tree_id, str(date)])


@app.get("/timestamps")
def timestamps():
    rows = db().execute(f"SELECT DISTINCT timestamp FROM {pq('building_shadows')} ORDER BY timestamp").fetchall()
    return [r[0] for r in rows]


@app.get("/shadows")
def shadows(timestamp: str, bbox: str | None = None):
    """Tree ground-shadow polygons for one sun sample (drives the time slider)."""
    return feature_collection(f"""
        SELECT tree_id, ground_shade_m2, sidewalk_shade_m2, leaf_on, ST_AsGeoJSON(geometry) AS geojson
        FROM {pq('shade')} WHERE timestamp = ? AND ground_shade_m2 > 0 AND {bbox_where(bbox)}""", [timestamp])


@app.get("/building-shadows")
def building_shadows(timestamp: str):
    return feature_collection(f"SELECT timestamp, ST_AsGeoJSON(geometry) AS geojson FROM {pq('building_shadows')} WHERE timestamp = ?", [timestamp])


@app.get("/buildings")
def buildings(bbox: str | None = None):
    return feature_collection(f"SELECT bin, height_m, ST_AsGeoJSON(geometry) AS geojson FROM {pq('buildings')} WHERE {bbox_where(bbox)}")


@app.get("/hvi")
def hvi():
    return feature_collection(f"SELECT nta2020, ntaname, hvi_quintile, ST_AsGeoJSON(geometry) AS geojson FROM {pq('hvi_nta')}")


@app.get("/sites")
def sites(bbox: str | None = None, min_score: float | None = None):
    """Empty street planting sites (PlantingSite). shade_deficit_score is null until v1 scoring lands."""
    where = bbox_where(bbox)
    if min_score is not None:
        where += f" AND shade_deficit_score >= {float(min_score)}"
    return feature_collection(f"SELECT * EXCLUDE (geometry), ST_AsGeoJSON(geometry) AS geojson FROM {pq('sites')} WHERE {where}")


class SimulateRequest(BaseModel):
    species: str = Field("Platanus x acerifolia", examples=["Platanus x acerifolia", "Gleditsia triacanthos"])
    years: list[int] = Field([5, 10, 15])
    lon: float
    lat: float
    stock_caliper_in: float = Field(2.5, description="nursery caliper at planting, inches")
    day: date = date(2026, 6, 21)


@app.post("/simulate")
def simulate_planting(req: SimulateRequest):
    """Predict the crown of a hypothetical tree at N years and run it through the SAME shade simulator."""
    from pipeline.aoi import AOI
    from pipeline.growth.predict import predict_crown
    from pipeline.shade import metrics, simulate, sun

    ctx = _context()
    samples = sun.day_samples(req.day)
    out = []
    for y in req.years:
        crown = predict_crown(req.species, req.stock_caliper_in, y, req.lon, req.lat)
        df = simulate.simulate([crown], ctx, samples)
        df.attrs.pop("building_shadows", None)
        summ = metrics.summarise(df).iloc[0].to_dict()
        hourly = [{**r.model_dump(mode="json")} for r in simulate.to_results(df)]
        shadows = [{"timestamp": str(t), "geometry": g.__geo_interface__}
                   for t, g in zip(df["timestamp"], df.to_crs(4326).geometry)]
        out.append({"years": y, "crown": crown.model_dump(), "summary": summ, "hourly": hourly, "shadows": shadows})
    return {"species": req.species, "lon": req.lon, "lat": req.lat, "scenarios": out}


_ctx = None


def _context():
    global _ctx
    if _ctx is None:
        from pipeline.aoi import AOI
        from pipeline.shade.simulate import ShadeContext
        _ctx = ShadeContext.from_interim(AOI.load(AOI_NAME))
    return _ctx


# serve the web app from the same origin: http://localhost:8811/
WEB = ROOT / "web"
app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")

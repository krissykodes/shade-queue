"""Heat Vulnerability Index by NTA 2020 (NYC DOHMH Environment & Health Data Portal, indicator 2411).

Values are already quintiles 1–5 (5 = most vulnerable). The EHDP GeoID = county FIPS*10000 + NTA digits
(e.g. BX0101 → 005|0101 → 50101). Boundaries come from NYC Open Data 9nt8-h7nd. Fallback: 4mhf-duep (HVI by ZCTA).
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

from pipeline.aoi import AOI
from pipeline.ingest import socrata

EHDP_URL = "https://raw.githubusercontent.com/nychealth/EHDP-data/production/indicators/data/2411.json"
NTA_ID = "9nt8-h7nd"


def build(aoi: AOI) -> gpd.GeoDataFrame:
    raw = aoi.dir("raw")
    hp = raw / "hvi_nta.json"
    if not hp.exists():
        hp.write_text(requests.get(EHDP_URL, timeout=60).text)
    np_ = raw / "nta2020.json"
    if not np_.exists():
        rows = socrata.query(NTA_ID, aoi.buffered(500).soql_intersects("the_geom"),
                             "nta2020,ntaname,borocode,countyfips,the_geom")
        np_.write_text(json.dumps(rows))
    h = json.loads(hp.read_text())
    hv = pd.DataFrame({"geoid": h["GeoID"], "hvi_quintile": h["Value"]})
    nt = pd.DataFrame(json.loads(np_.read_text()))
    g = gpd.GeoDataFrame(nt.drop(columns="the_geom"), geometry=[shape(x) for x in nt["the_geom"]], crs=4326)
    g["geoid"] = g["countyfips"].astype(int) * 10000 + g["nta2020"].str[2:].astype(int)
    g = g.merge(hv, on="geoid", how="left")
    g.to_parquet(aoi.dir("interim") / "hvi_nta.parquet")
    g.to_parquet(aoi.dir("processed") / "hvi_nta.parquet")
    print(f"[hvi] {len(g)} NTAs: " + ", ".join(f"{r.ntaname}={r.hvi_quintile}" for r in g.itertuples()))
    return g

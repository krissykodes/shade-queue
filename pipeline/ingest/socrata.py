"""NYC Open Data (Socrata SODA 2.x) fetchers, bbox-filtered. IDs verified live 2026-11-14."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from pipeline.aoi import AOI

BASE = "https://data.cityofnewyork.us/resource"

DATASETS = {
    # name: (id, where-builder, select or None)
    "census2015": ("uvpi-gqnh",
                   lambda a: f"latitude between {a.south} and {a.north} AND longitude between {a.west} and {a.east}",
                   # volunteer/steward fields are deliberately not ingested (no personal data)
                   "tree_id,tree_dbh,status,health,spc_latin,spc_common,curb_loc,nta,latitude,longitude"),
    "forms_trees": ("hn5i-inap", lambda a: a.soql_within_box("location"),
                    "objectid,globalid,dbh,tpstructure,tpcondition,genusspecies,planteddate,plantingspaceglobalid,location"),
    "forms_planting_spaces": ("82zj-84is", lambda a: a.soql_within_box("location"),
                              "objectid,globalid,psstatus,pssite,buildingnumber,zipcode,communityboard,plantingspaceonstreet,width,length,jurisdiction,"
                              "overheadutilities,streetname,nta,latitude,longitude,location"),
    "buildings": ("5zhs-2jue", lambda a: a.soql_intersects("the_geom"),
                  "bin,doitt_id,height_roof,ground_elevation,construction_year,feature_code,last_status_type,the_geom"),
    "sidewalks": ("52n9-sdep", lambda a: a.soql_intersects("the_geom"), "the_geom,feat_code,status"),
    "centerline": ("inkn-q76z", lambda a: a.soql_intersects("the_geom"),
                   "physicalid,full_street_name,streetwidth,trafdir,rw_type,segment_type,the_geom"),
}


def query(dataset_id: str, where: str, select: str | None = None, page: int = 50_000) -> list[dict]:
    headers = {}
    if tok := os.environ.get("SOCRATA_APP_TOKEN"):
        headers["X-App-Token"] = tok
    rows, offset = [], 0
    while True:
        params = {"$where": where, "$limit": page, "$offset": offset, "$order": ":id"}
        if select:
            params["$select"] = select
        r = requests.get(f"{BASE}/{dataset_id}.json", params=params, headers=headers, timeout=120)
        r.raise_for_status()
        batch = r.json()
        rows += batch
        if len(batch) < page:
            return rows
        offset += page


def fetch(aoi: AOI, name: str, refresh: bool = False) -> Path:
    ds_id, where, select = DATASETS[name]
    # buildings/streets need shadow context beyond the AOI
    area = aoi.buffered(60) if name in ("buildings", "centerline", "sidewalks") else aoi
    out = aoi.dir("raw") / f"{name}.json"
    if out.exists() and not refresh:
        return out
    rows = query(ds_id, where(area), select)
    out.write_text(json.dumps(rows))
    print(f"[socrata] {name} ({ds_id}): {len(rows)} rows → {out.relative_to(out.parents[3])}")
    return out


def fetch_all(aoi: AOI, refresh: bool = False) -> dict[str, Path]:
    return {n: fetch(aoi, n, refresh) for n in DATASETS}

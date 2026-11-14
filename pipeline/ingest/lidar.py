"""NYC LiDAR tiles from the NYS GIS FTP, selected by intersecting the official tile index.

2021 (Eagleview, flown 12–21 May 2021, 12 pts/m², classes 1–9 incl. 3/4/5 vegetation, 6 buildings)
is the default. 2017 topobathy (3–17 May 2017, ~10.8 first returns/m²) is available too.
"""
from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd

from pipeline.aoi import AOI, DATA

FTP = "ftp://ftp.gis.ny.gov/elevation/LIDAR"
COLLECTIONS = {
    2021: {"dir": "NYC_2021", "index": ["NYC2021_LAS_Index.{}".format(e) for e in ("shp", "shx", "dbf", "prj", "cpg")]},
    2017: {"dir": "NYC_TopoBathymetric2017", "index_zip": "NYC_Topobathy2017_LIDAR_Index.zip",
           "index": ["NYC_Topobathy2017_LIDAR_Index.shp"]},
}
LARGE_BYTES = 2 * 1024**3  # ask-first threshold agreed with the product lead


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=4 * 1024 * 1024)
    tmp.rename(dest)
    return dest


def tile_index(year: int) -> gpd.GeoDataFrame:
    c = COLLECTIONS[year]
    d = DATA / "raw" / "_lidar_index" / str(year)
    d.mkdir(parents=True, exist_ok=True)
    if "index_zip" in c:
        z = _download(f"{FTP}/{c['dir']}/{c['index_zip']}", d / c["index_zip"])
        if not (d / c["index"][0]).exists():
            zipfile.ZipFile(z).extractall(d)
    else:
        for f in c["index"]:
            _download(f"{FTP}/{c['dir']}/{f}", d / f)
    g = gpd.read_file(d / c["index"][0])
    if g.crs is None:  # the 2021 .prj is ESRI-flavoured; it is NY Long Island ftUS
        g = g.set_crs(6539, allow_override=True)
    return g


def tiles_for(aoi: AOI, year: int) -> gpd.GeoDataFrame:
    g = tile_index(year)
    area = gpd.GeoSeries([aoi.geom], crs=4326).to_crs(g.crs).iloc[0]
    return g[g.intersects(area)].copy()


def remote_size(url: str) -> int:
    with urllib.request.urlopen(url, timeout=60) as r:
        return int(r.headers.get("Content-Length") or r.length or 0)


def fetch(aoi: AOI, year: int | None = None, allow_large: bool = False) -> list[Path]:
    year = year or aoi.lidar_year
    hits = tiles_for(aoi, year)
    urls = hits["DIRECT_DL"].tolist()
    out = aoi.dir("raw") / f"lidar_{year}"
    out.mkdir(exist_ok=True)
    todo = [u for u in urls if not (out / Path(u).name).exists()]
    total = sum(remote_size(u) for u in todo)
    print(f"[lidar] {aoi.name} {year}: {len(urls)} tiles, {len(todo)} to fetch, {total/1e9:.2f} GB")
    if total > LARGE_BYTES and not allow_large:
        raise SystemExit(f"Refusing to download {total/1e9:.2f} GB without --allow-large (ask the team first).")
    paths = []
    for u in urls:
        p = _download(u, out / Path(u).name)
        print(f"[lidar]   {p.name} {p.stat().st_size/1e6:.0f} MB")
        paths.append(p)
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="mott_haven")
    ap.add_argument("--year", type=int)
    ap.add_argument("--allow-large", action="store_true")
    a = ap.parse_args()
    fetch(AOI.load(a.aoi), a.year, a.allow_large)

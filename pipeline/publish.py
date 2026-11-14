"""Write processed GeoParquet (EPSG:4326). api/ reads only these files."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from pipeline.aoi import AOI, WGS84
from pipeline.contracts import CrownModel


def crowns_gdf(crowns: list[CrownModel], extra: pd.DataFrame | None = None) -> gpd.GeoDataFrame:
    df = pd.DataFrame([c.model_dump() for c in crowns])
    df["leaf_on_start"] = df["leaf_on_months"].map(lambda t: t[0])
    df["leaf_on_end"] = df["leaf_on_months"].map(lambda t: t[1])
    df = df.drop(columns="leaf_on_months")
    if extra is not None:
        df = df.merge(extra, on="tree_id", how="left")
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=WGS84)


def write(aoi: AOI, name: str, gdf: pd.DataFrame) -> None:
    out = aoi.dir("processed") / f"{name}.parquet"
    if isinstance(gdf, gpd.GeoDataFrame):
        gdf = gdf.to_crs(WGS84)
    gdf.to_parquet(out)
    print(f"[publish] {name}: {len(gdf)} rows → {out.name}")


def crowns_from_frame(df: pd.DataFrame) -> list[CrownModel]:
    """Inverse of crowns_gdf (handles parquet NaN → None)."""
    out = []
    for r in df.to_dict("records"):
        kw = {k: (None if isinstance(r.get(k), float) and r[k] != r[k] else r.get(k))
              for k in CrownModel.model_fields if k in r}
        if "leaf_on_start" in r:
            kw["leaf_on_months"] = (int(r["leaf_on_start"]), int(r["leaf_on_end"]))
        out.append(CrownModel(**kw))
    return out

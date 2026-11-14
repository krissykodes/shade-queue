"""Areas of interest, paths and CRS helpers. Every pipeline step is parameterised by an AOI."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml
from pyproj import Transformer
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

WGS84 = "EPSG:4326"
METRIC = "EPSG:32618"  # UTM 18N, metres; all geometry math happens here
FT = 0.3048


@dataclass(frozen=True)
class AOI:
    name: str
    west: float
    south: float
    east: float
    north: float
    label: str = ""
    lidar_year: int = 2021

    @classmethod
    def load(cls, name: str, path: Path = ROOT / "aois.yaml") -> "AOI":
        cfg = yaml.safe_load(path.read_text())
        if name not in cfg:
            raise KeyError(f"AOI {name!r} not in {path.name}; choose from {sorted(cfg)}")
        c = cfg[name]
        w, s, e, n = c["bbox"]
        return cls(name, w, s, e, n, c.get("label", name), c.get("lidar_year", 2021))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    @cached_property
    def geom(self):
        return box(*self.bbox)

    def buffered(self, metres: float) -> "AOI":
        """Grow the bbox by roughly `metres` (for shadow context outside the AOI)."""
        dlat = metres / 111_320
        dlon = metres / (111_320 * 0.7575)  # cos(40.8°)
        return AOI(self.name, self.west - dlon, self.south - dlat, self.east + dlon,
                   self.north + dlat, self.label, self.lidar_year)

    def dir(self, stage: str) -> Path:
        """data/{raw,interim,processed}/{aoi}/"""
        p = DATA / stage / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # Socrata SoQL helpers (lat/lon order is Socrata's quirk)
    def soql_within_box(self, col: str) -> str:
        return f"within_box({col},{self.north},{self.west},{self.south},{self.east})"

    def soql_intersects(self, col: str) -> str:
        w, s, e, n = self.bbox
        return f"intersects({col},'POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))')"


_to_m = Transformer.from_crs(WGS84, METRIC, always_xy=True)
_to_ll = Transformer.from_crs(METRIC, WGS84, always_xy=True)


def to_metric(lon, lat):
    return _to_m.transform(lon, lat)


def to_lonlat(x, y):
    return _to_ll.transform(x, y)

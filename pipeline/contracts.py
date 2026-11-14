"""Shared data contracts. See ARCHITECTURE.md §3 and docs/adr/0001-contracts.md.

Rule: the shade simulator consumes CrownModel only, never a LiDAR cluster, so measured,
allometric and predicted crowns are interchangeable. Units: metres, degrees clockwise from north.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CrownSource = Literal["lidar", "allometric", "predicted"]
CrownShape = Literal["ellipsoid", "cone", "cylinder", "umbrella"]


class CrownModel(BaseModel):
    tree_id: str
    lon: float
    lat: float
    height_m: float = Field(gt=0, le=60)
    crown_radius_m: float = Field(gt=0, le=25)
    crown_base_m: float = Field(ge=0)
    shape: CrownShape = "ellipsoid"
    species: str | None = None
    source: CrownSource
    as_of_year: int
    confidence: float = Field(1.0, ge=0, le=1)
    leaf_on_months: tuple[int, int] = (5, 10)

    @model_validator(mode="after")
    def _base_below_top(self):
        if self.crown_base_m >= self.height_m:
            raise ValueError(f"crown_base_m ({self.crown_base_m}) must be < height_m ({self.height_m})")
        return self

    def leaf_on(self, month: int) -> bool:
        a, b = self.leaf_on_months
        return a <= month <= b if a <= b else (month >= a or month <= b)


class ShadeResult(BaseModel):
    tree_id: str
    timestamp: datetime
    sun_altitude_deg: float
    sun_azimuth_deg: float
    ground_shade_m2: float = Field(ge=0)
    facade_shade_m2: float = Field(ge=0)
    self_shaded_fraction: float = Field(ge=0, le=1)
    sidewalk_shade_m2: float = Field(ge=0)
    leaf_on: bool = True


class ShadeSummary(BaseModel):
    tree_id: str
    day: date
    usable_sidewalk_shade_hours: float
    mean_ground_shade_m2: float
    mean_sidewalk_shade_m2: float
    public_ground_fraction: float = Field(ge=0, le=1)
    leaf_on: bool = True


class PlantingSite(BaseModel):
    site_id: str
    lon: float
    lat: float
    status: str
    street_width_m: float | None = None
    orientation_deg: float | None = Field(None, ge=0, lt=180)
    nearby_building_heights: list[float] = []
    hvi_quintile: int | None = Field(None, ge=1, le=5)
    shade_deficit_score: float | None = Field(None, ge=0, le=1)

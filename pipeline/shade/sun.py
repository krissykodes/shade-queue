"""Sun position (pvlib NREL SPA, offline) for the scenario timestamps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pvlib

TZ = "America/New_York"
NYC_LAT, NYC_LON = 40.75, -73.95
MIN_ALTITUDE_DEG = 5.0  # below this, shadows run off to infinity and are not "usable" shade

SCENARIO_DAYS = {
    "summer_solstice": date(2026, 6, 21),
    "spring_equinox": date(2026, 3, 20),
    "autumn_equinox": date(2026, 9, 22),
    "winter_solstice": date(2026, 12, 21),
}


@dataclass(frozen=True)
class SunSample:
    timestamp: pd.Timestamp
    altitude_deg: float
    azimuth_deg: float  # clockwise from north


def sun_positions(times: pd.DatetimeIndex, lat: float = NYC_LAT, lon: float = NYC_LON) -> list[SunSample]:
    sp = pvlib.solarposition.get_solarposition(times, lat, lon)
    return [SunSample(t, float(a), float(z))
            for t, a, z in zip(times, sp["apparent_elevation"], sp["azimuth"]) if a >= MIN_ALTITUDE_DEG]


def day_samples(day: date, step_minutes: int = 60, lat: float = NYC_LAT, lon: float = NYC_LON) -> list[SunSample]:
    times = pd.date_range(f"{day} 05:00", f"{day} 20:00", freq=f"{step_minutes}min", tz=TZ)
    return sun_positions(times, lat, lon)


def scenario_samples(days: dict[str, date] | None = None, step_minutes: int = 60) -> list[SunSample]:
    out: list[SunSample] = []
    for d in (days or SCENARIO_DAYS).values():
        out += day_samples(d, step_minutes)
    return out

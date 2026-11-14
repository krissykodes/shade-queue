"""USFS Urban Tree Database allometry (McPherson, van Doorn & Peper 2016; RDS-2016-0005).

We use the *Northeast* region (reference city: Queens, NY, measured 2005) coefficients, vendored
in utd_noeast_coefficients.csv (US government work, public domain). DBH is in cm, lengths in m.

Components: "dbh" (from age), "age" (from dbh), "tree ht", "crown dia", "crown ht" (live crown
length), all from dbh. Unknown species fall back to genus, then to the median over all 21 species.
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

COEF_CSV = Path(__file__).with_name("utd_noeast_coefficients.csv")
COMPONENTS = ("dbh", "age", "tree ht", "crown dia", "crown ht")


@dataclass(frozen=True)
class Eq:
    form: str
    a: float
    b: float
    c: float
    d: float
    e: float
    lo: float  # application range of the *predicted* value
    hi: float

    def __call__(self, x: float) -> float:
        a, b, c, d, e = self.a, self.b, self.c, self.d, self.e
        f = self.form
        mse = c  # for loglog/expow forms, column c holds the MSE correction term
        if f == "lin":
            y = a + b * x
        elif f == "quad":
            y = a + b * x + c * x**2
        elif f == "cub":
            y = a + b * x + c * x**2 + d * x**3
        elif f == "quart":
            y = a + b * x + c * x**2 + d * x**3 + e * x**4
        elif f.startswith("loglogw"):
            core = a + b * math.log(math.log(x + 1))
            w = {"1": 1, "2": math.sqrt(x), "3": x, "4": x * x}[f[-1]]
            y = math.exp(core + w * mse / 2)
        elif f.startswith("expow"):
            core = a + b * x
            w = {"1": 1, "2": math.sqrt(x), "3": x, "4": x * x}[f[-1]]
            y = math.exp(core + w * mse / 2)
        else:
            raise ValueError(f)
        # keep predictions inside a margin of the fitted application range
        return float(min(max(y, self.lo * 0.5), self.hi * 1.25))


def _f(s: str) -> float:
    return float(s) if s.strip() else 0.0


@lru_cache(maxsize=1)
def table() -> dict[str, dict[str, Eq]]:
    out: dict[str, dict[str, Eq]] = {}
    with open(COEF_CSV, newline="") as fh:
        for r in csv.DictReader(fh):
            comp = r["Predicts component "].strip()
            if comp not in COMPONENTS:
                continue
            out.setdefault(r["Scientific Name"].strip(), {})[comp] = Eq(
                r["EqName"].strip(), _f(r["a"]), _f(r["b"]), _f(r["c"]), _f(r["d"]), _f(r["e"]),
                _f(r["Apps min"]), _f(r["Apps max"]))
    return out


def normalise_species(raw: str | None) -> str | None:
    """'Platanus x acerifolia - London planetree' → 'Platanus x acerifolia'; drops cultivars/var."""
    if not isinstance(raw, str) or not raw:
        return None
    s = raw.split(" - ")[0].strip()
    s = re.sub(r"'.*?'", "", s)          # cultivar
    s = re.sub(r"\s+var\..*$", "", s)    # variety
    s = re.sub(r"\s+", " ", s).strip()
    return None if s.lower() in ("unknown", "") else s


def resolve(species: str | None) -> tuple[str, str]:
    """Return (key into table, match level: species|genus|generic)."""
    t = table()
    sp = normalise_species(species)
    if sp:
        if sp in t:
            return sp, "species"
        genus = sp.split()[0]
        for k in t:
            if k.split()[0] == genus:
                return k, "genus"
    return "*", "generic"


def predict(species: str | None, component: str, x: float) -> float:
    key, _ = resolve(species)
    t = table()
    if key == "*":
        return float(np.median([eqs[component](x) for eqs in t.values() if component in eqs]))
    return t[key][component](x)


@dataclass
class Dimensions:
    dbh_cm: float
    height_m: float
    crown_radius_m: float
    crown_base_m: float
    match: str


def dims_from_dbh(species: str | None, dbh_cm: float) -> Dimensions:
    dbh_cm = float(min(max(dbh_cm, 2.5), 150.0))
    h = predict(species, "tree ht", dbh_cm)
    cd = predict(species, "crown dia", dbh_cm)
    ch = predict(species, "crown ht", dbh_cm)
    h = max(h, 2.0)
    ch = min(max(ch, 0.5), h * 0.9)
    base = max(h - ch, 0.3)
    return Dimensions(dbh_cm, h, max(cd / 2, 0.4), base, resolve(species)[1])


def dbh_at_age(species: str | None, age_yr: float) -> float:
    return predict(species, "dbh", max(age_yr, 1.0))


def age_at_dbh(species: str | None, dbh_cm: float) -> float:
    return predict(species, "age", max(dbh_cm, 1.0))

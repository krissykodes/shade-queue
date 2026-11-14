"""Tree size by age and by trunk diameter, from the USDA Forest Service Urban Tree Database.

Source: McPherson, van Doorn & Peper (2016), Urban Tree Database, RDS-2016-0005,
https://www.fs.usda.gov/rds/archive/catalog/RDS-2016-0005 . Table TS6 growth equations for the
Northeast region, whose reference city is Queens, NY (21 street-tree species).
For each species we chain age -> DBH -> tree height, crown diameter, crown height (crown depth),
then take the median across species.

Usage: python tree_sizes.py path/to/TS6_Growth_coefficients.csv   -> data/tree_sizes.json
"""
import csv, json, math, os, statistics as st, sys, collections

AGES = [5, 10, 15, 25]
DBH_GRID = list(range(3, 121, 3))  # cm, for sizing existing trees from inventory DBH


def ev(r, x):
    a, b = float(r["a"]), float(r["b"])
    c, d, e = (float(r[k] or 0) for k in ("c", "d", "e"))
    q = r["EqName"]
    L = lambda: math.log(math.log(x + 1))
    return {
        "lin": lambda: a + b * x, "quad": lambda: a + b * x + c * x * x,
        "cub": lambda: a + b * x + c * x * x + d * x ** 3,
        "quart": lambda: a + b * x + c * x * x + d * x ** 3 + e * x ** 4,
        "loglogw1": lambda: math.exp(a + b * L() + c / 2),
        "loglogw2": lambda: math.exp(a + b * L() + math.sqrt(x) * c / 2),
        "loglogw3": lambda: math.exp(a + b * L() + x * c / 2),
        "loglogw4": lambda: math.exp(a + b * L() + x * x * c / 2),
        "expow1": lambda: math.exp(a + b * x + c / 2),
        "expow2": lambda: math.exp(a + b * x + math.sqrt(x) * c / 2),
        "expow3": lambda: math.exp(a + b * x + x * c / 2),
        "expow4": lambda: math.exp(a + b * x + x * x * c / 2),
    }[q]()


def size_from_dbh(m, dbh):
    H = ev(m[("dbh", "tree ht")], dbh)
    CD = ev(m[("dbh", "crown dia")], dbh)
    CH = min(ev(m[("dbh", "crown ht")], dbh), H)
    return H, CD, CH


def main(path):
    sp = collections.defaultdict(dict)
    for r in csv.DictReader(open(path, encoding="latin-1")):
        if r["Region"] == "NoEast":
            sp[r["Scientific Name"]][(r["Independent variable"], r["Predicts component "].strip())] = r
    need = [("age", "dbh"), ("dbh", "tree ht"), ("dbh", "crown dia"), ("dbh", "crown ht")]
    sp = {k: v for k, v in sp.items() if all(n in v for n in need)}

    def summarize(rows):
        H, CD, CH = (st.median(x[i] for x in rows) for i in range(3))
        return {"height_m": round(H, 2), "crown_dia_m": round(CD, 2),
                "crown_center_m": round(H - CH / 2, 2), "crown_radius_m": round(CD / 2, 2)}

    by_age = {}
    for age in AGES:
        rows, dbhs = [], []
        for m in sp.values():
            dbh = ev(m[("age", "dbh")], age); dbhs.append(dbh)
            rows.append(size_from_dbh(m, dbh))
        by_age[str(age)] = dict(summarize(rows), dbh_cm=round(st.median(dbhs), 1))
    by_dbh = [dict(summarize([size_from_dbh(m, d) for m in sp.values()]), dbh_cm=d) for d in DBH_GRID]
    out = {"source": "USDA FS Urban Tree Database RDS-2016-0005, Northeast region (Queens, NY), "
                     f"median of {len(sp)} species", "species": sorted(sp), "by_age": by_age, "by_dbh": by_dbh}
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/tree_sizes.json", "w"), indent=1)
    for a, v in by_age.items():
        print(a, "yr", v)


if __name__ == "__main__":
    main(sys.argv[1])

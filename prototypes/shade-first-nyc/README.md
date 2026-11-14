# Shade First NYC — NYC GeoAI Hackathon 2026

> The original pit-score prototype. Shade Queue's `pipeline/sites/score.py` ports this method into the full simulator ([ADR-0005](../../docs/adr/0005-pit-score.md)). This folder keeps the standalone version: plain `requests` + `numpy` + `shapely`, a single MapLibre page, and the Queens Village and Central Harlem results quoted in the docs.

Ranks NYC Parks' empty street-tree pits by how much new **sidewalk** shade a tree there would cast
on a July afternoon, so Parks can plant within an HVI-priority ZIP in shade order instead of one undifferentiated pass.
Ranked areas: Central Harlem 10026 (heat impact for 191 W 116th St) and Queens Village 11429.

## Run
From this folder (`prototypes/shade-first-nyc/`):
```
pip install requests numpy shapely
python fetch_data.py                                   # citywide empty pits + HVI -> data/
python tree_sizes.py <path>/TS6_Growth_coefficients.csv  # USDA Urban Tree Database -> data/tree_sizes.json
python shade_score.py 10026 50 10                      # ZIP, top N, default tree age
python shade_score.py 11429 200 10
python build_web.py 10026 11429                        # -> web/data/, web/page.html, web/index.html
python -m http.server 8001 --directory web
```
Open http://localhost:8001. Edit `web/page.src.html` (not page.html or index.html), then rerun `build_web.py`.
Urban Tree Database: https://www.fs.usda.gov/rds/archive/catalog/RDS-2016-0005 (1.1 MB zip, file `Data/TS6_Growth_coefficients.csv`).

## Numbers (pulled Nov 14 2026)
- 136,027 Street pits with `psstatus = Empty`. **52,521 (39%)** have the placeholder coordinate
  (-77.52, 40.11, Pennsylvania); 83,506 map inside NYC. ZIP-level counts from the `zipcode` field include them.
- **10026 Central Harlem:** HVI 5, 445 empty pits (20% of street pits), 91 placed from address. 10-year trees:
  top 50 = 37% of the ZIP's possible new sidewalk shade (unranked: 11%), 3.3× per tree, about 9,600 sq ft of
  sunny sidewalk shaded 2–4 pm. 257 empty pits lie within a 5-minute walk (¼ mile) of 191 W 116th St; 25 are in the top 50.
- **11429 Queens Village:** HVI 5, 1,856 empty pits (35%), 185 placed from address. 10-year trees: top 200 = 22% (unranked 11%), 2.0×.

## Shade model (shade_score.py)
- Tree size by years after planting from the USDA Forest Service Urban Tree Database, Northeast region
  (reference city Queens, NY), median of 21 species:

  | Years | Height | Crown across | Shadow area |
  |---|---|---|---|
  | 5 | 17 ft | 11 ft | ~98 sq ft |
  | 10 | 22 ft | 16 ft | ~206 sq ft |
  | 15 | 28 ft | 21 ft | ~340 sq ft |
  | 25 | 35 ft | 25 ft | ~504 sq ft |
- Sun: NOAA solar position, July 15, 14:00–16:00 EDT every 30 min. The crown's shadow sits
  crown_center / tan(sun elevation) from the trunk and is checked at 17 spots (centre + two 8-point rings).
- A spot counts if it lands on Planimetric sidewalk (`52n9-sdep`), outside building shadow (ray-cast
  against Building Footprints `5zhs-2jue` roof heights) and outside existing street-tree shadow
  (Forestry Tree Points `hn5i-inap`, sized from inventory DBH with the same database).
- Shade yield = share of spots that count (0–1). Sq ft shaded = yield × shadow area (the average
  sunny-sidewalk area kept shaded over the window). HVI used as published; no demographic inputs.
- Checks (`data/checks_<ZIP>.json`, 10-year tree): 49 spots instead of 17 keeps 98% (Harlem) / 93% (Queens)
  of the top pits; widening to 12:00–18:00 keeps 70% / 62%; across ages 5–25, 86%+ (Harlem) / 67%+ (Queens).
- Limits: flat terrain, one typical species, viability inspections (`4pt5-3vv4`) not yet joined,
  191 W 116th St placed approximately (-73.9523, 40.8033) from neighbouring addresses.

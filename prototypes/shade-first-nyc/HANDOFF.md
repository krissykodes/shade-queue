# Shade First NYC — handoff (NYC GeoAI Hackathon 2026, Sat Nov 14 2026)

Kristin's civic hackathon project. Goal: show NYC Parks which empty street-tree pits to plant first for maximum pedestrian shade, a site-level ranking that sits inside Parks' existing HVI-ordered program. The deliverable is a working map, and it is built.

## Status: done and working (version 2)

- **Hosted map (private until shared from its Share menu):** https://claude.ai/artifact/SdvNdgD89Ck4saeuDYe4we
- **Local:** from the project folder, run `python3 -m http.server 8001 --directory web` and open http://localhost:8001. Run it from the project folder: started from `~` it serves 404s.
- Checked in a browser at desktop width in light mode and earlier at phone width: all steps, both ZIPs, tree-age switch, address picks, pit popup, 3D. Not yet checked: the hosted version 2 in a visible browser.

## The map (3-step story = the slide flow)

1. **Heat risk:** HVI choropleth by ZIP, plus counts of mapped empty pits per HVI level.
2. **Empty pits:** all 83,506 mappable empty street pits, with an "HVI at least" filter, plus a note on the placeholder-coordinate problem.
3. **Rank in a ZIP:** switch between **Central Harlem 10026** (default) and **Queens Village 11429**.
   - **"Heat impact for 191 West 116th Street"** box (Harlem only): purple pin plus a dashed ¼-mile (5-minute walk) circle; how many empty pits are nearby and how many are in the ZIP's top N; total sidewalk shade if all of them were planted; the 4 best nearby pits (click to fly there).
   - **Tree age selector (5 / 10 / 15 / 25 years)** with a plain-language line, e.g. "about 22 ft tall (roughly 2 storeys), crown 16 ft across, shadow about 206 sq ft, about 1.3 parking spaces."
   - "Plant the top N" slider (default 50 in Harlem, 200 in Queens), with stats in sq ft and parking spaces, a cumulative-shade curve ("best pits first" vs "no particular order"), toggles for 3D buildings, sidewalks and top-only.
   - **"Reading the numbers"** box explaining shade yield, sq ft shaded (a parking space ≈ 160 sq ft) and tree age in plain words.
   - Pit popup: rank, yield, sq ft shaded, a plain-language sentence, 2–4 pm bars, distance from 191 W 116th St, and the five shadow discs drawn at the selected tree age.

Built with MapLibre GL 4.7.1 and no basemap tiles, because the artifact sandbox blocks tile servers. HVI polygons, sidewalks and building footprints act as the base map.

## Key numbers (pulled live from NYC Open Data, Nov 14 2026)

| | |
|---|---|
| Empty street pits (`psstatus=Empty`, `pssite=Street`) | **136,027** (156,197 if park pits are included) |
| With the Pennsylvania placeholder coordinate (-77.52, 40.11) | **52,521 (39%)**. The earlier ~20% estimate was wrong. |
| Mappable inside NYC | **83,506** |
| Mapped pits by HVI 1/2/3/4/5 | 9,017 / 13,653 / 16,518 / 21,621 / 21,021 (plus 1,676 in ZIPs with no HVI) |

**Central Harlem 10026** (HVI 5, 445 empty pits, 20% of street pits; 91 placed from street address):

| Tree age | Top 50 share of possible new sidewalk shade | Sidewalk shaded by top 50, 2–4 pm |
|---|---|---|
| 5 yr | 36% | ~4,850 sq ft |
| 10 yr | 37% (unranked: 11%, so **3.3×** per tree) | ~9,600 sq ft (≈59 parking spaces) |
| 25 yr | 38% | ~17,800 sq ft |

- About 35% of Harlem pits score zero: their shadow falls where buildings (up to 125 m tall) or existing trees already shade, or off the sidewalk.
- **191 W 116th St:** 257 empty pits within ¼ mile; 25 are in the ZIP's top 50. Planting all 257 shades about 13,500 sq ft at 10 years. The closest top pick is 141 W 116th St (#11, 268 ft away, yield 0.98). Top pit in the ZIP: 241 Central Park North.

**Queens Village 11429** (HVI 5, 1,856 empty pits, 35% vacant; 185 placed from address): at 10 years, top 200 = 22% (unranked 11%, **2.0×**), ~31,000 sq ft (≈191 parking spaces).

The ZIP-level counts in the original brief (HVI1 19,719 … HVI5 33,628) come from the `zipcode` field. They include unmappable records, so don't describe them as "on the map."

## Shade model (`shade_score.py`)

The question it answers: if this pit is planted, how much of the new tree's afternoon shadow lands on sidewalk that is sunny today?

- **Tree size by age** comes from the USDA Forest Service Urban Tree Database (McPherson et al. 2016, RDS-2016-0005). It uses the Northeast region growth equations, whose reference city is Queens, NY; we chain age → trunk diameter → height, crown width, crown depth and take the median of 21 species (`tree_sizes.py` → `data/tree_sizes.json`). Ages are years after planting.

  | Years | Height | Crown across | Crown center height | Shadow area |
  |---|---|---|---|---|
  | 5 | 17 ft (5.3 m) | 11 ft | 3.5 m | ~98 sq ft |
  | 10 | 22 ft (6.9 m) | 16 ft | 4.4 m | ~206 sq ft |
  | 15 | 28 ft (8.4 m) | 21 ft | 5.4 m | ~340 sq ft |
  | 25 | 35 ft (10.7 m) | 25 ft | 6.8 m | ~504 sq ft |

  The original version used one "mature" size (8 m crown center, 4 m radius), close to the 25-year size. **The default is now 10 years**, about the age by 2035, the end of Parks' current planting cycle.
- **Sun:** NOAA solar position, July 15, 2:00–4:00 pm EDT every 30 minutes (azimuth 217°→257°, elevation 67°→48°). The window came from the original brief.
- **Sampling:** each shadow is checked at 17 spots per time step (center plus two 8-point rings at 50% and 95% of crown radius), which gives 85 checks per pit.
- **A spot counts** only if all of these hold:
  - it is on **sidewalk** (Planimetric `52n9-sdep`)
  - it is outside **building shadow** (ray cast toward the sun against Building Footprints `5zhs-2jue` roof heights)
  - it is outside the shadow of an **existing street tree** (Forestry Tree Points `hn5i-inap`, sized from inventory DBH with the same Urban Tree Database equations)
- **Shade yield** = share of spots that count (0–1). **Sq ft shaded** = yield × shadow area, which is the average sunny-sidewalk area kept shaded over 2–4 pm.
- **Robustness checks** (`data/checks_<ZIP>.json`, 10-year tree):

  | | Harlem (top 50) | Queens (top 200) |
  |---|---|---|
  | 49 spots instead of 17: top pits unchanged | 98% | 93% |
  | Window 12–6 pm instead of 2–4 pm | 70% | 62% |
  | Tree age 5, 15 or 25 vs. 10 | 86–94% | 67–81% |

  So the sampling is not a concern; the choice of hours matters most. In Queens, young and old trees favor somewhat different pits.
- Rubric guardrails are met: no demographic inputs, HVI used only as published.

**Limits to state:** flat terrain, one typical species, no awnings or scaffolding, pit viability inspections (`4pt5-3vv4`) not yet joined. 191 W 116th St is placed approximately (-73.9523, 40.8033) from neighboring addresses: PLUTO and GeoSearch don't list it on its own, probably because it's part of a corner lot on Adam Clayton Powell Jr. Blvd.

## Files (project folder)

- `fetch_data.py` → `data/empty_pits.geojson`, `data/hvi_zcta.geojson`, `data/summary.json`
- `tree_sizes.py <TS6_Growth_coefficients.csv>` → `data/tree_sizes.json`. The 1.1 MB Urban Tree Database zip was downloaded to a temporary folder; get it again from https://www.fs.usda.gov/rds/archive/catalog/RDS-2016-0005 if needed.
- `shade_score.py ZIP TOP_N DEFAULT_AGE` → `data/shade_<ZIP>.geojson` (per pit: `s5..s25` yield, `r5..r25` rank, `m5..m25` m²·h, `t5..t25` per-time), `data/shade_<ZIP>_stats.json`, `data/checks_<ZIP>.json`, `data/buildings_<ZIP>.geojson`, `data/sidewalks_<ZIP>.geojson`
- `build_web.py 10026 11429` → `web/data/*.json` (~13 MB) and builds `web/page.html` (the published artifact) and `web/index.html` from **`web/page.src.html`** (edit this one) plus `web/vendor/maplibre-gl.css`
- `README.md` has the run steps and method. `.claude/launch.json` holds the preview server config (port 8765).

Full rebuild:
```bash
python3 fetch_data.py && python3 tree_sizes.py <path>/TS6_Growth_coefficients.csv && python3 shade_score.py 10026 50 10 && python3 shade_score.py 11429 200 10 && python3 build_web.py 10026 11429
```

## Gotchas

- Anaconda's stale `certifi` breaks `requests` SSL. The scripts set `REQUESTS_CA_BUNDLE` from `ssl.get_default_verify_paths()`.
- `zipcode` in `82zj-84is` is text like `"11429.0"`. Use `starts_with(zipcode,'11429')`. Grouped Socrata queries can't use `$order=:id`.
- MapLibre 4 applies an inline style on an animation frame, so a hidden browser tab never draws the map. To test headless, temporarily replace `requestAnimationFrame` with a timer.
- Don't set `position` on a MapLibre marker element: it breaks marker placement.
- Map data is the Nov 14 snapshot. To refresh it, rerun the scripts and republish `web/page.html` with its `data/` files.

## Possible next steps

1. Join viability inspections (`4pt5-3vv4`) to drop unplantable pits.
2. Weight the ranking across several HVI-5 ZIPs by HVI for a cross-ZIP equity view (HVI is the published index, so this stays within the rubric).
3. Build slides: HVI map → pit map → 191 W 116th St heat impact → ranked pits + curve. Pitch: "Parks plants all 445 pits in 10026 in one pass; the best 50 give 37% of the new sidewalk shade, 3.3× per tree." Novelty vs. Cornell Tree Folio: they model existing trees; this scores the empty pits Parks already tracks. Feasibility: Parks keeps its process and only sorts within a ZIP.

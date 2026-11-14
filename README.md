# Shade Queue 🌳

**Where does NYC's street-tree shade actually fall, and where should Parks plant next?**

**Live demo:** https://krissykodes.github.io/shade-queue/, with Central Harlem around 191 W 116th St and Mott Haven (Bronx).

Shade Queue is an open, extensible rebuild of the core of
[TreeFolio NYC](https://www.treefolio.org/), made entirely from public data. It gives each
street tree a 3D crown model, measured from LiDAR or estimated from trunk diameter, and simulates
the shade that crown casts, hour by hour, against the real buildings around it.

![LiDAR vs allometry](docs/figures/lidar_vs_allometric.png)

| Stage | Status |
|---|---|
| **v0** Per-tree crowns + shade simulation + web map | ✅ Harlem (W 116th St) and Mott Haven |
| **v1** Rank empty tree pits by the new sidewalk shade a tree would add | ✅ ported from Shade First NYC ([ADR-0005](docs/adr/0005-pit-score.md)) |
| **v2** Recommend species, simulate their shade at 5/10/15 years | ✅ 6 species × 3 ages per pit in the map; species recommendation logic is next |

## Quick start

Needs [uv](https://docs.astral.sh/uv/). Python 3.12 and all dependencies install automatically.

```bash
make setup                      # create .venv
make data                       # fetch NYC Open Data for AOI=harlem_116, simulate shade, score pits
make lidar                      # optional: ~2.4 GB LiDAR download, then measured crowns (re-runs shade + pits)
make preview                    # export the static site and open http://127.0.0.1:8811
make deploy                     # publish site/ to GitHub Pages (gh-pages branch)
make serve                      # optional FastAPI with /simulate for any species/location (docs at /docs)
make test
```

Every command takes `AOI=<name>` from [`aois.yaml`](aois.yaml), so adding a neighbourhood
means adding a bounding box there. `SITE_AOIS="harlem_116 mott_haven"` controls which areas `make site` / `make deploy` publish.

**Coming back later:** the code is on `main`, and the published site is a single commit on `gh-pages`.
Raw data isn't in git. `make data AOI=… && make lidar AOI=… && make deploy` rebuilds everything from public sources.

## What you see

- **3D crowns** coloured by where they came from: green = LiDAR, olive = allometric (from DBH),
  orange = predicted (a hypothetical planting).
- **Shadows** for any hour on the solstices and equinoxes. Press ▶ to animate the day.
- **Click a tree** to see its height, crown, data confidence, and hourly sidewalk shade, net of
  shade the buildings already provide.
- **Planting queue**: empty pits ranked by new sidewalk shade. Slide "plant the top N" to see
  what share of the area's possible new shade those pits deliver, compared with planting in no particular order.
- **Click an orange empty pit** to pick a species and see its predicted crown, its shadow at the
  current time, and new shade at 5, 10 and 15 years, all from the *same* simulator.
- **Heat vulnerability** overlay (DOHMH HVI by neighbourhood). The whole pilot area is HVI 5/5.

## How it works

```
NYC Open Data ─┐
NYS LiDAR ─────┼─ ingest/ ─► canopy/ ─► CrownModel ─► shade/ ─► ShadeResult ─► GeoParquet ─► api/ ─► web/
USFS UTD ──────┘                ▲                                   │
                       growth/ (species × years → predicted crown) ─┘
```

- **Crowns from LiDAR**: we build a canopy-height model from the 2021 NYC LiDAR, then segment it
  into individual crowns with a watershed *seeded by the Parks tree inventory points*, so every
  crown links to a Parks tree ID ([ADR-0003](docs/adr/0003-inventory-seeded-segmentation.md)).
- **Crowns from allometry**: USFS Urban Tree Database equations (McPherson et al. 2016) whose
  Northeast coefficients were measured on Queens street trees. These fill in trees LiDAR misses
  (171 were planted after the 2021 flight) and drive the growth predictions.
- **Shade**: pvlib computes the sun position. Each crown's shadow is the convex hull of its
  projected horizontal slices, and each building's shadow is its footprint swept along the sun
  vector. 1,549 trees × 44 sun positions take about 40 s
  ([ADR-0002](docs/adr/0002-projected-shadows.md)).
- **Contracts first**: the simulator only accepts `CrownModel`, so measured, estimated and
  predicted trees are interchangeable ([ADR-0001](docs/adr/0001-contracts.md)).

Read [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries and [plan.md](plan.md) for today's checklist.

## The pit score in one paragraph

For each empty street pit, we "plant" a tree (a London plane at 10 years by default) and simulate
its shadow on a July afternoon (2–4 pm). Only shadow that falls on **sidewalk that is sunny today**
counts: not already shaded by a building, and not already shaded by an existing street tree.
**New shade (m²·h)** is that area averaged over the window × 2 hours. Pits are ranked by it.
**Yield** is the share of the tree's shadow that is new shade. Heat vulnerability is shown as
published and not mixed in, so the ranking slots into Parks' existing HVI-first process.
Method: Kristin's *Shade First NYC* prototype, rebuilt on Shade Queue's species-and-age crowns and
full shadow polygons ([ADR-0005](docs/adr/0005-pit-score.md)).

## Repo map

| Path | What |
|---|---|
| `pipeline/contracts.py` | Data contracts (start here) |
| `pipeline/ingest/` | Socrata, LiDAR, buildings, streets/sidewalks, HVI |
| `pipeline/canopy/` | `extract.py` (LiDAR crowns), `fallback.py` (allometric crowns) |
| `pipeline/growth/` | UTD allometry + `predict_crown()` for plantings |
| `pipeline/shade/` | sun, shadow geometry, simulator, daily metrics |
| `pipeline/sites/` | empty-pit discovery (incl. placeholder recovery) + `score.py` |
| `pipeline/export.py` | static site export (`site/`, deployed to GitHub Pages) |
| `api/main.py` | FastAPI + DuckDB spatial over `data/processed/` |
| `web/` | static deck.gl + MapLibre page that reads exported files; no build step, no server |
| `docs/adr/` | decision records |

## Data sources (all public; verified live 2026-11-14)

| Data | Source |
|---|---|
| Street trees (live) | NYC Parks ForMS *Forestry Tree Points* `hn5i-inap` |
| Empty planting sites | ForMS *Forestry Planting Spaces* `82zj-84is` (`psstatus = Empty`); placeholder locations geocoded with NYC Planning GeoSearch |
| Sidewalks | NYC Planimetric *Sidewalk* `52n9-sdep` |
| 2015 Street Tree Census | `uvpi-gqnh` (ingested for reference) |
| Building footprints + roof heights | `5zhs-2jue` (formerly `qb5r-6dgf`) |
| Street centerlines + widths | `inkn-q76z` |
| Neighbourhoods (NTA 2020) | `9nt8-h7nd` |
| Heat Vulnerability Index | NYC DOHMH EH Data Portal, indicator 2411 (by NTA) |
| LiDAR | NYS GIS Clearinghouse, NYC 2021 (12 pts/m², flown May 2021) |
| Allometry | USFS Urban Tree Database, RDS-2016-0005 (Northeast / Queens) |

Raw and processed data live in `data/` (gitignored). The pipeline re-downloads everything.

## Limitations (v0)

Crowns are opaque solids. Existing trees don't shade each other in the per-tree metrics (the pit
score does account for existing tree shade). Façade shade is approximate. Pit viability inspections
(`4pt5-3vv4`) are not joined yet. Terrain is treated as flat. In LiDAR,
a sapling next to a large tree can be mislinked to its neighbour's crown; `confidence` flags
these. Details are in the ADRs.

## Ethics

Public city data only. The unit of analysis is a tree or a planting pit, never a person. We
don't ingest census volunteer or steward fields, and we use heat vulnerability only at
neighbourhood level.

## Credits

The pit score comes from **Shade First NYC** (Kristin, NYC GeoAI Hackathon 2026). Inspired by
TreeFolio NYC (Cornell Design Across Scales Lab). This is an independent rebuild
from public inputs and is not affiliated with TreeFolio.

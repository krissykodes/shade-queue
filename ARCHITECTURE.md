# Shade Queue: Architecture

Shade Queue rebuilds the core of [TreeFolio NYC](https://www.treefolio.org/) from
public data: a per-tree 3D canopy model plus a shade simulation. It is built to
grow, in three stages:

| Stage | What | Status |
|---|---|---|
| **v0** | Per-tree crown models and shade simulation for one pilot area, shown on a web map | today |
| **v1** | Find **empty tree pits** and rank them by shade deficit × heat vulnerability | stub today |
| **v2** | For each empty pit, recommend a species and stock size, and simulate its shade at **5 / 10 / 15 years** | stub today |

The one rule that keeps v1 and v2 from forcing a rewrite: **the shade simulator
only ever sees a `CrownModel`.** It never sees a LiDAR point cluster. A crown
measured from LiDAR, a crown estimated from trunk diameter, and a crown predicted
for a tree that hasn't been planted yet all go through exactly the same code.

```
            ┌──────────── measured ─────────────┐
LiDAR ──► canopy/ ──┐                            │
                    ├──► CrownModel ──► shade/ ──► ShadeResult ──► publish ──► api/ ──► web/
DBH ──► allometry ──┘        ▲                   │
                             │                   │
species+years ──► growth/ ───┘  (predicted)      │
                                                 ▼
ForMS empty pits ──► sites/ ──► PlantingSite (shade_deficit_score, hvi_quintile)
```

---

## 1. Repo layout

```
shade-queue/
  aois.yaml              named bounding boxes (pilot: mott_haven)
  Makefile               make setup | make data AOI=… | make api | make web | make test
  pyproject.toml         uv-managed, Python 3.11
  data/                  gitignored
    raw/{aoi}/           untouched downloads (LAS, Socrata JSON)
    interim/{aoi}/       cleaned and reprojected, intermediate rasters
    processed/{aoi}/     GeoParquet: the only thing api/ reads
  pipeline/
    __main__.py          python -m pipeline run --aoi mott_haven [--steps ingest,canopy,shade,publish]
    contracts.py         pydantic models (§3): the source of truth
    aoi.py               AOI/bbox loading, CRS helpers
    ingest/              socrata.py lidar.py buildings.py streets.py hvi.py
    canopy/              ground.py segment.py fit.py link.py fallback.py
    growth/              allometry.py (UTD equations), predict.py (stub)
    shade/               sun.py geometry.py simulate.py metrics.py
    sites/               discover.py score.py (stubs)
    publish.py           processed GeoParquet → web-ready GeoJSON / (later) PMTiles
  api/                   FastAPI app, reads processed/ via DuckDB spatial
  web/                   static: index.html + main.js (deck.gl + MapLibre via CDN, no build step)
  docs/adr/              architecture decision records
  notebooks/             exploration only; nothing imports from here
  tests/
```

## 2. Spatial conventions

- **Input/output CRS:** EPSG:4326 (lon/lat) in every contract and every API response.
- **Compute CRS:** EPSG:32618 (UTM 18N, metres) for all geometry math. The LiDAR
  2017 data is in EPSG:6539 (NY Long Island, US feet) and building heights are in
  feet; ingest converts **everything to metres** on the way in.
- **Bbox everywhere:** every step takes an `AOI(name, west, south, east, north)`.
  Socrata queries use `within_box()` / `intersects()`; LiDAR tiles are chosen by
  intersecting the official tile index. The shade step reads a **buffered** bbox
  (default 60 m) so that buildings just outside the AOI still cast shadows onto
  trees inside it.

## 3. Contracts (`pipeline/contracts.py`)

These are defined before any other code, and changing them requires an ADR.
All lengths are in metres and all angles are in degrees clockwise from north.

```python
CrownSource = Literal["lidar", "allometric", "predicted"]
CrownShape  = Literal["ellipsoid", "cone", "cylinder", "umbrella"]

class CrownModel(BaseModel):
    tree_id: str             # ForMS globalid, census tree_id, or site_id for predicted
    lon: float; lat: float   # trunk / crown centre
    height_m: float          # top of crown above ground
    crown_radius_m: float    # horizontal radius (circular in v0)
    crown_base_m: float      # bottom of live crown above ground
    shape: CrownShape
    species: str | None      # latin binomial, normalised
    source: CrownSource      # "allometric" = fallback from DBH (flagged in UI)
    as_of_year: int          # LiDAR flight year, census year, or planting_year + N
    confidence: float = 1.0  # 0–1; segmentation/link quality or model uncertainty
    leaf_on_months: tuple[int, int] = (5, 10)  # deciduous default; evergreen = (1, 12)

class ShadeResult(BaseModel):
    tree_id: str
    timestamp: datetime          # tz-aware, America/New_York
    sun_altitude_deg: float; sun_azimuth_deg: float
    ground_shade_m2: float       # tree shadow on open ground (not on buildings)
    facade_shade_m2: float       # tree shadow intercepted by building walls/roofs
    self_shaded_fraction: float  # share of the tree's ground shadow already in building shadow
    sidewalk_shade_m2: float     # ground shadow ∩ sidewalk polygon, minus building shadow
    leaf_on: bool                # False for deciduous crowns outside leaf_on_months
    # v0 also writes the shadow polygon itself (WKB) in the GeoParquet row, for the map

class ShadeSummary(BaseModel):   # one row per tree per scenario day; drives the UI and ranking
    tree_id: str; day: date
    usable_sidewalk_shade_hours: float   # hours with sidewalk_shade_m2 ≥ threshold (default 5 m²)
    mean_ground_shade_m2: float; mean_sidewalk_shade_m2: float
    public_ground_fraction: float        # shadow on public ground ÷ total shadow

class PlantingSite(BaseModel):
    site_id: str                 # ForMS planting space globalid
    lon: float; lat: float
    status: str                  # ForMS psstatus, e.g. "Empty"
    street_width_m: float | None
    orientation_deg: float | None        # bearing of nearest centerline segment, 0–180
    nearby_building_heights: list[float] # heights (m) of buildings within 30 m, by side
    hvi_quintile: int | None             # 1–5, from DOHMH HVI by NTA2020
    shade_deficit_score: float | None    # v1: 0–1, higher = needs shade more
```

`ShadeResult` is pure numbers, so it can be compared across sources. Shadow polygons
are stored alongside it in GeoParquet, never in the contract itself.

## 4. Modules

### ingest/
One function per source, `fetch(aoi) -> Path`. Every fetch is idempotent: if the
raw file exists it is skipped, and `--refresh` forces a new download.

| File | Source (verified live 2026-11-14) | Notes |
|---|---|---|
| `socrata.py` | NYC Open Data SODA: `uvpi-gqnh` (2015 census), `hn5i-inap` (ForMS Tree Points), `82zj-84is` (ForMS Planting Spaces) | paged `$limit/$offset`; app token optional via env `SOCRATA_APP_TOKEN` |
| `buildings.py` | `5zhs-2jue` Building Footprints (`height_roof`, `ground_elevation` in ft) | brief's `qb5r-6dgf` is retired |
| `streets.py` | `inkn-q76z` Centerline (`streetwidth`, `trafdir`) | orientation = segment bearing |
| `hvi.py` | DOHMH EH Data Portal indicator 2411 (HVI by NTA2020, GitHub `nychealth/EHDP-data`) + `9nt8-h7nd` NTA boundaries; fallback `4mhf-duep` (HVI by ZCTA) | |
| `lidar.py` | NYS FTP `ftp.gis.ny.gov/elevation/LIDAR/NYC_2021/` and `…/NYC_TopoBathymetric2017/`, tiles selected via the index shapefile | **refuses to download >2 GB without `--allow-large`** |

`terravide` (PyPI 0.1.6, MIT) gets evaluated as an optional backend for `lidar.py`
behind the same `fetch(aoi)` interface. We don't depend on it.

### canopy/  (LiDAR → `CrownModel`)
1. `ground.py`: build a ground model (DTM) from class 2 returns, and a surface model
   (DSM) from first returns. Their difference is the height above ground (nDSM), at 0.5 m resolution.
2. Mask out building footprints (buffered 1 m) and anything under 3 m tall, which
   leaves candidate canopy.
3. `segment.py`: **inventory-seeded marker watershed**. Local maxima of the
   smoothed nDSM are merged with ForMS tree points as seeds, then a watershed
   splits the canopy into individual crowns. This is the GeoAI step: the official
   inventory acts as a weak label on the point cloud. If time allows, compare it
   against an unseeded version.
4. `fit.py`: for each crown, height = 99th percentile of z, radius = √(area/π),
   base = 10th percentile of the canopy points' z, and shape is classified from the
   vertical profile of the points.
5. `link.py`: one-to-one match between crowns and ForMS/census points (Hungarian
   assignment on distance, max 6 m). Confidence comes from the match distance and
   how well DBH agrees with the allometry. Crowns left unmatched are kept with
   `tree_id = "lidar:<n>"`.
6. `fallback.py`: **`source="allometric"`**. For every inventory tree without a LiDAR
   crown (or for all of them if LiDAR is cut), predict height, crown radius and crown
   base from DBH and species using `growth/allometry.py`.

### growth/  (species × age → `CrownModel`)
- `allometry.py`: USFS Urban Tree Database equations (McPherson, van Doorn & Peper
  2016, RDS-2016-0005). The UTD's **Northeast reference city is Queens, NY**, so its
  coefficients come from trees measured in NYC. Covers age → DBH, DBH → height,
  DBH → crown diameter and DBH → crown height, by species, with UTD's own equation
  forms. Species that aren't covered fall back to genus, then to a generic broadleaf.
- `predict.py` (stub today): `predict_crown(species, stock_caliper_in, years, lon, lat) -> CrownModel(source="predicted", as_of_year=now+years)`.
  The v0 fallback uses the same allometry, so v2 reuses tested code.

### shade/  (`CrownModel` + buildings + sun → `ShadeResult`)
- `sun.py`: pvlib solar position (NREL SPA, offline) for lat 40.7, America/New_York.
  The default scenario set is **summer solstice, both equinoxes and the winter
  solstice, hourly from sunrise+1h to sunset−1h.** The heat-relevant metrics only use
  timestamps inside `leaf_on_months`. Winter is computed but flagged leaf-off.
- `geometry.py`: the crown is treated as a solid (ellipsoid/cone/…) and sliced into
  horizontal discs. Each disc at height *z* is projected onto the ground, shifted by
  *z* / tan(altitude) away from the sun. The union of those projections is the
  shadow. The trunk is ignored. Buildings are extruded footprints, and their shadow
  is the union of footprint ∪ projected roof, using the same projection.
- `simulate.py`: `simulate(crowns, buildings, sidewalks, timestamps) -> list[ShadeResult]`.
  A vectorised shapely 2 implementation with an STRtree so each tree only checks
  nearby buildings. The math for one timestamp is shared across all trees. Target:
  ~2k trees × ~50 timestamps in under 2 minutes on a laptop.
- `metrics.py`: produces `ShadeSummary` from the per-hour results.
  - *Facade shade*: the part of the tree's projected shadow that lands inside a
    building footprint. In reality that shadow stops on the wall (or roof); in v0 we
    count the clipped area as facade shade. This is documented as an approximation.
  - *Sidewalk*: v0 approximates it as a 4.5 m band outside the curb, using
    centerline ± streetwidth/2, minus building footprints. The NYC planimetric
    sidewalk layer can replace it later behind the same function.

### sites/  (stub today)
- `discover.py`: ForMS Planting Spaces with `psstatus == "Empty"` become
  `PlantingSite` records (verified: 194 empty sites in the pilot bbox), enriched
  with street width, orientation, nearby building heights and HVI quintile.
- `score.py`: `shade_deficit_score` = shade the site *gets now* (building shadow plus
  existing tree shadow at its location) vs the shade it *could* get. Weighted by HVI.
  v2 runs `predict_crown` → `simulate` for each site × candidate species × {5,10,15} years.

### publish.py → api/ → web/
- Processed layout: `data/processed/{aoi}/{crowns,shade,shade_summary,buildings,sidewalks,sites}.parquet`
  (GeoParquet 1.1, EPSG:4326).
- **api/** (FastAPI, DuckDB + `spatial`, read-only):
  - `GET /trees?bbox=` → crowns as GeoJSON
  - `GET /trees/{id}` → crown + summary
  - `GET /trees/{id}/shade?date=YYYY-MM-DD` → hourly ShadeResults + shadow polygons
  - `GET /shadows?bbox=&timestamp=` → all shadow polygons for one time step (drives the time slider)
  - `GET /buildings?bbox=`
  - `GET /sites?bbox=&min_score=` → PlantingSites (empty until v1)
  - `POST /simulate {species, years, lon, lat}` → runs predict → simulate live, returns ShadeResults (stubbed until v2, but wired so it runs the same simulator on an allometric crown)
- **web/**: a single static page that loads deck.gl and MapLibre from a CDN, with
  CARTO Positron basemap tiles, so no token is needed. Layers:
  - extruded buildings (`PolygonLayer`)
  - crowns as scaled ellipsoids (`SimpleMeshLayer`), coloured by `source`, with
    allometric crowns hatched or greyed
  - shadow polygons for the current time step
  - a time slider (date preset × hour)
  - a click-a-tree panel: species, dimensions, source/confidence, a shade-hours chart

  GeoJSON is fine at pilot scale (~2k trees). Citywide moves to PMTiles behind the
  same endpoints.

## 5. Decisions & rationale (ADR stubs in `docs/adr/`)
- **ADR-0001 Contracts first.** The simulator consumes `CrownModel` only, so measured,
  estimated and predicted crowns are interchangeable.
- **ADR-0002 2.5-D projected shadows, not ray tracing.** This is accurate enough for
  footprint-level shade and fast enough to run citywide. Known limits: no transparency
  or leaf density (crowns are opaque; a porosity factor is a later option), no terrain
  slope, and facade shade is approximate.
- **ADR-0003 Inventory-seeded segmentation.** We use the ForMS points as seeds rather
  than unsupervised crown detection, because the output must link to Parks tree IDs anyway.
- **ADR-0004 LiDAR year.** We use whichever of 2017/2021 is leaf-on in the pilot area,
  to be confirmed from the flight reports, and record it as `as_of_year`.

## 6. Data ethics
Public, aggregate city data only. No personal data. We don't ingest the census
volunteer fields (`user_type`, `steward`). HVI is used at NTA level only. We make no
predictions about identifiable people or households; the unit of analysis is a tree
or a planting pit.

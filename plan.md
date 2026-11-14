# plan.md: Hackathon day, 2026-11-14

> **Status (afternoon):** the walking skeleton and the LiDAR crowns are both done (tags `v0-skeleton`, then `main`).
> 1,044 LiDAR crowns + 505 allometric; shade for 4 scenario days; map with the planting simulator.
> Left: try `terravide` (skipped: the FTP plus tile index worked first time), demo recording and slides, v1 scoring.

Goal for the end of day: **a working demo, not slides.** Open the map, scrub through
time, watch the shadows move, and click a tree to see its shade hours, for the
Mott Haven pilot.

Times are offsets from build start (T0, after this plan is approved). The total
budget is about 6 h. If time gets tight, cut from the bottom of each phase,
never the walking skeleton.

## Decisions needed before T0
- [x] **Approve ARCHITECTURE.md**: the contracts (§3) and module boundaries.
- [x] **Pilot AOI: Mott Haven** `-73.9290, 40.8050, -73.9160, 40.8140` (about 10×10 blocks).
  Verified for this box: 1,932 ForMS trees, 1,685 planting spaces (194 empty),
  1,126 buildings and 298 street segments. Brownsville needs 9 LiDAR tiles vs 6 here,
  at the same download speed, so Mott Haven wins.
- [x] **LiDAR budget: the area needs 6 tiles ≈ 2.5 GB** (2017: 2.48 GB, 2021: 2.55 GB).
  Measured at ~13 MB/s, that's about 3–4 min. **This is over the 2 GB ask-first line.**
  Choose one:
  - (a) approve ~2.5 GB for one year,
  - (b) trim the AOI to the 4 central tiles (~1.6 GB), or
  - (c) no LiDAR: allometric only.
  Recommendation: (a), for one year.

## Phase 0: Foundation (T0 → T0+0:45)
- [x] `pyproject.toml` (uv, py3.11), `Makefile`, `.gitignore` (`data/`), `aois.yaml`
- [x] `pipeline/contracts.py`: CrownModel, ShadeResult, ShadeSummary, PlantingSite + round-trip tests
- [x] `docs/adr/0001-contracts.md` (plus stubs 0002–0004)
- [x] README: what it is, 3-command quick start, repo map
- [x] Commit: "scaffold + contracts"

## Phase 1: Walking skeleton (T0+0:45 → T0+2:30)  ← the most important part
Get every stage working end to end with simple stand-ins, using allometric crowns.
- [x] `ingest/socrata.py`, `buildings.py`, `streets.py` → `data/raw/mott_haven/`
- [x] `growth/allometry.py`: UTD equations for the top ~15 species in the AOI + generic fallback
      (verify the UTD download, RDS-2016-0005, and its Queens reference-city coefficients)
- [x] `canopy/fallback.py` → `crowns.parquet` (`source="allometric"`)
- [x] `shade/sun.py` + `geometry.py` + `simulate.py`: test one tree with a hand-checked answer
      (a 10 m sphere at 45° altitude gives a shadow offset of 10 m), then run the whole AOI
- [x] `publish.py` → GeoParquet; `api/` with `/trees`, `/shadows`, `/buildings`
- [x] `web/`: buildings + crowns + shadows + time slider
- [x] **Checkpoint T0+2:30: demoable.** Commit and tag `v0-skeleton`.

## Phase 2: LiDAR crowns (T0+1:00 → T0+4:00, runs in parallel; hard stop at T0+4:00)
Starts once the budget is approved. It can run alongside Phase 1, because LiDAR only
replaces the crowns in `crowns.parquet`.
- [x] 15 min: read the 2017 and 2021 flight reports for leaf-on/off and point density, then pick a year (ADR-0004)
- [ ] 15 min: try `terravide`. If it lists and downloads tiles cleanly, use it; otherwise plain FTP plus the index shapefile (already verified) *(skipped: plain FTP + tile index worked first time)*
- [x] `ingest/lidar.py`: download the 6 tiles (with the >2 GB guard)
- [x] `canopy/ground.py` → nDSM (PDAL or laspy + numpy)
- [x] `canopy/segment.py`: ForMS-seeded watershed
- [x] `canopy/fit.py` + `link.py` → `crowns.parquet` (`source="lidar"`, allometric for the gaps)
- [x] Sanity check: LiDAR height vs allometric height, scatter plot by species (good for the demo)
- [x] **Gate at T0+4:00:** if the LiDAR crowns aren't credible, ship allometric and
      show LiDAR as "in progress" in the pitch

## Phase 3: Metrics + UI (T0+3:00 → T0+5:00)
- [x] `shade/metrics.py`: sidewalk band, `usable_sidewalk_shade_hours`, `public_ground_fraction`, `self_shaded_fraction`
- [x] API `/trees/{id}/shade`; web click-a-tree panel with an hourly shade chart
- [x] Colour crowns by source; a legend that flags allometric crowns
- [x] `ingest/hvi.py`: HVI by NTA as a map overlay (sets up the v1 story)

## Phase 4: v1/v2 hooks, visible but stubbed (T0+5:00 → T0+5:30)
- [x] `sites/discover.py`: show the 194 empty pits on the map (real data, no scoring yet)
- [x] `POST /simulate`: the same simulator on a `predict_crown` stub (allometry at planting + N years)
- [x] "What if we plant a London plane here?" Click an empty pit and see the 5/10/15-yr shadow.
      Stretch goal; it reuses everything above.

## Phase 5: Demo prep (T0+5:30 → T0+6:00)
- [ ] Screen recording of the flow as a backup, plus 3 slides: problem, method (GeoAI: inventory-seeded crown segmentation), what's next (Shade Queue for Parks)
- [x] README: methods, limitations (ADR-0002), data sources with IDs
- [ ] Final commit + tag `v0-demo`

## Risks
| Risk | Mitigation |
|---|---|
| LiDAR is leaf-off or segmentation is weak | Allometric fallback already wired (Phase 1); ADR-0004 |
| Socrata rate limits | Cache in `data/raw/`; optional app token |
| deck.gl ellipsoid meshes are slow or fiddly | Fall back to `ColumnLayer` cylinders |
| Python 3.8 on this machine | uv installs its own 3.11; nothing uses the system Python |

## Out of scope today
Citywide runs, vector tiles, species recommendation logic, leaf porosity, terrain.

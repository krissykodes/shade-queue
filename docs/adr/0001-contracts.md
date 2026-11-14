# ADR-0001: Contracts first; the simulator consumes CrownModel only

**Status:** accepted, 2026-11-14

**Context.** Today we measure crowns from LiDAR. Next we estimate them for trees LiDAR can't see. After that we predict them for trees that don't exist yet (empty pits at 5/10/15 years). If the shade code depends on point clouds, every stage needs a rewrite.

**Decision.** `pipeline/contracts.py` defines `CrownModel`, `ShadeResult`, `ShadeSummary` and `PlantingSite` (pydantic v2, metres, degrees clockwise from north, EPSG:4326 lon/lat). `shade.simulate.simulate()` accepts `list[CrownModel]` and nothing else. `source ∈ {lidar, allometric, predicted}` and `confidence` travel with each crown, so the UI and the ranking can show where every number came from.

**Consequences.** A predicted crown runs through exactly the same simulator as a measured one (`POST /simulate`). Changing a contract requires a new ADR. Shadow polygons sit next to `ShadeResult` in GeoParquet, never inside it.

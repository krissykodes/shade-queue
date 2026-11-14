# ADR-0002: 2.5-D projected shadows, not ray tracing

**Status:** accepted, 2026-11-14

**Decision.** A crown is a convex solid of revolution (ellipsoid, cone, umbrella or cylinder), sliced into 7 horizontal discs. Each disc projects to the ground shifted by z / tan(sun altitude). Because the projection of a convex body is convex, the shadow is exactly the convex hull of those discs. Buildings are flat-roofed prisms, and their shadow is the footprint swept along the sun vector. Sun positions come from pvlib (NREL SPA, offline). The scenario set is the solstices and equinoxes, hourly, with sun altitude ≥ 5°.

**Metrics.** `ground_shade_m2` = tree shadow minus building footprints. `facade_shade_m2` = the part of the shadow that lands inside a footprint (approximation: in reality it stops on the wall). `self_shaded_fraction` = the share of ground shadow already inside building shadow. `sidewalk_shade_m2` = ground shadow ∩ sidewalk, minus building shadow. "Usable" sidewalk shade means ≥ 5 m² in a leaf-on month.

**Known limits.** Crowns are opaque (no leaf porosity). Terrain is flat. Trees don't shade each other (each tree is simulated independently). Grid convergence (<1°) is ignored. The v0 sidewalk is a 4.5 m band outside the curb, derived from centerline width. The 5 m² usability threshold saturates for large trees, so v1 should switch to shaded m²·hours.

**Performance.** 1,549 trees × 44 sun samples run in about 40 s on a laptop, which makes a citywide run feasible.

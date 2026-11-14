# ADR-0005: Rank empty pits by NEW sidewalk shade (ported from Shade First NYC)

**Status:** accepted, 2026-11-14

**Context.** Parks' planting program already orders neighbourhoods by the Heat Vulnerability Index, but within an HVI-5 area every empty pit looks the same. Kristin's Shade First NYC prototype showed that ranking pits by the new pedestrian shade a tree would add concentrates the benefit: in Queens Village 11429, the top 200 of 1,856 pits gave 22% of the possible new shade, 2.1× per tree.

**Decision.** `pipeline/sites/score.py` asks: *if this pit is planted, how much of the new tree's shadow lands on sidewalk that is sunny today?*

- **Tree:** `predict_crown(species, 2.5″ caliper, years)` using the UTD Northeast (Queens) growth curves. The default is a London plane at 10 years; scenarios cover 6 species × {5, 10, 15} years.
- **Window:** July 15, 14:00–16:00 EDT, every 30 min (Shade First NYC's window), plus an hourly profile from 07:00 to 19:00 for charts.
- **New shade:** the tree's ground shadow ∩ Planimetric sidewalk (`52n9-sdep`), minus building shadow, minus existing street-tree shadow. Existing crowns come from LiDAR or allometry, via `simulate(existing=...)`.
- **`new_shade_m2h`** = mean new sidewalk shade over the window × 2 h. Pits are ranked by it.
- **`shade_yield`** = new shade ÷ the tree's whole shadow (0–1). This fills the contract's `shade_deficit_score`.
- **HVI** is reported as published and never blended into the score. Parks already prioritises by HVI; this ranks pits within an area.
- **Placeholder pits:** 39% of empty street pits citywide carry a Pennsylvania placeholder location. Pits in the AOI's ZIP codes are geocoded from their address with NYC GeoSearch, snapped to the nearest sidewalk, and kept if they land inside the AOI.

**What changed from Shade First NYC.** One generic 8 m / 4 m crown became a species × age crown. 17 sample points became the full shadow polygon. A 0.27 m × DBH crown estimate for existing trees became LiDAR-measured crowns. The ray-cast became the shared swept-prism simulator. The question, the window, the sidewalk layer and the guardrails are unchanged.

**Limits.** Viability inspections (`4pt5-3vv4`) are not joined yet, so some top pits may not be plantable. Overhead wires are shown but don't affect the score. The window covers a single afternoon. Trees are opaque.

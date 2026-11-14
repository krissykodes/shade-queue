# ADR-0003: Inventory-seeded crown segmentation

**Status:** accepted, 2026-11-14

**Decision.** Build a 0.5 m canopy height model (CHM) from LiDAR vegetation classes 3, 4 and 5 minus a ground DTM from class 2, and mask out buildings and anything under 3 m. Then run a marker watershed whose markers are the **ForMS tree points**, each snapped to the highest CHM cell within 2.5 m. Extra CHM peaks more than 3.5 m from any seed become *unlinked* crowns (park and yard trees), stored separately.

**Why.** The output has to carry Parks tree IDs anyway. Using the inventory as a weak label avoids a separate matching step and splits touching crowns where Parks knows there are two trees. This is the GeoAI step: the official inventory is fused with the point cloud.

**Result (Mott Haven).** 1,044 of 1,549 live inventory trees got LiDAR crowns. Against UTD allometry, height r = 0.54 and radius r = 0.67, with matching medians (9.6 m). Most of the 505 left over are young: 171 were planted after the flight, and the median DBH of the rest is 7.6 cm. Failure mode: a sapling next to a large crown can snap onto its neighbour's peak, which shows up as low `confidence`.

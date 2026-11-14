# ADR-0004: Use the 2021 LiDAR

**Status:** accepted, 2026-11-14

Both NYC collections were flown in May: 2017 topobathy on 3–17 May (about 10.8 first returns/m²), 2021 Eagleview on 12–21 May (12 pts/m²). We use **2021** because it was flown later in leaf-out, is denser, is more recent, and comes with vegetation classes (3/4/5) and buildings (6). Crowns carry `as_of_year=2021`; allometric crowns carry 2026, from the live inventory DBH. Tiles come from `ftp.gis.ny.gov/elevation/LIDAR/NYC_2021/`, selected via the tile index. Mott Haven needs 6 tiles (2.55 GB), a download the product lead approved.

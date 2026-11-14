AOI ?= mott_haven

.PHONY: setup data lidar crowns shade serve test clean

setup:            ## install Python 3.12 env + deps with uv
	uv sync

data:             ## fetch + build everything for $(AOI) with allometric crowns (≈1 min)
	uv run python -m pipeline run --aoi $(AOI) --steps ingest,canopy,shade,sites

lidar:            ## download LiDAR (≈2.5 GB for mott_haven) and extract crowns, then re-run shade
	uv run python -m pipeline.ingest.lidar --aoi $(AOI) --allow-large
	uv run python -m pipeline run --aoi $(AOI) --steps lidar,canopy,shade

serve:            ## API + web map on http://localhost:8811
	SHADE_AOI=$(AOI) uv run uvicorn api.main:app --port 8811 --reload

test:
	uv run pytest -q

clean:            ## remove processed outputs (keeps raw downloads)
	rm -rf data/interim/$(AOI) data/processed/$(AOI)

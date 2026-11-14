AOI ?= harlem_116
SITE_AOIS ?= harlem_116 mott_haven

.PHONY: setup data lidar crowns shade site deploy serve test clean

setup:            ## install Python 3.12 env + deps with uv
	uv sync

data:             ## fetch + build everything for $(AOI) with allometric crowns (shade ≈1 min, pit scenarios ≈5–10 min)
	uv run python -m pipeline run --aoi $(AOI) --steps ingest,canopy,shade,sites

lidar:            ## download LiDAR (≈2.5 GB for mott_haven) and extract crowns, then re-run shade
	uv run python -m pipeline.ingest.lidar --aoi $(AOI) --allow-large
	uv run python -m pipeline run --aoi $(AOI) --steps lidar,canopy,shade,sites

site:             ## export static site for $(SITE_AOIS) into site/
	uv run python -m pipeline export $(foreach a,$(SITE_AOIS),--aoi $(a)) --out site

preview: site     ## serve the static site locally on http://127.0.0.1:8811
	uv run python -m http.server 8811 --bind 127.0.0.1 --directory site

deploy: site      ## publish site/ to GitHub Pages (gh-pages branch)
	scripts/deploy_pages.sh

serve:            ## FastAPI (programmatic access, /docs) on http://localhost:8811
	SHADE_AOI=$(AOI) uv run uvicorn api.main:app --port 8811 --reload

test:
	uv run pytest -q

clean:            ## remove processed outputs (keeps raw downloads)
	rm -rf data/interim/$(AOI) data/processed/$(AOI)

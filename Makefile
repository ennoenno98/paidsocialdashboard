.PHONY: install parse refresh app test lint fixture ci

UV ?= uv
PY := .venv/bin/python

install:
	$(UV) venv --python 3.12 .venv
	$(UV) pip install -e ".[dev]"

fixture:
	$(PY) tests/fixtures/build_fixture.py

parse:            ## parse the workbook, print tidy frames + block coverage report
	$(PY) -m src.cli parse --xlsx $${SOCIAL_XLSX:-data/Social_Media.xlsx} --out data/processed

refresh:          ## run all ingests (workbook, Klar, Instagram) -> data/processed
	$(PY) -m src.cli refresh --klar-days 400

refresh-offline:  ## same, but fixtures/cache only (no API calls)
	$(PY) -m src.cli refresh --offline

app:              ## local: streamlit run app/Home.py ; cloud entrypoint: streamlit_app.py
	.venv/bin/streamlit run app/Home.py

test:
	$(PY) -m pytest

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

ci: lint test

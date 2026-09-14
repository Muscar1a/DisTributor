.PHONY: run test lint format check clean

PY = .venv/Scripts/python.exe

run:
	$(PY) -m uvicorn src.gateway.app.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PY) -m pytest src/gateway/tests/ -v

lint:
	$(PY) -m ruff check src/gateway/

format:
	$(PY) -m ruff format src/gateway/

check: lint test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +

deploy:
	bash deploy.sh


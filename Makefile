.PHONY: run setup test
run:
	bash run.sh

setup:
	python3 -m venv command-center/backend/.venv
	command-center/backend/.venv/bin/python -m pip install -r command-center/backend/requirements.txt
	cd command-center/frontend && npm ci
	cd command-center/frontend && npx playwright install chromium

test:
	command-center/backend/.venv/bin/python scripts/run_tests.py

.PHONY: test check package

test:
	uv run pytest

check:
	uv run ruff check src tests
	uv run ruff format --check src tests
	python -m compileall -q src main.py

package:
	uv build

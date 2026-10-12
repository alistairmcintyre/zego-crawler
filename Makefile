.PHONY: install lint format typecheck test test-unit test-integration check docker

install:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test-unit:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration

test:
	uv run pytest --cov

check: lint typecheck test

docker:
	docker build -t zego-crawler .

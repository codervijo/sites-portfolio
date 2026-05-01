# Portfolio (Python/uv). Mirrors target conventions from ../Makefile.

IS_DOCKER := $(shell [ -f /.dockerenv ] && echo "yes" || echo "no")
ifeq ($(IS_DOCKER),no)
$(warning "Warning: Not running inside Docker. Make sure this is intentional.")
endif

# uv installs to ~/.local/bin by default; make sure it is on PATH for recipes.
export PATH := $(HOME)/.local/bin:$(PATH)

ARGS ?=

.PHONY: help all deps build run test clean install-uv lock sync

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  deps      - Install Python dependencies via uv (auto-installs uv if missing)"
	@echo "  lock      - Refresh uv.lock"
	@echo "  sync      - Sync the venv to the lockfile"
	@echo "  build     - Build the wheel"
	@echo "  run       - Run the portfolio CLI (pass args via ARGS=...)"
	@echo "  test      - Run pytest"
	@echo "  clean     - Remove build artifacts and venv"
	@echo "  help      - Show this help message"

all: build

install-uv:
	@command -v uv >/dev/null 2>&1 || { \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}

deps: install-uv
	uv sync

lock: install-uv
	uv lock

sync: install-uv
	uv sync

build: deps
	uv build

run: deps
	uv run portfolio $(ARGS)

test: deps
	uv run pytest

clean:
	rm -rf .venv dist build *.egg-info src/*.egg-info .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Docker harness, emulator helpers and the demo server (sdk-kit).
#   make -C harness test          unit tests (pytest, coverage gates >= 90 %) + wait-for script tests
#   make -C harness lint          shellcheck + ruff
#   make -C harness test-docker   end-to-end compose tests (Docker; serialised through a lock file)
PYTHON ?= python3
LOCK ?= $(HOME)/grow/.artifcats/locks/sdk-docker-1.lock
KIT := $(abspath ..)
SH_FILES := $(KIT)/template/common/docker/harness/*.sh $(KIT)/template/common/docker/bootstrap/*.sh \
	$(KIT)/demo/bootstrap/bootstrap.sh fakeintake/bootstrap.sh betterstack-stub/bootstrap.sh tests/*.sh

.PHONY: test lint test-docker
test:
	cd $(KIT)/demo && PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider tests \
	  --cov=server --cov-branch --cov-fail-under=90
	cd betterstack-stub && PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider tests \
	  --cov=stub --cov=sql --cov=otlp --cov=msgpack_decode --cov-branch --cov-fail-under=90
	cd fakeintake && PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider tests \
	  --cov=fakeintake --cov-branch --cov-fail-under=90
	sh tests/test-wait-for.sh

lint:
	shellcheck -s sh -x -P SCRIPTDIR $(SH_FILES)
	$(PYTHON) -m ruff check $(KIT)/demo .
	$(PYTHON) -m ruff format --check $(KIT)/demo .

test-docker:
	flock $(LOCK) sh tests/test-compose-demo.sh
	flock $(LOCK) sh tests/test-compose-emulators.sh

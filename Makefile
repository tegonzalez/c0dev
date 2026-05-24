.PHONY: help doctor fix build start restart stop status sh root logs test

C0 ?= ./bin/c0
PUBLIC_TESTS := \
	test/c0-activate-path.sh \
	test/c0-entrypoints.sh \
	test/c0-preflight.sh

help:
	@printf '%s\n' \
		'c0dev commands:' \
		'  make doctor         Check onboarding prerequisites' \
		'  make fix            Create missing repo-local host dirs where safe' \
		'  make build          Build tools and image' \
		'  make start          Start c0dev' \
		'  make restart        Restart c0dev' \
		'  make stop           Stop c0dev' \
		'  make status         Show c0dev status' \
		'  make sh             Shell as dev user' \
		'  make root           Shell as root' \
		'  make logs           Follow container logs' \
		'  make test           Run c0dev shell tests'

doctor:
	$(C0) doctor

fix:
	$(C0) doctor --fix

build:
	$(C0) build

start:
	$(C0) start

restart:
	$(C0) restart

stop:
	$(C0) stop

status:
	$(C0) status

sh:
	$(C0) sh

root:
	$(C0) root

logs:
	$(C0) logs

test:
	@set -e; for test_script in $(PUBLIC_TESTS); do bash "$$test_script"; done

-include Makefile.local

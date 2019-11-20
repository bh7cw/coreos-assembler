PREFIX ?= /usr
DESTDIR ?=

GOARCH:=$(shell uname -m)
# Copied from coreos-assembler Makefile
ifeq ($(GOARCH),x86_64)
	GOARCH=amd64
else ifeq ($(GOARCH),aarch64)
	GOARCH=arm64
endif

.PHONY: build test vendor
build:
	./build

.PHONY: install
install: build
	install -D -t $(DESTDIR)$(PREFIX)/bin bin/{ore,kola,plume}
	install -D -m 0755 -t $(DESTDIR)$(PREFIX)/lib/kola/$(GOARCH) bin/$(GOARCH)/kolet

test:
	./test

vendor:
	@go mod vendor

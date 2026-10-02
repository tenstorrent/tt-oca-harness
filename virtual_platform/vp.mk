# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# ocah.mk fragment for the SEP virtual platform (virtual_platform/).
#
# Thin delegation only: the VP's own Makefile relies on .ONESHELL /
# .DEFAULT_GOAL / SHELL settings that must not leak into the root make
# context, so every target here re-enters it with $(MAKE) -C. Run
# `make -C virtual_platform help` for the full target/variable list.

ifndef ocah_vp_mk
ocah_vp_mk := 1

OCAH_VP_DIR ?= $(OCAH_ROOT)/virtual_platform

## @section SEP Virtual Platform

## Initialize the tt-oca-harness-model submodule (recursive; required before ocah-vp-build).
.PHONY: ocah-vp-init
ocah-vp-init:
	git -C "$(OCAH_ROOT)" submodule update --init --recursive virtual_platform/tt-oca-harness-model

## Build the SystemC/Boost/OpenSSL/CCI dependencies into virtual_platform/local/.
.PHONY: ocah-vp-deps
ocah-vp-deps:
	$(MAKE) -C "$(OCAH_VP_DIR)" deps

## Build/rebuild the sep-vp virtual platform (incremental; deps assumed built).
.PHONY: ocah-vp-build
ocah-vp-build:
	$(MAKE) -C "$(OCAH_VP_DIR)" vp

## Run the VP pytest suites (bootcode, SPI, fw, fuses). Pass PYTEST_ARGS=...
.PHONY: ocah-vp-test
ocah-vp-test:
	$(MAKE) -C "$(OCAH_VP_DIR)" vp-test

## Build + run the SEP boot ROM on sep-vp (BOOT_ARGS="--boot primary ...").
.PHONY: ocah-vp-boot-run
ocah-vp-boot-run:
	$(MAKE) -C "$(OCAH_VP_DIR)" boot-run

## Remove VP build artifacts (downloads/, local/, tt-oca-harness-model/vp/build).
.PHONY: ocah-vp-clean
ocah-vp-clean:
	$(MAKE) -C "$(OCAH_VP_DIR)" clean

OCAH_PHONY += ocah-vp-init ocah-vp-deps ocah-vp-build ocah-vp-test ocah-vp-boot-run ocah-vp-clean

endif

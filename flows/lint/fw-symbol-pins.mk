# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_fw_symbol_pins_mk
ocah_lint_fw_symbol_pins_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

ocah_fw_symbol_pins_script := $(OCAH_ROOT)/tools/dv/check_fw_symbol_pins.py

## @section Lint (firmware symbol pins)

## Compare hand-committed firmware PC pins against the .sym the firmware build
## emits. sep_debug_bus_symbols.h pins the PCs the CLA matches on; its own
## #error guards cannot detect an image rebuilt with those PCs at other
## plausible addresses, which leaves the CLA matching the wrong instruction on
## a test that still passes. A missing .sym is a failure.
.PHONY: ocah-lint-fw-symbol-pins
ocah-lint-fw-symbol-pins:
	$(OCAH_UV_RUN) python3 $(ocah_fw_symbol_pins_script)

## Rewrite the pins to match the built .sym. Run after rebuilding the image.
.PHONY: ocah-lint-fw-symbol-pins-update
ocah-lint-fw-symbol-pins-update:
	$(OCAH_UV_RUN) python3 $(ocah_fw_symbol_pins_script) --update

OCAH_PHONY += ocah-lint-fw-symbol-pins ocah-lint-fw-symbol-pins-update

endif

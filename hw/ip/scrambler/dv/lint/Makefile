#-----------------------------------------------------------------------------
# Makefile for Scrambler RTL Lint (slang-tidy)
#
# Copyright 2026 Tenstorrent Inc.
#-----------------------------------------------------------------------------

RTL_DIR = ../rtl

SLANG_TIDY       = slang-tidy
SLANG_TIDY_CFG   = $(abspath scrambler.toml)
SLANG_TIDY_FLAGS = --lint-only --ignore-unknown-modules \
                   --config-file $(SLANG_TIDY_CFG)

RTL_FILES = \
    $(RTL_DIR)/scrambler_pkg.sv \
    $(RTL_DIR)/scrambler_addr_tweak.sv \
    $(RTL_DIR)/scrambler_rotator.sv \
    $(RTL_DIR)/scrambler.sv \
    $(RTL_DIR)/scrambler_512x32.sv \
    $(RTL_DIR)/scrambler_1024x32.sv \
    $(RTL_DIR)/scrambler_2048x32.sv \
    $(RTL_DIR)/scrambler_4096x32.sv \
    $(RTL_DIR)/scrambler_8192x32.sv

.PHONY: lint clean help
.DEFAULT_GOAL := lint

lint:
	@for f in $(RTL_FILES); do \
	    echo "=== $$f ==="; \
	    $(SLANG_TIDY) $(SLANG_TIDY_FLAGS) $$f || true; \
	done
	@echo ""
	@echo "Lint check complete"

clean:
	@echo "Nothing to clean."

help:
	@echo "Scrambler Lint Makefile (slang-tidy)"
	@echo ""
	@echo "Targets:"
	@echo "  lint  - Run slang-tidy on all RTL modules (default)"
	@echo "  help  - Show this help"

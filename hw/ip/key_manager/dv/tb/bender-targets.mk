# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# Key Manager standalone testbench - Bender design filelist generation.
#
# The Key Manager RTL, its generated register packages and the scrambler IP it
# depends on are selected by the `key_manager` target. Those blocks are shared
# with the SEP subsystem (`any(sep, key_manager)` in the root Bender.yml), so
# `key_manager` yields the KM design alone without sep_pkg.sv and the VeeR EL2
# collateral that the full `sep` target drags in.
#
# The testbench top (tb_key_manager.sv) is added by the Makefile, not by Bender,
# as in the other cocotb testbenches (e.g. hw/ip/gpio/dv/tb).

# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

# Key Manager design + dependencies (AXI, common_cells, register_interface).
# The KM design also needs the OpenTitan primitives (prim_lfsr, prim_rst_sync,
# prim_fifo_sync, prim_diff_decode_multi) and the PicoRV32 core it embeds; both
# vendor file lists are opt-in Bender targets.
COMMON_TARGETS = -t axi_rtl -t common_cells_rtl -t register_interface_l1 \
                 -t key_manager -t picorv32_rtl

# ==============================================================================
# CocoTB Simulation File List Generation
# ==============================================================================
.PHONY: cocotb_simulation_filelist
# Register packages are generated centrally (`make -f ocah.mk ocah-regen-regs`)
# and committed under hw/ip/key_manager/regs/gen. Bender.lock is refreshed so
# Bender.local path overrides cannot go stale.
cocotb_simulation_filelist:
	@echo "Generating CocoTB simulation filelist from Bender..."
	@cd $(OCH_ROOT) && bender update --local --no-checkout
	@cd $(OCH_ROOT) && bender checkout
	@set -e; \
	tmp_file="$$(mktemp "$(FILE_LIST).tmp.XXXXXX")"; \
	trap 'rm -f "$$tmp_file"' 0; \
	cd "$(OCH_ROOT)"; \
	bender script flist-plus $(COMMON_TARGETS) -t 'not(synthesis)' > "$$tmp_file"; \
	mv -f "$$tmp_file" "$(FILE_LIST)"; \
	trap - 0
	@echo "CocoTB filelist generated: $(FILE_LIST)"

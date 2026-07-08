# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# AoU (AXI-over-UCIe) lint/synth flow descriptor for the vendored
# `vendor/tenstorrent/aou-rtl` package. Lives in `overlay/` rather than at the
# package root, matching this repo's convention for TT-specific collateral
# layered onto a vendored tree (see e.g. vendor/lowRISC/opentitan/overlay/,
# vendor/pulp-platform/axi/overlay/) instead of editing `upstream/` directly
# or forking a second copy of this file under hw/. One shared descriptor
# feeds both `make lint BLOCK=aou-rtl` and `make synth BLOCK=aou-rtl
# TECH=...` (flows/common.mk resolves the actual bender filelist), so the two
# flows can never drift onto different inputs - see flows/lint/slang.mk for
# why that matters.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../../flows/preamble.mk

# `AOU_TOP` (upstream/RTL/AOU_TOP.sv) is the package's actual top-level
# module name, unlike the hw/sys blocks where FLOW_DESIGN happens to match
# the block name.
FLOW_DESIGN := AOU_TOP
# ../Bender.yml (package `aou`) is a slim, dependency-free manifest with a
# single unconditional `sources:` list and no `targets:` - bender's own
# nearest-Bender.yml discovery from this directory resolves there (not to
# tt-oca's root Bender.yml), so the flist here is scoped to just the
# vendored AoU sources. No FLOW_BENDER_TARGETS needed.
FLOW_BENDER_TARGETS :=

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

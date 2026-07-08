# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMU lint/synth flow descriptor. One shared descriptor feeds both
# `make lint TARGET=smu` and `make synth TARGET=smu TECH=...` (flows/common.mk
# resolves the actual bender filelist), so the two flows can never drift onto
# different inputs - see flows/lint/slang.mk for why that matters.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../flows/preamble.mk

FLOW_DESIGN := smu
# tt-oca's own Bender.yml sourceset is not yet partitioned per hw/sys block (a
# single `all(not(dv), not(fv))` target covers the whole open RTL tree), so
# every block's flist is identical today and `--top $(FLOW_DESIGN)` alone
# selects the right hierarchy. Populate this once Bender.yml grows real
# per-block targets, mirroring tt-oca-hw's `-t smu -t ...` pattern.
FLOW_BENDER_TARGETS :=

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_regs_mk
ocah_regs_mk := 1

# Discovers register blocks and regenerates their collateral (SV/C/Python/docs)
# from RDL via peakrdl.

# Global knobs, defined before the includes so the rule defines see them.
OCAH_REGBLOCK_UDP ?= $(OCAH_ROOT)/hw/common/regs/regblock_udps.rdl
OCAH_REG_CPU_IF ?= axi4-lite-flat
OCAH_REG_DEFAULT_RESET ?= arst_n
OCAH_REGGEN_WRAPPER ?= $(OCAH_ROOT)/tools/regs/reggen_wrapper.py
OCAH_REGEN_REG_JOBS ?= 8

# Stage-1 feature parity exceptions: these TT-owned blocks intentionally keep
# the protocol/interface shape used by the DV/coverage-proven tt-oca-hw RTL.
# TODO: make register protocol selection uniform in a second cleanup stage and
# remove these per-block overrides once the RTL/reg generation contract is common.
OCAH_REG_CPU_IF_NAME_avsbus_controller ?= apb4-flat
OCAH_REG_CPU_IF_NAME_efuse_bank ?= apb4-flat
OCAH_REG_CPU_IF_NAME_efuse_interface_ctrl ?= apb4-flat
OCAH_REG_CPU_IF_NAME_efuse_mmr ?= apb4-flat
OCAH_REG_CPU_IF_NAME_entropy_source ?= axi4-lite

# Regen is parallel across blocks; default these goals to -j unless -j was passed.
ocah_reg_make_goals := $(filter regen-regs% ocah-regen-regs%,$(MAKECMDGOALS))
ifneq ($(ocah_reg_make_goals),)
ifeq ($(filter -j% --jobs%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(OCAH_REGEN_REG_JOBS)
endif
endif

# Run from repo root with pipefail so a tee'd log does not mask failures.
ocah_sh := cd "$(OCAH_ROOT)" && bash -o pipefail -c

# Find blocks and resolve their paths/policy.
include $(OCAH_ROOT)/hw/common/regs/discover.mk
include $(OCAH_ROOT)/hw/common/regs/classify.mk

# Build output paths, rules, and user-facing targets.
include $(OCAH_ROOT)/hw/common/regs/out.mk
include $(OCAH_ROOT)/hw/common/regs/rules.mk
include $(OCAH_ROOT)/hw/common/regs/phony.mk

endif

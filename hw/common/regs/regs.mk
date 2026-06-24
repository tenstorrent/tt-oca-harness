# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_regs_mk
ocah_regs_mk := 1

# Discovers register blocks and regenerates their collateral (SV/C/Python/docs)
# from RDL via peakrdl.

# Global knobs, defined before the includes so the rule defines see them.
OCAH_REGBLOCK_UDP ?= $(OCAH_ROOT)/hw/common/regs/regblock_udps.rdl
OCAH_REG_CPU_IF ?= axi4-lite-flat
OCAH_REG_DEFAULT_RESET ?= arst_n
OCAH_PANDOC ?= pandoc
OCAH_REGGEN_WRAPPER ?= $(OCAH_ROOT)/tools/regs/reggen_wrapper.py
OCAH_REGEN_REG_JOBS ?= 8

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

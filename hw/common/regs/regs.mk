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

# uv-sync creates this environment before every register recipe. Invoke its
# tools directly so hundreds of parallel recipes do not each repeat uv's
# project discovery and lock checks. UV_PROJECT_ENVIRONMENT remains honored.
OCAH_REG_UV_ENV ?= $(if $(UV_PROJECT_ENVIRONMENT),$(UV_PROJECT_ENVIRONMENT),$(OCAH_ROOT)/.venv)
OCAH_REG_PYTHON ?= $(OCAH_REG_UV_ENV)/bin/python
OCAH_REG_PEAKRDL ?= $(OCAH_REG_UV_ENV)/bin/peakrdl

# The CI full-regeneration check stamps generated files in batches after Make
# completes. Normal and individually addressed targets still stamp immediately.
OCAH_REG_DEFER_STAMP ?= 0

# A forced regeneration would otherwise run the phony uv-sync prerequisite once
# while rebuilding included depfiles and again after Make restarts. CI syncs
# explicitly once, then suppresses only those redundant order-only prerequisites.
OCAH_REG_SKIP_UV_SYNC ?= 0
OCAH_REG_UV_PREREQ = $(if $(filter 1,$(OCAH_REG_SKIP_UV_SYNC)),,uv-sync)

# Stage-1 feature parity exceptions: these TT-owned blocks intentionally keep
# the protocol/interface shape used by the DV/coverage-proven RTL.
# TODO: make register protocol selection uniform in a second cleanup stage and
# remove these per-block overrides once the RTL/reg generation contract is common.
OCAH_REG_CPU_IF_NAME_avsbus_controller ?= apb4-flat
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

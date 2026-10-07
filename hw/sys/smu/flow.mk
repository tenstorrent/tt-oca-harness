# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMU lint/synth flow descriptor, shared by `make lint-slang-all BLOCK=smu`,
# `make synth-yosys-all BLOCK=smu TECH=...` and `make synth-vivado-all BLOCK=smu`.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../flows/preamble.mk

FLOW_DESIGN := smu
FLOW_BENDER_TARGETS := -t idma_rtl -t dtp -t sep -t smc -t sep_el2
FLOW_INTEGRATION_SIM_FROM_DV := 1
FLOW_VERILATOR_WAIVERS := \
	hw/sys/sep/lint/sep.verilator.vlt \
	hw/sys/smc/lint/smc.verilator.vlt
FLOW_SYNTH_SLANG_EXPECTED_ERRORS := vendor/tenstorrent/tt-hw-debug/overlay/lint/synthesis.slang.expected-errors
FLOW_SYNTH_SLANG_COMPAT_FLAGS := --relax-enum-conversions

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk
include $(OCAH_ROOT)/flows/synth/vivado/vivado.mk

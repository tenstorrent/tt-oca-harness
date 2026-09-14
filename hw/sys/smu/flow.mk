# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMU lint/synth flow descriptor, shared by `make lint-slang-all BLOCK=smu`
# and `make synth-all BLOCK=smu TECH=...`.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../flows/preamble.mk

FLOW_DESIGN := smu
FLOW_BENDER_TARGETS := -t idma_rtl -t dtp -t sep -t smc -t sep_el2
FLOW_VERILATOR_WAIVERS := \
	hw/sys/sep/lint/sep.verilator.vlt \
	hw/sys/smc/lint/smc.verilator.vlt

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

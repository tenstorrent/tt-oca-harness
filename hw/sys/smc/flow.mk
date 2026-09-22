# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC lint/synth flow descriptor, shared by `make lint-slang-all BLOCK=smc`
# and `make synth-yosys-all BLOCK=smc TECH=...`.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../flows/preamble.mk

FLOW_DESIGN := smc
FLOW_BENDER_TARGETS := -t idma_rtl -t smc
FLOW_INTEGRATION_SIM_FROM_DV := 1
FLOW_VERILATOR_WAIVERS := hw/sys/smc/lint/smc.verilator.vlt

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC lint/synth flow descriptor, shared by `make lint BLOCK=smc` and
# `make synth BLOCK=smc TECH=...`.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../flows/preamble.mk

FLOW_DESIGN := smc
# Empty until Bender.yml gains real per-block targets; every block shares
# the same flist today.
FLOW_BENDER_TARGETS :=

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

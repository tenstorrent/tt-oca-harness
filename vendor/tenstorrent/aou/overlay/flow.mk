# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# AoU (AXI-over-UCIe) lint/synth flow descriptor for the vendored
# `vendor/tenstorrent/aou` package. Lives in `overlay/`, alongside other
# TT-specific collateral layered onto vendored packages.
FLOW_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FLOW_DIR)/../../../../flows/preamble.mk

# Actual top-level module name (upstream/RTL/AOU_TOP.sv).
FLOW_DESIGN := AOU_TOP
FLOW_INTEGRATION_NAME := aou
# ../Bender.yml scopes the flist to just this package's sources.
FLOW_BENDER_TARGETS := -t aou
OCAH_FLOW_COMMON_BENDER_TARGETS :=

include $(OCAH_ROOT)/flows/common.mk
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// RTL File List for Cross Trigger Matrix
// Use $OCH_ROOT environment variable for portability

// AXI package (must come first, before typedef macros)
$OCH_ROOT/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv

// Generated register collateral (the package below reads its port counts from these)
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/regs/gen/sv/cross_trigger_matrix_addrmap_pkg.sv
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/regs/gen/sv/cross_trigger_matrix_reg_pkg.sv

// Package
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/rtl/cross_trigger_matrix_pkg.sv

// RTL modules (in dependency order)
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/regs/gen/sv/cross_trigger_matrix_reg.sv
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/rtl/ctm_src_selector.sv

// Top-level module (last)
$OCH_ROOT/hw/ip/cross_trigger/cross_trigger_matrix/rtl/cross_trigger_matrix.sv

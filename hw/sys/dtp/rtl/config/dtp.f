# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# DTP (Debug and Test Ports) Module File List
# Copyright 2025 Tenstorrent Inc.

# Include directories
+incdir+$OCH_ROOT/hw/sys/dtp/rtl
+incdir+$OCH_ROOT/hw/common/ocah_prim/rtl
+incdir+$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim/rtl
+incdir+$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl

# Package files (must be compiled first)
$OCH_ROOT/hw/common/ocah_prim/rtl/prim_jtag_pkg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_tap_pkg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_inst_reg_pkg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_tmp_pkg.sv

# Primitive JTAG modules
$OCH_ROOT/hw/common/ocah_prim/rtl/prim_jtag_scan_reg.sv
$OCH_ROOT/hw/common/ocah_prim/rtl/prim_jtag_sib_mux_pre.sv
$OCH_ROOT/hw/common/ocah_prim/rtl/prim_jtag_sib_mux_post.sv

# JTAG PTAP modules
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_tap_ctrlr.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_inst_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_byp_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_inv_byp_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_3dcr_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_idcode_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_tmp.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_tmp_status_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_ic_reset_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_debug_ctrl_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_caps_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_jtag2axi_caps_reg.sv
$OCH_ROOT/hw/ip/jtag/jtag_ptap/rtl/jtag_ptap.sv

# JTAG STAP module
$OCH_ROOT/hw/ip/jtag/jtag_stap/rtl/jtag_stap.sv

# JTAG Interface Unit
$OCH_ROOT/hw/ip/jtag/jtag_intf_unit/rtl/jtag_intf_unit.sv

# Top-level DTP module
$OCH_ROOT/hw/sys/dtp/rtl/dtp.sv

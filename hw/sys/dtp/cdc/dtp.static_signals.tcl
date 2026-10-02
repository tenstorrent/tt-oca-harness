# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
########################################################
# Quasi Static Signals (DTP)
########################################################
# Hierarchy-reusable: port references go through cdc_port_or_pin (get_ports at the DTP
# top, u_dtp/<port> instance pins at the SMU top). CDC-only (create_static).

if { [info procs cdc_is_block_top] eq "" } {
    source $::env(GIT_ROOT)/flows/synth/constraints/cdc_hier_procs.tcl
}

# Debug-disable straps: fuse/CSR sourced feature gating, programmed before any debug
# activity and stable during operation. Declaring them quasi-static also exempts the
# reconvergence of their per-bit gen_dbg_disable_sync_n0_scan syncs at the JTAG scan muxes
# (CDC_COHERENCY_RECONV_SEQ at ptap_stap_host_scan_in / u_dft_*_sib).
set _dtp_dbg_disable [cdc_port_or_pin {dbg_disable_i*}]
if { [sizeof_collection $_dtp_dbg_disable] > 0 } {
    create_static -name $_dtp_dbg_disable
} else {
    puts "WARNING: dtp_static_signals: no dbg_disable_i objects found - skipped"
}

unset -nocomplain _dtp_dbg_disable

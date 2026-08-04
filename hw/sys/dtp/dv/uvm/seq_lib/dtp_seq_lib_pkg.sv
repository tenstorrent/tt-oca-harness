// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// dtp_jtag_base_seq issues ocah_jtag_item transactions on the shared
// ocah_jtag_vip agent's sequencer (the SV analogue of the cocotb
// dtp_jtag_base_test_seq): TAP reset, IR/DR scans, raw TMS walks, DTP-local
// reset sequencing, scan-path checks, and the BYPASS latency check.
// Pin-level driving lives in the VIP driver; per-cycle FSM legality and
// closure live in the env's dtp_tap_fsm_checker. Scenario sequences
// (dtp_sanity_seq, ...) extend the base.

`timescale 1ns/1ps

package dtp_seq_lib_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    import ocah_jtag_uvm_pkg::*;
    import jtag_tap_pkg::*;       // DUT one-hot tap_state_e for scan-path checks
    import jtag_inst_reg_pkg::*;

    `include "dtp_jtag_base_seq.svh"
    `include "dtp_sanity_seq.svh"

endpackage : dtp_seq_lib_pkg

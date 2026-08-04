// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM sequence library package (`<DUT>_seq_lib_pkg` convention).
//
// dtp_jtag_base_seq holds the reusable pin-level JTAG driving tasks and the
// IEEE 1149.1 reference model/checkers (the SV analogue of the cocotb
// dtp_jtag_base_test_seq). Scenario sequences (dtp_sanity_seq, ...) extend it.
//
// Sequences currently run sequencer-less (`seq.start(null)`) and drive the
// virtual interfaces directly; when the shared ocah_jtag_vip grows its SV-UVM
// agent (uvm/ folder), the driving tasks migrate into the VIP driver and
// these become ordinary sequences on its sequencer.

`timescale 1ns/1ps

package dtp_seq_lib_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    import jtag_tap_pkg::*;
    import jtag_inst_reg_pkg::*;

    `include "dtp_jtag_base_seq.svh"
    `include "dtp_sanity_seq.svh"

endpackage : dtp_seq_lib_pkg

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local TB interface for the SV-UVM flow: system/power-on resets
// (sequenced by the test) and the DUT-produced one-hot IEEE 1149.1 TAP state
// used by the FSM reference-model checks. Deliberately separate from the
// shared ocah_jtag_if, which carries generic JTAG pins only.

interface dtp_tb_if;

    // Driven by the TB (reset sequencing owned by the test/sequence).
    logic por_rst_n;
    logic sys_rst_n;

    // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
    logic [15:0] tap_state;

endinterface : dtp_tb_if

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Generic pin-level IEEE 1149.1 JTAG interface, shared across OCAH DUTs
// (DTP and SMU expose these exact raw TAP pins at their TB tops).
//
// Scope: JTAG pins ONLY. DUT-specific TB collateral (system resets, decoded
// TAP-state observables, ...) belongs in a DUT-local interface next to that
// DUT's tb_top, never here.
//
// This is the SystemVerilog side of ocah_jtag_vip; the cocotb BFM lives in
// the sibling Python modules. Framework-specific agents (uvm/, cocotb/) will
// join this interface as the VIP grows per-framework folders.

interface ocah_jtag_if;

    // Driven by the TB (BFM / sequence / agent driver).
    logic tck;
    logic tms;
    logic trst_n;   // active-low asynchronous TAP reset
    logic tdi;

    // Driven by the DUT.
    logic tdo;
    logic tdo_oen;

endinterface : ocah_jtag_if

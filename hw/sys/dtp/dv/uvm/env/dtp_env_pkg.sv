// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: the environment builds the shared
// ocah_jtag_vip agent and the DTP TAP FSM checker; further agents and
// scoreboards attach here as the flow matures.

`timescale 1ns/1ps

package dtp_env_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    import ocah_jtag_uvm_pkg::*;
    import ocah_axi_uvm_pkg::*;   // passive AXI monitor/ref-model/scoreboard (issue #3295)
    import jtag_tap_pkg::*;       // DUT one-hot tap_state_e + is_onehot/is_valid helpers

    `include "dtp_tap_fsm_checker.svh"
    `include "dtp_env.svh"

endpackage : dtp_env_pkg

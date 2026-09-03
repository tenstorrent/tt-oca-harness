// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment package (`<DUT>_env_pkg` convention). Everything in
// uvm/env/ is REUSABLE across tests: DUT constants and codecs, the two
// configuration levels, the virtual sequencer, the reference models the
// scoreboard and the scan scenarios predict from, the always-on scoreboard
// and subscribers, and the environment that composes the shared VIPs.
// Compiles before dtp_seq_lib_pkg, whose virtual sequences run on the
// dtp_virtual_sequencer declared here.
//
// Include order is load-bearing: types first (every class reads them), then
// the cfgs (the env cfg derives from the test cfg), the virtual sequencer,
// the plain model classes, the subscribers and the scoreboard, the env last.

`timescale 1ns/1ps

package dtp_env_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    import ocah_checker_uvm_pkg::*; // protocol-neutral named-evidence base
    import ocah_lib_pkg::*;         // shared framework bases, knobs, rng
    import ocah_jtag_uvm_pkg::*;
    import ocah_axi_uvm_pkg::*;
    import jtag_tap_pkg::*;         // DUT one-hot tap_state_e + is_onehot/is_valid helpers
    import jtag_inst_reg_pkg::*;    // DUT instruction opcodes and decoded one-hots

    `include "dtp_types.svh"
    `include "dtp_test_cfg.svh"
    `include "dtp_env_cfg.svh"
    `include "dtp_virtual_sequencer.svh"

    // Plain reference models (no UVM parent): iJTAG SIB gating, one
    // downstream STAP TAP, the PTAP 3DCR + STAP chain, the CTM routing OR.
    `include "dtp_ijtag_sib_model.svh"
    `include "dtp_stap_ds_state.svh"
    `include "dtp_stap_3dcr_model.svh"
    `include "dtp_xtrig_ctm_ref_model.svh"

    `include "dtp_tap_fsm_checker.svh"
    `include "dtp_scan_window_monitor.svh"
    `include "dtp_scoreboard.svh"
    `include "dtp_env.svh"

endpackage : dtp_env_pkg

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_jtag_vip SV-UVM package: reusable IEEE 1149.1 JTAG agent driving/
// observing the shared pin-level ocah_jtag_if (interface/ocah_jtag_if.sv).
//
// Contents (include order is load-bearing):
//   ocah_jtag_types.svh        — encoding-agnostic TAP state enum + next-state table
//   ocah_jtag_event.svh        — passive monitor observation event (STEP / TRST)
//   ocah_jtag_scan_item.svh    — reconstructed IR/DR scan record
//   ocah_jtag_item.svh         — stimulus sequence item (TAP_RESET/IR_SCAN/DR_SCAN/RAW_TMS)
//   ocah_jtag_cfg.svh          — agent configuration (vif, activity, TCK timing)
//   ocah_jtag_sequencer.svh    — sequencer typedef
//   ocah_jtag_driver.svh       — pin-level TCK bit-bang driver
//   ocah_jtag_monitor.svh      — passive per-TCK step / TRST observer
//   ocah_jtag_scan_builder.svh — IR/DR scan reconstruction over the step stream
//   ocah_jtag_checker.svh      — named-evidence checker with TAP reference model
//   ocah_jtag_agent.svh        — standard agent bundle
//   ocah_jtag_env.svh          — VIP-level env: the unit DUTs instantiate and
//                                commercial-VIP integrations override
//
// The monitor publishes raw observations only. ocah_jtag_scan_builder layers
// IR/DR scan reconstruction on the step stream, and ocah_jtag_checker owns
// named TAP-contract evidence (issue tt-oca-hw#3296); pairing steps with a
// DUT's decoded TAP state remains a DUT-side subscriber's job (e.g. DTP's
// dtp_tap_fsm_checker).

`timescale 1ns/1ps

package ocah_jtag_uvm_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    `include "ocah_jtag_types.svh"
    `include "ocah_jtag_event.svh"
    `include "ocah_jtag_scan_item.svh"
    `include "ocah_jtag_item.svh"
    `include "ocah_jtag_cfg.svh"
    `include "ocah_jtag_sequencer.svh"
    `include "ocah_jtag_driver.svh"
    `include "ocah_jtag_monitor.svh"
    `include "ocah_jtag_scan_builder.svh"
    `include "ocah_jtag_checker.svh"
    `include "ocah_jtag_agent.svh"
    `include "ocah_jtag_env.svh"

endpackage : ocah_jtag_uvm_pkg

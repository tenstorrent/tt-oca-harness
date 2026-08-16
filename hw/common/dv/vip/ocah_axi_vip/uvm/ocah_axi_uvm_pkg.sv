// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_vip SV-UVM package: PASSIVE AXI4/AXI4-Lite observation over the
// shared ocah_axi_if (interface/ocah_axi_if.sv) — monitor, reference model,
// scoreboard with named CHK-* evidence, and optional coverage subscriber.
// There is deliberately no driver/sequencer/agent: active SV-UVM stimulus is
// tracked separately (BFM issue #2906); DUT bridges or responders generate
// the traffic this layer observes (checker issue #3295).
//
// Contents (include order is load-bearing):
//   ocah_axi_types.svh      — resp/protocol/dir/burst enums (cocotb-matching
//                             encodings) + worst-resp helpers
//   ocah_axi_item.svh       — completed-transaction record (max-width fields)
//   ocah_axi_cfg.svh        — vif, geometry, gating, expected-response arming
//   ocah_axi_checker.svh    — CHK-*/CHECKER_SUMMARY evidence mechanics
//   ocah_axi_monitor.svh    — passive burst reconstruction (per-ID pairing)
//   ocah_axi_ref_model.svh  — shadow memory + expected-item prediction
//   ocah_axi_cov_sub.svh    — optional ocah_axi_cov_if sampler (VCS-only)
//   ocah_axi_scoreboard.svh — in-order pairing + evidence + finalization
//   ocah_axi_env.svh        — cfg-gated bundle DUT environments instantiate
//
// The clean-room SVA protocol checker (sva/ocah_axi_protocol_checker.sv) and
// the behavioral responders (sv/ocah_axi{l,}_ram_responder.sv) are module
// collateral compiled alongside this package, not part of it.

`timescale 1ns/1ps

package ocah_axi_uvm_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    `include "ocah_axi_types.svh"
    `include "ocah_axi_item.svh"
    `include "ocah_axi_cfg.svh"
    `include "ocah_axi_checker.svh"
    `include "ocah_axi_monitor.svh"
    `include "ocah_axi_ref_model.svh"
    `include "ocah_axi_cov_sub.svh"
    `include "ocah_axi_scoreboard.svh"
    `include "ocah_axi_env.svh"

endpackage : ocah_axi_uvm_pkg

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_vip SV-UVM package: AXI4/AXI4-Lite verification over the shared
// ocah_axi_if (interface/ocah_axi_if.sv) — the side-neutral PASSIVE
// observation stack (monitor, reference model, scoreboard with named CHK-*
// evidence, optional coverage subscriber, cfg-gated env) plus the ACTIVE
// slave side (reactive memory-backed responder agent). The master side
// (active SV-UVM initiator) is not shipped yet; DUT bridges generate the
// master-side traffic this layer observes and answers.
//
// Contents (include order is load-bearing):
//   ocah_axi_types.svh          — resp/protocol/dir/burst enums (cocotb-
//                                 matching encodings) + worst-resp helpers
//   ocah_axi_item.svh           — completed-transaction record (max widths)
//   ocah_axi_config.svh         — passive cfg: vif, geometry, gating,
//                                 expected-response arming
//   ocah_axi_slave_config.svh   — slave cfg: vif, memory, one-shot injection
//   ocah_axi_checker.svh        — CHK-*/CHECKER_SUMMARY evidence mechanics
//   ocah_axi_monitor.svh        — passive burst reconstruction (per-ID
//                                 pairing; side-neutral bus observer)
//   ocah_axi_ref_model.svh      — shadow memory + expected-item prediction
//   ocah_axi_slave_driver.svh   — reactive memory-backed responder (device)
//   ocah_axi_cov.svh            — optional ocah_axi_cov_if sampler (VCS-only)
//   ocah_axi_scoreboard.svh     — in-order pairing + evidence + finalization
//   ocah_axi_slave_sequence.svh — slave test-facing API (backdoor/inject)
//   ocah_axi_slave_agent.svh    — slave agent bundle (reactive: no sequencer)
//   ocah_axi_env.svh            — cfg-gated PASSIVE bundle DUT environments
//                                 instantiate (side-neutral; no side token)
//
// The clean-room SVA protocol checker (sva/ocah_axi_sva.sv) and
// the behavioral responders (sv/ocah_axi{l,}_ram_responder.sv) are module
// collateral compiled alongside this package, not part of it.

`timescale 1ns/1ps

package ocah_axi_uvm_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    `include "ocah_axi_types.svh"
    `include "ocah_axi_item.svh"
    `include "ocah_axi_config.svh"
    `include "ocah_axi_slave_config.svh"
    `include "ocah_axi_checker.svh"
    `include "ocah_axi_monitor.svh"
    `include "ocah_axi_ref_model.svh"
    `include "ocah_axi_slave_driver.svh"
    `include "ocah_axi_cov.svh"
    `include "ocah_axi_scoreboard.svh"
    `include "ocah_axi_slave_sequence.svh"
    `include "ocah_axi_slave_agent.svh"
    `include "ocah_axi_env.svh"

endpackage : ocah_axi_uvm_pkg

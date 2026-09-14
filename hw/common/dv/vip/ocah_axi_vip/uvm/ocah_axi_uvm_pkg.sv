// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_vip SV-UVM package: AXI4/AXI4-Lite verification over the shared
// ocah_axi_if (interface/ocah_axi_if.sv) — the side-neutral PASSIVE
// observation stack (monitor, reference model, scoreboard with named CHK-*
// evidence, optional coverage subscriber, cfg-gated env), the ACTIVE slave
// side (reactive memory-backed responder agent with one-shot fault
// controls), and the ACTIVE master side (initiator agent driven through the
// ocah_axi_master_sequence API; results carry live-sampled response IDs).
//
// Contents (include order is load-bearing):
//   ocah_axi_types.svh            — resp/protocol/dir/burst enums (cocotb-
//                                   matching encodings) + worst-resp helpers
//   ocah_axi_item.svh             — completed-transaction record (max
//                                   widths); doubles as the master sequence
//                                   item and result object
//   ocah_axi_config.svh           — passive cfg: vif, geometry, gating,
//                                   expected-response arming
//   ocah_axi_slave_config.svh     — slave cfg: vif, memory, one-shot
//                                   injection (responses and response IDs)
//   ocah_axi_master_config.svh    — master cfg: vif, geometry, watchdog
//   ocah_axi_checker.svh          — AXI checker identity over the shared
//                                   ocah_checker evidence base
//                                   (ocah_checker_uvm_pkg)
//   ocah_axi_monitor.svh          — passive burst reconstruction (per-ID
//                                   pairing; side-neutral bus observer)
//   ocah_axi_ref_model.svh        — shadow memory + expected-item prediction
//   ocah_axi_slave_driver.svh     — reactive memory-backed responder (device)
//   ocah_axi_master_driver.svh    — active initiator (AW/W/B, AR/R engines)
//   ocah_axi_master_sequencer.svh — standard sequencer over ocah_axi_item
//   ocah_axi_master_sequence.svh  — master test-facing API (write/read/burst
//                                   result operations)
//   ocah_axi_cov.svh              — optional ocah_axi_cov_if sampler (VCS-only)
//   ocah_axi_scoreboard.svh       — in-order pairing + evidence + finalization
//   ocah_axi_slave_sequence.svh   — slave test-facing API (backdoor/inject)
//   ocah_axi_slave_agent.svh      — slave agent bundle (reactive: no sequencer)
//   ocah_axi_master_agent.svh     — master agent bundle (driver + sequencer;
//                                   observation stays with the passive env)
//   ocah_axi_env.svh              — cfg-gated PASSIVE bundle DUT environments
//                                   instantiate (side-neutral; no side token)
//   ocah_axi_master_env.svh       — master env (frozen surface: m_sequencer,
//                                   cfg; the commercial-override unit)
//
// The clean-room SVA protocol checker (sva/ocah_axi_sva.sv) and the
// struct-port bridge (interface/ocah_axi_struct_bridge.sv) are module
// collateral compiled alongside this package, not part of it.

`timescale 1ns / 1ps

package ocah_axi_uvm_pkg;

  import uvm_pkg::*;
  import ocah_checker_uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "ocah_axi_types.svh"
  `include "ocah_axi_item.svh"
  `include "ocah_axi_config.svh"
  `include "ocah_axi_slave_config.svh"
  `include "ocah_axi_master_config.svh"
  `include "ocah_axi_checker.svh"
  `include "ocah_axi_monitor.svh"
  `include "ocah_axi_ref_model.svh"
  `include "ocah_axi_slave_driver.svh"
  `include "ocah_axi_master_driver.svh"
  `include "ocah_axi_master_sequencer.svh"
  `include "ocah_axi_master_sequence.svh"
  `include "ocah_axi_cov.svh"
  `include "ocah_axi_scoreboard.svh"
  `include "ocah_axi_slave_sequence.svh"
  `include "ocah_axi_slave_agent.svh"
  `include "ocah_axi_master_agent.svh"
  `include "ocah_axi_env.svh"
  `include "ocah_axi_master_env.svh"

endpackage : ocah_axi_uvm_pkg

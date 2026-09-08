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
//   ocah_jtag_master_config.svh    — master agent configuration (vif, activity, TCK timing, en_cov)
//   ocah_jtag_slave_config.svh     — slave device configuration (IDCODE, IR width, register map)
//   ocah_jtag_ref_model.svh        — IEEE 1149.1 TAP controller reference model
//   ocah_jtag_master_sequencer.svh — sequencer typedef
//   ocah_jtag_master_sequence.svh  — VIP-level base sequence (master stimulus API)
//   ocah_jtag_master_driver.svh    — pin-level TCK bit-bang driver (host side)
//   ocah_jtag_slave_driver.svh     — reactive TAP device responder (device side)
//   ocah_jtag_master_monitor.svh   — passive per-TCK step / TRST observer
//   ocah_jtag_slave_monitor.svh    — same observation for slave-side agents
//   ocah_jtag_scan_builder.svh     — IR/DR scan reconstruction over the step stream
//   ocah_jtag_checker.svh          — TAP-contract checker over the reference model
//                                    and the shared ocah_checker evidence base
//                                    (ocah_checker_uvm_pkg)
//   ocah_jtag_slave_sequence.svh   — slave test-facing API (configure/inspect the device)
//   ocah_jtag_cov.svh              — optional functional-coverage subscriber (cfg.en_cov)
//   ocah_jtag_master_agent.svh     — master agent bundle
//   ocah_jtag_slave_agent.svh      — slave agent bundle (reactive: no sequencer)
//   ocah_jtag_master_env.svh       — VIP-level env: the unit DUTs instantiate and
//                                    commercial-VIP integrations override
//
// Sibling non-package collateral: sva/ocah_jtag_sva.sv (protocol assertions,
// also listed by cocotb/Verilator builds) and cov/ocah_jtag_cov.sv
// (covergroup interface, commercial-simulator filelists only).
//
// The monitor publishes raw observations only. ocah_jtag_scan_builder layers
// IR/DR scan reconstruction on the step stream, and ocah_jtag_checker owns
// named TAP-contract evidence; pairing steps with a DUT's decoded TAP state
// remains a DUT-side subscriber's job (e.g. DTP's dtp_tap_fsm_checker).

`timescale 1ns / 1ps

package ocah_jtag_uvm_pkg;

  import uvm_pkg::*;
  import ocah_checker_uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "ocah_jtag_types.svh"
  `include "ocah_jtag_event.svh"
  `include "ocah_jtag_scan_item.svh"
  `include "ocah_jtag_item.svh"
  `include "ocah_jtag_master_config.svh"
  `include "ocah_jtag_slave_config.svh"
  `include "ocah_jtag_ref_model.svh"
  `include "ocah_jtag_master_sequencer.svh"
  `include "ocah_jtag_master_sequence.svh"
  `include "ocah_jtag_master_driver.svh"
  `include "ocah_jtag_slave_driver.svh"
  `include "ocah_jtag_master_monitor.svh"
  `include "ocah_jtag_slave_monitor.svh"
  `include "ocah_jtag_scan_builder.svh"
  `include "ocah_jtag_checker.svh"
  `include "ocah_jtag_slave_sequence.svh"
  `include "ocah_jtag_cov.svh"
  `include "ocah_jtag_master_agent.svh"
  `include "ocah_jtag_slave_agent.svh"
  `include "ocah_jtag_master_env.svh"

endpackage : ocah_jtag_uvm_pkg

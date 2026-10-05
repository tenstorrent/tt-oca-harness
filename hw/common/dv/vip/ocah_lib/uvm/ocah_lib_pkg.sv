// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// OCAH shared framework library, SV-UVM realization (`ocah_lib_pkg`). Every
// bench class extends a library base instead of a bare UVM class, so the
// knob transport, the seed and loop policy, the pass banner, the scoreboard
// feature registry, and the evidence plumbing are written once. Each base
// takes the UVM class name with `uvm_` replaced by `ocah_`; utilities with
// no UVM ancestor take `ocah_` plus a noun. The cocotb twin is the Python
// package `ocah_lib` with identical basenames.
//
// Include order is load-bearing: knobs and rng have no dependencies; the two
// cfg bases precede the test; the item precedes the sequence; the scoreboard
// and the subscriber compose ocah_checker (imported from ocah_checker_uvm_pkg);
// the reference model precedes the scoreboard it feeds; the env and the test
// come last because they reference the others.
//
// The pass banner and the step formats are methods on ocah_test and
// ocah_sequence. SV interfaces cannot inherit, so each bench's base test
// owns bring_up() through its own <dut>_tb_if.

`timescale 1ns / 1ps

package ocah_lib_pkg;

  import uvm_pkg::*;
  import ocah_checker_uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "ocah_knobs.svh"
  `include "ocah_rng.svh"
  `include "ocah_test_cfg.svh"
  `include "ocah_env_cfg.svh"
  `include "ocah_sequence_item.svh"
  `include "ocah_sequence.svh"
  `include "ocah_sequencer.svh"
  `include "ocah_driver.svh"
  `include "ocah_monitor.svh"
  `include "ocah_agent.svh"
  `include "ocah_subscriber.svh"
  `include "ocah_ref_model.svh"
  `include "ocah_scoreboard.svh"
  `include "ocah_env.svh"
  `include "ocah_test.svh"

endpackage : ocah_lib_pkg

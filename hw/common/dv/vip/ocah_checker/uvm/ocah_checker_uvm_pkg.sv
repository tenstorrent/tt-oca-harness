// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared SV-UVM checker-evidence package: the protocol-neutral
// CHK-*/CHECKER_SUMMARY mechanics every ocah_<protocol>_vip UVM checker
// extends -- the SV mirror of the shared cocotb ocah_checker layer. Compiled
// ahead of the protocol VIP packages: each dependent VIP manifest lists this
// package before its own, and the flow's source-list expansion dedup-merges
// the entry when several VIPs are consumed together.

`timescale 1ns / 1ps

package ocah_checker_uvm_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "ocah_checker.svh"

endpackage : ocah_checker_uvm_pkg

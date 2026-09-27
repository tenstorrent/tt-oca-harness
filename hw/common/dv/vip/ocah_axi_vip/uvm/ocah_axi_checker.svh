// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI protocol checker over the shared evidence base: the named
// CHK-*/CHECKER_SUMMARY mechanics live in ocah_checker_uvm_pkg::ocah_checker
// (the SV mirror of ocah_checker/cocotb/checker.py), and this subclass owns
// only the AXI identity. AXI protocol legality itself is checked by the SVA
// collateral and the scoreboard's reference-model pairing; they report their
// findings through this checker's inherited API.

class ocah_axi_checker extends ocah_checker;
  `uvm_object_utils(ocah_axi_checker)

  function new(string name = "ocah_axi_checker");
    super.new(name);
    name_tag = "ocah_axi";
  endfunction

endclass : ocah_axi_checker

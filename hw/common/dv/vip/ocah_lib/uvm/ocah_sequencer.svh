// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Sequencer base mirroring uvm_sequencer. Typed by a VIP item it is the
// parent a VIP master sequencer adopts; with the default item type it is
// the parent of every <dut>_virtual_sequencer, which adds one typed handle
// per agent sequencer and one per responder sequence and nothing else. The
// cocotb twin is ocah_lib.OcahSequencer.

class ocah_sequencer #(
  type REQ = uvm_sequence_item,
  type RSP = REQ
) extends uvm_sequencer #(REQ, RSP);
  `uvm_component_param_utils(ocah_sequencer#(REQ, RSP))

  function new(string name = "ocah_sequencer", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass : ocah_sequencer

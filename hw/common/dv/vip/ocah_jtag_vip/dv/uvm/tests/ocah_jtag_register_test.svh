// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_jtag_register_test: see ocah_jtag_register_test_seq.svh for the scenario.

class ocah_jtag_register_test extends ocah_jtag_vip_base_test;
  `uvm_component_utils(ocah_jtag_register_test)

  function new(string name = "ocah_jtag_register_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    string ids[$] = {"CHK-SLAVE-DR-UPDATE",
                     "CHK-SLAVE-DR-UPDATE-COUNT",
                     "CHK-SLAVE-REG",
                     "CHK-JTAG-DR-READBACK",
                     "CHK-JTAG-DR-PAUSE",
                     "CHK-JTAG-DR-CAPTURE-ONLY",
                     "CHK-JTAG-RO-CAPTURE",
                     "CHK-SCAN-IR-LEN",
                     "CHK-SCAN-DR-LEN"};
    super.end_of_elaboration_phase(phase);
    require_ids(ids);
  endfunction

  task run_phase(uvm_phase phase);
    ocah_jtag_register_test_seq seq = ocah_jtag_register_test_seq::type_id::create("seq");
    run_scenario(seq, phase);
  endtask
endclass : ocah_jtag_register_test

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_irq_ip_to_aggregator_test (`--items sep_irq_ip_to_aggregator_test`):
// runs sep_irq_ip_to_aggregator_test_seq on the environment's virtual
// sequencer once per pass. The scenario does no predicted cpu_ctrl CSR
// read, so it requires no scoreboard feature; its evidence is the
// sequence's named checks.

class sep_irq_ip_to_aggregator_test extends sep_base_test;
  `uvm_component_utils(sep_irq_ip_to_aggregator_test)

  function new(string name = "sep_irq_ip_to_aggregator_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_irq_ip_to_aggregator_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_IRQ_IP_TO_AGGREGATOR_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_SYSTEM_TEST_LOOPS";
  endfunction

endclass : sep_irq_ip_to_aggregator_test

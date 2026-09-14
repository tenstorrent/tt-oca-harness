// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_rand_deterministic_csr_sweep_test — exhaustive CTP config/stretch/byte-strobe CSR sweep in seeded order
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_xtrig_rand_deterministic_csr_sweep_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_rand_deterministic_csr_sweep_test)

  function new(string name = "dtp_xtrig_rand_deterministic_csr_sweep_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "ctp_csr_sweep";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_RAND_DETERMINISTIC_CSR_SWEEP_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_rand_deterministic_csr_sweep_test

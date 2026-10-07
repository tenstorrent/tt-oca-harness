// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_scan_dbg_disable_matrix_test — the debug-disable matrix over the
// eight scan-side gate fields: one-hot, boundary, and seeded multi-hot
// rows with temporal-window and chain-readback outcome proofs. The matrix
// runs one pass, which sweeps one all_clear row, one one-hot row per
// scan-side gate field, the configured number of seeded multi-hot rows, and
// one all_disabled row.

class dtp_scan_dbg_disable_matrix_test extends dtp_base_test;
  `uvm_component_utils(dtp_scan_dbg_disable_matrix_test)

  function new(string name = "dtp_scan_dbg_disable_matrix_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_scan_dbg_disable_matrix_test_seq seq =
            dtp_scan_dbg_disable_matrix_test_seq::type_id::create(
        "seq"
    );
    seq.multi_hot_rows = test_cfg.scan_matrix_multi_hot_rows;
    return seq;
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this, {get_type_name(), " running"});
    run_single_scenario();
    phase.drop_objection(this, {get_type_name(), " done"});
  endtask

endclass : dtp_scan_dbg_disable_matrix_test

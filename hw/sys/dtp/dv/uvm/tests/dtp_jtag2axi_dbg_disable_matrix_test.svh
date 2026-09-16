// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_dbg_disable_matrix_test — the debug-disable matrix over the
// three JTAG2AXI bridge gate fields: allowed bridges complete write+read
// with real request activity, blocked bridges show zero activity with RAM
// sentinels intact through release (no delayed replay), then recover. Each
// matrix pass sweeps one all_clear row, one one-hot row per bridge gate
// field, the configured number of seeded multi-hot rows, and one
// all_disabled row.

class dtp_jtag2axi_dbg_disable_matrix_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_dbg_disable_matrix_test)

  function new(string name = "dtp_jtag2axi_dbg_disable_matrix_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-RDATA");
    ids.push_back("CHK-AXI-GATE-AW");
    ids.push_back("CHK-AXI-GATE-W");
    ids.push_back("CHK-AXI-GATE-AR");
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_dbg_disable_jtag2axi_matrix_test_seq seq =
            dtp_dbg_disable_jtag2axi_matrix_test_seq::type_id::create(
        "seq"
    );
    seq.multi_hot_rows = test_cfg.jtag2axi_matrix_multi_hot_rows;
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_DBG_DISABLE_MATRIX_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_dbg_disable_matrix_test

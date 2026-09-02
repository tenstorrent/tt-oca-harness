// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_dbg_disable_matrix_test — the debug-disable matrix over the
// three JTAG2AXI bridge gate fields: allowed bridges complete write+read
// with real request activity, blocked bridges show zero activity with RAM
// sentinels intact through release (no delayed replay), then recover. One
// matrix pass carries 16 seeded rows (1 all_clear + 3 one-hot + 11
// multi-hot + 1 all_disabled), meeting the 16-iteration floor in a single
// pass.

class dtp_jtag2axi_dbg_disable_matrix_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_dbg_disable_matrix_test)

  function new(string name = "dtp_jtag2axi_dbg_disable_matrix_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void add_required_axi_ids(ocah_axi_config cfg);
    super.add_required_axi_ids(cfg);
    cfg.required_ids.push_back("CHK-AXI-WADDR");
    cfg.required_ids.push_back("CHK-AXI-WDATA");
    cfg.required_ids.push_back("CHK-AXI-STRB");
    cfg.required_ids.push_back("CHK-AXI-RDATA");
    cfg.required_ids.push_back("CHK-AXI-GATE-AW");
    cfg.required_ids.push_back("CHK-AXI-GATE-W");
    cfg.required_ids.push_back("CHK-AXI-GATE-AR");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_dbg_disable_jtag2axi_matrix_test_seq seq =
            dtp_dbg_disable_jtag2axi_matrix_test_seq::type_id::create(
        "seq"
    );
    int unsigned rows;
    if ($value$plusargs("DTP_DBG_DISABLE_MULTI_HOT_ROWS=%d", rows)) seq.multi_hot_rows = rows;
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG2AXI_DBG_DISABLE_MATRIX_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_dbg_disable_matrix_test

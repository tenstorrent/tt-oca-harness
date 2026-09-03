// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_backpressure_abort_at_data_w_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// System-reset pulse after a write issued against a stalled W channel
// on every bridge; a recovery write with memory-vs-intent compare
// proves no stuck bridge state.

class dtp_jtag2axi_backpressure_abort_at_data_w_test extends dtp_jtag2axi_robustness_base_test;
    `uvm_component_utils(dtp_jtag2axi_backpressure_abort_at_data_w_test)

    function new(string name = "dtp_jtag2axi_backpressure_abort_at_data_w_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    virtual function string scenario_name();
        return "backpressure_abort_at_data_w";
    endfunction

    virtual function string specific_loops_knob();
        return "DTP_JTAG2AXI_BACKPRESSURE_ABORT_AT_DATA_W_TEST_LOOPS";
    endfunction

    virtual function void add_required_axi_ids(ref string ids[$]);
        super.add_required_axi_ids(ids);
        ids.push_back("CHK-AXI-WADDR");
        ids.push_back("CHK-AXI-WDATA");
        ids.push_back("CHK-AXI-STRB");
        ids.push_back("CHK-AXI-WMEM");
    endfunction

endclass : dtp_jtag2axi_backpressure_abort_at_data_w_test

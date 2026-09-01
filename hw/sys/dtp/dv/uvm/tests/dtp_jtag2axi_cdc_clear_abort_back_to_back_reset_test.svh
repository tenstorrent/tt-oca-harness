// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Two adjacent system-reset pulses with seeded spacing on every
// bridge, then recovery write and read accesses prove the bridges
// come back clean after repeated CDC clears.

class dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test extends dtp_jtag2axi_robustness_base_test;
    `uvm_component_utils(dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test)

    function new(string name = "dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    virtual function string scenario_name();
        return "cdc_clear_abort_back_to_back_reset";
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_JTAG2AXI_CDC_CLEAR_ABORT_BACK_TO_BACK_RESET_TEST_LOOPS";
    endfunction

    virtual function void add_required_axi_ids(ocah_axi_config cfg);
        super.add_required_axi_ids(cfg);
        cfg.required_ids.push_back("CHK-AXI-WADDR");
        cfg.required_ids.push_back("CHK-AXI-WDATA");
        cfg.required_ids.push_back("CHK-AXI-STRB");
        cfg.required_ids.push_back("CHK-AXI-RADDR");
        cfg.required_ids.push_back("CHK-AXI-RDATA");
        cfg.required_ids.push_back("CHK-AXI-WMEM");
    endfunction

endclass : dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM tests (`<DUT>_tests.sv` convention). Tests are non-reusable by
// definition, so they are NOT packaged: this file is `include`d in module
// scope by tb/tb_top.sv under `ifdef DTP_UVM_TB and compiles as part of the
// top. Test classes stay thin — scenario content lives in dtp_seq_lib_pkg
// sequences; shared infrastructure lives in dtp_env_pkg.
//
// Testlist mapping (testlists/uvm.toml): logical item names are framework-
// neutral VPLAN scenario names; `module` carries the class name here and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import dtp_env_pkg::*;
import dtp_seq_lib_pkg::*;

// ---------------------------------------------------------------------
// Base test: environment construction and the pass-banner contract.
// "UVM TEST PASSED" is emitted only from report_phase and only when the
// global UVM_ERROR/UVM_FATAL counts are both zero (uvm-log parser contract);
// never from sequence or scoreboard code mid-run.
// ---------------------------------------------------------------------
class dtp_uvm_base_test extends uvm_test;
    `uvm_component_utils(dtp_uvm_base_test)

    dtp_uvm_env m_env;

    function new(string name = "dtp_uvm_base_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        m_env = dtp_uvm_env::type_id::create("m_env", this);
    endfunction

    function void report_phase(uvm_phase phase);
        uvm_report_server svr = uvm_report_server::get_server();
        super.report_phase(phase);
        if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
            `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
        else
            `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
    endfunction

endclass : dtp_uvm_base_test

// ---------------------------------------------------------------------
// dtp_uvm_sanity_test — VPLAN 0.1 (`--items dtp_sanity_test`): runs
// dtp_sanity_seq on the shared ocah_jtag_vip agent's sequencer, then
// asserts full FSM state/edge closure via the env checker (this scenario's
// closure obligation — the per-cycle legality check is always on). Also
// arms the JTAG TAP-contract named evidence (issue #3296): required CHK-*
// IDs finalize through env.m_jtag_checker in check_phase.
// ---------------------------------------------------------------------
class dtp_uvm_sanity_test extends dtp_uvm_base_test;
    `uvm_component_utils(dtp_uvm_sanity_test)

    function new(string name = "dtp_uvm_sanity_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.jtag_require_checks = 1'b1;
        m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-STATE");
        m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-RESET-TLR");
        m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-TLR-TMS5");
        m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-GOTO");
        m_env.m_jtag_checker.required_ids.push_back("CHK-TAP-TLR-IDCODE");
        m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-RAW");
        m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-STABLE");
        m_env.m_jtag_checker.required_ids.push_back("CHK-IDCODE-MARKER");
        m_env.m_jtag_checker.required_ids.push_back("CHK-BYPASS-LATENCY");
        m_env.m_jtag_checker.required_ids.push_back("CHK-SCAN-IR-LEN");
        m_env.m_jtag_checker.required_ids.push_back("CHK-SCAN-DR-LEN");
        m_env.m_jtag_checker.required_ids.push_back("CHK-NONVAC");
    endfunction

    task run_phase(uvm_phase phase);
        dtp_sanity_seq seq;
        phase.raise_objection(this, "dtp_uvm_sanity_test running");
        seq = dtp_sanity_seq::type_id::create("seq");
        seq.tb_vif       = m_env.tb_vif;
        seq.evidence     = m_env.m_jtag_checker;
        seq.scan_builder = m_env.m_scan_builder;
        seq.start(m_env.m_jtag_env.m_sequencer);
        m_env.m_fsm_checker.check_fsm_closure();
        phase.drop_objection(this, "dtp_uvm_sanity_test done");
    endtask

endclass : dtp_uvm_sanity_test

// ---------------------------------------------------------------------
// dtp_uvm_jtag2axi_smc_otp_test — issue #3295 (`--items
// dtp_jtag2axi_smc_otp_axi_single_write_read_test`): JTAG2AXI single-op
// traffic on the SMC OTP AXI-Lite port through the shared ocah_axi_vip
// passive env — randomized write/readback, armed SLVERR/DECERR classified
// as EXPECTED, security-gating no-activity, and required CHK-* evidence.
// ---------------------------------------------------------------------
class dtp_uvm_jtag2axi_smc_otp_test extends dtp_uvm_base_test;
    `uvm_component_utils(dtp_uvm_jtag2axi_smc_otp_test)

    function new(string name = "dtp_uvm_jtag2axi_smc_otp_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_otp_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AW");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AR");
    endfunction

    task run_phase(uvm_phase phase);
        dtp_jtag2axi_single_op_seq seq;
        phase.raise_objection(this, "dtp_uvm_jtag2axi_smc_otp_test running");
        seq = dtp_jtag2axi_single_op_seq::type_id::create("seq");
        seq.tb_vif        = m_env.tb_vif;
        seq.target_name   = "smc_otp";
        seq.axi_cfg       = m_env.m_smc_otp_axi_cfg;
        seq.axi_evidence  = m_env.m_smc_otp_axi_env.m_scoreboard.m_checker;
        seq.otp_slave_seq = m_env.m_smc_otp_slave_agent.seq;
        seq.start(m_env.m_jtag_env.m_sequencer);
        phase.drop_objection(this, "dtp_uvm_jtag2axi_smc_otp_test done");
    endtask

endclass : dtp_uvm_jtag2axi_smc_otp_test

// ---------------------------------------------------------------------
// dtp_uvm_jtag2axi_smc_axi_test — issue #3295 Phase B: the same single-op
// scenario on the SMC fabric AXI4 manager port (132-bit wide TDR scans,
// 64-bit data, ID-tagged bursts observed by the shared monitor).
// ---------------------------------------------------------------------
class dtp_uvm_jtag2axi_smc_axi_test extends dtp_uvm_base_test;
    `uvm_component_utils(dtp_uvm_jtag2axi_smc_axi_test)

    function new(string name = "dtp_uvm_jtag2axi_smc_axi_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AW");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AR");
    endfunction

    task run_phase(uvm_phase phase);
        dtp_jtag2axi_single_op_seq seq;
        phase.raise_objection(this, "dtp_uvm_jtag2axi_smc_axi_test running");
        seq = dtp_jtag2axi_single_op_seq::type_id::create("seq");
        seq.tb_vif       = m_env.tb_vif;
        seq.target_name  = "smc_axi";
        seq.axi_cfg      = m_env.m_smc_axi_cfg;
        seq.axi_evidence = m_env.m_smc_axi_env.m_scoreboard.m_checker;
        seq.start(m_env.m_jtag_env.m_sequencer);
        phase.drop_objection(this, "dtp_uvm_jtag2axi_smc_axi_test done");
    endtask

endclass : dtp_uvm_jtag2axi_smc_axi_test

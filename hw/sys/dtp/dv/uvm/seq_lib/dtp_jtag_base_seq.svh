// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base JTAG sequence: issues ocah_jtag_item transactions on the shared
// ocah_jtag_vip agent's sequencer (pin-level driving lives in the VIP
// driver; per-cycle FSM legality/closure checking lives in the env's
// dtp_tap_fsm_checker subscriber). This base keeps:
//   * DTP-local reset sequencing (por/sys via dtp_tb_if),
//   * scan-path state checks against the DUT one-hot TAP state
//     (sanity_scan_path_chk — coarse, after-transaction checks),
//   * the BYPASS 1-TCK latency check (sanity_bypass_latency_chk), which
//     compares spec-derived expected TDO with the DR_SCAN item response.

class dtp_jtag_base_seq extends uvm_sequence #(ocah_jtag_item);
    `uvm_object_utils(dtp_jtag_base_seq)

    localparam int unsigned IrWidth = 6;

    // Plumbed by the test from dtp_uvm_env before start(sequencer).
    virtual dtp_tb_if tb_vif;

    function new(string name = "dtp_jtag_base_seq");
        super.new(name);
    endfunction

    task do_jtag(ocah_jtag_item it);
        start_item(it);
        finish_item(it);
    endtask

    // One raw TCK step (tms/tdi) from any state.
    task step(bit tms, bit tdi = 1'b0);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("step");
        it.op       = OCAH_JTAG_RAW_TMS;
        it.tms_bits = new[1];
        it.tdi_bits = new[1];
        it.tms_bits[0] = tms;
        it.tdi_bits[0] = tdi;
        do_jtag(it);
    endtask

    // Raw TMS/TDI walk, one TCK cycle per element.
    task raw_walk(bit tms_bits[], bit tdi_bits[]);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("raw_walk");
        it.op       = OCAH_JTAG_RAW_TMS;
        it.tms_bits = tms_bits;
        it.tdi_bits = tdi_bits;
        do_jtag(it);
    endtask

    function void check_state(tap_state_e expected, string checker, string what);
        if (tb_vif.tap_state !== expected)
            `uvm_error(checker, $sformatf(
                "%s: expected TAP state %s (0x%04h), got 0x%04h",
                what, expected.name(), expected, tb_vif.tap_state))
        else
            `uvm_info(checker, $sformatf("%s: TAP state %s as expected", what, expected.name()),
                      UVM_MEDIUM)
    endfunction

    // Power-on/system reset sequencing (DTP-local, via dtp_tb_if). The JTAG
    // pins themselves idle under the VIP driver (tck=0, tms=1, trst_n=1);
    // the TAP's asynchronous reset is exercised by tap_reset() right after.
    task sys_reset();
        `uvm_info(get_type_name(), "sequencing power-on and system resets", UVM_MEDIUM)
        tb_vif.por_rst_n <= 1'b0;
        tb_vif.sys_rst_n <= 1'b0;
        #200ns;
        tb_vif.por_rst_n <= 1'b1;
        #100ns;
        tb_vif.sys_rst_n <= 1'b1;
        #100ns;
    endtask

    // TAP reset: TRST pulse via the driver -> Test-Logic-Reset.
    task tap_reset();
        ocah_jtag_item it = ocah_jtag_item::type_id::create("tap_reset");
        `uvm_info(get_type_name(), "asserting TRST for TAP reset", UVM_MEDIUM)
        it.op = OCAH_JTAG_TAP_RESET;
        do_jtag(it);
        check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after TRST release");
    endtask

    // Return to Test-Logic-Reset from any state via five TMS=1 cycles.
    task goto_tlr_via_tms();
        bit tms[] = '{1'b1, 1'b1, 1'b1, 1'b1, 1'b1};
        bit tdi[] = '{1'b0, 1'b0, 1'b0, 1'b0, 1'b0};
        raw_walk(tms, tdi);
        check_state(TEST_LOGIC_RESET, "sanity_scan_path_chk", "after 5x TMS=1");
    endtask

    // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
    task load_ir(bit [IrWidth-1:0] instr);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("ir_scan");
        `uvm_info(get_type_name(), $sformatf("IR scan: loading 0x%02h (%0d bits)", instr, IrWidth),
                  UVM_MEDIUM)
        it.op    = OCAH_JTAG_IR_SCAN;
        it.width = IrWidth;
        it.wdata = 64'(instr);
        do_jtag(it);
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after IR scan");
    endtask

    // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
    task shift_dr(input bit [63:0] pattern, input int unsigned width,
                  output bit [63:0] observed);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("dr_scan");
        it.op    = OCAH_JTAG_DR_SCAN;
        it.width = width;
        it.wdata = pattern;
        do_jtag(it);
        observed = it.tdo;
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after DR scan");
    endtask

    // sanity_bypass_latency_chk: BYPASS (IR 0x00) => exactly 1-TCK
    // TDI-to-TDO delay: observed = {pattern[width-2:0], 1'b0} LSB-first.
    task check_bypass_latency(bit [63:0] pattern, int unsigned width);
        bit [63:0] observed, expected;
        expected = ((pattern << 1) & ((width < 64) ? ((64'h1 << width) - 1) : '1));
        shift_dr(pattern, width, observed);
        if (observed !== expected)
            `uvm_error("sanity_bypass_latency_chk", $sformatf(
                "BYPASS TDI-to-TDO latency not 1 TCK: pattern=0x%016h width=%0d expected=0x%016h observed=0x%016h",
                pattern, width, expected, observed))
        else
            `uvm_info("sanity_bypass_latency_chk", $sformatf(
                "BYPASS 1-TCK latency OK: pattern=0x%016h width=%0d observed=0x%016h",
                pattern, width, observed), UVM_MEDIUM)
    endtask

endclass : dtp_jtag_base_seq

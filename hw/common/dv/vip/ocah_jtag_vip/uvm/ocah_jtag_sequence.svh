// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VIP-level base sequence: the reusable stimulus API over ocah_jtag_item.
// DUT sequence libraries extend this class and add their DUT-specific
// checking (observable TAP-state comparison, reset sequencing, evidence
// hooks) on top of these protocol-neutral operations. Scan preconditions
// follow the item contract: IR/DR scans assume Run-Test/Idle (the driver
// navigates RTI -> scan leg -> RTI).

class ocah_jtag_base_sequence extends uvm_sequence #(ocah_jtag_item);
    `uvm_object_utils(ocah_jtag_base_sequence)

    function new(string name = "ocah_jtag_base_sequence");
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

    // TAP reset: TRST pulse via the driver -> Test-Logic-Reset.
    task tap_reset_op();
        ocah_jtag_item it = ocah_jtag_item::type_id::create("tap_reset");
        it.op = OCAH_JTAG_TAP_RESET;
        do_jtag(it);
    endtask

    // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
    task ir_scan(input bit [63:0] instr, input int unsigned width,
                 output bit [63:0] captured);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("ir_scan");
        it.op    = OCAH_JTAG_IR_SCAN;
        it.width = width;
        it.wdata = instr;
        do_jtag(it);
        captured = it.tdo;
    endtask

    // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
    task dr_scan(input bit [63:0] pattern, input int unsigned width,
                 output bit [63:0] observed);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("dr_scan");
        it.op    = OCAH_JTAG_DR_SCAN;
        it.width = width;
        it.wdata = pattern;
        do_jtag(it);
        observed = it.tdo;
    endtask

    // Wide DR scan (no 64-bit limit), one bit per element, LSB-first.
    task dr_scan_wide(input bit pattern[], output bit observed[]);
        ocah_jtag_item it = ocah_jtag_item::type_id::create("dr_scan_wide");
        it.op    = OCAH_JTAG_DR_SCAN;
        it.wbits = pattern;
        do_jtag(it);
        observed = it.rbits;
    endtask

endclass : ocah_jtag_base_sequence

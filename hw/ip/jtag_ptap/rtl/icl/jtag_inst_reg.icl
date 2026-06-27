//-----------------------------------------------------------------------------
// JTAG Instruction Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1 compliant 6-bit instruction register
// Default instruction after reset is IDCODE (0x01)
// Capture value is 0x01 (LSB=1 per IEEE 1149.1 Section 7.2.1)
//-----------------------------------------------------------------------------

Module jtag_inst_reg {
    // Client scan interface (from TAP controller)
    ScanInPort     scan_in_i;
    CaptureEnPort  scan_ctrl_i__capture_en;
    ShiftEnPort    scan_ctrl_i__shift_en;
    UpdateEnPort   scan_ctrl_i__update_en;
    SelectEnPort   scan_ctrl_i__select;
    ResetPort      scan_ctrl_i__rst_n {
        ActivePolarity 0;
    }
    TCKPort        scan_ctrl_i__tck;
    ScanOutPort    scan_out_o {
        Source     ir_scan_data[0];
        Attribute  LaunchEdge = "Rising";
    }

    // Decoded instruction output (active high one-hot)
    DataOutPort    inst_decoded_o[63:0] {
        Source     ir_decoded[63:0];
    }

    ScanInterface client {
        Port  scan_in_i;
        Port  scan_ctrl_i__capture_en;
        Port  scan_ctrl_i__shift_en;
        Port  scan_ctrl_i__update_en;
        Port  scan_ctrl_i__select;
        Port  scan_ctrl_i__rst_n;
        Port  scan_ctrl_i__tck;
        Port  scan_out_o;
    }

    // 6-bit instruction scan register
    // Capture value: 6'b000001 (per IEEE 1149.1 Section 7.2.1)
    // Reset value: 6'b000001 (IDCODE instruction)
    ScanRegister ir_scan_data[5:0] {
        ScanInSource   scan_in_i;
        CaptureSource  6'b000001;
        ResetValue     6'b000001;
    }

    // Instruction decoder (one-hot encoding)
    Alias ir_decoded[63:0] = 64'b1 << ir_scan_data[5:0];
}

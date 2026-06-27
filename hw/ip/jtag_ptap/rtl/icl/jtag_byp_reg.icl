//-----------------------------------------------------------------------------
// JTAG Bypass Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1 compliant single-bit bypass register
// Captures 0 during Capture-DR, shifts during Shift-DR
//-----------------------------------------------------------------------------

Module jtag_byp_reg {
    // Client scan interface
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
        Source     bypass_data[0];
        Attribute  LaunchEdge = "Rising";
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

    // Single-bit bypass register
    // Per IEEE 1149.1 Section 10.1.1: loads 0 on capture
    ScanRegister bypass_data[0:0] {
        ScanInSource   scan_in_i;
        CaptureSource  1'b0;
        ResetValue     1'b0;
    }
}

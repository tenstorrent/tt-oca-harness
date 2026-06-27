//-----------------------------------------------------------------------------
// JTAG Inverted Bypass Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// Single-bit register with inverted output (INV_BYPASS instruction)
// Captures 0 during Capture-DR, output is inverted
//-----------------------------------------------------------------------------

Module jtag_inv_byp_reg {
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
        Source     inverted_out;
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

    // Single-bit bypass register (same as standard bypass)
    ScanRegister inv_bypass_data[0:0] {
        ScanInSource   scan_in_i;
        CaptureSource  1'b0;
        ResetValue     1'b0;
    }

    // Inverted output
    LogicSignal inverted_out {
        ~inv_bypass_data[0];
    }
}

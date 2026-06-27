//--------------------------------------------------
// JTAG Scan Register
//
// Copyright 2025 Tenstorrent Inc.
//--------------------------------------------------
Module prim_jtag_scan_reg {
    Parameter      WIDTH = 1;
    ScanInPort     scan_in_i;
    CaptureEnPort  scan_ctrl_i__capture_en;
    ShiftEnPort    scan_ctrl_i__scan_en;
    UpdateEnPort   scan_ctrl_i__update_en;
    SelectEnPort   scan_ctrl_i__select;
    ResetPort      scan_ctrl_i__rst_n {
        ActivePolarity 0;
    }
    TCKPort        scan_ctrl_i__tck;
    ScanOutPort    scan_out_o {
        Source     scan_data[0];
        Attribute  LaunchEdge = "Rising";
    }
    DataInPort     data_in_i[$WIDTH-1:0];
    DataOutPort    data_out_o[$WIDTH-1:0] {
        Source  scan_data[$WIDTH-1:0];
    }
    ScanInterface client {
        Port  scan_in_i;
        Port  scan_ctrl_i__capture_en;
        Port  scan_ctrl_i__scan_en;
        Port  scan_ctrl_i__update_en;
        Port  scan_ctrl_i__select;
        Port  scan_ctrl_i__rst_n;
        Port  scan_ctrl_i__tck;
        Port  scan_out_o;
    }
    ScanRegister  scan_data[$WIDTH-1:0] {
        ScanInSource   scan_in_i;
        CaptureSource  data_in_i[$WIDTH-1:0];
        ResetValue     $WIDTH'b0;
    }
}

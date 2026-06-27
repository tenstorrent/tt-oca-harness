//--------------------------------------------------
// JTAG SIB with MUX Before SR Register
//
// Copyright 2025 Tenstorrent Inc.
//--------------------------------------------------
Module prim_jtag_sib_mux_pre {
    ScanInPort     client_scan_in_i;
    CaptureEnPort  client_scan_ctrl_i__capture_en;
    ShiftEnPort    client_scan_ctrl_i__scan_en;
    UpdateEnPort   client_scan_ctrl_i__update_en;
    SelectEnPort   client_scan_ctrl_i__select;
    ResetPort      client_scan_ctrl_i__rst_n {
        ActivePolarity 0;
    }
    TCKPort        client_scan_ctrl_i__tck;
    ScanOutPort    client_scan_out_o {
        Source     scan_reg.scan_data[0];
        Attribute  LaunchEdge = "Rising";
    }
    ScanInterface client {
        Port  client_scan_in_i;
        Port  client_scan_ctrl_i__capture_en;
        Port  client_scan_ctrl_i__scan_en;
        Port  client_scan_ctrl_i__update_en;
        Port  client_scan_ctrl_i__select;
        Port  client_scan_ctrl_i__rst_n;
        Port  client_scan_ctrl_i__tck;
        Port  client_scan_out_o;
    }
    ScanInPort       host_scan_in_i;
    ToCaptureEnPort  host_scan_ctrl_o__capture_en;
    ToShiftEnPort    host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   host_scan_ctrl_o__update_en;
    ToSelectPort     host_scan_ctrl_o__select;
    ToResetPort      host_scan_ctrl_o__rst_n {
        ActivePolarity 0;
    }
    ToTCKPort        host_scan_ctrl_o__tck;
    ScanOutPort      host_scan_out_o {
        Source     client_scan_in_i;
        Attribute  LaunchEdge = "Rising";
    }
    ScanInterface host {
        Port  host_scan_in_i;
        Port  host_scan_ctrl_o__capture_en;
        Port  host_scan_ctrl_o__shift_en;
        Port  host_scan_ctrl_o__update_en;
        Port  host_scan_ctrl_o__select;
        Port  host_scan_ctrl_o__rst_n;
        Port  host_scan_ctrl_o__tck;
        Port  host_scan_out_o;
    }
    Instance scan_reg Of prim_jtag_scan_reg {
        Parameter  WIDTH = 1;
        InputPort  scan_in_i = sib_mux;
        InputPort  scan_ctrl_i__capture_en = client_scan_ctrl_i__capture_en;
        InputPort  scan_ctrl_i__scan_en = client_scan_ctrl_i__scan_en;
        InputPort  scan_ctrl_i__update_en = client_scan_ctrl_i__update_en;
        InputPort  scan_ctrl_i__select = client_scan_ctrl_i__select;
        InputPort  scan_ctrl_i__rst_n = client_scan_ctrl_i__rst_n;
        InputPort  scan_ctrl_i__tck = client_scan_ctrl_i__tck;
        InputPort  data_in_i = scan_reg.scan_data[0];
    }
    ScanMux sib_mux SelectedBy scan_reg.scan_data[0] {
        1'b0 : client_scan_in_i;
        1'b1 : host_scan_in_i;
    }
}

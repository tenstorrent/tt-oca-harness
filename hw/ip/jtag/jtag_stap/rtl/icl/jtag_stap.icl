//-----------------------------------------------------------------------------
// JTAG Secondary TAP (STAP) ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1838 compliant Secondary TAP interface module
// Contains SIB for STAP selection and 3DCR register for TAP control
//-----------------------------------------------------------------------------

Module jtag_stap {
    // Configuration parameters
    Parameter  SCAN_IN_PIPE    = 0;
    Parameter  TDI_LOCKUP      = 0;
    Parameter  SCAN_OUT_LOCKUP = 0;

    //-------------------------------------------------------------------------
    // Client Interface (from PTAP)
    //-------------------------------------------------------------------------

    CaptureEnPort  client_scan_ctrl_i__capture_en;
    ShiftEnPort    client_scan_ctrl_i__shift_en;
    UpdateEnPort   client_scan_ctrl_i__update_en;
    SelectEnPort   client_scan_ctrl_i__select;
    ResetPort      client_scan_ctrl_i__rst_n {
        ActivePolarity 0;
    }
    TCKPort        client_scan_ctrl_i__tck;
    ScanInPort     client_scan_in_i;
    ScanOutPort    client_scan_out_o {
        Source     u_sib.client_scan_out_o;
        Attribute  LaunchEdge = "Rising";
    }

    // TAP control from PTAP
    DataInPort     client_tap_ctrl_i__tms;
    DataInPort     client_tap_ctrl_i__trst_n;
    DataInPort     client_tap_ctrl_i__tck;

    //-------------------------------------------------------------------------
    // Host Interface (to downstream TAP)
    //-------------------------------------------------------------------------

    ToTMSPort      host_tap_ctrl_o__tms;
    ToTRSTPort     host_tap_ctrl_o__trst_n;
    ToTCKPort      host_tap_ctrl_o__tck;
    TDOPort        host_tdo_o {
        Source     stap_scan_in;
        Attribute  LaunchEdge = "Falling";
    }
    DataOutPort    host_tdo_oen_o {
        Source     tdo_oen;
    }
    TDIPort        host_tdi_i;

    //-------------------------------------------------------------------------
    // Scan Interfaces
    //-------------------------------------------------------------------------

    ScanInterface client {
        Port  client_scan_ctrl_i__capture_en;
        Port  client_scan_ctrl_i__shift_en;
        Port  client_scan_ctrl_i__update_en;
        Port  client_scan_ctrl_i__select;
        Port  client_scan_ctrl_i__rst_n;
        Port  client_scan_ctrl_i__tck;
        Port  client_scan_in_i;
        Port  client_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // Internal Signals
    //-------------------------------------------------------------------------

    // Optional scan input pipeline
    LogicSignal stap_scan_in {
        client_scan_in_i;
    }

    // STAP TDI (with optional lockup latch)
    LogicSignal stap_tdi {
        host_tdi_i;
    }

    // SIB input mux (selects between scan chain and STAP TDI based on stap_sel)
    ScanMux sib_client_scan_in SelectedBy u_3dcr.stap_sel {
        1'b0 : stap_scan_in;
        1'b1 : stap_tdi;
    }

    //-------------------------------------------------------------------------
    // SIB Instance (using prim_jtag_sib_mux_pre)
    //-------------------------------------------------------------------------

    Instance u_sib Of prim_jtag_sib_mux_pre {
        InputPort  client_scan_ctrl_i__capture_en = client_scan_ctrl_i__capture_en;
        InputPort  client_scan_ctrl_i__scan_en = client_scan_ctrl_i__shift_en;
        InputPort  client_scan_ctrl_i__update_en = client_scan_ctrl_i__update_en;
        InputPort  client_scan_ctrl_i__select = client_scan_ctrl_i__select;
        InputPort  client_scan_ctrl_i__rst_n = client_scan_ctrl_i__rst_n;
        InputPort  client_scan_ctrl_i__tck = client_scan_ctrl_i__tck;
        InputPort  client_scan_in_i = sib_client_scan_in;
        InputPort  host_scan_in_i = u_3dcr.scan_out_o;
    }

    //-------------------------------------------------------------------------
    // 3DCR Register Instance (3-bit)
    //-------------------------------------------------------------------------
    // Bit[0]: config_hold - When 1, protects config from TLR reset
    // Bit[1]: stap_sel - When 1, enables STAP chain
    // Bit[2]: tms_hold - TMS value when stap_sel=0

    Instance u_3dcr Of prim_jtag_scan_reg {
        Parameter  WIDTH = 3;
        InputPort  scan_in_i = u_sib.host_scan_out_o;
        InputPort  scan_ctrl_i__capture_en = u_sib.host_scan_ctrl_o__capture_en;
        InputPort  scan_ctrl_i__scan_en = u_sib.host_scan_ctrl_o__shift_en;
        InputPort  scan_ctrl_i__update_en = u_sib.host_scan_ctrl_o__update_en;
        InputPort  scan_ctrl_i__select = u_sib.host_scan_ctrl_o__select;
        InputPort  scan_ctrl_i__rst_n = cr3d_rst_n;
        InputPort  scan_ctrl_i__tck = client_scan_ctrl_i__tck;
        InputPort  data_in_i = u_3dcr.data_out_o;
    }

    // 3DCR fields
    Alias config_hold = u_3dcr.data_out_o[0];
    Alias stap_sel    = u_3dcr.data_out_o[1];
    Alias tms_hold    = u_3dcr.data_out_o[2];

    // 3DCR reset control: only reset when config_hold=0 and TLR asserted
    LogicSignal cr3d_rst_n {
        client_tap_ctrl_i__trst_n & (config_hold | client_scan_ctrl_i__rst_n);
    }

    //-------------------------------------------------------------------------
    // Host TAP Control Outputs
    //-------------------------------------------------------------------------

    // TMS output: when stap_sel=1, pass through TMS; when stap_sel=0, use tms_hold
    ScanMux host_tms SelectedBy stap_sel {
        1'b0 : tms_hold;
        1'b1 : client_tap_ctrl_i__tms;
    }

    // TDO output enable: active when stap_sel=1 and in shift state
    LogicSignal tdo_oen {
        stap_sel & client_scan_ctrl_i__shift_en;
    }
}

//-----------------------------------------------------------------------------
// JTAG 3DCR Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1838 compliant 2-bit 3D Control Register for STAP selection
// Bit[0]: config_hold - When 1, protects config from TLR reset
// Bit[1]: stap_sel - When 1, enables STAP chain
//-----------------------------------------------------------------------------

Module jtag_3dcr_reg {
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
        Source     cr3d_data[0];
        Attribute  LaunchEdge = "Rising";
    }

    // STAP select output
    DataOutPort    stap_sel_o {
        Source  cr3d_data[1];
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

    // 2-bit 3DCR register
    // Bit[0]: config_hold (closest to TDO)
    // Bit[1]: stap_sel (closest to TDI)
    ScanRegister cr3d_data[1:0] {
        ScanInSource   scan_in_i;
        CaptureSource  cr3d_data[1:0];
        ResetValue     2'b00;
    }
}

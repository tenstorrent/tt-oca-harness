//-----------------------------------------------------------------------------
// JTAG TMP Status Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1 Section 16.1 compliant 2-bit TMP status register
// Bit[0]: bypass_escape - User programmable escape enable
// Bit[1]: persistence_mode - Read-only TMP controller state
//-----------------------------------------------------------------------------

Module jtag_tmp_status_reg {
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
        Source     tmp_status_data[0];
        Attribute  LaunchEdge = "Rising";
    }

    // TMP status inputs/outputs
    DataInPort     persistence_mode_i;
    DataOutPort    bypass_escape_bit_o {
        Source  tmp_status_data[0];
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

    // 2-bit TMP status register
    // Bit[0]: bypass_escape (closest to TDO) - R/W
    // Bit[1]: persistence_mode (closest to TDI) - RO, captures from input
    ScanRegister tmp_status_data[1:0] {
        ScanInSource   scan_in_i;
        CaptureSource  {persistence_mode_i, tmp_status_data[0]};
        ResetValue     2'b10;
    }
}

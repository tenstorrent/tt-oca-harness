//-----------------------------------------------------------------------------
// JTAG IDCODE Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1 compliant 32-bit IDCODE register
// Read-only register that captures device identification code
//-----------------------------------------------------------------------------

Module jtag_idcode_reg {
    // Parameters for IDCODE construction
    Parameter  IDCODE_MFR_ID   = 11'h000;
    Parameter  IDCODE_PART_NUM = 16'h0000;
    Parameter  IDCODE_SI_REV   = 4'h0;

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
        Source     idcode_data[0];
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

    // 32-bit IDCODE register (read-only)
    // Format per IEEE 1149.1 Section 12:
    // [31:28] = Version (SI_REV)
    // [27:12] = Part Number
    // [11:1]  = Manufacturer ID
    // [0]     = Always 1
    ScanRegister idcode_data[31:0] {
        ScanInSource   scan_in_i;
        CaptureSource  {$IDCODE_SI_REV, $IDCODE_PART_NUM, $IDCODE_MFR_ID, 1'b1};
        ResetValue     {$IDCODE_SI_REV, $IDCODE_PART_NUM, $IDCODE_MFR_ID, 1'b1};
    }
}

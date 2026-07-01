//-----------------------------------------------------------------------------
// JTAG2AXI Capabilities Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// Read-only capabilities register for JTAG2AXI interface
// Reports address width, data width, and pipeline depths
//-----------------------------------------------------------------------------

Module jtag_jtag2axi_caps_reg {
    // Configuration parameters
    Parameter  ADDR_WIDTH   = 32;
    Parameter  DATA_WIDTH   = 32;
    Parameter  RD_PL_DEPTH  = 3;
    Parameter  WR_PL_DEPTH  = 3;
    Parameter  IS_AXI4_LITE = 0;

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
        Source     j2a_caps_data[0];
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

    // Capabilities register (variable width based on configuration)
    // Captures constant value reflecting JTAG2AXI configuration
    ScanRegister j2a_caps_data[23:0] {
        ScanInSource   scan_in_i;
        CaptureSource  {$IS_AXI4_LITE, $WR_PL_DEPTH[1:0], $RD_PL_DEPTH[1:0],
                        $DATA_WIDTH[7:0], $ADDR_WIDTH[7:0], 3'b000};
        ResetValue     {$IS_AXI4_LITE, $WR_PL_DEPTH[1:0], $RD_PL_DEPTH[1:0],
                        $DATA_WIDTH[7:0], $ADDR_WIDTH[7:0], 3'b000};
    }
}

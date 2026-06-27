//-----------------------------------------------------------------------------
// JTAG Debug Control Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// 5-bit debug control register for clock stop and boot stall control
// Bit[0]: boot_stall (R/W, closest to TDO)
// Bit[1]: boot_stall_ovrd (R/W)
// Bit[2]: cla_clock_stop_en (R/W)
// Bit[3]: jtag_clock_stop (R/W)
// Bit[4]: cla_clock_stop (RO, captures status, closest to TDI)
//-----------------------------------------------------------------------------

Module jtag_debug_ctrl_reg {
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
        Source     debug_ctrl_data[0];
        Attribute  LaunchEdge = "Rising";
    }

    // Status input and control outputs
    DataInPort     cla_clock_stop_i;
    DataOutPort    jtag_clock_stop_o {
        Source  debug_ctrl_data[3];
    }
    DataOutPort    cla_clock_stop_en_o {
        Source  debug_ctrl_data[2];
    }
    DataOutPort    boot_stall_ovrd_o {
        Source  debug_ctrl_data[1];
    }
    DataOutPort    boot_stall_o {
        Source  debug_ctrl_data[0];
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

    // 5-bit debug control register
    // Bit[4] (cla_clock_stop) is read-only, captures from input
    // Bits[3:0] are R/W, retain value on capture
    ScanRegister debug_ctrl_data[4:0] {
        ScanInSource   scan_in_i;
        CaptureSource  {cla_clock_stop_i, debug_ctrl_data[3:0]};
        ResetValue     5'b00000;
    }
}

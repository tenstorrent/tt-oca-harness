//-----------------------------------------------------------------------------
// JTAG IC Reset Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1 Section 17 compliant IC_RESET register
// Contains reset_hold bit and reset_enable/control pairs
// Total width: 1 + (2 * NUM_IC_RESET_PORTS) bits
//-----------------------------------------------------------------------------

Module jtag_ic_reset_reg {
    // Number of IC reset ports
    Parameter  NUM_IC_RESET_PORTS = 3;

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
        Source     reset_hold_data[0];
        Attribute  LaunchEdge = "Rising";
    }

    // TAP control for reset_hold (uses TRST instead of TLR reset)
    ResetPort      tap_ctrl_i__trst_n {
        ActivePolarity 0;
    }

    // IC Reset control outputs
    DataOutPort    ic_reset_ovrd_o[$NUM_IC_RESET_PORTS-1:0] {
        Source  ic_reset_ovrd[$NUM_IC_RESET_PORTS-1:0];
    }
    DataOutPort    ic_reset_ctrl_n_o[$NUM_IC_RESET_PORTS-1:0] {
        Source  ic_reset_ctrl_n[$NUM_IC_RESET_PORTS-1:0];
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

    // Reset enable/control register (2*NUM_IC_RESET_PORTS bits)
    // Closest to TDI, reset by scan_ctrl_i__rst_n when reset_hold=0
    // Bit ordering: [2*i] = reset_enable[i], [2*i+1] = reset_control[i]
    ScanRegister reset_enable_control_data[$NUM_IC_RESET_PORTS*2-1:0] {
        ScanInSource   scan_in_i;
        CaptureSource  reset_enable_control_data[$NUM_IC_RESET_PORTS*2-1:0];
        ResetValue     {$NUM_IC_RESET_PORTS*2{1'b1}};
    }

    // Reset hold register (1 bit, closest to TDO)
    // Only reset by TRST, never by TLR
    ScanRegister reset_hold_data[0:0] {
        ScanInSource   reset_enable_control_data[0];
        CaptureSource  reset_hold_data[0];
        ResetValue     1'b1;
    }

    // Extract reset_enable (inverted to get ic_reset_ovrd)
    Alias ic_reset_ovrd[$NUM_IC_RESET_PORTS-1:0] =
        ~{reset_enable_control_data[($NUM_IC_RESET_PORTS-1)*2],
          reset_enable_control_data[($NUM_IC_RESET_PORTS-2)*2],
          reset_enable_control_data[($NUM_IC_RESET_PORTS-3)*2]};

    // Extract reset_control directly
    Alias ic_reset_ctrl_n[$NUM_IC_RESET_PORTS-1:0] =
        {reset_enable_control_data[($NUM_IC_RESET_PORTS-1)*2+1],
         reset_enable_control_data[($NUM_IC_RESET_PORTS-2)*2+1],
         reset_enable_control_data[($NUM_IC_RESET_PORTS-3)*2+1]};
}

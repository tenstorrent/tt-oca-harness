//-----------------------------------------------------------------------------
// JTAG Interface Unit ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// Top-level JTAG interface containing:
// - Primary TAP (PTAP)
// - Secondary TAPs (STAPs) for I/O, SEP, and extra connectivity
// - iJTAG SIBs for DFT and DFD access
//-----------------------------------------------------------------------------

Module jtag_intf_unit {
    // Configuration parameters
    Parameter  BSR_ENABLE          = 1;
    Parameter  EXTEST_TRAIN_ENABLE = 1;
    Parameter  EXTEST_PULSE_ENABLE = 1;
    Parameter  INTEST_ENABLE       = 1;
    Parameter  CLAMP_ENABLE        = 1;
    Parameter  HIGHZ_ENABLE        = 1;
    Parameter  RUNBIST_ENABLE      = 1;
    Parameter  TMP_ENABLE          = 1;
    Parameter  IC_RESET_SMC_ENABLE = 0;
    Parameter  IC_RESET_SEP_ENABLE = 0;
    Parameter  IC_RESET_EXT_ENABLE = 0;
    Parameter  SMC_DBG_ENABLE      = 1;
    Parameter  SEP_DBG_ENABLE      = 1;
    Parameter  STAP_IO_ENABLE      = 1;
    Parameter  NUM_SMC_IC_RESET    = 0;
    Parameter  NUM_SEP_IC_RESET    = 0;
    Parameter  NUM_EXT_IC_RESET    = 0;
    Parameter  NUM_EXTRA_STAPS     = 0;
    Parameter  IDCODE_MFR_ID       = 11'h000;
    Parameter  IDCODE_PART_NUM     = 16'h0000;
    Parameter  IDCODE_SI_REV       = 4'h0;
    Parameter  NUM_XTRIG_CTP       = 8;
    Parameter  NUM_XTRIG_INT_CT    = 1;
    Parameter  OCH_VER             = 8'h00;

    //-------------------------------------------------------------------------
    // Primary JTAG TAP Interface (External Pins)
    //-------------------------------------------------------------------------

    TMSPort        ptap_client_tap_ctrl_i__tms;
    TRSTPort       ptap_client_tap_ctrl_i__trst_n {
        ActivePolarity 0;
    }
    TCKPort        ptap_client_tap_ctrl_i__tck;
    TDIPort        ptap_client_tdi_i;
    TDOPort        ptap_client_tdo_o {
        Source     u_jtag_ptap.client_tdo_o;
        Attribute  LaunchEdge = "Falling";
    }
    DataOutPort    ptap_client_tdo_oen_o;

    //-------------------------------------------------------------------------
    // Boundary Scan Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  bsr_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    bsr_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   bsr_host_scan_ctrl_o__update_en;
    ToSelectPort     bsr_host_scan_ctrl_o__select;
    ToResetPort      bsr_host_scan_ctrl_o__rst_n;
    ToTCKPort        bsr_host_scan_ctrl_o__tck;
    ScanInPort       bsr_host_scan_in_i;
    ScanOutPort      bsr_host_scan_out_o {
        Source     u_jtag_ptap.bsr_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // I/O STAP Interface (Chiplet-to-Chiplet)
    //-------------------------------------------------------------------------

    ToTMSPort      stap_io_host_tap_ctrl_o__tms;
    ToTRSTPort     stap_io_host_tap_ctrl_o__trst_n;
    ToTCKPort      stap_io_host_tap_ctrl_o__tck;
    ScanInPort     stap_io_host_tdi_i;
    ScanOutPort    stap_io_host_tdo_o {
        Source     u_stap_io.host_tdo_o;
    }
    DataOutPort    stap_io_host_tdo_oen_o {
        Source     u_stap_io.host_tdo_oen_o;
    }

    //-------------------------------------------------------------------------
    // SEP Debug STAP Interface
    //-------------------------------------------------------------------------

    ToTMSPort      stap_sep_host_tap_ctrl_o__tms;
    ToTRSTPort     stap_sep_host_tap_ctrl_o__trst_n;
    ToTCKPort      stap_sep_host_tap_ctrl_o__tck;
    ScanInPort     stap_sep_host_tdi_i;
    ScanOutPort    stap_sep_host_tdo_o {
        Source     u_stap_sep.host_tdo_o;
    }
    DataOutPort    stap_sep_host_tdo_oen_o {
        Source     u_stap_sep.host_tdo_oen_o;
    }

    //-------------------------------------------------------------------------
    // Extended STAP Scan Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  stap_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    stap_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   stap_host_scan_ctrl_o__update_en;
    ToSelectPort     stap_host_scan_ctrl_o__select;
    ToResetPort      stap_host_scan_ctrl_o__rst_n;
    ToTCKPort        stap_host_scan_ctrl_o__tck;
    ScanInPort       stap_host_scan_in_i;
    ScanOutPort      stap_host_scan_out_o {
        Source     stap_chain_out;
    }

    //-------------------------------------------------------------------------
    // External DFD iJTAG Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  dfd_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    dfd_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   dfd_host_scan_ctrl_o__update_en;
    ToSelectPort     dfd_host_scan_ctrl_o__select;
    ToResetPort      dfd_host_scan_ctrl_o__rst_n;
    ToTCKPort        dfd_host_scan_ctrl_o__tck;
    ScanInPort       dfd_host_scan_in_i;
    ScanOutPort      dfd_host_scan_out_o {
        Source     u_dfd_sib.host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // External DFT iJTAG Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  dft_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    dft_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   dft_host_scan_ctrl_o__update_en;
    ToSelectPort     dft_host_scan_ctrl_o__select;
    ToResetPort      dft_host_scan_ctrl_o__rst_n;
    ToTCKPort        dft_host_scan_ctrl_o__tck;
    ScanInPort       dft_host_scan_in_i;
    ScanOutPort      dft_host_scan_out_o {
        Source     u_dft_sib.host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // Scan Interfaces
    //-------------------------------------------------------------------------

    ScanInterface bsr_host {
        Port  bsr_host_scan_ctrl_o__capture_en;
        Port  bsr_host_scan_ctrl_o__shift_en;
        Port  bsr_host_scan_ctrl_o__update_en;
        Port  bsr_host_scan_ctrl_o__select;
        Port  bsr_host_scan_ctrl_o__rst_n;
        Port  bsr_host_scan_ctrl_o__tck;
        Port  bsr_host_scan_in_i;
        Port  bsr_host_scan_out_o;
    }

    ScanInterface stap_host {
        Port  stap_host_scan_ctrl_o__capture_en;
        Port  stap_host_scan_ctrl_o__shift_en;
        Port  stap_host_scan_ctrl_o__update_en;
        Port  stap_host_scan_ctrl_o__select;
        Port  stap_host_scan_ctrl_o__rst_n;
        Port  stap_host_scan_ctrl_o__tck;
        Port  stap_host_scan_in_i;
        Port  stap_host_scan_out_o;
    }

    ScanInterface dfd_host {
        Port  dfd_host_scan_ctrl_o__capture_en;
        Port  dfd_host_scan_ctrl_o__shift_en;
        Port  dfd_host_scan_ctrl_o__update_en;
        Port  dfd_host_scan_ctrl_o__select;
        Port  dfd_host_scan_ctrl_o__rst_n;
        Port  dfd_host_scan_ctrl_o__tck;
        Port  dfd_host_scan_in_i;
        Port  dfd_host_scan_out_o;
    }

    ScanInterface dft_host {
        Port  dft_host_scan_ctrl_o__capture_en;
        Port  dft_host_scan_ctrl_o__shift_en;
        Port  dft_host_scan_ctrl_o__update_en;
        Port  dft_host_scan_ctrl_o__select;
        Port  dft_host_scan_ctrl_o__rst_n;
        Port  dft_host_scan_ctrl_o__tck;
        Port  dft_host_scan_in_i;
        Port  dft_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // Primary TAP Instance
    //-------------------------------------------------------------------------

    Instance u_jtag_ptap Of jtag_ptap {
        Parameter  BSR_ENABLE          = $BSR_ENABLE;
        Parameter  EXTEST_TRAIN_ENABLE = $EXTEST_TRAIN_ENABLE;
        Parameter  EXTEST_PULSE_ENABLE = $EXTEST_PULSE_ENABLE;
        Parameter  INTEST_ENABLE       = $INTEST_ENABLE;
        Parameter  CLAMP_ENABLE        = $CLAMP_ENABLE;
        Parameter  HIGHZ_ENABLE        = $HIGHZ_ENABLE;
        Parameter  RUNBIST_ENABLE      = $RUNBIST_ENABLE;
        Parameter  TMP_ENABLE          = $TMP_ENABLE;
        Parameter  IC_RESET_SMC_ENABLE = $IC_RESET_SMC_ENABLE;
        Parameter  IC_RESET_SEP_ENABLE = $IC_RESET_SEP_ENABLE;
        Parameter  IC_RESET_EXT_ENABLE = $IC_RESET_EXT_ENABLE;
        Parameter  SMC_DBG_ENABLE      = $SMC_DBG_ENABLE;
        Parameter  SEP_DBG_ENABLE      = $SEP_DBG_ENABLE;
        Parameter  STAP_IO_ENABLE      = $STAP_IO_ENABLE;
        Parameter  NUM_SMC_IC_RESET    = $NUM_SMC_IC_RESET;
        Parameter  NUM_SEP_IC_RESET    = $NUM_SEP_IC_RESET;
        Parameter  NUM_EXT_IC_RESET    = $NUM_EXT_IC_RESET;
        Parameter  NUM_EXTRA_STAPS     = $NUM_EXTRA_STAPS;
        Parameter  IDCODE_MFR_ID       = $IDCODE_MFR_ID;
        Parameter  IDCODE_PART_NUM     = $IDCODE_PART_NUM;
        Parameter  IDCODE_SI_REV       = $IDCODE_SI_REV;
        Parameter  NUM_XTRIG_CTP       = $NUM_XTRIG_CTP;
        Parameter  NUM_XTRIG_INT_CT    = $NUM_XTRIG_INT_CT;
        Parameter  OCH_VER             = $OCH_VER;
        // Primary JTAG interface
        InputPort  client_tap_ctrl_i__tms = ptap_client_tap_ctrl_i__tms;
        InputPort  client_tap_ctrl_i__trst_n = ptap_client_tap_ctrl_i__trst_n;
        InputPort  client_tap_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        InputPort  client_tdi_i = ptap_client_tdi_i;
        // Boundary scan interface
        InputPort  bsr_host_scan_in_i = bsr_host_scan_in_i;
        // iJTAG interface
        InputPort  ijtag_host_scan_in_i = ptap_ijtag_scan_in;
        // STAP interface
        InputPort  stap_host_scan_in_i = stap_host_scan_in_i;
    }

    //-------------------------------------------------------------------------
    // I/O STAP Instance (Chiplet-to-Chiplet Connectivity)
    //-------------------------------------------------------------------------

    Instance u_stap_io Of jtag_stap {
        Parameter  SCAN_IN_PIPE    = 0;
        Parameter  TDI_LOCKUP      = 1;
        Parameter  SCAN_OUT_LOCKUP = 0;
        // Client interface (from PTAP)
        InputPort  client_scan_ctrl_i__capture_en = u_jtag_ptap.stap_host_scan_ctrl_o__capture_en;
        InputPort  client_scan_ctrl_i__shift_en = u_jtag_ptap.stap_host_scan_ctrl_o__shift_en;
        InputPort  client_scan_ctrl_i__update_en = u_jtag_ptap.stap_host_scan_ctrl_o__update_en;
        InputPort  client_scan_ctrl_i__select = u_jtag_ptap.stap_host_scan_ctrl_o__select;
        InputPort  client_scan_ctrl_i__rst_n = u_jtag_ptap.stap_host_scan_ctrl_o__rst_n;
        InputPort  client_scan_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        InputPort  client_scan_in_i = u_jtag_ptap.stap_host_scan_out_o;
        InputPort  client_tap_ctrl_i__tms = ptap_client_tap_ctrl_i__tms;
        InputPort  client_tap_ctrl_i__trst_n = ptap_client_tap_ctrl_i__trst_n;
        InputPort  client_tap_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        // Host interface
        InputPort  host_tdi_i = stap_io_host_tdi_i;
    }

    //-------------------------------------------------------------------------
    // SEP Debug STAP Instance
    //-------------------------------------------------------------------------

    Instance u_stap_sep Of jtag_stap {
        Parameter  SCAN_IN_PIPE    = 0;
        Parameter  TDI_LOCKUP      = 0;
        Parameter  SCAN_OUT_LOCKUP = 0;
        // Client interface (from I/O STAP)
        InputPort  client_scan_ctrl_i__capture_en = u_jtag_ptap.stap_host_scan_ctrl_o__capture_en;
        InputPort  client_scan_ctrl_i__shift_en = u_jtag_ptap.stap_host_scan_ctrl_o__shift_en;
        InputPort  client_scan_ctrl_i__update_en = u_jtag_ptap.stap_host_scan_ctrl_o__update_en;
        InputPort  client_scan_ctrl_i__select = u_jtag_ptap.stap_host_scan_ctrl_o__select;
        InputPort  client_scan_ctrl_i__rst_n = u_jtag_ptap.stap_host_scan_ctrl_o__rst_n;
        InputPort  client_scan_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        InputPort  client_scan_in_i = u_stap_io.client_scan_out_o;
        InputPort  client_tap_ctrl_i__tms = ptap_client_tap_ctrl_i__tms;
        InputPort  client_tap_ctrl_i__trst_n = ptap_client_tap_ctrl_i__trst_n;
        InputPort  client_tap_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        // Host interface
        InputPort  host_tdi_i = stap_sep_host_tdi_i;
    }

    // STAP chain output (from last STAP in chain)
    Alias stap_chain_out = u_stap_sep.client_scan_out_o;

    //-------------------------------------------------------------------------
    // iJTAG SIB Chain
    // Chain: PTAP iJTAG scan out -> DFT SIB -> DFD SIB -> PTAP iJTAG scan in
    //-------------------------------------------------------------------------

    // DFT SIB (first in chain after PTAP)
    Instance u_dft_sib Of prim_jtag_sib_mux_post {
        // Client interface (from PTAP)
        InputPort  client_scan_ctrl_i__capture_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__capture_en;
        InputPort  client_scan_ctrl_i__scan_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__shift_en;
        InputPort  client_scan_ctrl_i__update_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__update_en;
        InputPort  client_scan_ctrl_i__select = u_jtag_ptap.ijtag_host_scan_ctrl_o__select;
        InputPort  client_scan_ctrl_i__rst_n = u_jtag_ptap.ijtag_host_scan_ctrl_o__rst_n;
        InputPort  client_scan_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        InputPort  client_scan_in_i = u_jtag_ptap.ijtag_host_scan_out_o;
        // Host interface (to external DFT)
        InputPort  host_scan_in_i = dft_host_scan_in_i;
    }

    // DFD SIB (second in chain)
    Instance u_dfd_sib Of prim_jtag_sib_mux_post {
        // Client interface (from DFT SIB)
        InputPort  client_scan_ctrl_i__capture_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__capture_en;
        InputPort  client_scan_ctrl_i__scan_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__shift_en;
        InputPort  client_scan_ctrl_i__update_en = u_jtag_ptap.ijtag_host_scan_ctrl_o__update_en;
        InputPort  client_scan_ctrl_i__select = u_jtag_ptap.ijtag_host_scan_ctrl_o__select;
        InputPort  client_scan_ctrl_i__rst_n = u_jtag_ptap.ijtag_host_scan_ctrl_o__rst_n;
        InputPort  client_scan_ctrl_i__tck = ptap_client_tap_ctrl_i__tck;
        InputPort  client_scan_in_i = u_dft_sib.client_scan_out_o;
        // Host interface (to external DFD)
        InputPort  host_scan_in_i = dfd_host_scan_in_i;
    }

    // Complete the iJTAG scan chain back to PTAP
    Alias ptap_ijtag_scan_in = u_dfd_sib.client_scan_out_o;

    //-------------------------------------------------------------------------
    // Scan Control Output Assignments
    //-------------------------------------------------------------------------

    // BSR scan control (from PTAP)
    Alias bsr_host_scan_ctrl_o__capture_en = u_jtag_ptap.bsr_host_scan_ctrl_o__capture_en;
    Alias bsr_host_scan_ctrl_o__shift_en   = u_jtag_ptap.bsr_host_scan_ctrl_o__shift_en;
    Alias bsr_host_scan_ctrl_o__update_en  = u_jtag_ptap.bsr_host_scan_ctrl_o__update_en;
    Alias bsr_host_scan_ctrl_o__select     = u_jtag_ptap.bsr_host_scan_ctrl_o__select;
    Alias bsr_host_scan_ctrl_o__rst_n      = u_jtag_ptap.bsr_host_scan_ctrl_o__rst_n;
    Alias bsr_host_scan_ctrl_o__tck        = ptap_client_tap_ctrl_i__tck;

    // STAP scan control (from PTAP)
    Alias stap_host_scan_ctrl_o__capture_en = u_jtag_ptap.stap_host_scan_ctrl_o__capture_en;
    Alias stap_host_scan_ctrl_o__shift_en   = u_jtag_ptap.stap_host_scan_ctrl_o__shift_en;
    Alias stap_host_scan_ctrl_o__update_en  = u_jtag_ptap.stap_host_scan_ctrl_o__update_en;
    Alias stap_host_scan_ctrl_o__select     = u_jtag_ptap.stap_host_scan_ctrl_o__select;
    Alias stap_host_scan_ctrl_o__rst_n      = u_jtag_ptap.stap_host_scan_ctrl_o__rst_n;
    Alias stap_host_scan_ctrl_o__tck        = ptap_client_tap_ctrl_i__tck;

    // DFT scan control (from iJTAG through SIB)
    Alias dft_host_scan_ctrl_o__capture_en = u_dft_sib.host_scan_ctrl_o__capture_en;
    Alias dft_host_scan_ctrl_o__shift_en   = u_dft_sib.host_scan_ctrl_o__shift_en;
    Alias dft_host_scan_ctrl_o__update_en  = u_dft_sib.host_scan_ctrl_o__update_en;
    Alias dft_host_scan_ctrl_o__select     = u_dft_sib.host_scan_ctrl_o__select;
    Alias dft_host_scan_ctrl_o__rst_n      = u_dft_sib.host_scan_ctrl_o__rst_n;
    Alias dft_host_scan_ctrl_o__tck        = u_dft_sib.host_scan_ctrl_o__tck;

    // DFD scan control (from iJTAG through SIB)
    Alias dfd_host_scan_ctrl_o__capture_en = u_dfd_sib.host_scan_ctrl_o__capture_en;
    Alias dfd_host_scan_ctrl_o__shift_en   = u_dfd_sib.host_scan_ctrl_o__shift_en;
    Alias dfd_host_scan_ctrl_o__update_en  = u_dfd_sib.host_scan_ctrl_o__update_en;
    Alias dfd_host_scan_ctrl_o__select     = u_dfd_sib.host_scan_ctrl_o__select;
    Alias dfd_host_scan_ctrl_o__rst_n      = u_dfd_sib.host_scan_ctrl_o__rst_n;
    Alias dfd_host_scan_ctrl_o__tck        = u_dfd_sib.host_scan_ctrl_o__tck;

    // STAP TAP control outputs
    Alias stap_io_host_tap_ctrl_o__tms     = u_stap_io.host_tap_ctrl_o__tms;
    Alias stap_io_host_tap_ctrl_o__trst_n  = u_stap_io.host_tap_ctrl_o__trst_n;
    Alias stap_io_host_tap_ctrl_o__tck     = u_stap_io.host_tap_ctrl_o__tck;
    Alias stap_sep_host_tap_ctrl_o__tms    = u_stap_sep.host_tap_ctrl_o__tms;
    Alias stap_sep_host_tap_ctrl_o__trst_n = u_stap_sep.host_tap_ctrl_o__trst_n;
    Alias stap_sep_host_tap_ctrl_o__tck    = u_stap_sep.host_tap_ctrl_o__tck;
}

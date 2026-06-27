//-----------------------------------------------------------------------------
// Debug and Test Ports (DTP) ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// Top-level DTP module containing:
// - JTAG Interface Unit (jtag_intf_unit)
// - Cross Trigger Network (functional, not modeled in ICL)
//
// This ICL file models only the JTAG scan chain connectivity.
// Non-JTAG functionality (cross triggers, AXI interfaces) is not modeled.
//-----------------------------------------------------------------------------

Module dtp {
    // Configuration parameters
    Parameter  JTAG_BSR_ENABLE          = 1;
    Parameter  JTAG_EXTEST_TRAIN_ENABLE = 1;
    Parameter  JTAG_EXTEST_PULSE_ENABLE = 1;
    Parameter  JTAG_INTEST_ENABLE       = 1;
    Parameter  JTAG_CLAMP_ENABLE        = 1;
    Parameter  JTAG_HIGHZ_ENABLE        = 1;
    Parameter  JTAG_RUNBIST_ENABLE      = 1;
    Parameter  JTAG_TMP_ENABLE          = 1;
    Parameter  JTAG_IC_RESET_SMC_ENABLE = 1;
    Parameter  JTAG_IC_RESET_SEP_ENABLE = 1;
    Parameter  JTAG_IC_RESET_EXT_ENABLE = 1;
    Parameter  JTAG_SMC_DBG_ENABLE      = 1;
    Parameter  JTAG_SEP_DBG_ENABLE      = 1;
    Parameter  JTAG_STAP_IO_ENABLE      = 1;
    Parameter  JTAG_NUM_SMC_IC_RESET    = 0;
    Parameter  JTAG_NUM_SEP_IC_RESET    = 0;
    Parameter  JTAG_NUM_EXT_IC_RESET    = 0;
    Parameter  JTAG_NUM_EXTRA_STAPS     = 0;
    Parameter  JTAG_IDCODE_MFR_ID       = 11'h000;
    Parameter  JTAG_IDCODE_PART_NUM     = 16'h0000;
    Parameter  JTAG_IDCODE_SI_REV       = 4'h0;
    Parameter  JTAG_OCH_VER             = 8'h00;
    // These values must match dtp_pkg::DEFAULT_NUM_CTP and dtp_pkg::DEFAULT_NUM_INT_CT
    Parameter  XTRIG_NUM_CTP            = 16;  // Templated: matches dtp_pkg::DEFAULT_NUM_CTP
    Parameter  XTRIG_NUM_INT_CT         = 10;  // Templated: matches dtp_pkg::DEFAULT_NUM_INT_CT

    //-------------------------------------------------------------------------
    // Primary JTAG TAP Interface (External Pins)
    //-------------------------------------------------------------------------

    TMSPort        jtag_ptap_client_tap_ctrl_i__tms;
    TRSTPort       jtag_ptap_client_tap_ctrl_i__trst_n {
        ActivePolarity 0;
    }
    TCKPort        jtag_ptap_client_tap_ctrl_i__tck;
    TDIPort        jtag_ptap_client_tdi_i;
    TDOPort        jtag_ptap_client_tdo_o {
        Source     u_jtag_intf_unit.ptap_client_tdo_o;
        Attribute  LaunchEdge = "Falling";
    }
    DataOutPort    jtag_ptap_client_tdo_oen_o {
        Source     u_jtag_intf_unit.ptap_client_tdo_oen_o;
    }

    //-------------------------------------------------------------------------
    // Boundary Scan Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  jtag_bsr_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    jtag_bsr_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   jtag_bsr_host_scan_ctrl_o__update_en;
    ToSelectPort     jtag_bsr_host_scan_ctrl_o__select;
    ToResetPort      jtag_bsr_host_scan_ctrl_o__rst_n;
    ToTCKPort        jtag_bsr_host_scan_ctrl_o__tck;
    ScanInPort       jtag_bsr_host_scan_in_i;
    ScanOutPort      jtag_bsr_host_scan_out_o {
        Source     u_jtag_intf_unit.bsr_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // I/O STAP Interface (Chiplet-to-Chiplet Connectivity)
    //-------------------------------------------------------------------------

    ToTMSPort      jtag_stap_io_host_tap_ctrl_o__tms;
    ToTRSTPort     jtag_stap_io_host_tap_ctrl_o__trst_n;
    ToTCKPort      jtag_stap_io_host_tap_ctrl_o__tck;
    ScanInPort     jtag_stap_io_host_tdi_i;
    ScanOutPort    jtag_stap_io_host_tdo_o {
        Source     u_jtag_intf_unit.stap_io_host_tdo_o;
    }
    DataOutPort    jtag_stap_io_host_tdo_oen_o {
        Source     u_jtag_intf_unit.stap_io_host_tdo_oen_o;
    }

    //-------------------------------------------------------------------------
    // SEP Debug STAP Interface
    //-------------------------------------------------------------------------

    ToTMSPort      jtag_stap_sep_host_tap_ctrl_o__tms;
    ToTRSTPort     jtag_stap_sep_host_tap_ctrl_o__trst_n;
    ToTCKPort      jtag_stap_sep_host_tap_ctrl_o__tck;
    ScanInPort     jtag_stap_sep_host_tdi_i;
    ScanOutPort    jtag_stap_sep_host_tdo_o {
        Source     u_jtag_intf_unit.stap_sep_host_tdo_o;
    }
    DataOutPort    jtag_stap_sep_host_tdo_oen_o {
        Source     u_jtag_intf_unit.stap_sep_host_tdo_oen_o;
    }

    //-------------------------------------------------------------------------
    // Extended STAP Scan Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  jtag_stap_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    jtag_stap_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   jtag_stap_host_scan_ctrl_o__update_en;
    ToSelectPort     jtag_stap_host_scan_ctrl_o__select;
    ToResetPort      jtag_stap_host_scan_ctrl_o__rst_n;
    ToTCKPort        jtag_stap_host_scan_ctrl_o__tck;
    ScanInPort       jtag_stap_host_scan_in_i;
    ScanOutPort      jtag_stap_host_scan_out_o {
        Source     u_jtag_intf_unit.stap_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // External DFD iJTAG Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  jtag_dfd_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    jtag_dfd_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   jtag_dfd_host_scan_ctrl_o__update_en;
    ToSelectPort     jtag_dfd_host_scan_ctrl_o__select;
    ToResetPort      jtag_dfd_host_scan_ctrl_o__rst_n;
    ToTCKPort        jtag_dfd_host_scan_ctrl_o__tck;
    ScanInPort       jtag_dfd_host_scan_in_i;
    ScanOutPort      jtag_dfd_host_scan_out_o {
        Source     u_jtag_intf_unit.dfd_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // External DFT iJTAG Interface
    //-------------------------------------------------------------------------

    ToCaptureEnPort  jtag_dft_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    jtag_dft_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   jtag_dft_host_scan_ctrl_o__update_en;
    ToSelectPort     jtag_dft_host_scan_ctrl_o__select;
    ToResetPort      jtag_dft_host_scan_ctrl_o__rst_n;
    ToTCKPort        jtag_dft_host_scan_ctrl_o__tck;
    ScanInPort       jtag_dft_host_scan_in_i;
    ScanOutPort      jtag_dft_host_scan_out_o {
        Source     u_jtag_intf_unit.dft_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // Scan Interfaces
    //-------------------------------------------------------------------------

    ScanInterface jtag_bsr_host {
        Port  jtag_bsr_host_scan_ctrl_o__capture_en;
        Port  jtag_bsr_host_scan_ctrl_o__shift_en;
        Port  jtag_bsr_host_scan_ctrl_o__update_en;
        Port  jtag_bsr_host_scan_ctrl_o__select;
        Port  jtag_bsr_host_scan_ctrl_o__rst_n;
        Port  jtag_bsr_host_scan_ctrl_o__tck;
        Port  jtag_bsr_host_scan_in_i;
        Port  jtag_bsr_host_scan_out_o;
    }

    ScanInterface jtag_stap_host {
        Port  jtag_stap_host_scan_ctrl_o__capture_en;
        Port  jtag_stap_host_scan_ctrl_o__shift_en;
        Port  jtag_stap_host_scan_ctrl_o__update_en;
        Port  jtag_stap_host_scan_ctrl_o__select;
        Port  jtag_stap_host_scan_ctrl_o__rst_n;
        Port  jtag_stap_host_scan_ctrl_o__tck;
        Port  jtag_stap_host_scan_in_i;
        Port  jtag_stap_host_scan_out_o;
    }

    ScanInterface jtag_dfd_host {
        Port  jtag_dfd_host_scan_ctrl_o__capture_en;
        Port  jtag_dfd_host_scan_ctrl_o__shift_en;
        Port  jtag_dfd_host_scan_ctrl_o__update_en;
        Port  jtag_dfd_host_scan_ctrl_o__select;
        Port  jtag_dfd_host_scan_ctrl_o__rst_n;
        Port  jtag_dfd_host_scan_ctrl_o__tck;
        Port  jtag_dfd_host_scan_in_i;
        Port  jtag_dfd_host_scan_out_o;
    }

    ScanInterface jtag_dft_host {
        Port  jtag_dft_host_scan_ctrl_o__capture_en;
        Port  jtag_dft_host_scan_ctrl_o__shift_en;
        Port  jtag_dft_host_scan_ctrl_o__update_en;
        Port  jtag_dft_host_scan_ctrl_o__select;
        Port  jtag_dft_host_scan_ctrl_o__rst_n;
        Port  jtag_dft_host_scan_ctrl_o__tck;
        Port  jtag_dft_host_scan_in_i;
        Port  jtag_dft_host_scan_out_o;
    }

    //-------------------------------------------------------------------------
    // JTAG Interface Unit Instance
    //-------------------------------------------------------------------------

    Instance u_jtag_intf_unit Of jtag_intf_unit {
        Parameter  BSR_ENABLE          = $JTAG_BSR_ENABLE;
        Parameter  EXTEST_TRAIN_ENABLE = $JTAG_EXTEST_TRAIN_ENABLE;
        Parameter  EXTEST_PULSE_ENABLE = $JTAG_EXTEST_PULSE_ENABLE;
        Parameter  INTEST_ENABLE       = $JTAG_INTEST_ENABLE;
        Parameter  CLAMP_ENABLE        = $JTAG_CLAMP_ENABLE;
        Parameter  HIGHZ_ENABLE        = $JTAG_HIGHZ_ENABLE;
        Parameter  RUNBIST_ENABLE      = $JTAG_RUNBIST_ENABLE;
        Parameter  TMP_ENABLE          = $JTAG_TMP_ENABLE;
        Parameter  IC_RESET_SMC_ENABLE = $JTAG_IC_RESET_SMC_ENABLE;
        Parameter  IC_RESET_SEP_ENABLE = $JTAG_IC_RESET_SEP_ENABLE;
        Parameter  IC_RESET_EXT_ENABLE = $JTAG_IC_RESET_EXT_ENABLE;
        Parameter  SMC_DBG_ENABLE      = $JTAG_SMC_DBG_ENABLE;
        Parameter  SEP_DBG_ENABLE      = $JTAG_SEP_DBG_ENABLE;
        Parameter  STAP_IO_ENABLE      = $JTAG_STAP_IO_ENABLE;
        Parameter  NUM_SMC_IC_RESET    = $JTAG_NUM_SMC_IC_RESET;
        Parameter  NUM_SEP_IC_RESET    = $JTAG_NUM_SEP_IC_RESET;
        Parameter  NUM_EXT_IC_RESET    = $JTAG_NUM_EXT_IC_RESET;
        Parameter  NUM_EXTRA_STAPS     = $JTAG_NUM_EXTRA_STAPS;
        Parameter  IDCODE_MFR_ID       = $JTAG_IDCODE_MFR_ID;
        Parameter  IDCODE_PART_NUM     = $JTAG_IDCODE_PART_NUM;
        Parameter  IDCODE_SI_REV       = $JTAG_IDCODE_SI_REV;
        Parameter  NUM_XTRIG_CTP       = $XTRIG_NUM_CTP;
        Parameter  NUM_XTRIG_INT_CT    = $XTRIG_NUM_INT_CT;
        Parameter  OCH_VER             = $JTAG_OCH_VER;

        // Primary JTAG interface
        InputPort  ptap_client_tap_ctrl_i__tms = jtag_ptap_client_tap_ctrl_i__tms;
        InputPort  ptap_client_tap_ctrl_i__trst_n = jtag_ptap_client_tap_ctrl_i__trst_n;
        InputPort  ptap_client_tap_ctrl_i__tck = jtag_ptap_client_tap_ctrl_i__tck;
        InputPort  ptap_client_tdi_i = jtag_ptap_client_tdi_i;

        // Boundary scan interface
        InputPort  bsr_host_scan_in_i = jtag_bsr_host_scan_in_i;

        // I/O STAP interface
        InputPort  stap_io_host_tdi_i = jtag_stap_io_host_tdi_i;

        // SEP STAP interface
        InputPort  stap_sep_host_tdi_i = jtag_stap_sep_host_tdi_i;

        // Extended STAP interface
        InputPort  stap_host_scan_in_i = jtag_stap_host_scan_in_i;

        // DFD iJTAG interface
        InputPort  dfd_host_scan_in_i = jtag_dfd_host_scan_in_i;

        // DFT iJTAG interface
        InputPort  dft_host_scan_in_i = jtag_dft_host_scan_in_i;
    }

    //-------------------------------------------------------------------------
    // Scan Control Output Assignments
    //-------------------------------------------------------------------------

    // BSR scan control (from JTAG interface unit)
    Alias jtag_bsr_host_scan_ctrl_o__capture_en = u_jtag_intf_unit.bsr_host_scan_ctrl_o__capture_en;
    Alias jtag_bsr_host_scan_ctrl_o__shift_en   = u_jtag_intf_unit.bsr_host_scan_ctrl_o__shift_en;
    Alias jtag_bsr_host_scan_ctrl_o__update_en  = u_jtag_intf_unit.bsr_host_scan_ctrl_o__update_en;
    Alias jtag_bsr_host_scan_ctrl_o__select     = u_jtag_intf_unit.bsr_host_scan_ctrl_o__select;
    Alias jtag_bsr_host_scan_ctrl_o__rst_n      = u_jtag_intf_unit.bsr_host_scan_ctrl_o__rst_n;
    Alias jtag_bsr_host_scan_ctrl_o__tck        = u_jtag_intf_unit.bsr_host_scan_ctrl_o__tck;

    // STAP scan control
    Alias jtag_stap_host_scan_ctrl_o__capture_en = u_jtag_intf_unit.stap_host_scan_ctrl_o__capture_en;
    Alias jtag_stap_host_scan_ctrl_o__shift_en   = u_jtag_intf_unit.stap_host_scan_ctrl_o__shift_en;
    Alias jtag_stap_host_scan_ctrl_o__update_en  = u_jtag_intf_unit.stap_host_scan_ctrl_o__update_en;
    Alias jtag_stap_host_scan_ctrl_o__select     = u_jtag_intf_unit.stap_host_scan_ctrl_o__select;
    Alias jtag_stap_host_scan_ctrl_o__rst_n      = u_jtag_intf_unit.stap_host_scan_ctrl_o__rst_n;
    Alias jtag_stap_host_scan_ctrl_o__tck        = u_jtag_intf_unit.stap_host_scan_ctrl_o__tck;

    // DFD scan control
    Alias jtag_dfd_host_scan_ctrl_o__capture_en = u_jtag_intf_unit.dfd_host_scan_ctrl_o__capture_en;
    Alias jtag_dfd_host_scan_ctrl_o__shift_en   = u_jtag_intf_unit.dfd_host_scan_ctrl_o__shift_en;
    Alias jtag_dfd_host_scan_ctrl_o__update_en  = u_jtag_intf_unit.dfd_host_scan_ctrl_o__update_en;
    Alias jtag_dfd_host_scan_ctrl_o__select     = u_jtag_intf_unit.dfd_host_scan_ctrl_o__select;
    Alias jtag_dfd_host_scan_ctrl_o__rst_n      = u_jtag_intf_unit.dfd_host_scan_ctrl_o__rst_n;
    Alias jtag_dfd_host_scan_ctrl_o__tck        = u_jtag_intf_unit.dfd_host_scan_ctrl_o__tck;

    // DFT scan control
    Alias jtag_dft_host_scan_ctrl_o__capture_en = u_jtag_intf_unit.dft_host_scan_ctrl_o__capture_en;
    Alias jtag_dft_host_scan_ctrl_o__shift_en   = u_jtag_intf_unit.dft_host_scan_ctrl_o__shift_en;
    Alias jtag_dft_host_scan_ctrl_o__update_en  = u_jtag_intf_unit.dft_host_scan_ctrl_o__update_en;
    Alias jtag_dft_host_scan_ctrl_o__select     = u_jtag_intf_unit.dft_host_scan_ctrl_o__select;
    Alias jtag_dft_host_scan_ctrl_o__rst_n      = u_jtag_intf_unit.dft_host_scan_ctrl_o__rst_n;
    Alias jtag_dft_host_scan_ctrl_o__tck        = u_jtag_intf_unit.dft_host_scan_ctrl_o__tck;

    // STAP TAP control outputs
    Alias jtag_stap_io_host_tap_ctrl_o__tms     = u_jtag_intf_unit.stap_io_host_tap_ctrl_o__tms;
    Alias jtag_stap_io_host_tap_ctrl_o__trst_n  = u_jtag_intf_unit.stap_io_host_tap_ctrl_o__trst_n;
    Alias jtag_stap_io_host_tap_ctrl_o__tck     = u_jtag_intf_unit.stap_io_host_tap_ctrl_o__tck;
    Alias jtag_stap_sep_host_tap_ctrl_o__tms    = u_jtag_intf_unit.stap_sep_host_tap_ctrl_o__tms;
    Alias jtag_stap_sep_host_tap_ctrl_o__trst_n = u_jtag_intf_unit.stap_sep_host_tap_ctrl_o__trst_n;
    Alias jtag_stap_sep_host_tap_ctrl_o__tck    = u_jtag_intf_unit.stap_sep_host_tap_ctrl_o__tck;
}

//-----------------------------------------------------------------------------
// JTAG Primary TAP ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// IEEE 1149.1/1687/1838 compliant Primary TAP controller
// Contains TAP FSM, instruction register, and all data registers
//-----------------------------------------------------------------------------

Module jtag_ptap {
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
    // TAP Interface Ports
    //-------------------------------------------------------------------------

    // Primary JTAG interface (client side)
    TMSPort        client_tap_ctrl_i__tms;
    TRSTPort       client_tap_ctrl_i__trst_n {
        ActivePolarity 0;
    }
    TCKPort        client_tap_ctrl_i__tck;
    TDIPort        client_tdi_i;
    TDOPort        client_tdo_o {
        Source     tdo_mux;
        Attribute  LaunchEdge = "Falling";
    }

    // Host TAP control output (for downstream STAPs)
    ToTMSPort      host_tap_ctrl_o__tms;
    ToTRSTPort     host_tap_ctrl_o__trst_n;
    ToTCKPort      host_tap_ctrl_o__tck;

    // Boundary scan register interface
    ToCaptureEnPort  bsr_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    bsr_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   bsr_host_scan_ctrl_o__update_en;
    ToSelectPort     bsr_host_scan_ctrl_o__select;
    ToResetPort      bsr_host_scan_ctrl_o__rst_n;
    ToTCKPort        bsr_host_scan_ctrl_o__tck;
    ScanInPort       bsr_host_scan_in_i;
    ScanOutPort      bsr_host_scan_out_o {
        Source     client_tdi_i;
    }

    // iJTAG network interface
    ToCaptureEnPort  ijtag_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    ijtag_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   ijtag_host_scan_ctrl_o__update_en;
    ToSelectPort     ijtag_host_scan_ctrl_o__select;
    ToResetPort      ijtag_host_scan_ctrl_o__rst_n;
    ToTCKPort        ijtag_host_scan_ctrl_o__tck;
    ScanInPort       ijtag_host_scan_in_i;
    ScanOutPort      ijtag_host_scan_out_o {
        Source     client_tdi_i;
    }

    // STAP scan interface (for downstream secondary TAPs)
    ToCaptureEnPort  stap_host_scan_ctrl_o__capture_en;
    ToShiftEnPort    stap_host_scan_ctrl_o__shift_en;
    ToUpdateEnPort   stap_host_scan_ctrl_o__update_en;
    ToSelectPort     stap_host_scan_ctrl_o__select;
    ToResetPort      stap_host_scan_ctrl_o__rst_n;
    ToTCKPort        stap_host_scan_ctrl_o__tck;
    ScanInPort       stap_host_scan_in_i;
    ScanOutPort      stap_host_scan_out_o {
        Source     zlb_tdr_mux;
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

    ScanInterface ijtag_host {
        Port  ijtag_host_scan_ctrl_o__capture_en;
        Port  ijtag_host_scan_ctrl_o__shift_en;
        Port  ijtag_host_scan_ctrl_o__update_en;
        Port  ijtag_host_scan_ctrl_o__select;
        Port  ijtag_host_scan_ctrl_o__rst_n;
        Port  ijtag_host_scan_ctrl_o__tck;
        Port  ijtag_host_scan_in_i;
        Port  ijtag_host_scan_out_o;
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

    //-------------------------------------------------------------------------
    // TAP Controller
    //-------------------------------------------------------------------------

    TapController u_tap {
        TMSPort    client_tap_ctrl_i__tms;
        TRSTPort   client_tap_ctrl_i__trst_n;
        TCKPort    client_tap_ctrl_i__tck;
        TDIPort    client_tdi_i;
        TDOPort    client_tdo_o;
        InstructionRegisterLength  6;
        InstructionCapture         6'b000001;
        InstructionOpcodeReset     6'b000001;
    }

    //-------------------------------------------------------------------------
    // Instruction Register
    //-------------------------------------------------------------------------

    // 6-bit instruction register
    ScanRegister ir_data[5:0] {
        ScanInSource   client_tdi_i;
        CaptureSource  6'b000001;
        ResetValue     6'b000001;
    }

    //-------------------------------------------------------------------------
    // Data Registers
    //-------------------------------------------------------------------------

    // Bypass register (1-bit)
    Instance u_bypass Of jtag_byp_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = bypass_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    // Inverted bypass register (1-bit)
    Instance u_inv_bypass Of jtag_inv_byp_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = inv_bypass_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    // IDCODE register (32-bit)
    Instance u_idcode Of jtag_idcode_reg {
        Parameter  IDCODE_MFR_ID   = $IDCODE_MFR_ID;
        Parameter  IDCODE_PART_NUM = $IDCODE_PART_NUM;
        Parameter  IDCODE_SI_REV   = $IDCODE_SI_REV;
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = idcode_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    // 3DCR register (2-bit) - only when STAPs are enabled
    Instance u_3dcr Of jtag_3dcr_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = tap_3dcr_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    // TMP status register (2-bit)
    Instance u_tmp_status Of jtag_tmp_status_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = tmp_status_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
        InputPort  persistence_mode_i = 1'b0;
    }

    // IC_RESET register
    Instance u_ic_reset Of jtag_ic_reset_reg {
        Parameter  NUM_IC_RESET_PORTS = $NUM_SMC_IC_RESET + $NUM_SEP_IC_RESET + $NUM_EXT_IC_RESET;
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = ic_reset_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
        InputPort  tap_ctrl_i__trst_n = client_tap_ctrl_i__trst_n;
    }

    // DEBUG_CTRL register (5-bit)
    Instance u_debug_ctrl Of jtag_debug_ctrl_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = debug_ctrl_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
        InputPort  cla_clock_stop_i = 1'b0;
    }

    // JTAG_CAPS register (60-bit)
    Instance u_caps Of jtag_caps_reg {
        Parameter  BSR_ENABLE          = $BSR_ENABLE;
        Parameter  EXTEST_TRAIN_ENABLE = $EXTEST_TRAIN_ENABLE;
        Parameter  EXTEST_PULSE_ENABLE = $EXTEST_PULSE_ENABLE;
        Parameter  INTEST_ENABLE       = $INTEST_ENABLE;
        Parameter  CLAMP_ENABLE        = $CLAMP_ENABLE;
        Parameter  HIGHZ_ENABLE        = $HIGHZ_ENABLE;
        Parameter  RUNBIST_ENABLE      = $RUNBIST_ENABLE;
        Parameter  TMP_ENABLE          = $TMP_ENABLE;
        Parameter  IC_RESET_ENABLE     = $IC_RESET_SMC_ENABLE | $IC_RESET_SEP_ENABLE | $IC_RESET_EXT_ENABLE;
        Parameter  SMC_DBG_ENABLE      = $SMC_DBG_ENABLE;
        Parameter  SEP_DBG_ENABLE      = $SEP_DBG_ENABLE;
        Parameter  STAP_IO_ENABLE      = $STAP_IO_ENABLE;
        Parameter  NUM_SMC_IC_RESET    = $NUM_SMC_IC_RESET;
        Parameter  NUM_SEP_IC_RESET    = $NUM_SEP_IC_RESET;
        Parameter  NUM_EXT_IC_RESET    = $NUM_EXT_IC_RESET;
        Parameter  NUM_EXTRA_STAPS     = $NUM_EXTRA_STAPS;
        Parameter  NUM_XTRIG_CTP       = $NUM_XTRIG_CTP;
        Parameter  NUM_XTRIG_INT_CT    = $NUM_XTRIG_INT_CT;
        Parameter  OCH_VER             = $OCH_VER;
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = caps_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    // JTAG2AXI capabilities registers (3 instances)
    Instance u_smc_otp_j2a_caps Of jtag_jtag2axi_caps_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = smc_otp_j2a_caps_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    Instance u_sep_otp_j2a_caps Of jtag_jtag2axi_caps_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = sep_otp_j2a_caps_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    Instance u_smc_j2a_caps Of jtag_jtag2axi_caps_reg {
        InputPort  scan_in_i = client_tdi_i;
        InputPort  scan_ctrl_i__capture_en = dr_capture;
        InputPort  scan_ctrl_i__shift_en = dr_shift;
        InputPort  scan_ctrl_i__update_en = dr_update;
        InputPort  scan_ctrl_i__select = smc_j2a_caps_select;
        InputPort  scan_ctrl_i__rst_n = dr_rst_n;
        InputPort  scan_ctrl_i__tck = client_tap_ctrl_i__tck;
    }

    //-------------------------------------------------------------------------
    // Instruction Decoding
    //-------------------------------------------------------------------------

    // Instruction opcodes (from jtag_inst_reg_pkg.sv)
    Alias BYPASS_ALT_INSTR      = 6'h00;
    Alias IDCODE_INSTR          = 6'h01;
    Alias RUNBIST_INSTR         = 6'h02;
    Alias SAMPLE_PRELOAD_INSTR  = 6'h03;
    Alias EXTEST_INSTR          = 6'h04;
    Alias TMP_STATUS_INSTR      = 6'h0C;
    Alias IC_RESET_INSTR        = 6'h0D;
    Alias TAP_3DCR_INSTR        = 6'h0E;
    Alias DEBUG_CONTROL_INSTR   = 6'h18;
    Alias JTAG_CAPS_INSTR       = 6'h19;
    Alias SELECT_IJTAG_INSTR    = 6'h1A;
    Alias SMC_OTP_J2A_CAPS_INSTR= 6'h1B;
    Alias SEP_OTP_J2A_CAPS_INSTR= 6'h21;
    Alias SMC_J2A_CAPS_INSTR    = 6'h27;
    Alias ZERO_LENGTH_BYPASS_INSTR = 6'h3D;
    Alias INV_BYPASS_INSTR      = 6'h3E;
    Alias BYPASS_INSTR          = 6'h3F;

    // Register select signals based on instruction
    LogicSignal bypass_select {
        (ir_data[5:0] == BYPASS_ALT_INSTR) | (ir_data[5:0] == BYPASS_INSTR);
    }
    LogicSignal inv_bypass_select {
        ir_data[5:0] == INV_BYPASS_INSTR;
    }
    LogicSignal idcode_select {
        ir_data[5:0] == IDCODE_INSTR;
    }
    LogicSignal tap_3dcr_select {
        ir_data[5:0] == TAP_3DCR_INSTR;
    }
    LogicSignal tmp_status_select {
        ir_data[5:0] == TMP_STATUS_INSTR;
    }
    LogicSignal ic_reset_select {
        ir_data[5:0] == IC_RESET_INSTR;
    }
    LogicSignal debug_ctrl_select {
        ir_data[5:0] == DEBUG_CONTROL_INSTR;
    }
    LogicSignal caps_select {
        ir_data[5:0] == JTAG_CAPS_INSTR;
    }
    LogicSignal smc_otp_j2a_caps_select {
        ir_data[5:0] == SMC_OTP_J2A_CAPS_INSTR;
    }
    LogicSignal sep_otp_j2a_caps_select {
        ir_data[5:0] == SEP_OTP_J2A_CAPS_INSTR;
    }
    LogicSignal smc_j2a_caps_select {
        ir_data[5:0] == SMC_J2A_CAPS_INSTR;
    }
    LogicSignal bsr_select {
        (ir_data[5:0] == EXTEST_INSTR) | (ir_data[5:0] == SAMPLE_PRELOAD_INSTR);
    }
    LogicSignal ijtag_select {
        (ir_data[5:0] == SELECT_IJTAG_INSTR) | (ir_data[5:0] == RUNBIST_INSTR);
    }
    LogicSignal zlb_select {
        ir_data[5:0] == ZERO_LENGTH_BYPASS_INSTR;
    }

    //-------------------------------------------------------------------------
    // TDO Multiplexing
    //-------------------------------------------------------------------------

    // Zero-length bypass / TDR mux
    ScanMux zlb_tdr_mux SelectedBy zlb_select {
        1'b0 : tdr_mux;
        1'b1 : client_tdi_i;
    }

    // STAP select / ZLB mux
    ScanMux tdo_mux SelectedBy u_3dcr.stap_sel_o {
        1'b0 : zlb_tdr_mux;
        1'b1 : stap_host_scan_in_i;
    }

    // Main TDR multiplexer
    ScanMux tdr_mux SelectedBy ir_data[5:0] {
        BYPASS_ALT_INSTR     : u_bypass.scan_out_o;
        IDCODE_INSTR         : u_idcode.scan_out_o;
        TAP_3DCR_INSTR       : u_3dcr.scan_out_o;
        TMP_STATUS_INSTR     : u_tmp_status.scan_out_o;
        IC_RESET_INSTR       : u_ic_reset.scan_out_o;
        DEBUG_CONTROL_INSTR  : u_debug_ctrl.scan_out_o;
        JTAG_CAPS_INSTR      : u_caps.scan_out_o;
        SMC_OTP_J2A_CAPS_INSTR : u_smc_otp_j2a_caps.scan_out_o;
        SEP_OTP_J2A_CAPS_INSTR : u_sep_otp_j2a_caps.scan_out_o;
        SMC_J2A_CAPS_INSTR   : u_smc_j2a_caps.scan_out_o;
        INV_BYPASS_INSTR     : u_inv_bypass.scan_out_o;
        BYPASS_INSTR         : u_bypass.scan_out_o;
        EXTEST_INSTR         : bsr_host_scan_in_i;
        SAMPLE_PRELOAD_INSTR : bsr_host_scan_in_i;
        SELECT_IJTAG_INSTR   : ijtag_host_scan_in_i;
        RUNBIST_INSTR        : ijtag_host_scan_in_i;
        default              : u_bypass.scan_out_o;
    }
}

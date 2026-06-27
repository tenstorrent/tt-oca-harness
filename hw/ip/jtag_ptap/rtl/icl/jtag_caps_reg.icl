//-----------------------------------------------------------------------------
// JTAG Capabilities Register ICL Model
//
// Copyright 2025 Tenstorrent Inc.
//
// 60-bit read-only capabilities register reporting DTP configuration
// This register captures a constant value reflecting enabled features
//-----------------------------------------------------------------------------

Module jtag_caps_reg {
    // Configuration parameters
    Parameter  BSR_ENABLE          = 1;
    Parameter  EXTEST_TRAIN_ENABLE = 1;
    Parameter  EXTEST_PULSE_ENABLE = 1;
    Parameter  INTEST_ENABLE       = 1;
    Parameter  CLAMP_ENABLE        = 1;
    Parameter  HIGHZ_ENABLE        = 1;
    Parameter  RUNBIST_ENABLE      = 1;
    Parameter  TMP_ENABLE          = 1;
    Parameter  IC_RESET_ENABLE     = 1;
    Parameter  SMC_DBG_ENABLE      = 1;
    Parameter  SEP_DBG_ENABLE      = 1;
    Parameter  STAP_IO_ENABLE      = 1;
    Parameter  NUM_SMC_IC_RESET    = 0;
    Parameter  NUM_SEP_IC_RESET    = 0;
    Parameter  NUM_EXT_IC_RESET    = 0;
    Parameter  NUM_EXTRA_STAPS     = 0;
    Parameter  NUM_XTRIG_CTP       = 8;
    Parameter  NUM_XTRIG_INT_CT    = 1;
    Parameter  OCH_VER             = 8'h00;

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
        Source     caps_data[0];
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

    // 60-bit capabilities register (read-only)
    // Bit layout:
    // [59:54] = num_xtrig_int_ct (6 bits)
    // [53:48] = num_xtrig_ctp (6 bits)
    // [47:44] = num_xtra_stap (4 bits)
    // [43]    = stap_io_en
    // [42]    = sep_dbg_en
    // [41]    = smc_dbg_en
    // [40:33] = num_smc_ic_rst (8 bits)
    // [32:25] = num_sep_ic_rst (8 bits)
    // [24:17] = num_ext_ic_rst (8 bits)
    // [16]    = ic_rst_inst_en
    // [15]    = tmp_inst_en
    // [14]    = runbist_inst_en
    // [13]    = highz_inst_en
    // [12]    = clamp_inst_en
    // [11]    = intest_inst_en
    // [10]    = extest_pulse_en
    // [9]     = extest_train_en
    // [8]     = bsr_inst_en
    // [7:0]   = och_ver (8 bits)
    ScanRegister caps_data[59:0] {
        ScanInSource   scan_in_i;
        CaptureSource  {$NUM_XTRIG_INT_CT[5:0], $NUM_XTRIG_CTP[5:0],
                        $NUM_EXTRA_STAPS[3:0], $STAP_IO_ENABLE, $SEP_DBG_ENABLE,
                        $SMC_DBG_ENABLE, $NUM_SMC_IC_RESET[7:0], $NUM_SEP_IC_RESET[7:0],
                        $NUM_EXT_IC_RESET[7:0], $IC_RESET_ENABLE,
                        $TMP_ENABLE, $RUNBIST_ENABLE, $HIGHZ_ENABLE,
                        $CLAMP_ENABLE, $INTEST_ENABLE, $EXTEST_PULSE_ENABLE,
                        $EXTEST_TRAIN_ENABLE, $BSR_ENABLE, $OCH_VER[7:0]};
        ResetValue     {$NUM_XTRIG_INT_CT[5:0], $NUM_XTRIG_CTP[5:0],
                        $NUM_EXTRA_STAPS[3:0], $STAP_IO_ENABLE, $SEP_DBG_ENABLE,
                        $SMC_DBG_ENABLE, $NUM_SMC_IC_RESET[7:0], $NUM_SEP_IC_RESET[7:0],
                        $NUM_EXT_IC_RESET[7:0], $IC_RESET_ENABLE,
                        $TMP_ENABLE, $RUNBIST_ENABLE, $HIGHZ_ENABLE,
                        $CLAMP_ENABLE, $INTEST_ENABLE, $EXTEST_PULSE_ENABLE,
                        $EXTEST_TRAIN_ENABLE, $BSR_ENABLE, $OCH_VER[7:0]};
    }
}

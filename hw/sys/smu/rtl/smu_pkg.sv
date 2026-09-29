// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold System Management Unit configuration types and defaults.
//
// Define smu_cfg_t and DefaultCfg for JTAG feature enables, cross-trigger counts,
// pipeline depths, and SEP/Adams-Bridge options consumed by smu; the JTAG, cross-trigger
// and pipeline fields configure its DTP instance. XTRIG_NUM_INT_CT and
// XTRIG_NUM_CLK_STOP_REQ are the SMU-exposed counts; smu adds the SMC-reserved lanes
// (XTRIG_SMC_INT_CT_LANES, XTRIG_SMC_CLK_STOP_LANES) before passing them to DTP.
// NoSepCfg holds the same values as DefaultCfg, and SmuConfigs lists both.

package smu_pkg;

  import dtp_pkg::*;

  localparam int unsigned XTRIG_SMC_INT_CT_LANES = 2;
  localparam int unsigned XTRIG_SMC_CLK_STOP_LANES = 1;
  localparam int unsigned XTRIG_INT_CT_MODE_WIDTH = 32;

  typedef struct packed {
    int unsigned NUM_INT_TO_SMC;

    // JTAG feature enables
    bit JTAG_BSR_ENABLE;
    bit JTAG_EXTEST_TRAIN_ENABLE;
    bit JTAG_EXTEST_PULSE_ENABLE;
    bit JTAG_INTEST_ENABLE;
    bit JTAG_CLAMP_ENABLE;
    bit JTAG_HIGHZ_ENABLE;
    bit JTAG_RUNBIST_ENABLE;
    bit JTAG_TMP_ENABLE;
    bit JTAG_IC_RESET_ENABLE;
    bit JTAG_SMC_DBG_ENABLE;
    bit JTAG_STAP_IO_ENABLE;

    // JTAG instance counts
    int unsigned JTAG_NUM_EXTRA_STAPS;

    // JTAG identification
    logic [10:0] JTAG_IDCODE_MFR_ID;
    logic [15:0] JTAG_IDCODE_PART_NUM;
    logic [3:0]  JTAG_IDCODE_SI_REV;
    logic [7:0]  JTAG_OCH_VER;

    // Cross-trigger configuration. XTRIG_NUM_INT_CT and XTRIG_NUM_CLK_STOP_REQ
    // are the SMU-exposed counts; smu adds the SMC-reserved lanes for DTP.
    int unsigned XTRIG_NUM_CTP;
    int unsigned XTRIG_NUM_INT_CT;
    int unsigned XTRIG_NUM_CLK_STOP_REQ;
    logic [XTRIG_INT_CT_MODE_WIDTH-1:0] XTRIG_INT_CT_MODE;

    // Pipeline depth parameters
    logic [1:0] SMC_OTP_RD_PL_DEPTH;
    logic [1:0] SMC_OTP_WR_PL_DEPTH;
    logic [1:0] SMC_RD_PL_DEPTH;
    logic [1:0] SMC_WR_PL_DEPTH;

    // SEP Key Manager PicoRV32 memory configuration
    bit SEP_KM_LATCHED_MEM_RDATA;

    // Adams Bridge SRAM configuration
    bit          SEP_ABR_MASKING_EN;
    int unsigned SEP_ABR_SRAM_LATENCY;
  } smu_cfg_t;

  localparam smu_cfg_t DefaultCfg = '{
      NUM_INT_TO_SMC: 32'd256,  // smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS.
      JTAG_BSR_ENABLE: 1'b1,
      JTAG_EXTEST_TRAIN_ENABLE: 1'b1,
      JTAG_EXTEST_PULSE_ENABLE: 1'b1,
      JTAG_INTEST_ENABLE: 1'b1,
      JTAG_CLAMP_ENABLE: 1'b1,
      JTAG_HIGHZ_ENABLE: 1'b1,
      JTAG_RUNBIST_ENABLE: 1'b1,
      JTAG_TMP_ENABLE: 1'b1,
      JTAG_IC_RESET_ENABLE: 1'b1,
      JTAG_SMC_DBG_ENABLE: 1'b1,
      JTAG_STAP_IO_ENABLE: 1'b1,
      JTAG_NUM_EXTRA_STAPS: 32'd1,
      JTAG_IDCODE_MFR_ID: 11'h000,
      JTAG_IDCODE_PART_NUM: 16'h0000,
      JTAG_IDCODE_SI_REV: 4'h0,
      JTAG_OCH_VER: 8'h00,
      XTRIG_NUM_CTP: dtp_pkg::DEFAULT_NUM_CTP,
      XTRIG_NUM_INT_CT: dtp_pkg::DEFAULT_NUM_INT_CT - XTRIG_SMC_INT_CT_LANES,
      XTRIG_NUM_CLK_STOP_REQ: dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ - XTRIG_SMC_CLK_STOP_LANES,
      XTRIG_INT_CT_MODE: '0,
      SMC_OTP_RD_PL_DEPTH: 2'h3,
      SMC_OTP_WR_PL_DEPTH: 2'h3,
      SMC_RD_PL_DEPTH: 2'h3,
      SMC_WR_PL_DEPTH: 2'h3,
      SEP_KM_LATCHED_MEM_RDATA: 1'b1,
      SEP_ABR_MASKING_EN: 1'b1,
      SEP_ABR_SRAM_LATENCY: 32'd1
  };

  localparam smu_cfg_t NoSepCfg = '{
      NUM_INT_TO_SMC: 32'd256,  // smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS.
      JTAG_BSR_ENABLE: 1'b1,
      JTAG_EXTEST_TRAIN_ENABLE: 1'b1,
      JTAG_EXTEST_PULSE_ENABLE: 1'b1,
      JTAG_INTEST_ENABLE: 1'b1,
      JTAG_CLAMP_ENABLE: 1'b1,
      JTAG_HIGHZ_ENABLE: 1'b1,
      JTAG_RUNBIST_ENABLE: 1'b1,
      JTAG_TMP_ENABLE: 1'b1,
      JTAG_IC_RESET_ENABLE: 1'b1,
      JTAG_SMC_DBG_ENABLE: 1'b1,
      JTAG_STAP_IO_ENABLE: 1'b1,
      JTAG_NUM_EXTRA_STAPS: 32'd1,
      JTAG_IDCODE_MFR_ID: 11'h000,
      JTAG_IDCODE_PART_NUM: 16'h0000,
      JTAG_IDCODE_SI_REV: 4'h0,
      JTAG_OCH_VER: 8'h00,
      XTRIG_NUM_CTP: dtp_pkg::DEFAULT_NUM_CTP,
      XTRIG_NUM_INT_CT: dtp_pkg::DEFAULT_NUM_INT_CT - XTRIG_SMC_INT_CT_LANES,
      XTRIG_NUM_CLK_STOP_REQ: dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ - XTRIG_SMC_CLK_STOP_LANES,
      XTRIG_INT_CT_MODE: '0,
      SMC_OTP_RD_PL_DEPTH: 2'h3,
      SMC_OTP_WR_PL_DEPTH: 2'h3,
      SMC_RD_PL_DEPTH: 2'h3,
      SMC_WR_PL_DEPTH: 2'h3,
      SEP_KM_LATCHED_MEM_RDATA: 1'b1,
      SEP_ABR_MASKING_EN: 1'b1,
      SEP_ABR_SRAM_LATENCY: 32'd1
  };

  localparam int unsigned NumSmuConfigs = 2;
  localparam smu_cfg_t [NumSmuConfigs-1:0] SmuConfigs = {
    NoSepCfg,  // [1] SMC + DTP only.
    DefaultCfg  // [0] Full SMU (SMC + SEP + DTP).
  };

endpackage : smu_pkg

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold System Management Unit configuration types and defaults.
//
// Define smu_cfg_t, the configuration smu takes as CFG, its presets, and the functions that
// derive the DTP cross-trigger and extra-STAP parameters from it. SmuConfigs lists DefaultCfg
// at index 0 and NoSepCfg at index 1. CFG defaults to SmuConfigs[CFG_IDX], and a CFG set
// directly takes precedence over CFG_IDX. NoSepCfg differs from DefaultCfg only in SEP. The
// JTAG, cross-trigger and pipeline fields configure the DTP instance in smu, each forwarded to
// the DTP parameter of the same name unless its clause says otherwise.
// XTRIG_NUM_INT_CT and XTRIG_NUM_CLK_STOP_REQ are the SMU-exposed counts; smu adds the
// SMC-reserved lanes (XtrigSmcIntCtLanes, XtrigSmcClkStopLanes) before passing them to DTP.
//
// DefaultCfg enables every JTAG feature with one extra STAP and zero ID fields, and sets 16
// CTPs, 8 exposed internal CT lanes, 8 exposed clock-stop requests, all lanes in pulse-sync
// mode, pipeline depths of 3, 256 SMC interrupts, two outstanding SMC AXI-Lite transactions
// and 4-byte eFuse shim windows. It includes the SEP with a zero secure-disable token, three
// external TRNG streams, Adams Bridge masking on and a one-cycle Adams Bridge SRAM latency.

package smu_pkg;

  import dtp_pkg::*;

  localparam int unsigned XtrigSmcIntCtLanes = 2;
  localparam int unsigned XtrigSmcClkStopLanes = 1;
  localparam int unsigned XtrigIntCtModeWidth = 32;

  typedef struct packed {
    int unsigned NUM_INT_TO_SMC;  // Width of smc_ext_interrupts_i, 1 to 256; smu zero-extends
                                  // it to the 256 SMC external interrupt inputs.

    // JTAG enables
    bit JTAG_BSR_ENABLE;           // Enables the mandatory boundary-scan instructions.
    bit JTAG_EXTEST_TRAIN_ENABLE;  // Enables the optional EXTEST_TRAIN instruction; needs
                                   // JTAG_BSR_ENABLE.
    bit JTAG_EXTEST_PULSE_ENABLE;  // Enables the optional EXTEST_PULSE instruction; needs
                                   // JTAG_BSR_ENABLE.
    bit JTAG_INTEST_ENABLE;        // Enables the optional INTEST instruction; needs
                                   // JTAG_BSR_ENABLE.
    bit JTAG_CLAMP_ENABLE;         // Reports CLAMP support in JTAG_CAPS; it sets only the CAPS
                                   // bit, and CLAMP decodes either way.
    bit JTAG_HIGHZ_ENABLE;         // Reports HIGHZ support in JTAG_CAPS; it sets only the CAPS
                                   // bit, and HIGHZ decodes either way.
    bit JTAG_RUNBIST_ENABLE;       // Enables the optional RUNBIST instruction.
    bit JTAG_TMP_ENABLE;           // Enables the TMP controller and its instructions.
    bit JTAG_IC_RESET_ENABLE;      // Enables the external slice of the IC_RESET TDR; drives the
                                   // DTP JTAG_IC_RESET_EXT_ENABLE. The SMC slice is always on,
                                   // and the SEP slice follows SEP.
    bit JTAG_SMC_DBG_ENABLE;       // Enables the JTAG2AXI bridge to the SMC debug interface.
    bit JTAG_STAP_IO_ENABLE;       // Enables the I/O STAP for chiplet-to-chiplet connectivity.

    // JTAG instance counts
    int unsigned JTAG_NUM_EXTRA_STAPS;  // Number of additional STAPs for local connectivity, 0
                                        // to 15 to fit its 4-bit JTAG_CAPS field. The extra
                                        // STAP port arrays keep one entry when it is 0.

    // JTAG identification
    logic [10:0] JTAG_IDCODE_MFR_ID;    // JEDEC manufacturer ID in the DTP IDCODE, and in the
                                        // SMC CPU and SEP JTAG ID codes.
    logic [15:0] JTAG_IDCODE_PART_NUM;  // Part number in the DTP IDCODE, and in the SMC CPU and
                                        // SEP JTAG ID codes.
    logic [3:0]  JTAG_IDCODE_SI_REV;    // Silicon revision in the DTP IDCODE, and the version
                                        // in the SMC CPU and SEP JTAG ID codes.
    logic [7:0]  JTAG_OCH_VER;          // DTP IP major version reported over JTAG.

    // Cross-trigger
    int unsigned XTRIG_NUM_CTP;           // External cross-trigger port count, at least 1;
                                          // forwarded to the DTP XTRIG_NUM_CTP.
                                          // XTRIG_NUM_CTP + XTRIG_NUM_INT_CT +
                                          // XtrigSmcIntCtLanes must equal the 26 CT ports
                                          // of the generated cross-trigger matrix map.
    int unsigned XTRIG_NUM_INT_CT;        // SMU-exposed internal CT lane count, 1 to 32; the
                                          // DTP gets these plus the XtrigSmcIntCtLanes
                                          // SMC lanes below them.
    int unsigned XTRIG_NUM_CLK_STOP_REQ;  // SMU-exposed clock-stop request count, at least 1;
                                          // the DTP gets these plus the
                                          // XtrigSmcClkStopLanes SMC lane below them.
    logic [XtrigIntCtModeWidth-1:0] XTRIG_INT_CT_MODE;  // Per exposed lane, 0 for pulse
                                                        // sync and 1 for req/ack. Bits at
                                                        // and above XTRIG_NUM_INT_CT are
                                                        // ignored, and the SMC lanes are
                                                        // always pulse sync.

    // Pipeline depths
    logic [1:0] SMC_OTP_RD_PL_DEPTH;  // DTP JTAG2AXI read pipeline depth toward the SMC OTP, 0
                                      // to 3; 0 is a single outstanding read.
    logic [1:0] SMC_OTP_WR_PL_DEPTH;  // Write pipeline depth toward the SMC OTP, 0 to 3; it is
                                      // reported in the JTAG2AXI CAPS only.
    logic [1:0] SMC_RD_PL_DEPTH;      // DTP JTAG2AXI read pipeline depth toward the SMC fabric,
                                      // 0 to 3; 0 is a single outstanding read.
    logic [1:0] SMC_WR_PL_DEPTH;      // Write pipeline depth toward the SMC fabric, 0 to 3; it
                                      // is reported in the JTAG2AXI CAPS only.

    // SMC
    int unsigned MAX_TRANS;            // Maximum outstanding AXI-Lite transactions in the SMC
                                       // pad-ring GPIO demux and each GPIO interface, at least
                                       // 1; forwarded to the SMC MAX_TRANS.
    int unsigned SMC_EFUSE_SHIM_SIZE;  // Size in bytes of the vendor eFuse shim CSR block
                                       // carved off the base of the smc_external window,
                                       // greater than 0 and smaller than that window;
                                       // forwarded to the SMC EFUSE_SHIM_SIZE.

    // SEP
    bit          SEP;                    // 1 includes the Secure Execution Processor and the
                                         // SMU AXI crossbar, and enables the DTP SEP IC_RESET
                                         // slice and SEP debug STAP. 0 ties the SEP ports off
                                         // and connects the SMC to the external AXI ports
                                         // through ID-width converters.
    int unsigned SEP_EFUSE_SHIM_SIZE;    // Size in bytes of the eFuse shim CSR window that the
                                         // SEP diverts from its external aperture to the eFuse
                                         // wrapper, 1 to 0x1000_0000, the offset of the
                                         // execute-in-place window; it should cover the shim
                                         // CSR block. Forwarded to the SEP EFUSE_SHIM_SIZE and
                                         // unused when SEP is 0.
    bit [255:0]  SEP_SEC_DISABLE_TOKEN;  // Expected SEP secure-disable token digest, any
                                         // value. Each bit selects the tap of one revision
                                         // cell, so a metal ECO can change the digest.
                                         // Forwarded to the SEP and unused when SEP is 0.
    int unsigned EXT_TRNG_NUM_AXIS;      // External TRNG AXI-stream count, one per SEP entropy
                                         // mux leg; must equal
                                         // sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT (3).
                                         // Sets the ext_trng_axis_* port widths and is
                                         // forwarded to the SEP EXT_TRNG_NUM_AXIS.

    // SEP Key Manager
    bit SEP_KM_LATCHED_MEM_RDATA;  // 1 when the Key Manager ROM and SRAM macros hold their
                                   // read data, so the PicoRV32 can look ahead; set it only for
                                   // such macros. Forwarded to the SEP KM_LATCHED_MEM_RDATA and
                                   // unused when SEP is 0.

    // SEP Adams Bridge
    bit          SEP_ABR_MASKING_EN;    // Enables Adams Bridge 2-share DOM masking; must match
                                        // the sep_ip_integration ABR_MASKING_EN. Forwarded to
                                        // the SEP ABR_MASKING_EN and unused when SEP is 0.
    int unsigned SEP_ABR_SRAM_LATENCY;  // Adams Bridge SRAM read latency in cycles, at least 1
                                        // and equal to the macro read latency, 1 for the open
                                        // prim_ram_1r1w. Forwarded to the SEP ABR_SRAM_LATENCY
                                        // and unused when SEP is 0.
  } smu_cfg_t;

  localparam smu_cfg_t DefaultCfg = '{
      NUM_INT_TO_SMC: 32'd256,  // smc_4core_cpu_pkg::NumExtInterrupts.
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
      XTRIG_NUM_CTP: dtp_pkg::DefaultNumCtp,
      XTRIG_NUM_INT_CT: dtp_pkg::DefaultNumIntCt - XtrigSmcIntCtLanes,
      XTRIG_NUM_CLK_STOP_REQ: dtp_pkg::DefaultNumClkStopReq - XtrigSmcClkStopLanes,
      XTRIG_INT_CT_MODE: '0,
      SMC_OTP_RD_PL_DEPTH: 2'h3,
      SMC_OTP_WR_PL_DEPTH: 2'h3,
      SMC_RD_PL_DEPTH: 2'h3,
      SMC_WR_PL_DEPTH: 2'h3,
      MAX_TRANS: 32'd2,
      SMC_EFUSE_SHIM_SIZE: 32'h4,
      SEP: 1'b1,
      SEP_EFUSE_SHIM_SIZE: 32'h4,
      SEP_SEC_DISABLE_TOKEN: '0,
      EXT_TRNG_NUM_AXIS: 32'd3,
      SEP_KM_LATCHED_MEM_RDATA: 1'b1,
      SEP_ABR_MASKING_EN: 1'b1,
      SEP_ABR_SRAM_LATENCY: 32'd1
  };

  localparam smu_cfg_t NoSepCfg = '{
      NUM_INT_TO_SMC: 32'd256,  // smc_4core_cpu_pkg::NumExtInterrupts.
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
      XTRIG_NUM_CTP: dtp_pkg::DefaultNumCtp,
      XTRIG_NUM_INT_CT: dtp_pkg::DefaultNumIntCt - XtrigSmcIntCtLanes,
      XTRIG_NUM_CLK_STOP_REQ: dtp_pkg::DefaultNumClkStopReq - XtrigSmcClkStopLanes,
      XTRIG_INT_CT_MODE: '0,
      SMC_OTP_RD_PL_DEPTH: 2'h3,
      SMC_OTP_WR_PL_DEPTH: 2'h3,
      SMC_RD_PL_DEPTH: 2'h3,
      SMC_WR_PL_DEPTH: 2'h3,
      MAX_TRANS: 32'd2,
      SMC_EFUSE_SHIM_SIZE: 32'h4,
      SEP: 1'b0,
      SEP_EFUSE_SHIM_SIZE: 32'h4,
      SEP_SEC_DISABLE_TOKEN: '0,
      EXT_TRNG_NUM_AXIS: 32'd3,
      SEP_KM_LATCHED_MEM_RDATA: 1'b1,
      SEP_ABR_MASKING_EN: 1'b1,
      SEP_ABR_SRAM_LATENCY: 32'd1
  };

  localparam int unsigned NumSmuConfigs = 2;
  localparam smu_cfg_t [NumSmuConfigs-1:0] SmuConfigs = {
    NoSepCfg,  // [1] SMC + DTP only.
    DefaultCfg  // [0] Full SMU (SMC + SEP + DTP).
  };

  // DTP internal CT lane count: the exposed lanes plus the SMC-reserved lanes.
  function automatic int unsigned dtp_xtrig_num_int_ct(input smu_cfg_t cfg);
    return cfg.XTRIG_NUM_INT_CT + XtrigSmcIntCtLanes;
  endfunction

  // DTP clock-stop request count: the exposed requests plus the SMC-reserved lane.
  function automatic int unsigned dtp_xtrig_num_clk_stop_req(input smu_cfg_t cfg);
    return cfg.XTRIG_NUM_CLK_STOP_REQ + XtrigSmcClkStopLanes;
  endfunction

  // Extra STAP port count: JTAG_NUM_EXTRA_STAPS, but at least one for the tie-off.
  function automatic int unsigned jtag_num_extra_stap_ports(input smu_cfg_t cfg);
    return (cfg.JTAG_NUM_EXTRA_STAPS > 0) ? cfg.JTAG_NUM_EXTRA_STAPS : 1;
  endfunction

  // DTP per-lane CT mode vector, wide enough for every legal XTRIG_NUM_INT_CT.
  typedef logic [XtrigIntCtModeWidth+XtrigSmcIntCtLanes-1:0] dtp_ct_mode_t;

  // DTP per-lane CT mode: the exposed lanes' modes above the zeroed SMC-reserved lanes.
  function automatic dtp_ct_mode_t dtp_xtrig_int_ct_mode(input smu_cfg_t cfg);
    return {cfg.XTRIG_INT_CT_MODE & ~('1 << cfg.XTRIG_NUM_INT_CT), {XtrigSmcIntCtLanes{1'b0}}};
  endfunction

endpackage : smu_pkg

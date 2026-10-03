// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Aggregate SMC internal CSR blocks on the internal AXI-Lite and APB maps.
//
// Decodes filter, remap, mailbox, DFT, and base-config CSRs and exposes their structs.
// Publishes the SMC address window, clock-gate enables, and AXI hang-detector config from
// smc_base_config for consumers outside this module.
// Carries DFD, TDR debug, and trace-sink memory sidebands plus DFT status and clock-gater
// activity indicators.
// The mailbox, filter and remap register blocks each run on their own idle-gated copy of
// the SMC core clock. Writes to a filter whose FILTER_CONFIG.locked bit is set receive
// DECERR; reads of a locked filter still complete.

module smc_internal_regs #(
  parameter int unsigned NUM_OUTBOUND_FILTERS = 16,  // Number of outbound filter register blocks;
                                                     // sizes the outbound filter CSR arrays and the
                                                     // AXI-Lite demux that selects one block per
                                                     // 32-byte address window.
  parameter int unsigned NUM_INBOUND_FILTERS  = 16,  // Number of inbound filter register blocks;
                                                     // sizes the inbound filter CSR arrays and the
                                                     // AXI-Lite demux that selects one block per
                                                     // 32-byte address window.

  localparam type outbound_select_t = logic [$clog2(NUM_OUTBOUND_FILTERS)-1:0],  // Index that selects one outbound filter
                                                                                 // register block from the AXI-Lite address.
  localparam type inbound_select_t  = logic [$clog2(NUM_INBOUND_FILTERS)-1:0]  // Index that selects one inbound filter
                                                                               // register block from the AXI-Lite address.
) (
  input  logic clk_ref_i,               // Reference clock, used only by the DFD block for the CLA
                                        // time tick.
  input  logic clk_smc_i,               // SMC core clock for every CSR block, and the source of
                                        // their gated clocks.

  input  logic rst_primary_smc_clk_ni,  // Primary reset, active-low, synchronized to the SMC core
                                        // clock; resets every CSR block in this module.

  input  filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status_i [NUM_OUTBOUND_FILTERS-1:0],  // Hardware status of
                                                                                                       // each outbound filter
                                                                                                       // entry, from the output
                                                                                                       // fabric.
  output filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl_o [NUM_OUTBOUND_FILTERS-1:0],  // Register
                                                                                                     // configuration of each
                                                                                                     // outbound filter entry.
  input  filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status_i [NUM_INBOUND_FILTERS-1:0],  // Hardware status of
                                                                                                     // each inbound filter
                                                                                                     // entry, from the input
                                                                                                     // fabric.
  output filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl_o [NUM_INBOUND_FILTERS-1:0],  // Register
                                                                                                   // configuration of each
                                                                                                   // inbound filter entry.

  output output_remap_reg_pkg::output_remap__out_t mR_ctrl_o [smc_pkg::NumMmodeOutputRemapRegions-1:0],      // Register
                                                                                                             // configuration of each
                                                                                                             // M-mode output remap
                                                                                                             // region.
  output output_remap_reg_pkg::output_remap__out_t xR_ctrl_o [smc_pkg::NumXvisorOutputRemapRegions-1:0],      // Register
                                                                                                              // configuration of each
                                                                                                              // Xvisor output remap
                                                                                                              // region.
  output alias_remap_reg_pkg::alias_remap__out_t   aR_ctrl_o [smc_pkg::NumAliasRemapRegions-1:0],     // Register
                                                                                                      // configuration of each
                                                                                                      // alias remap region.

  input  smc_pkg::smc_dfd_apb_req_t  apb_smc_dfd_reg_req_i,  // APB request from the local
                                                             // crossbar for the CLA and DST
                                                             // registers.
  output smc_pkg::smc_dfd_apb_resp_t apb_smc_dfd_reg_resp_o,  // APB response to the local
                                                              // crossbar.

  input  smc_pkg::smc_axil_32_64_req_t  axil_inbound_filter_ctrl_req_i,  // Request from the
                                                                         // internal CSR crossbar
                                                                         // for the inbound
                                                                         // filter windows.
  output smc_pkg::smc_axil_32_64_resp_t axil_inbound_filter_ctrl_resp_o,  // Response for the
                                                                          // inbound filter
                                                                          // windows.
  input  smc_pkg::smc_axil_32_64_req_t  axil_outbound_filter_ctrl_req_i,  // Request from the
                                                                          // internal CSR
                                                                          // crossbar for the
                                                                          // outbound filter
                                                                          // windows.
  output smc_pkg::smc_axil_32_64_resp_t axil_outbound_filter_ctrl_resp_o,  // Response for the
                                                                           // outbound filter
                                                                           // windows.

  input  smc_pkg::smc_axil_32_64_req_t  axil_mR_ctrl_req_i,  // Request from the internal CSR
                                                             // crossbar for the M-mode remap
                                                             // windows.
  output smc_pkg::smc_axil_32_64_resp_t axil_mR_ctrl_resp_o,  // Response for the M-mode
                                                              // remap windows.
  input  smc_pkg::smc_axil_32_64_req_t  axil_xR_ctrl_req_i,  // Request from the internal CSR
                                                             // crossbar for the Xvisor remap
                                                             // windows.
  output smc_pkg::smc_axil_32_64_resp_t axil_xR_ctrl_resp_o,  // Response for the Xvisor
                                                              // remap windows.
  input  smc_pkg::smc_axil_32_64_req_t  axil_aR_ctrl_req_i,  // Request from the internal CSR
                                                             // crossbar for the alias remap
                                                             // windows.
  output smc_pkg::smc_axil_32_64_resp_t axil_aR_ctrl_resp_o,  // Response for the alias remap
                                                              // windows.

  input  smc_pkg::smc_axil_32_64_req_t  axil_mailbox_req_i,  // Request from the internal CSR
                                                             // crossbar for the mailbox
                                                             // window.
  output smc_pkg::smc_axil_32_64_resp_t axil_mailbox_resp_o,  // Response for the mailbox
                                                              // window.

  input  smc_pkg::smc_axil_32_64_req_t  axil_dfx_csr_req_i,  // Request from the internal CSR
                                                             // crossbar for the DFX control
                                                             // window.
  output smc_pkg::smc_axil_32_64_resp_t axil_dfx_csr_resp_o,  // Response for the DFX control
                                                              // window.

  output logic [smc_pkg::NumMailboxes-1:0] inbound_interrupt_o,   // Per-mailbox inbound data
                                                                  // interrupt; smc_base routes
                                                                  // it to the SMC CPU.
  output logic [smc_pkg::NumMailboxes-1:0] outbound_interrupt_o,   // Per-mailbox outbound data
                                                                   // interrupt; smc_base drives
                                                                   // it out of the SMC.

  input  smc_pkg::smc_axil_32_64_req_t  axil_smc_base_config_req_i,  // Request from the
                                                                     // internal CSR crossbar
                                                                     // for the base-config
                                                                     // window.
  output smc_pkg::smc_axil_32_64_resp_t axil_smc_base_config_resp_o,  // Response for the
                                                                      // base-config window.

  output smc_pkg::smc_axi_addr_t smc_global_base_o,  // SMC global base address from
                                                     // GLOBAL_BASE.
  output smc_pkg::smc_axi_addr_t smc_local_base_o,  // SMC local base address from
                                                    // LOCAL_BASE.
  output logic [31:0]            smc_region_size_o,  // SMC region size in bytes from
                                                     // REGION_SIZE.

  output logic                cg_ctrl_dma_cg_en_o,  // Enables idle clock gating of the DMA
                                                    // when high.
  output logic                cg_ctrl_ob_filter_axi_cg_en_o,  // Enables idle clock gating of
                                                              // the outbound filter datapath
                                                              // when high.
  output logic                cg_ctrl_ib_filter_axi_cg_en_o,  // Enables idle clock gating of
                                                              // the inbound filter datapath
                                                              // when high.
  output logic                cg_ctrl_output_fabric_cg_en_o,  // Enables idle clock gating of
                                                              // the output fabric when high.
  output logic                cg_ctrl_zeroer_cg_en_o,  // Enables idle clock gating of the
                                                       // zeroer when high.
  output logic                cg_ctrl_i3c_cg_en_o,  // In smc, stops the I3C peripheral clock
                                                    // when high.
  output logic                cg_ctrl_avs_cg_en_o,  // In smc, stops the AVSBus controller
                                                    // peripheral and reference clocks when
                                                    // high.
  output logic                cg_ctrl_i2c_cg_en_o,  // In smc, stops the I2C peripheral clock
                                                    // when high.
  output logic                cg_ctrl_uart_cg_en_o,  // In smc, stops the UART peripheral clock
                                                     // when high.
  output logic                cg_ctrl_tel_cg_en_o,  // In smc, stops the telemetry unit's gated
                                                    // SMC and telemetry clocks when high.
  output smc_pkg::cg_hyster_t cg_ctrl_hysteresis_o,  // Idle SMC core clock cycles every idle
                                                     // clock gate waits before stopping its
                                                     // clock; also used by the gates in this
                                                     // module.

  output logic        hang_det_sys_axi_enable_o,  // Enables the system AXI hang detector.
  output logic        hang_det_sys_axi_irq_en_o,  // Enables the system AXI hang interrupt.
  output logic        hang_det_sys_axi_irq_test_o,  // Forces the system AXI hang interrupt
                                                    // high.
  output logic [19:0] hang_det_sys_axi_threshold_o,  // Stall cycles after which the system
                                                     // AXI hang detector fires.
  output logic        hang_det_sep_axi_enable_o,  // Enables the SEP AXI hang detector.
  output logic        hang_det_sep_axi_irq_en_o,  // Enables the SEP AXI hang interrupt.
  output logic        hang_det_sep_axi_irq_test_o,  // Forces the SEP AXI hang interrupt high.
  output logic [19:0] hang_det_sep_axi_threshold_o,  // Stall cycles after which the SEP AXI
                                                     // hang detector fires.
  output logic        hang_det_data_accel_enable_o,  // Enables the data-accelerator AXI hang
                                                     // detector.
  output logic        hang_det_data_accel_irq_en_o,  // Enables the data-accelerator AXI hang
                                                     // interrupt.
  output logic        hang_det_data_accel_irq_test_o,  // Forces the data-accelerator AXI hang
                                                       // interrupt high.
  output logic [19:0] hang_det_data_accel_threshold_o,  // Stall cycles after which the
                                                        // data-accelerator AXI hang detector
                                                        // fires.

  output logic                                             cla_interrupt_o,  // Debug interrupt raised by
                                                                             // a CLA external action.
  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,  // Custom CLA
                                                                                     // external-action
                                                                                     // outputs, one bit per
                                                                                     // action.

  output smc_pkg::xtrigger_t      xtrigger_ss_o,  // Cross-trigger outputs from the CLA to the
                                                  // subsystem cross-trigger network, masked by the
                                                  // DFD cross-trigger clock-halt mask.
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,  // Cross-trigger inputs from the subsystem
                                                  // cross-trigger network to the CLA.

  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,  // Enables reporting a CLA halt-clock
                                                   // action as a clock stop.
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,  // High while an enabled CLA
                                                           // halt-clock action requests a
                                                           // clock stop.

  input  logic [1023:0] debug_bus_i,    // Debug bus observed by the CLA, 64 lanes of 16 bits whose
                                        // upper 32 lanes carry adopter signals; not synchronized to
                                        // the SMC core clock.
  output logic [7:0]    debug_marker_o,  // Debug marker byte driven by the CLA.

  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,  // Requests from the DFD
                                                                                          // trace sink to the
                                                                                          // external trace RAMs.
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,  // Read data from the
                                                                                           // external trace RAMs.

  input  logic test_en_i,               // Scan test mode enable, active-high; forces the CSR clock
                                        // gates on and switches the DFD block onto scan_rst_ni.
  input  logic scan_rst_ni,             // Scan reset, active-low, used by the DFD block while
                                        // test_en_i is high.

  input  logic mem_repair_done_i,       // Memory repair has finished; reported in the DFX
                                        // STATUS_SMU register.
  input  logic mem_repair_success_i,    // Memory repair succeeded; reported in the DFX STATUS_SMU
                                        // register.
  input  logic mem_repair_abort_i,      // Memory repair was aborted; reported in the DFX STATUS_SMU
                                        // register.
  input  logic mbist_done_i,            // Memory BIST has finished; reported in the DFX STATUS_SMU
                                        // register.
  input  logic mbist_pass_i,            // Memory BIST passed; reported in the DFX STATUS_SMU
                                        // register.
  input  logic mbist_abort_i,           // Memory BIST was aborted; reported in the DFX STATUS_SMU
                                        // register.

  output logic mailbox_clk_active_o,    // High while the mailbox gated clock is running.
  output logic mailbox_bus_active_o,    // High while the mailbox register port has a
                                        // transaction outstanding.
  output logic ob_filter_clk_active_o,  // High while the outbound filter register gated clock is
                                        // running.
  output logic ob_filter_bus_active_o,  // High while the outbound filter register port has a
                                        // transaction outstanding.
  output logic ib_filter_clk_active_o,  // High while the inbound filter register gated clock is
                                        // running.
  output logic ib_filter_bus_active_o,  // High while the inbound filter register port has a
                                        // transaction outstanding.
  output logic mmode_remap_clk_active_o,  // High while the M-mode remap register gated clock is
                                          // running.
  output logic mmode_remap_bus_active_o,  // High while the M-mode remap register port has a
                                          // transaction outstanding.
  output logic xvisor_remap_clk_active_o,  // High while the Xvisor remap register gated clock
                                           // is running.
  output logic xvisor_remap_bus_active_o,  // High while the Xvisor remap register port has a
                                           // transaction outstanding.
  output logic alias_remap_clk_active_o,  // High while the alias remap register gated clock is
                                          // running.
  output logic alias_remap_bus_active_o  // High while the alias remap register port has a
                                         // transaction outstanding.
);

  // Clock-gate enables from smc_base_config consumed within this module
  logic                          cg_ctrl_mailbox_cg_en;
  logic                          cg_ctrl_ob_filter_reg_cg_en;
  logic                          cg_ctrl_ib_filter_reg_cg_en;
  logic                          cg_ctrl_addr_remap_cg_en;
  smc_pkg::cg_hyster_t           cg_ctrl_hysteresis;

  assign cg_ctrl_hysteresis_o = cg_ctrl_hysteresis;

  // Outstanding-transaction bound for axi_cg_snoop
  // per-master-port axi_lite_mux that gates transactions to them is sized by XbarCfg.MaxSlvTrans
  localparam int unsigned AxilOutstandingTx = smc_internal_axi_lite_xbar_pkg::XbarCfg.MaxSlvTrans;

  // DFD config from the DFT/DFD CSR block
  smc_pkg::dfd_enable_t                   dfd_enables;
  tt_dbm_pkg::DbgMuxSelMmr_s          dbg_mux_sel_csr;

  /////////////////
  // SMC Mailbox //
  /////////////////

  localparam int unsigned SpacePerMailbox = smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR - smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR;

  logic mailbox_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_mailbox_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_mailbox_req_i.aw_valid),
    .snoop_aw_ready_i(axil_mailbox_resp_o.aw_ready),
    .snoop_w_valid_i (axil_mailbox_req_i.w_valid),
    .snoop_b_valid_i (axil_mailbox_resp_o.b_valid),
    .snoop_b_ready_i (axil_mailbox_req_i.b_ready),
    .snoop_ar_valid_i(axil_mailbox_req_i.ar_valid),
    .snoop_ar_ready_i(axil_mailbox_resp_o.ar_ready),
    .snoop_r_valid_i (axil_mailbox_resp_o.r_valid),
    .snoop_r_ready_i (axil_mailbox_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_mailbox_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (mailbox_clk_active_o),
    .gated_clk_o     (mailbox_clk),
    .bus_active_o    (mailbox_bus_active_o)
  );

  axi_lite_mailbox_unit #(
    .NUM_MAILBOXES          (smc_pkg::NumMailboxes),
    .MAILBOX_DEPTH          (smc_pkg::MailboxDepth),
    .MAX_TRANS              (smc_pkg::FabricMaxTrans),
    .MAILBOX_BASE_ADDR      (smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
    .MAILBOX_SIZE           (SpacePerMailbox),
    .ADDR_WIDTH             (smc_pkg::SmcLocalAddrWidth),
    .DATA_WIDTH             (smc_pkg::AxiLite64DataWidth),
    .aw_chan_t              (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t               (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t               (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t              (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t               (smc_pkg::smc_axil_32_64_r_chan_t),
    .axi_req_t              (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t             (smc_pkg::smc_axil_32_64_resp_t)
  ) u_smc_axil_mailbox (
    .clk_i                  (mailbox_clk),
    .rst_ni                 (rst_primary_smc_clk_ni),
    .test_en_i              (test_en_i),

    .mailbox_axi_req_i      (axil_mailbox_req_i),
    .mailbox_axi_resp_o     (axil_mailbox_resp_o),

    .inbound_interrupt_o    (inbound_interrupt_o),
    .outbound_interrupt_o   (outbound_interrupt_o)
  );

  //------------------------//
  // OUTBOUND FILTER CONFIG //
  //------------------------//

  outbound_select_t outbound_axil_aw_select;
  outbound_select_t outbound_axil_ar_select;

  smc_pkg::smc_axil_32_64_req_t  [NUM_OUTBOUND_FILTERS-1:0] outbound_filter_axi_lite_reqs;
  smc_pkg::smc_axil_32_64_resp_t [NUM_OUTBOUND_FILTERS-1:0] outbound_filter_axi_lite_resps;

  logic outbound_filter_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_outbound_filter_reg_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_outbound_filter_ctrl_req_i.aw_valid),
    .snoop_aw_ready_i(axil_outbound_filter_ctrl_resp_o.aw_ready),
    .snoop_w_valid_i (axil_outbound_filter_ctrl_req_i.w_valid),
    .snoop_b_valid_i (axil_outbound_filter_ctrl_resp_o.b_valid),
    .snoop_b_ready_i (axil_outbound_filter_ctrl_req_i.b_ready),
    .snoop_ar_valid_i(axil_outbound_filter_ctrl_req_i.ar_valid),
    .snoop_ar_ready_i(axil_outbound_filter_ctrl_resp_o.ar_ready),
    .snoop_r_valid_i (axil_outbound_filter_ctrl_resp_o.r_valid),
    .snoop_r_ready_i (axil_outbound_filter_ctrl_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_ob_filter_reg_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (ob_filter_clk_active_o),
    .gated_clk_o     (outbound_filter_clk),
    .bus_active_o    (ob_filter_bus_active_o)
  );

  always_comb begin
    outbound_axil_aw_select = axil_outbound_filter_ctrl_req_i.aw.addr[5+:$clog2(NUM_OUTBOUND_FILTERS)];
    outbound_axil_ar_select = axil_outbound_filter_ctrl_req_i.ar.addr[5+:$clog2(NUM_OUTBOUND_FILTERS)];
  end

  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),

    .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),

    .NoMstPorts  (NUM_OUTBOUND_FILTERS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_outbound_filter_axil_demux (
    .clk_i            (outbound_filter_clk),
    .rst_ni           (rst_primary_smc_clk_ni),
    .test_i           (test_en_i),
    .slv_req_i        (axil_outbound_filter_ctrl_req_i),
    .slv_resp_o       (axil_outbound_filter_ctrl_resp_o),

    .slv_aw_select_i  (outbound_axil_aw_select),
    .slv_ar_select_i  (outbound_axil_ar_select),

    .mst_reqs_o       (outbound_filter_axi_lite_reqs),
    .mst_resps_i      (outbound_filter_axi_lite_resps)
  );

  for (genvar f = 0; f < NUM_OUTBOUND_FILTERS; f = f + 1) begin : gen_outbound_filter_config

    // Intermediate signals for conditional connection based on locked status
    smc_pkg::smc_axil_32_64_req_t filter_reg_req, locked_reg_req;
    smc_pkg::smc_axil_32_64_resp_t filter_reg_resp, locked_reg_resp;

    // The demux spill stores the port select with the AW. locked updates on the
    // clock edge that arms B, so the next AW waits until that B is accepted and
    // the select is sampled with locked already set. Reads are not held.
    smc_pkg::smc_axil_32_64_req_t  gated_req;
    smc_pkg::smc_axil_32_64_resp_t gated_resp;
    logic aw_valid, aw_ready;
    logic filter_reg_aw_select;

    stream_throttle #(
      .MaxNumPending (1)
    ) u_outbound_filter_aw_throttle (
      .clk_i       (outbound_filter_clk),
      .rst_ni      (rst_primary_smc_clk_ni),
      .req_valid_i (outbound_filter_axi_lite_reqs[f].aw_valid),
      .req_valid_o (aw_valid),
      .req_ready_i (gated_resp.aw_ready),
      .req_ready_o (aw_ready),
      .rsp_valid_i (gated_resp.b_valid),
      .rsp_ready_i (outbound_filter_axi_lite_reqs[f].b_ready),
      .credit_i    (1'b1)
    );

    always_comb begin
      gated_req                                  = outbound_filter_axi_lite_reqs[f];
      gated_req.aw_valid                         = aw_valid;
      outbound_filter_axi_lite_resps[f]          = gated_resp;
      outbound_filter_axi_lite_resps[f].aw_ready = aw_ready;
      // If filter is locked, block writes but allow reads
      filter_reg_aw_select = outbound_filter_ctrl_o[f].FILTER_CONFIG.locked.value
                             && (gated_req.aw_valid || gated_req.w_valid);
    end

    // Demux between filter control register and axilite error slave (for locked filters)
    axi_lite_demux #(
      .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
      .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
      .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
      .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
      .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),

      .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
      .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),

      .NoMstPorts  (2),
      .MaxTrans    (1),
      .FallThrough (1'b0),
      .SpillAw     (1'b1),
      .SpillW      (1'b0),
      .SpillB      (1'b0),
      .SpillAr     (1'b1),
      .SpillR      (1'b0)
    ) u_outbound_filter_axi_lite_demux (
      .clk_i            (outbound_filter_clk),
      .rst_ni           (rst_primary_smc_clk_ni),
      .test_i           (test_en_i),
      .slv_req_i        (gated_req),
      .slv_resp_o       (gated_resp),

      .slv_aw_select_i  (filter_reg_aw_select),
      .slv_ar_select_i  (1'b0), // Always pass through reads

      .mst_reqs_o       ({locked_reg_req, filter_reg_req}),
      .mst_resps_i      ({locked_reg_resp, filter_reg_resp})
    );

    // Filter control register
    filter_ctrl_reg u_outbound_filter_ctrl_reg (
      .clk            (outbound_filter_clk),
      .arst_n         (rst_primary_smc_clk_ni),

      .s_axil_awready (filter_reg_resp.aw_ready),
      .s_axil_awvalid (filter_reg_req.aw_valid),
      .s_axil_awaddr  (filter_reg_req.aw.addr[filter_ctrl_reg_pkg::FILTER_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
      .s_axil_awprot  (filter_reg_req.aw.prot),
      .s_axil_wready  (filter_reg_resp.w_ready),
      .s_axil_wvalid  (filter_reg_req.w_valid),
      .s_axil_wdata   (filter_reg_req.w.data),
      .s_axil_wstrb   (filter_reg_req.w.strb),
      .s_axil_bready  (filter_reg_req.b_ready),
      .s_axil_bvalid  (filter_reg_resp.b_valid),
      .s_axil_bresp   (filter_reg_resp.b.resp),
      .s_axil_arready (filter_reg_resp.ar_ready),
      .s_axil_arvalid (filter_reg_req.ar_valid),
      .s_axil_araddr  (filter_reg_req.ar.addr[filter_ctrl_reg_pkg::FILTER_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
      .s_axil_arprot  (filter_reg_req.ar.prot),
      .s_axil_rready  (filter_reg_req.r_ready),
      .s_axil_rvalid  (filter_reg_resp.r_valid),
      .s_axil_rdata   (filter_reg_resp.r.data),
      .s_axil_rresp   (filter_reg_resp.r.resp),

      .hwif_in        (outbound_filter_status_i[f]),
      .hwif_out       (outbound_filter_ctrl_o[f])
    );

    // AXI-Lite error slave for locked filters
    prim_axi_lite_err_slv #(
      .AXI_ADDR_WIDTH (smc_pkg::SmcLocalAddrWidth),
      .AXI_DATA_WIDTH (smc_pkg::AxiLite64DataWidth),

      .axil_req_t     (smc_pkg::smc_axil_32_64_req_t),
      .axil_resp_t    (smc_pkg::smc_axil_32_64_resp_t)
    ) u_err_slv (
      .clk_i          (outbound_filter_clk),
      .rst_ni         (rst_primary_smc_clk_ni),
      .axil_req_i     (locked_reg_req),
      .axil_resp_o    (locked_reg_resp)
    );

  end

  //-----------------------//
  // INBOUND FILTER CONFIG //
  //-----------------------//

  inbound_select_t inbound_axil_aw_select;
  inbound_select_t inbound_axil_ar_select;

  smc_pkg::smc_axil_32_64_req_t  [NUM_INBOUND_FILTERS-1:0] inbound_filter_axi_lite_reqs;
  smc_pkg::smc_axil_32_64_resp_t [NUM_INBOUND_FILTERS-1:0] inbound_filter_axi_lite_resps;

  always_comb begin
    inbound_axil_aw_select = axil_inbound_filter_ctrl_req_i.aw.addr[5+:$clog2(NUM_INBOUND_FILTERS)];
    inbound_axil_ar_select = axil_inbound_filter_ctrl_req_i.ar.addr[5+:$clog2(NUM_INBOUND_FILTERS)];
  end

  logic inbound_filter_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_inbound_filter_reg_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_inbound_filter_ctrl_req_i.aw_valid),
    .snoop_aw_ready_i(axil_inbound_filter_ctrl_resp_o.aw_ready),
    .snoop_w_valid_i (axil_inbound_filter_ctrl_req_i.w_valid),
    .snoop_b_valid_i (axil_inbound_filter_ctrl_resp_o.b_valid),
    .snoop_b_ready_i (axil_inbound_filter_ctrl_req_i.b_ready),
    .snoop_ar_valid_i(axil_inbound_filter_ctrl_req_i.ar_valid),
    .snoop_ar_ready_i(axil_inbound_filter_ctrl_resp_o.ar_ready),
    .snoop_r_valid_i (axil_inbound_filter_ctrl_resp_o.r_valid),
    .snoop_r_ready_i (axil_inbound_filter_ctrl_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_ib_filter_reg_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (ib_filter_clk_active_o),
    .gated_clk_o     (inbound_filter_clk),
    .bus_active_o    (ib_filter_bus_active_o)
  );

  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),

    .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),

    .NoMstPorts  (NUM_INBOUND_FILTERS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_inbound_filter_axil_demux (
    .clk_i            (inbound_filter_clk),
    .rst_ni           (rst_primary_smc_clk_ni),
    .test_i           (test_en_i),
    .slv_req_i        (axil_inbound_filter_ctrl_req_i),
    .slv_resp_o       (axil_inbound_filter_ctrl_resp_o),

    .slv_aw_select_i  (inbound_axil_aw_select),
    .slv_ar_select_i  (inbound_axil_ar_select),

    .mst_reqs_o       (inbound_filter_axi_lite_reqs),
    .mst_resps_i      (inbound_filter_axi_lite_resps)
  );

  for (genvar f = 0; f < NUM_INBOUND_FILTERS; f = f + 1) begin : gen_inbound_filter_config

    // Intermediate signals for conditional connection based on locked status
    smc_pkg::smc_axil_32_64_req_t filter_reg_req, locked_reg_req;
    smc_pkg::smc_axil_32_64_resp_t filter_reg_resp, locked_reg_resp;

    // The demux spill stores the port select with the AW. locked updates on the
    // clock edge that arms B, so the next AW waits until that B is accepted and
    // the select is sampled with locked already set. Reads are not held.
    smc_pkg::smc_axil_32_64_req_t  gated_req;
    smc_pkg::smc_axil_32_64_resp_t gated_resp;
    logic aw_valid, aw_ready;
    logic filter_reg_aw_select;

    stream_throttle #(
      .MaxNumPending (1)
    ) u_inbound_filter_aw_throttle (
      .clk_i       (inbound_filter_clk),
      .rst_ni      (rst_primary_smc_clk_ni),
      .req_valid_i (inbound_filter_axi_lite_reqs[f].aw_valid),
      .req_valid_o (aw_valid),
      .req_ready_i (gated_resp.aw_ready),
      .req_ready_o (aw_ready),
      .rsp_valid_i (gated_resp.b_valid),
      .rsp_ready_i (inbound_filter_axi_lite_reqs[f].b_ready),
      .credit_i    (1'b1)
    );

    always_comb begin
      gated_req                                 = inbound_filter_axi_lite_reqs[f];
      gated_req.aw_valid                        = aw_valid;
      inbound_filter_axi_lite_resps[f]          = gated_resp;
      inbound_filter_axi_lite_resps[f].aw_ready = aw_ready;
      // If filter is locked, block writes but allow reads
      filter_reg_aw_select = inbound_filter_ctrl_o[f].FILTER_CONFIG.locked.value
                             && (gated_req.aw_valid || gated_req.w_valid);
    end

    // Demux between filter control register and axilite error slave (for locked filters)
    axi_lite_demux #(
      .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
      .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
      .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
      .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
      .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),

      .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
      .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),

      .NoMstPorts  (2),
      .MaxTrans    (1),
      .FallThrough (1'b0),
      .SpillAw     (1'b1),
      .SpillW      (1'b0),
      .SpillB      (1'b0),
      .SpillAr     (1'b1),
      .SpillR      (1'b0)
    ) u_inbound_filter_axi_lite_demux (
      .clk_i            (inbound_filter_clk),
      .rst_ni           (rst_primary_smc_clk_ni),
      .test_i           (test_en_i),
      .slv_req_i        (gated_req),
      .slv_resp_o       (gated_resp),

      .slv_aw_select_i  (filter_reg_aw_select),
      .slv_ar_select_i  (1'b0), // Always pass through reads

      .mst_reqs_o       ({locked_reg_req, filter_reg_req}),
      .mst_resps_i      ({locked_reg_resp, filter_reg_resp})
    );

    // Filter control register
    filter_ctrl_reg u_inbound_filter_ctrl_reg (
      .clk            (inbound_filter_clk),
      .arst_n         (rst_primary_smc_clk_ni),

      .s_axil_awready (filter_reg_resp.aw_ready),
      .s_axil_awvalid (filter_reg_req.aw_valid),
      .s_axil_awaddr  (filter_reg_req.aw.addr[filter_ctrl_reg_pkg::FILTER_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
      .s_axil_awprot  (filter_reg_req.aw.prot),
      .s_axil_wready  (filter_reg_resp.w_ready),
      .s_axil_wvalid  (filter_reg_req.w_valid),
      .s_axil_wdata   (filter_reg_req.w.data),
      .s_axil_wstrb   (filter_reg_req.w.strb),
      .s_axil_bready  (filter_reg_req.b_ready),
      .s_axil_bvalid  (filter_reg_resp.b_valid),
      .s_axil_bresp   (filter_reg_resp.b.resp),
      .s_axil_arready (filter_reg_resp.ar_ready),
      .s_axil_arvalid (filter_reg_req.ar_valid),
      .s_axil_araddr  (filter_reg_req.ar.addr[filter_ctrl_reg_pkg::FILTER_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
      .s_axil_arprot  (filter_reg_req.ar.prot),
      .s_axil_rready  (filter_reg_req.r_ready),
      .s_axil_rvalid  (filter_reg_resp.r_valid),
      .s_axil_rdata   (filter_reg_resp.r.data),
      .s_axil_rresp   (filter_reg_resp.r.resp),

      .hwif_in        (inbound_filter_status_i[f]),
      .hwif_out       (inbound_filter_ctrl_o[f])
    );

    // AXI-Lite error slave for locked filters
    prim_axi_lite_err_slv #(
      .AXI_ADDR_WIDTH (smc_pkg::SmcLocalAddrWidth),
      .AXI_DATA_WIDTH (smc_pkg::AxiLite64DataWidth),

      .axil_req_t     (smc_pkg::smc_axil_32_64_req_t),
      .axil_resp_t    (smc_pkg::smc_axil_32_64_resp_t)
    ) u_err_slv (
      .clk_i       (inbound_filter_clk),
      .rst_ni      (rst_primary_smc_clk_ni),
      .axil_req_i  (locked_reg_req),
      .axil_resp_o (locked_reg_resp)
    );

  end


  //--------------------//
  // MMODE REMAP CONFIG //
  //--------------------//

  logic mR_local_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_mmode_remap_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_mR_ctrl_req_i.aw_valid),
    .snoop_aw_ready_i(axil_mR_ctrl_resp_o.aw_ready),
    .snoop_w_valid_i (axil_mR_ctrl_req_i.w_valid),
    .snoop_b_valid_i (axil_mR_ctrl_resp_o.b_valid),
    .snoop_b_ready_i (axil_mR_ctrl_req_i.b_ready),
    .snoop_ar_valid_i(axil_mR_ctrl_req_i.ar_valid),
    .snoop_ar_ready_i(axil_mR_ctrl_resp_o.ar_ready),
    .snoop_r_valid_i (axil_mR_ctrl_resp_o.r_valid),
    .snoop_r_ready_i (axil_mR_ctrl_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_addr_remap_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (mmode_remap_clk_active_o),
    .gated_clk_o     (mR_local_clk),
    .bus_active_o    (mmode_remap_bus_active_o)
  );

  localparam int unsigned MmodeRemapSelStartIdx = $clog2(
      smc_top_addrmap_pkg::SMC_TOP_SMC_MMODE_REMAP_SIZE
  );
  localparam int unsigned MmodeRemapSelEndIdx = MmodeRemapSelStartIdx + smc_pkg::MmodeRemapSelW - 1;

  smc_pkg::smc_axil_32_64_req_t  [smc_pkg::NumMmodeOutputRemapRegions-1:0] axil_mR_ctrl_reqs;
  smc_pkg::smc_axil_32_64_resp_t [smc_pkg::NumMmodeOutputRemapRegions-1:0] axil_mR_ctrl_resps;

  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),
    .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),
    .NoMstPorts  (smc_pkg::NumMmodeOutputRemapRegions),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_mmode_remap_axil_demux (
    .clk_i           (mR_local_clk),
    .rst_ni          (rst_primary_smc_clk_ni),
    .test_i          (test_en_i),
    .slv_req_i       (axil_mR_ctrl_req_i),
    .slv_resp_o      (axil_mR_ctrl_resp_o),
    .slv_aw_select_i (axil_mR_ctrl_req_i.aw.addr[MmodeRemapSelEndIdx:MmodeRemapSelStartIdx]),
    .slv_ar_select_i (axil_mR_ctrl_req_i.ar.addr[MmodeRemapSelEndIdx:MmodeRemapSelStartIdx]),
    .mst_reqs_o      (axil_mR_ctrl_reqs),
    .mst_resps_i     (axil_mR_ctrl_resps)
  );

  for (genvar i = 0; i < smc_pkg::NumMmodeOutputRemapRegions; i++) begin : gen_mmode_remap_reg
    output_remap_reg u_smc_mmode_remap_reg (
      .clk            (mR_local_clk),
      .arst_n         (rst_primary_smc_clk_ni),

      .s_axil_awready (axil_mR_ctrl_resps[i].aw_ready),
      .s_axil_awvalid (axil_mR_ctrl_reqs[i].aw_valid),
      .s_axil_awaddr  ({1'b0, axil_mR_ctrl_reqs[i].aw.addr[MmodeRemapSelStartIdx-1:0]}),
      .s_axil_awprot  (axil_mR_ctrl_reqs[i].aw.prot),
      .s_axil_wready  (axil_mR_ctrl_resps[i].w_ready),
      .s_axil_wvalid  (axil_mR_ctrl_reqs[i].w_valid),
      .s_axil_wdata   (axil_mR_ctrl_reqs[i].w.data),
      .s_axil_wstrb   (axil_mR_ctrl_reqs[i].w.strb),
      .s_axil_bready  (axil_mR_ctrl_reqs[i].b_ready),
      .s_axil_bvalid  (axil_mR_ctrl_resps[i].b_valid),
      .s_axil_bresp   (axil_mR_ctrl_resps[i].b.resp),
      .s_axil_arready (axil_mR_ctrl_resps[i].ar_ready),
      .s_axil_arvalid (axil_mR_ctrl_reqs[i].ar_valid),
      .s_axil_araddr  ({1'b0, axil_mR_ctrl_reqs[i].ar.addr[MmodeRemapSelStartIdx-1:0]}),
      .s_axil_arprot  (axil_mR_ctrl_reqs[i].ar.prot),
      .s_axil_rready  (axil_mR_ctrl_reqs[i].r_ready),
      .s_axil_rvalid  (axil_mR_ctrl_resps[i].r_valid),
      .s_axil_rdata   (axil_mR_ctrl_resps[i].r.data),
      .s_axil_rresp   (axil_mR_ctrl_resps[i].r.resp),

      .hwif_out       (mR_ctrl_o[i])
    );
  end

  //---------------------//
  // XVISOR REMAP CONFIG //
  //---------------------//

  logic xR_local_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_xvisor_remap_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_xR_ctrl_req_i.aw_valid),
    .snoop_aw_ready_i(axil_xR_ctrl_resp_o.aw_ready),
    .snoop_w_valid_i (axil_xR_ctrl_req_i.w_valid),
    .snoop_b_valid_i (axil_xR_ctrl_resp_o.b_valid),
    .snoop_b_ready_i (axil_xR_ctrl_req_i.b_ready),
    .snoop_ar_valid_i(axil_xR_ctrl_req_i.ar_valid),
    .snoop_ar_ready_i(axil_xR_ctrl_resp_o.ar_ready),
    .snoop_r_valid_i (axil_xR_ctrl_resp_o.r_valid),
    .snoop_r_ready_i (axil_xR_ctrl_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_addr_remap_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (xvisor_remap_clk_active_o),
    .gated_clk_o     (xR_local_clk),
    .bus_active_o    (xvisor_remap_bus_active_o)
  );

  localparam int unsigned XvisorRemapSelStartIdx = $clog2(
      smc_top_addrmap_pkg::SMC_TOP_SMC_XVISOR_REMAP_SIZE
  );
  localparam int unsigned XvisorRemapSelEndIdx = XvisorRemapSelStartIdx + smc_pkg::XvisorRemapSelW - 1;

  smc_pkg::smc_axil_32_64_req_t  [smc_pkg::NumXvisorOutputRemapRegions-1:0] axil_xR_ctrl_reqs;
  smc_pkg::smc_axil_32_64_resp_t [smc_pkg::NumXvisorOutputRemapRegions-1:0] axil_xR_ctrl_resps;

  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),
    .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),
    .NoMstPorts  (smc_pkg::NumXvisorOutputRemapRegions),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_xvisor_remap_axil_demux (
    .clk_i           (xR_local_clk),
    .rst_ni          (rst_primary_smc_clk_ni),
    .test_i          (test_en_i),
    .slv_req_i       (axil_xR_ctrl_req_i),
    .slv_resp_o      (axil_xR_ctrl_resp_o),
    .slv_aw_select_i (axil_xR_ctrl_req_i.aw.addr[XvisorRemapSelEndIdx:XvisorRemapSelStartIdx]),
    .slv_ar_select_i (axil_xR_ctrl_req_i.ar.addr[XvisorRemapSelEndIdx:XvisorRemapSelStartIdx]),
    .mst_reqs_o      (axil_xR_ctrl_reqs),
    .mst_resps_i     (axil_xR_ctrl_resps)
  );

  for (genvar i = 0; i < smc_pkg::NumXvisorOutputRemapRegions; i++) begin : gen_xvisor_remap_reg
    output_remap_reg u_smc_xvisor_remap_reg (
      .clk            (xR_local_clk),
      .arst_n         (rst_primary_smc_clk_ni),

      .s_axil_awready (axil_xR_ctrl_resps[i].aw_ready),
      .s_axil_awvalid (axil_xR_ctrl_reqs[i].aw_valid),
      .s_axil_awaddr  ({1'b0, axil_xR_ctrl_reqs[i].aw.addr[XvisorRemapSelStartIdx-1:0]}),
      .s_axil_awprot  (axil_xR_ctrl_reqs[i].aw.prot),
      .s_axil_wready  (axil_xR_ctrl_resps[i].w_ready),
      .s_axil_wvalid  (axil_xR_ctrl_reqs[i].w_valid),
      .s_axil_wdata   (axil_xR_ctrl_reqs[i].w.data),
      .s_axil_wstrb   (axil_xR_ctrl_reqs[i].w.strb),
      .s_axil_bready  (axil_xR_ctrl_reqs[i].b_ready),
      .s_axil_bvalid  (axil_xR_ctrl_resps[i].b_valid),
      .s_axil_bresp   (axil_xR_ctrl_resps[i].b.resp),
      .s_axil_arready (axil_xR_ctrl_resps[i].ar_ready),
      .s_axil_arvalid (axil_xR_ctrl_reqs[i].ar_valid),
      .s_axil_araddr  ({1'b0, axil_xR_ctrl_reqs[i].ar.addr[XvisorRemapSelStartIdx-1:0]}),
      .s_axil_arprot  (axil_xR_ctrl_reqs[i].ar.prot),
      .s_axil_rready  (axil_xR_ctrl_reqs[i].r_ready),
      .s_axil_rvalid  (axil_xR_ctrl_resps[i].r_valid),
      .s_axil_rdata   (axil_xR_ctrl_resps[i].r.data),
      .s_axil_rresp   (axil_xR_ctrl_resps[i].r.resp),

      .hwif_out       (xR_ctrl_o[i])
    );
  end

  //--------------------//
  // ALIAS REMAP CONFIG //
  //--------------------//

  logic aR_local_clk;

  axi_cg_snoop #(
    .OUTSTANDING_TX(AxilOutstandingTx), // all in-flight txns this AXI-Lite port admits
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_alias_remap_cg (
    .clk_i           (clk_smc_i),
    .rst_ni          (rst_primary_smc_clk_ni),

    .snoop_aw_valid_i(axil_aR_ctrl_req_i.aw_valid),
    .snoop_aw_ready_i(axil_aR_ctrl_resp_o.aw_ready),
    .snoop_w_valid_i (axil_aR_ctrl_req_i.w_valid),
    .snoop_b_valid_i (axil_aR_ctrl_resp_o.b_valid),
    .snoop_b_ready_i (axil_aR_ctrl_req_i.b_ready),
    .snoop_ar_valid_i(axil_aR_ctrl_req_i.ar_valid),
    .snoop_ar_ready_i(axil_aR_ctrl_resp_o.ar_ready),
    .snoop_r_valid_i (axil_aR_ctrl_resp_o.r_valid),
    .snoop_r_ready_i (axil_aR_ctrl_req_i.r_ready),
    .snoop_r_last_i  (1'b1), // every beat is "last" in AXI-L

    .kick_i          (~cg_ctrl_addr_remap_cg_en), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_ctrl_hysteresis),
    .clk_active_o    (alias_remap_clk_active_o),
    .gated_clk_o     (aR_local_clk),
    .bus_active_o    (alias_remap_bus_active_o)
  );

  localparam int unsigned AliasRemapSelStartIdx = $clog2(
      smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_SIZE
  );
  localparam int unsigned AliasRemapSelEndIdx = AliasRemapSelStartIdx + smc_pkg::AliasRemapSelW - 1;

  smc_pkg::smc_axil_32_64_req_t  [smc_pkg::NumAliasRemapRegions-1:0] axil_aR_ctrl_reqs;
  smc_pkg::smc_axil_32_64_resp_t [smc_pkg::NumAliasRemapRegions-1:0] axil_aR_ctrl_resps;

  // AXI-Lite Demux for alias remap regions
  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_64_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_64_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_64_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_64_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_64_r_chan_t),
    .axi_req_t   (smc_pkg::smc_axil_32_64_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_64_resp_t),
    .NoMstPorts  (smc_pkg::NumAliasRemapRegions),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_axi_alias_remap_demux (
    .clk_i            (aR_local_clk),
    .rst_ni           (rst_primary_smc_clk_ni),
    .test_i           (test_en_i),
    .slv_req_i        (axil_aR_ctrl_req_i),
    .slv_resp_o       (axil_aR_ctrl_resp_o),
    .slv_aw_select_i  (axil_aR_ctrl_req_i.aw.addr[AliasRemapSelEndIdx:AliasRemapSelStartIdx]),
    .slv_ar_select_i  (axil_aR_ctrl_req_i.ar.addr[AliasRemapSelEndIdx:AliasRemapSelStartIdx]),
    .mst_reqs_o       (axil_aR_ctrl_reqs),
    .mst_resps_i      (axil_aR_ctrl_resps)
  );

  for (genvar i = 0; i < smc_pkg::NumAliasRemapRegions; i++) begin : gen_alias_remap_reg
    alias_remap_reg u_smc_alias_remap_reg (
      .clk            (aR_local_clk),
      .arst_n         (rst_primary_smc_clk_ni),

      .s_axil_awready (axil_aR_ctrl_resps[i].aw_ready),
      .s_axil_awvalid (axil_aR_ctrl_reqs[i].aw_valid),
      .s_axil_awaddr  (axil_aR_ctrl_reqs[i].aw.addr[AliasRemapSelStartIdx-1:0]),
      .s_axil_awprot  (axil_aR_ctrl_reqs[i].aw.prot),
      .s_axil_wready  (axil_aR_ctrl_resps[i].w_ready),
      .s_axil_wvalid  (axil_aR_ctrl_reqs[i].w_valid),
      .s_axil_wdata   (axil_aR_ctrl_reqs[i].w.data),
      .s_axil_wstrb   (axil_aR_ctrl_reqs[i].w.strb),
      .s_axil_bready  (axil_aR_ctrl_reqs[i].b_ready),
      .s_axil_bvalid  (axil_aR_ctrl_resps[i].b_valid),
      .s_axil_bresp   (axil_aR_ctrl_resps[i].b.resp),
      .s_axil_arready (axil_aR_ctrl_resps[i].ar_ready),
      .s_axil_arvalid (axil_aR_ctrl_reqs[i].ar_valid),
      .s_axil_araddr  (axil_aR_ctrl_reqs[i].ar.addr[AliasRemapSelStartIdx-1:0]),
      .s_axil_arprot  (axil_aR_ctrl_reqs[i].ar.prot),
      .s_axil_rready  (axil_aR_ctrl_reqs[i].r_ready),
      .s_axil_rvalid  (axil_aR_ctrl_resps[i].r_valid),
      .s_axil_rdata   (axil_aR_ctrl_resps[i].r.data),
      .s_axil_rresp   (axil_aR_ctrl_resps[i].r.resp),

      .hwif_out       (aR_ctrl_o[i])
    );
  end


  /////////////////////
  // CLA/DFD Wrapper //
  /////////////////////

  smc_dfd_wrap #(
    .BASE_ADDR(smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_BASE_ADDR[22:0])
  ) u_smc_dfd_wrap (
    .clk_smc_i                                  (clk_smc_i),
    .clk_ref_i                                  (clk_ref_i),
    .rst_primary_ni                             (rst_primary_smc_clk_ni),

    .apb_smc_dfd_reg_req_i                      (apb_smc_dfd_reg_req_i),
    .apb_smc_dfd_reg_resp_o                     (apb_smc_dfd_reg_resp_o),

    .dfd_enables_i                              (dfd_enables),

    .external_action_debug_interrupt_o          (cla_interrupt_o),
    .external_action_custom_o                   (cla_ext_action_custom_o),

    .xtrigger_ss_o                              (xtrigger_ss_o),
    .xtrigger_ss_i                              (xtrigger_ss_i),

    .tdr_dbg_ctrl_clock_stop_en_i               (tdr_dbg_ctrl_clock_stop_en_i),
    .tdr_dbg_ctrl_clocks_stopped_by_cla_o       (tdr_dbg_ctrl_clocks_stopped_by_cla_o),

    .dbg_mux_sel_csr_i                          (dbg_mux_sel_csr),
    .debug_bus_i                                (debug_bus_i),    // We could add a sync2 here for every bit of the debug bus to smc clk but I that's a lot of area 'wasted'
    .debug_marker_o                             (debug_marker_o),

    .trace_mem_req_o                            (trace_mem_req_o),
    .trace_mem_resp_i                           (trace_mem_resp_i),

    .test_en_i                                  (test_en_i),
    .scan_rst_ni                                (scan_rst_ni)
  );

  /////////////////////
  // DFT STATUS WRAP //
  /////////////////////

  smc_dfx_ctrl_status_wrap u_smc_dfx_ctrl_status_wrap (
    .clk_i                  (clk_smc_i),
    .rst_ni                 (rst_primary_smc_clk_ni),
    .axil_dfx_csr_req_i     (axil_dfx_csr_req_i),
    .axil_dfx_csr_resp_o    (axil_dfx_csr_resp_o),
    .mem_repair_done_i      (mem_repair_done_i),
    .mem_repair_success_i   (mem_repair_success_i),
    .mem_repair_abort_i     (mem_repair_abort_i),
    .mbist_done_i           (mbist_done_i),
    .mbist_pass_i           (mbist_pass_i),
    .mbist_abort_i          (mbist_abort_i),
    .dfd_enables_o          (dfd_enables),
    .dbg_mux_sel_csr_o      (dbg_mux_sel_csr)
  );

  //////////////////////
  // BASE CONFIG WRAP //
  //////////////////////

  smc_base_config_wrap u_smc_base_config_wrap (
    .clk_i                           (clk_smc_i),
    .rst_n_i                         (rst_primary_smc_clk_ni),

    .axil_base_config_req_i          (axil_smc_base_config_req_i),
    .axil_base_config_resp_o         (axil_smc_base_config_resp_o),

    .smc_global_base_o               (smc_global_base_o),
    .smc_local_base_o                (smc_local_base_o),
    .smc_region_size_o               (smc_region_size_o),

    .cg_ctrl_dma_cg_en_o             (cg_ctrl_dma_cg_en_o),
    .cg_ctrl_mailbox_cg_en_o         (cg_ctrl_mailbox_cg_en),
    .cg_ctrl_ob_filter_axi_cg_en_o   (cg_ctrl_ob_filter_axi_cg_en_o),
    .cg_ctrl_ob_filter_reg_cg_en_o   (cg_ctrl_ob_filter_reg_cg_en),
    .cg_ctrl_ib_filter_axi_cg_en_o   (cg_ctrl_ib_filter_axi_cg_en_o),
    .cg_ctrl_ib_filter_reg_cg_en_o   (cg_ctrl_ib_filter_reg_cg_en),
    .cg_ctrl_addr_remap_cg_en_o      (cg_ctrl_addr_remap_cg_en),
    .cg_ctrl_output_fabric_cg_en_o   (cg_ctrl_output_fabric_cg_en_o),
    .cg_ctrl_zeroer_cg_en_o          (cg_ctrl_zeroer_cg_en_o),
    .cg_ctrl_i3c_cg_en_o             (cg_ctrl_i3c_cg_en_o),
    .cg_ctrl_avs_cg_en_o             (cg_ctrl_avs_cg_en_o),
    .cg_ctrl_i2c_cg_en_o             (cg_ctrl_i2c_cg_en_o),
    .cg_ctrl_uart_cg_en_o            (cg_ctrl_uart_cg_en_o),
    .cg_ctrl_tel_cg_en_o             (cg_ctrl_tel_cg_en_o),
    .cg_ctrl_hysteresis_o            (cg_ctrl_hysteresis),

    .hang_det_sys_axi_enable_o       (hang_det_sys_axi_enable_o),
    .hang_det_sys_axi_irq_en_o       (hang_det_sys_axi_irq_en_o),
    .hang_det_sys_axi_irq_test_o     (hang_det_sys_axi_irq_test_o),
    .hang_det_sys_axi_threshold_o    (hang_det_sys_axi_threshold_o),
    .hang_det_sep_axi_enable_o       (hang_det_sep_axi_enable_o),
    .hang_det_sep_axi_irq_en_o       (hang_det_sep_axi_irq_en_o),
    .hang_det_sep_axi_irq_test_o     (hang_det_sep_axi_irq_test_o),
    .hang_det_sep_axi_threshold_o    (hang_det_sep_axi_threshold_o),
    .hang_det_data_accel_enable_o    (hang_det_data_accel_enable_o),
    .hang_det_data_accel_irq_en_o    (hang_det_data_accel_irq_en_o),
    .hang_det_data_accel_irq_test_o  (hang_det_data_accel_irq_test_o),
    .hang_det_data_accel_threshold_o (hang_det_data_accel_threshold_o)
  );

endmodule

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-------------------------------------------------
// SMC Reset Unit
//
//-------------------------------------------------

module smc_reset_unit (

  input  logic                                   clk_ref_i,
  input  logic                                   clk_smc_i,
  input  logic                                   clk_periph_i,

  input  logic                                   powergood_i,
  output logic                                   powergood_stable_o,          // Stable powergood signal

  input  logic                                   rst_cold_ni,                 // cold reset

  input  logic                                   fuse_reset_ni,

  // Stable cold reset for GPIO
  output logic                                   rst_cold_stable_ref_clk_no,
  output logic                                   rst_cold_stable_smc_clk_no,

  input  smc_pkg::jtag_smc_reset_ctrl_t          jtag_reset_ctrl_i,

  // AXI-Lite Register Interface
  input  smc_pkg::smc_axil_32_32_req_t           reg_axi_lite_req_i,
  output smc_pkg::smc_axil_32_32_resp_t          reg_axi_lite_resp_o,

  // Reset Control Signals
  input  logic                                   rst_ext_wdt_ni,              // other watchdog timers
  input  logic                                   smc_wdt_first_timeout_i,
  input  logic                                   smc_wdt_second_timeout_i,

  // FLR Signals
  input  logic                                   isolate_req_pin_i,           // Set which subsystems are isolated from cool reset from external pin
  input  logic                                   cfg_flr_pf_active_i,         // Indicates that FLR is requested from PCIe
  input  logic                                   rst_cool_ni,                 // Incoming cool reset request from primary chiplet to place in internal register for visibility
  output logic [31:0]                            isolate_req_o,               // Controls isolation of subsystems like PCIe and/or ETH during FLR
  output logic                                   skip_mem_repair_o,           // Signal to skip memory repair & MBIST during FLR
  output logic                                   rst_cool_no,                 // Cool reset from primary chiplet to other chiplets

  // Subsystem Reset Signals
  input  logic [31:0]                            ss_reset_complete_i,
  output logic [31:0]                            ss_config_o,
  output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o[31:0],

  // Reset Sync Signals
  output logic                                   rst_primary_ref_clk_no,
  output logic                                   rst_primary_smc_clk_no,
  output logic                                   rst_warm_smc_clk_no,
  output logic                                   rst_wdt_smc_clk_no,
  output logic                                   rst_primary_periph_clk_no,

  // Sync IRQ Signals
  output logic                                   sync_irq_o,

  // Test mode signals
  input  logic                                   test_en_i,
  input  logic                                   scan_rst_ni

);

  logic rst_primary_n;
  logic rst_warm_n;
  logic rst_cool_from_flr_n;
  logic rst_wdt_n;

  /////////////////////
  // Reset Overrides //
  /////////////////////

  logic rst_cold_int_n;
  logic rst_cool_from_flr_int_n;
  logic rst_warm_int_n;

  smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_intermediate[31:0];
  logic fuse_reset_n; // post jtag override

  //////////////////////////////////////////////////////////////////////////
  // Cold Reset Post De-glitcher Synchronized to Reference and SMC clocks //
  //////////////////////////////////////////////////////////////////////////

  logic rst_cold_stable_n;
  logic rst_cold_ref_n, rst_cold_smc_n;

  ///////////////////////////////////
  // Reset Unit Register Interface //
  ///////////////////////////////////

  reset_unit_reg_pkg::reset_unit__in_t    hwif_in;
  reset_unit_reg_pkg::reset_unit__in_t    hwif_in_subsys;
  reset_unit_reg_pkg::reset_unit__in_t    hwif_in_cool;
  reset_unit_reg_pkg::reset_unit__out_t   hwif_out;

  // Combine hwif_in signals from different modules
  // Each module drives different fields of the struct
  always_comb begin
    hwif_in = '{default: '0};  // Default all fields to zero

    // Fields driven by smc_subsystem_resets
    hwif_in.SS_RESET_COMPLETE = hwif_in_subsys.SS_RESET_COMPLETE;
    hwif_in.SS_CONFIG         = hwif_in_subsys.SS_CONFIG;
    hwif_in.SS_COLD_RESET_N   = hwif_in_subsys.SS_COLD_RESET_N;

    // Fields driven by smc_cool_reset_wrap
    hwif_in.ISOLATE_REQ_VIS                     = hwif_in_cool.ISOLATE_REQ_VIS;
    hwif_in.ISOLATE_REQ_REG                     = hwif_in_cool.ISOLATE_REQ_REG;
    hwif_in.ISOLATE_REQ_PINEN_REG               = hwif_in_cool.ISOLATE_REQ_PINEN_REG;
    hwif_in.ISOLATE_REQ_SMC_REG                 = hwif_in_cool.ISOLATE_REQ_SMC_REG;
    hwif_in.ISOLATE_REQ_SMCEN_REG               = hwif_in_cool.ISOLATE_REQ_SMCEN_REG;
    hwif_in.ISOLATE_REQ_FLR_COUNTER_VALUE       = hwif_in_cool.ISOLATE_REQ_FLR_COUNTER_VALUE;
    hwif_in.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE = hwif_in_cool.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE;

    // Fields driven by captured straps
  end

  reset_unit_reg u_reset_unit_reg (
    .clk            (clk_smc_i),
    .arst_n         (rst_primary_smc_clk_no),

    .s_axil_awvalid (reg_axi_lite_req_i.aw_valid),
    .s_axil_awaddr  (reg_axi_lite_req_i.aw.addr[reset_unit_reg_pkg::RESET_UNIT_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (reg_axi_lite_req_i.aw.prot),
    .s_axil_wvalid  (reg_axi_lite_req_i.w_valid),
    .s_axil_wdata   (reg_axi_lite_req_i.w.data),
    .s_axil_wstrb   (reg_axi_lite_req_i.w.strb),
    .s_axil_bready  (reg_axi_lite_req_i.b_ready),
    .s_axil_arvalid (reg_axi_lite_req_i.ar_valid),
    .s_axil_araddr  (reg_axi_lite_req_i.ar.addr[reset_unit_reg_pkg::RESET_UNIT_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (reg_axi_lite_req_i.ar.prot),
    .s_axil_rready  (reg_axi_lite_req_i.r_ready),

    .s_axil_awready (reg_axi_lite_resp_o.aw_ready),
    .s_axil_wready  (reg_axi_lite_resp_o.w_ready),
    .s_axil_bvalid  (reg_axi_lite_resp_o.b_valid),
    .s_axil_bresp   (reg_axi_lite_resp_o.b.resp),
    .s_axil_arready (reg_axi_lite_resp_o.ar_ready),
    .s_axil_rvalid  (reg_axi_lite_resp_o.r_valid),
    .s_axil_rdata   (reg_axi_lite_resp_o.r.data),
    .s_axil_rresp   (reg_axi_lite_resp_o.r.resp),

    .hwif_in        (hwif_in),
    .hwif_out       (hwif_out)
  );

  //////////////////////
  // Subsystem Resets //
  //////////////////////

  smc_subsystem_resets u_smc_subsystem_resets (
    .clk_i                           (clk_smc_i),
    .rst_primary_ni                  (rst_primary_smc_clk_no),

    .hwif_in                         (hwif_in_subsys),
    .hwif_out                        (hwif_out),

    .ss_reset_complete_i             (ss_reset_complete_i),
    .ss_config_o                     (ss_config_o),
    .ss_reset_ctrl_o                 (ss_reset_ctrl_intermediate)
  );

  /////////////////////////////////////////////
  // Cool Reset Wrap (Function Level Resets) //
  /////////////////////////////////////////////

  smc_cool_reset_wrap u_smc_cool_reset_wrap (
    .clk_ref_i              (clk_ref_i),
    .rst_cold_ref_ni        (rst_cold_ref_n),
    .clk_smc_i              (clk_smc_i),
    .rst_cold_smc_ni        (rst_cold_smc_n),

    .hwif_in                (hwif_in_cool),
    .hwif_out               (hwif_out),

    .isolate_req_pin_i      (isolate_req_pin_i),
    .cfg_flr_pf_active_i    (cfg_flr_pf_active_i),
    .rst_cool_ni            (rst_cool_ni),

    .isolate_req_o          (isolate_req_o),
    .skip_mem_repair_o      (skip_mem_repair_o),

    .rst_cool_no            (rst_cool_from_flr_n)
  );

  ////////////////
  // Reset CTRL //
  ////////////////

  smc_reset_ctrl u_smc_reset_ctrl (
    .clk_ref_i                  (clk_ref_i),
    .powergood_i                (powergood_i),

    .rst_cold_ni                (rst_cold_int_n),

    .fuse_reset_ni              (fuse_reset_n),

    .rst_ext_wdt_ni             (rst_ext_wdt_ni),
    .smc_wdt_first_timeout_i    (smc_wdt_first_timeout_i),
    .smc_wdt_second_timeout_i   (smc_wdt_second_timeout_i),

    .rst_cool_from_pin_ni       (rst_cool_ni),                // Received by secondary chiplets
    .rst_cool_from_flr_ni       (rst_cool_from_flr_int_n),    // Generated by primary chiplets, potential jtag override and sent to secondary chiplets

    .powergood_stable_o         (powergood_stable_o),
    .stable_cold_rst_no         (rst_cold_stable_n),
    .rst_primary_no             (rst_primary_n),
    .rst_warm_no                (rst_warm_n),
    .rst_wdt_no                 (rst_wdt_n),

    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni)
  );

  ////////////////
  // Reset Sync //
  ////////////////

  smc_reset_sync u_smc_reset_sync (
    .clk_smc_i                      (clk_smc_i),
    .clk_ref_i                      (clk_ref_i),
    .clk_periph_i                   (clk_periph_i),

    .rst_cold_stable_ni             (rst_cold_stable_n),
    .rst_primary_ni                 (rst_primary_n),
    .rst_warm_ni                    (rst_warm_int_n),
    .rst_wdt_ni                     (rst_wdt_n),

    .rst_cold_smc_no                (rst_cold_smc_n),
    .rst_primary_smc_clk_no         (rst_primary_smc_clk_no),
    .rst_warm_smc_clk_no            (rst_warm_smc_clk_no),
    .rst_wdt_smc_clk_no             (rst_wdt_smc_clk_no),
    .rst_primary_periph_clk_no      (rst_primary_periph_clk_no),

    .rst_cold_ref_clk_no            (rst_cold_ref_n),
    .rst_primary_ref_clk_no         (rst_primary_ref_clk_no),

    .test_en_i                      (test_en_i),
    .scan_rst_ni                    (scan_rst_ni)
  );

  ////////////////////////
  // JTAG Reset Control //
  ////////////////////////

  // jtag_reset_ctrl_i contains both an override bit and a reset value, both are on TCKCLK

  prim_rst_mux2_hf_n u_fuse_reset_ovrd_mux (
    .rst0_ni (fuse_reset_ni),
    .rst1_ni (jtag_reset_ctrl_i.val.fuse_reset_n_val),
    .sel_i   (jtag_reset_ctrl_i.ovrd.fuse_reset_n_ovrd),
    .rst_no  (fuse_reset_n)
  );

  prim_rst_mux2_hf_n u_cold_reset_ovrd_mux (
    .rst0_ni (rst_cold_ni),
    .rst1_ni (jtag_reset_ctrl_i.val.cold_reset_n_val),
    .sel_i   (jtag_reset_ctrl_i.ovrd.cold_reset_n_ovrd),
    .rst_no  (rst_cold_int_n)
  );

  prim_rst_mux2_hf_n u_cool_reset_ovrd_mux (
    .rst0_ni (rst_cool_from_flr_n),
    .rst1_ni (jtag_reset_ctrl_i.val.cool_reset_n_val),
    .sel_i   (jtag_reset_ctrl_i.ovrd.cool_reset_n_ovrd),
    .rst_no  (rst_cool_from_flr_int_n)
  );

  prim_rst_mux2_hf_n u_warm_reset_ovrd_mux (
    .rst0_ni (rst_warm_n),
    .rst1_ni (jtag_reset_ctrl_i.val.warm_reset_n_val),
    .sel_i   (jtag_reset_ctrl_i.ovrd.warm_reset_n_ovrd),
    .rst_no  (rst_warm_int_n)
  );

  for (genvar i = 0; i < 32; i = i + 1) begin : gen_ss_jtag_ovrd
    logic ss_cold_reset_n;
    logic ss_warm_reset_n;

    prim_rst_mux2_hf_n u_ss_cold_reset_ovrd_mux (
      .rst0_ni (ss_reset_ctrl_intermediate[i].cold_reset_n),
      .rst1_ni (jtag_reset_ctrl_i.val.ss_cold_reset_n_val[i]),
      .sel_i   (jtag_reset_ctrl_i.ovrd.ss_cold_reset_n_ovrd[i]),
      .rst_no  (ss_cold_reset_n)
    );

    prim_rst_mux2_hf_n u_ss_warm_reset_ovrd_mux (
      .rst0_ni (ss_reset_ctrl_intermediate[i].warm_reset_n),
      .rst1_ni (jtag_reset_ctrl_i.val.ss_warm_reset_n_val[i]),
      .sel_i   (jtag_reset_ctrl_i.ovrd.ss_warm_reset_n_ovrd[i]),
      .rst_no  (ss_warm_reset_n)
    );

    assign ss_reset_ctrl_o[i].cold_reset_n         = ss_cold_reset_n;
    assign ss_reset_ctrl_o[i].warm_reset_n         = ss_warm_reset_n;
    assign ss_reset_ctrl_o[i].config_state_hold    = ss_reset_ctrl_intermediate[i].config_state_hold;
    assign ss_reset_ctrl_o[i].critical_signal_hold = ss_reset_ctrl_intermediate[i].critical_signal_hold;
    assign ss_reset_ctrl_o[i].sram_hold            = ss_reset_ctrl_intermediate[i].sram_hold;
    assign ss_reset_ctrl_o[i].debug_hold           = ss_reset_ctrl_intermediate[i].debug_hold;
    assign ss_reset_ctrl_o[i].force_to_ref_clk_n   = ss_reset_ctrl_intermediate[i].force_to_ref_clk_n;
  end


  //////////////
  // Sync IRQ //
  //////////////

  assign sync_irq_o = hwif_out.SYNC_REG.sync.value;

  assign rst_cold_stable_ref_clk_no = rst_cold_ref_n; // Stable cold reset synced to reference clock domain
  assign rst_cold_stable_smc_clk_no = rst_cold_smc_n; // Stable cold reset synced to SMC clock domain

  assign rst_cool_no = rst_cool_from_flr_int_n;

endmodule

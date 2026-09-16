// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Base

module smc_base #(
  parameter bit NO_ADDR_REMAP = 1'b1,

  localparam int unsigned NUM_CPU_CORES      = smc_4core_cpu_pkg::NUM_CPU_CORES,
  localparam int unsigned NUM_CPU_INTERRUPTS = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,
  localparam int unsigned NUM_EXT_INTERRUPTS = smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS

) (
  // Clocks from PLLs
  input  logic clk_smc_i,
  input  logic clk_ref_i,

  // Resets
  input  logic rst_primary_smc_clk_ni,

  // AXI Input
  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  jtag_axi_in_req_i,
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t jtag_axi_in_resp_o,

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,

  input  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_i,
  output smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_o,

  // AXI Output
  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,

  // Consolidated AXI-Lite interface for all peripherals
  output smc_pkg::smc_axil_32_32_req_t  axil_peripherals_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_peripherals_resp_i,

  // WDT
  output logic wdt_first_timeout_o,

  // Mailbox interrupts
  output logic [smc_pkg::NUM_MAILBOXES-1:0] ext_mailbox_interrupts_o,

  // External interrupts
  input  logic [NUM_EXT_INTERRUPTS-1:0] ext_interrupts_i,
  input  logic [31:0]                   peripheral_interrupts_i,

  // CPU wrapper bridge ports (outputs to smc_cpu_wrapper)
  output smc_pkg::smc_local_32_64_8_12_axi_req_t       cpu_axi_front_port_req_o,
  input  wire smc_pkg::smc_local_32_64_8_12_axi_resp_t cpu_axi_front_port_resp_i,
  output logic [NUM_CPU_INTERRUPTS-1:0]                cpu_interrupts_o,

  // CPU wrapper bridge ports (inputs from smc_cpu_wrapper)
  input  wire smc_pkg::smc_cpu_mmio_axi_req_t cpu_axi_mmio_port_req_i,
  output smc_pkg::smc_cpu_mmio_axi_resp_t     cpu_axi_mmio_port_resp_o,
  input  wire logic [NUM_CPU_CORES-1:0][57:0] cpu_wb_reg_pc_i,
  input  wire logic [NUM_CPU_CORES-1:0]       cpu_wdt_timeout_cluster_i,
  input  wire logic                           cpu_cluster_ded_i,
  input  wire logic                           wdt_second_timeout_i,

  // SMC address window from smc_base_config (in u_internal_regs)
  output smc_pkg::smc_axi_addr_t smc_global_base_o,
  output logic [31:0]            smc_region_size_o,

  // Peripheral clock-gate enables from smc_base_config (consumed at smc top)
  output logic cg_ctrl_i3c_cg_en_o,
  output logic cg_ctrl_avs_cg_en_o,
  output logic cg_ctrl_i2c_cg_en_o,
  output logic cg_ctrl_uart_cg_en_o,
  output logic cg_ctrl_tel_cg_en_o,

  // Debug
  input  logic [511:0] ext_debug_bus_i,
  input  logic [16:0]  avsbus_cur_state_debug_i,
  input  logic [8:0]   system_timer_octs_credits_debug_i,
  input  logic         system_timer_octs_credits_left_debug_i,

  input  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0][3:0] telemetry_debug_i,
  input  logic [smc_config_pkg::NUM_I2C-1:0][3:0]                 i2c_debug_i,
  input  logic [9:0]                                              efuse_debug_i,

  // DFD signals
  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,

  output smc_pkg::xtrigger_t      xtrigger_ss_o,
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,

  // TDR debug control signals
  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,

  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,

  // Test mode
  input  logic test_en_i,
  input  logic scan_rst_ni,

  // indicators for DFT status
  input  logic mem_repair_done_i,
  input  logic mem_repair_success_i,
  input  logic mem_repair_abort_i,
  input  logic mbist_done_i,
  input  logic mbist_pass_i,
  input  logic mbist_abort_i,

  // AXI hang detector OR'd fault output to safety island. Config now comes
  // from the smc_base_config register block inside u_internal_regs.
  output logic axi_hang_irq_o
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Input Fabric Inputs from Data Accelerator
  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_data_accel_req;
  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_data_accel_resp;

  smc_pkg::smc_dfd_apb_req_t  apb_smc_dfd_reg_req;
  smc_pkg::smc_dfd_apb_resp_t apb_smc_dfd_reg_resp;


  smc_pkg::smc_local_32_64_8_12_axi_req_t  axi_data_accel_ctrl_req;
  smc_pkg::smc_local_32_64_8_12_axi_resp_t axi_data_accel_ctrl_rsp;

  // AXI-Lite interface signals
  smc_pkg::smc_axil_32_64_req_t  axil_dfx_csr_req;
  smc_pkg::smc_axil_32_64_resp_t axil_dfx_csr_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_aR_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_aR_ctrl_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_mR_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_mR_ctrl_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_xR_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_xR_ctrl_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_inbound_filter_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_inbound_filter_ctrl_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_outbound_filter_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_outbound_filter_ctrl_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_mailbox_req;
  smc_pkg::smc_axil_32_64_resp_t axil_mailbox_resp;
  smc_pkg::smc_axil_32_64_req_t  axil_smc_base_config_req;
  smc_pkg::smc_axil_32_64_resp_t axil_smc_base_config_resp;

  // SMC address window from smc_base_config (in u_internal_regs)
  smc_pkg::smc_axi_addr_t smc_local_base;

  // Clock-gate enables from smc_base_config (in u_internal_regs)
  logic                cg_ctrl_dma_cg_en;
  logic                cg_ctrl_ob_filter_axi_cg_en;
  logic                cg_ctrl_ib_filter_axi_cg_en;
  logic                cg_ctrl_output_fabric_cg_en;
  logic                cg_ctrl_zeroer_cg_en;
  smc_pkg::cg_hyster_t cg_ctrl_hysteresis;

  // AXI hang detector config from smc_base_config (in u_internal_regs)
  logic hang_det_sys_axi_enable, hang_det_sep_axi_enable, hang_det_data_accel_enable;
  logic hang_det_sys_axi_irq_en, hang_det_sep_axi_irq_en, hang_det_data_accel_irq_en;
  logic hang_det_sys_axi_irq_test, hang_det_sep_axi_irq_test, hang_det_data_accel_irq_test;
  logic [19:0]
      hang_det_sys_axi_threshold, hang_det_sep_axi_threshold, hang_det_data_accel_threshold;

  // CSR structs for filter configurations
  filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status [smc_pkg::NumOutboundFilters-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl   [smc_pkg::NumOutboundFilters-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status  [smc_pkg::NumInboundFilters-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl    [smc_pkg::NumInboundFilters-1:0];

  // CSR structs for remap configurations
  output_remap_reg_pkg::output_remap__out_t mR_ctrl [smc_pkg::NUM_MMODE_OUTPUT_REMAP_REGIONS-1:0];
  output_remap_reg_pkg::output_remap__out_t xR_ctrl [smc_pkg::NUM_XVISOR_OUTPUT_REMAP_REGIONS-1:0];
  alias_remap_reg_pkg::alias_remap__out_t aR_ctrl [smc_pkg::NUM_ALIAS_REMAP_REGIONS-1:0];


  logic fabric_clk_active;
  logic fabric_bus_active;
  logic sys_out_filter_clk_active;
  logic sys_out_filter_bus_active;
  logic sys_in_filter_clk_active;
  logic sys_in_filter_bus_active;

  logic mailbox_clk_active;
  logic mailbox_bus_active;
  logic ob_filter_clk_active;
  logic ob_filter_bus_active;
  logic ib_filter_clk_active;
  logic ib_filter_bus_active;
  logic mmode_remap_clk_active;
  logic mmode_remap_bus_active;
  logic xvisor_remap_clk_active;
  logic xvisor_remap_bus_active;
  logic alias_remap_clk_active;
  logic alias_remap_bus_active;


  // Interrupts
  logic [smc_pkg::NUM_MAILBOXES-1:0]  mailbox_interrupts;

  // Debug signals
  smc_pkg::remap_debug_t  remap_debug_mmio;
  smc_pkg::remap_debug_t  remap_debug_jtag;
  smc_pkg::remap_debug_t  remap_debug_log;
  smc_pkg::remap_debug_t  remap_debug_dma;
  logic [$clog2(smc_pkg::NumInboundFilters)-1:0]
      outbound_write_filter_hit_debug, outbound_read_filter_hit_debug;
  logic [$clog2(smc_pkg::NumOutboundFilters)-1:0]
      inbound_write_filter_hit_debug, inbound_read_filter_hit_debug;

  // DMA busy signal
  logic dma_frontend_clk_active;
  logic dma_frontend_bus_active;
  logic zeroer_clk_active;
  logic zeroer_bus_active;

  logic dma_busy;
  logic dma_intp;

  // Zero-er busy signal
  logic zeroer_busy;
  logic zeroer_intp;

  // DFD signals
  logic cla_interrupt;

  assign wdt_first_timeout_o = |cpu_wdt_timeout_cluster_i;

  ////////////////
  // Interrupts //
  ////////////////

  // Synchronize ext_interrupts_i to smc_clk
  logic [NUM_EXT_INTERRUPTS-1:0] ext_interrupts_smc_clk;
  prim_sync3 #(
    .WIDTH(NUM_EXT_INTERRUPTS)
  ) u_ext_interrupts_sync3 (
    .i_clk (clk_smc_i),
    .i_d   (ext_interrupts_i),
    .o_q   (ext_interrupts_smc_clk)
  );

  // Interrupt distribution: N external interrupts, 32 peripheral interrupts,
  // 32 mailbox interrupts, 4 internal interrupts
  always_comb begin
    cpu_interrupts_o = '0;
    cpu_interrupts_o[NUM_EXT_INTERRUPTS-1:0]        = ext_interrupts_smc_clk;
    cpu_interrupts_o[NUM_EXT_INTERRUPTS+:32]        = peripheral_interrupts_i;               // 32 peripheral interrupts
    cpu_interrupts_o[(NUM_EXT_INTERRUPTS+32)+:32]   = mailbox_interrupts;                    // 32 mailbox interrupts
    cpu_interrupts_o[(NUM_EXT_INTERRUPTS+64)]       = tdr_dbg_ctrl_clocks_stopped_by_cla_o;  // internal interrupt 0
    cpu_interrupts_o[(NUM_EXT_INTERRUPTS+64)+1]     = cla_interrupt;                         // internal interrupt 1
    cpu_interrupts_o[(NUM_EXT_INTERRUPTS+64)+2]     = dma_intp;                              // internal interrupt 2
    cpu_interrupts_o[(NUM_EXT_INTERRUPTS+64)+3]     = zeroer_intp;                           // internal interrupt 3
  end


  ///////////////
  // Debug Bus //
  ///////////////

  logic [511:0] ext_debug_bus_smc_clk;
  prim_sync3 #(
    .WIDTH(512)
  ) u_ext_debug_bus_sync3 (
    .i_clk (clk_smc_i),
    .i_d   (ext_debug_bus_i),
    .o_q   (ext_debug_bus_smc_clk)
  );

  logic [1023:0] debug_bus;
  logic [7:0]    debug_marker;

  assign debug_bus[16*1-1:16*0]       = cpu_wb_reg_pc_i[0][15:0];
  assign debug_bus[16*2-1:16*1]       = cpu_wb_reg_pc_i[0][31:16];
  assign debug_bus[16*3-1:16*2]       = cpu_wb_reg_pc_i[1][15:0];
  assign debug_bus[16*4-1:16*3]       = cpu_wb_reg_pc_i[1][31:16];
  assign debug_bus[16*5-1:16*4]       = cpu_wb_reg_pc_i[2][15:0];
  assign debug_bus[16*6-1:16*5]       = cpu_wb_reg_pc_i[2][31:16];
  assign debug_bus[16*7-1:16*6]       = cpu_wb_reg_pc_i[3][15:0];
  assign debug_bus[16*8-1:16*7]       = cpu_wb_reg_pc_i[3][31:16];

  assign debug_bus[16*9-1:16*8]       = cpu_interrupts_o[15:0]    | cpu_interrupts_o[143:128];
  assign debug_bus[16*10-1:16*9]      = cpu_interrupts_o[31:16]   | cpu_interrupts_o[159:144];
  assign debug_bus[16*11-1:16*10]     = cpu_interrupts_o[47:32]   | cpu_interrupts_o[175:160];
  assign debug_bus[16*12-1:16*11]     = cpu_interrupts_o[63:48]   | cpu_interrupts_o[191:176];
  assign debug_bus[16*13-1:16*12]     = cpu_interrupts_o[79:64]   | cpu_interrupts_o[207:192];
  assign debug_bus[16*14-1:16*13]     = cpu_interrupts_o[95:80]   | cpu_interrupts_o[223:208];
  assign debug_bus[16*15-1:16*14]     = cpu_interrupts_o[111:96]  | cpu_interrupts_o[239:224];
  assign debug_bus[16*16-1:16*15]     = cpu_interrupts_o[127:112] | cpu_interrupts_o[255:240];

  assign debug_bus[16*17-1:16*16]     = peripheral_interrupts_i[15:0];
  assign debug_bus[16*18-1:16*17]     = peripheral_interrupts_i[31:16];
  assign debug_bus[16*19-1:16*18]     = mailbox_interrupts[15:0];
  assign debug_bus[16*20-1:16*19]     = mailbox_interrupts[31:16];
  // [10] zeroer  [9] idma_frontend_wrapper  [8] sys_in_filter  [7] sys_out_filter  [6] fabric
  // [5] alias_remap  [4] xvisor_remap  [3] mmode_remap  [2] ib_filter  [1] ob_filter  [0] mailbox
  assign debug_bus[16*21-1:16*20]     = {5'h0, zeroer_clk_active, dma_frontend_clk_active,
                                          sys_in_filter_clk_active, sys_out_filter_clk_active,
                                          fabric_clk_active, alias_remap_clk_active,
                                          xvisor_remap_clk_active, mmode_remap_clk_active,
                                          ib_filter_clk_active, ob_filter_clk_active,
                                          mailbox_clk_active};
  assign debug_bus[16*22-1:16*21]     = {5'h0, zeroer_bus_active, dma_frontend_bus_active,
                                          sys_in_filter_bus_active, sys_out_filter_bus_active,
                                          fabric_bus_active, alias_remap_bus_active,
                                          xvisor_remap_bus_active, mmode_remap_bus_active,
                                          ib_filter_bus_active, ob_filter_bus_active,
                                          mailbox_bus_active};
  assign debug_bus[16*23-1:16*22]     = 16'h0;
  assign debug_bus[16*24-1:16*23]     = {6'h0, efuse_debug_i};

  assign debug_bus[16*25-1:16*24]     = {{(16 - 4 * smc_config_pkg::NUM_I2C){1'b0}},
                                          i2c_debug_i};
  assign debug_bus[16*26-1:16*25]     = {{(16 - 4 * smc_config_pkg::NUM_TELEMETRY_RECEIVERS){1'b0}},
                                          telemetry_debug_i};
  assign debug_bus[16*27-1:16*26]     = avsbus_cur_state_debug_i[15:0];
  assign debug_bus[16*28-1:16*27]     = {6'h0, system_timer_octs_credits_left_debug_i, system_timer_octs_credits_debug_i};
  assign debug_bus[16*29-1:16*28]     = {zeroer_busy, dma_busy, cpu_cluster_ded_i, wdt_second_timeout_i,
                                          {{(4-NUM_CPU_CORES){1'b0}}, cpu_wdt_timeout_cluster_i},
                                          debug_marker};
  assign debug_bus[16*30-1:16*29]     = {4'h0, remap_debug_mmio.aw_remap_hit_debug, remap_debug_mmio.ar_remap_hit_debug,
                                                remap_debug_jtag.aw_remap_hit_debug, remap_debug_jtag.ar_remap_hit_debug};
  assign debug_bus[16*31-1:16*30]     = {4'h0, remap_debug_log.aw_remap_hit_debug, remap_debug_log.ar_remap_hit_debug,
                                                remap_debug_dma.aw_remap_hit_debug, remap_debug_dma.ar_remap_hit_debug};
  assign debug_bus[16*32-1:16*31]     = {outbound_write_filter_hit_debug, outbound_read_filter_hit_debug,
                                          inbound_write_filter_hit_debug, inbound_read_filter_hit_debug};

  // The remaining 512 bits are reserved for adopter to use, Note: Ensure signals are 16-bit aligned
  assign debug_bus[16*64-1:16*32]     = ext_debug_bus_smc_clk;

  ////////////////
  // SMC Fabric //
  ////////////////

  smc_fabric #(
    .NO_ADDR_REMAP              (NO_ADDR_REMAP),
    .NumInboundFilters          (smc_pkg::NumInboundFilters),
    .NumOutboundFilters         (smc_pkg::NumOutboundFilters),
    .MaxTrans                   (smc_pkg::FABRIC_MAX_TRANS),
    .FilterReqPipelineEnable    (1'b1),
    .FilterRspPipelineEnable    (1'b1)
  ) u_smc_fabric (
    .clk_i                                  (clk_smc_i),
    .rst_ni                                 (rst_primary_smc_clk_ni),
    .test_en_i                              (test_en_i),
    .scan_rst_ni                            (scan_rst_ni),

    .ob_filter_axi_cg_en_i                  (cg_ctrl_ob_filter_axi_cg_en),
    .ib_filter_axi_cg_en_i                  (cg_ctrl_ib_filter_axi_cg_en),
    .fabric_cg_en_i                         (cg_ctrl_output_fabric_cg_en),
    .cg_hysteresis_i                        (cg_ctrl_hysteresis),

    .global_base_addr_i                     (smc_global_base_o),
    .local_base_addr_i                      (smc_local_base),
    .region_size_i                          (smc_region_size_o),

    // Input Fabric interfaces (placeholder connections)
    .axi_in_jtag_req_i                      (jtag_axi_in_req_i),
    .axi_in_jtag_resp_o                     (jtag_axi_in_resp_o),
    .axi_in_mmio_req_i                      (cpu_axi_mmio_port_req_i),
    .axi_in_mmio_resp_o                     (cpu_axi_mmio_port_resp_o),
    .axi_in_data_accel_req_i                (axi_data_accel_req),
    .axi_in_data_accel_resp_o               (axi_data_accel_resp),
    .axi_lite_log_req_i                     (axil_log_engine_req_i),
    .axi_lite_log_resp_o                    (axil_log_engine_resp_o),

    // System AXI Input
    .sys_axi_in_req_i                       (sys_axi_in_req_i),
    .sys_axi_in_resp_o                      (sys_axi_in_resp_o),

    // SEP AXI Input (converted from 9-bit to 6-bit ID)
    .sep_axi_in_req_i                       (sep_axi_in_req_i),
    .sep_axi_in_resp_o                      (sep_axi_in_resp_o),

    // Local Fabric interfaces to peripherals
    .axi_front_port_req_o                   (cpu_axi_front_port_req_o),
    .axi_front_port_rsp_i                   (cpu_axi_front_port_resp_i),
    .apb_smc_dfd_reg_req_o                  (apb_smc_dfd_reg_req),
    .apb_smc_dfd_reg_resp_i                 (apb_smc_dfd_reg_resp),
    .axi_data_accel_ctrl_req_o              (axi_data_accel_ctrl_req),
    .axi_data_accel_ctrl_rsp_i              (axi_data_accel_ctrl_rsp),

    // Consolidated to 1 AXI-Lite interface for all peripherals
    .axil_peripherals_req_o                 (axil_peripherals_req_o),
    .axil_peripherals_resp_i                (axil_peripherals_resp_i),

    .axil_aR_ctrl_req_o                     (axil_aR_ctrl_req),
    .axil_aR_ctrl_resp_i                    (axil_aR_ctrl_resp),
    .axil_mR_ctrl_req_o                     (axil_mR_ctrl_req),
    .axil_mR_ctrl_resp_i                    (axil_mR_ctrl_resp),
    .axil_xR_ctrl_req_o                     (axil_xR_ctrl_req),
    .axil_xR_ctrl_resp_i                    (axil_xR_ctrl_resp),
    .axil_inbound_filter_ctrl_req_o         (axil_inbound_filter_ctrl_req),
    .axil_inbound_filter_ctrl_resp_i        (axil_inbound_filter_ctrl_resp),
    .axil_outbound_filter_ctrl_req_o        (axil_outbound_filter_ctrl_req),
    .axil_outbound_filter_ctrl_resp_i       (axil_outbound_filter_ctrl_resp),
    .axil_mailbox_req_o                     (axil_mailbox_req),
    .axil_mailbox_resp_i                    (axil_mailbox_resp),
    .axil_smc_base_config_req_o             (axil_smc_base_config_req),
    .axil_smc_base_config_resp_i            (axil_smc_base_config_resp),
    .axil_dfx_csr_req_o                     (axil_dfx_csr_req),
    .axil_dfx_csr_resp_i                    (axil_dfx_csr_resp),

    // Output Fabric interfaces (placeholder connections)
    .axi_filtered_remapped_req_o            (output_axi_req_o),
    .axi_filtered_remapped_resp_i           (output_axi_resp_i),

    // Filter config structs from register block
    .outbound_filter_status_o               (outbound_filter_status),
    .outbound_filter_ctrl_i                 (outbound_filter_ctrl),
    .inbound_filter_status_o                (inbound_filter_status),
    .inbound_filter_ctrl_i                  (inbound_filter_ctrl),

    // CSR structs for remap configurations
    .mR_ctrl_i                              (mR_ctrl),
    .xR_ctrl_i                              (xR_ctrl),
    .aR_ctrl_i                              (aR_ctrl),

    // Debug outputs
    .remap_debug_mmio_o                     (remap_debug_mmio),
    .remap_debug_jtag_o                     (remap_debug_jtag),
    .remap_debug_log_o                      (remap_debug_log),
    .remap_debug_dma_o                      (remap_debug_dma),
    .outbound_write_filter_hit_debug_o      (outbound_write_filter_hit_debug),
    .outbound_read_filter_hit_debug_o       (outbound_read_filter_hit_debug),
    .inbound_write_filter_hit_debug_o       (inbound_write_filter_hit_debug),
    .inbound_read_filter_hit_debug_o        (inbound_read_filter_hit_debug),

    // Clock gater activity indicators
    .fabric_clk_active_o                    (fabric_clk_active),
    .fabric_bus_active_o                    (fabric_bus_active),
    .sys_out_filter_clk_active_o            (sys_out_filter_clk_active),
    .sys_out_filter_bus_active_o            (sys_out_filter_bus_active),
    .sys_in_filter_clk_active_o             (sys_in_filter_clk_active),
    .sys_in_filter_bus_active_o             (sys_in_filter_bus_active)
  );

  ////////////////////////////
  // SMC Internal Registers //
  ////////////////////////////

  smc_internal_regs #(
    .NumOutboundFilters               (smc_pkg::NumOutboundFilters),
    .NumInboundFilters                (smc_pkg::NumInboundFilters)
  ) u_internal_regs (
    .clk_ref_i                        (clk_ref_i),
    .clk_smc_i                        (clk_smc_i),

    .rst_primary_smc_clk_ni           (rst_primary_smc_clk_ni),

    // CSR structs for filter configurations
    .outbound_filter_status_i         (outbound_filter_status),
    .outbound_filter_ctrl_o           (outbound_filter_ctrl),
    .inbound_filter_status_i          (inbound_filter_status),
    .inbound_filter_ctrl_o            (inbound_filter_ctrl),

    // CSR structs for remap configurations
    .mR_ctrl_o                        (mR_ctrl),
    .xR_ctrl_o                        (xR_ctrl),
    .aR_ctrl_o                        (aR_ctrl),

    // APB interface from smc_local_xbar -- DFD
    .apb_smc_dfd_reg_req_i            (apb_smc_dfd_reg_req),
    .apb_smc_dfd_reg_resp_o           (apb_smc_dfd_reg_resp),

    // AXI-Lite interface from smc_internal_axi_lite_xbar -- filters
    .axil_inbound_filter_ctrl_req_i   (axil_inbound_filter_ctrl_req),
    .axil_inbound_filter_ctrl_resp_o  (axil_inbound_filter_ctrl_resp),
    .axil_outbound_filter_ctrl_req_i  (axil_outbound_filter_ctrl_req),
    .axil_outbound_filter_ctrl_resp_o (axil_outbound_filter_ctrl_resp),

    // AXI-Lite interface from smc_internal_axi_lite_xbar -- remaps
    .axil_mR_ctrl_req_i               (axil_mR_ctrl_req),
    .axil_mR_ctrl_resp_o              (axil_mR_ctrl_resp),
    .axil_xR_ctrl_req_i               (axil_xR_ctrl_req),
    .axil_xR_ctrl_resp_o              (axil_xR_ctrl_resp),
    .axil_aR_ctrl_req_i               (axil_aR_ctrl_req),
    .axil_aR_ctrl_resp_o              (axil_aR_ctrl_resp),

    // AXI-Lite interface from smc_internal_axi_lite_xbar -- Mailbox
    .axil_mailbox_req_i               (axil_mailbox_req),
    .axil_mailbox_resp_o              (axil_mailbox_resp),

    // AXI-Lite interface from smc_internal_axi_lite_xbar -- DFT CSR
    .axil_dfx_csr_req_i               (axil_dfx_csr_req),
    .axil_dfx_csr_resp_o              (axil_dfx_csr_resp),

    // AXI-Lite interface from smc_internal_axi_lite_xbar -- base config CSR
    .axil_smc_base_config_req_i       (axil_smc_base_config_req),
    .axil_smc_base_config_resp_o      (axil_smc_base_config_resp),

    // Mailbox interrupts
    .inbound_interrupt_o              (mailbox_interrupts),
    .outbound_interrupt_o             (ext_mailbox_interrupts_o),

    // SMC address window from smc_base_config
    .smc_global_base_o                (smc_global_base_o),
    .smc_local_base_o                 (smc_local_base),
    .smc_region_size_o                (smc_region_size_o),

    // Clock-gate enables from smc_base_config
    .cg_ctrl_dma_cg_en_o              (cg_ctrl_dma_cg_en),
    .cg_ctrl_ob_filter_axi_cg_en_o    (cg_ctrl_ob_filter_axi_cg_en),
    .cg_ctrl_ib_filter_axi_cg_en_o    (cg_ctrl_ib_filter_axi_cg_en),
    .cg_ctrl_output_fabric_cg_en_o    (cg_ctrl_output_fabric_cg_en),
    .cg_ctrl_zeroer_cg_en_o           (cg_ctrl_zeroer_cg_en),
    .cg_ctrl_i3c_cg_en_o              (cg_ctrl_i3c_cg_en_o),
    .cg_ctrl_avs_cg_en_o              (cg_ctrl_avs_cg_en_o),
    .cg_ctrl_i2c_cg_en_o              (cg_ctrl_i2c_cg_en_o),
    .cg_ctrl_uart_cg_en_o             (cg_ctrl_uart_cg_en_o),
    .cg_ctrl_tel_cg_en_o              (cg_ctrl_tel_cg_en_o),
    .cg_ctrl_hysteresis_o             (cg_ctrl_hysteresis),

    // AXI hang detector config from smc_base_config
    .hang_det_sys_axi_enable_o        (hang_det_sys_axi_enable),
    .hang_det_sys_axi_irq_en_o        (hang_det_sys_axi_irq_en),
    .hang_det_sys_axi_irq_test_o      (hang_det_sys_axi_irq_test),
    .hang_det_sys_axi_threshold_o     (hang_det_sys_axi_threshold),
    .hang_det_sep_axi_enable_o        (hang_det_sep_axi_enable),
    .hang_det_sep_axi_irq_en_o        (hang_det_sep_axi_irq_en),
    .hang_det_sep_axi_irq_test_o      (hang_det_sep_axi_irq_test),
    .hang_det_sep_axi_threshold_o     (hang_det_sep_axi_threshold),
    .hang_det_data_accel_enable_o     (hang_det_data_accel_enable),
    .hang_det_data_accel_irq_en_o     (hang_det_data_accel_irq_en),
    .hang_det_data_accel_irq_test_o   (hang_det_data_accel_irq_test),
    .hang_det_data_accel_threshold_o  (hang_det_data_accel_threshold),

    // DFD signals
    .cla_interrupt_o                  (cla_interrupt),
    .cla_ext_action_custom_o          (cla_ext_action_custom_o),

    .xtrigger_ss_o                    (xtrigger_ss_o),
    .xtrigger_ss_i                    (xtrigger_ss_i),

    .tdr_dbg_ctrl_clock_stop_en_i     (tdr_dbg_ctrl_clock_stop_en_i),
    .tdr_dbg_ctrl_clocks_stopped_by_cla_o (tdr_dbg_ctrl_clocks_stopped_by_cla_o),

    .debug_bus_i                      (debug_bus),
    .debug_marker_o                   (debug_marker),

    .trace_mem_req_o                  (trace_mem_req_o),
    .trace_mem_resp_i                 (trace_mem_resp_i),

    .test_en_i                        (test_en_i),
    .scan_rst_ni                      (scan_rst_ni),

    .mem_repair_done_i                (mem_repair_done_i),
    .mem_repair_success_i             (mem_repair_success_i),
    .mem_repair_abort_i               (mem_repair_abort_i),
    .mbist_done_i                     (mbist_done_i),
    .mbist_pass_i                     (mbist_pass_i),
    .mbist_abort_i                    (mbist_abort_i),

    // Clock gater activity indicators
    .mailbox_clk_active_o             (mailbox_clk_active),
    .mailbox_bus_active_o             (mailbox_bus_active),
    .ob_filter_clk_active_o           (ob_filter_clk_active),
    .ob_filter_bus_active_o           (ob_filter_bus_active),
    .ib_filter_clk_active_o           (ib_filter_clk_active),
    .ib_filter_bus_active_o           (ib_filter_bus_active),
    .mmode_remap_clk_active_o         (mmode_remap_clk_active),
    .mmode_remap_bus_active_o         (mmode_remap_bus_active),
    .xvisor_remap_clk_active_o        (xvisor_remap_clk_active),
    .xvisor_remap_bus_active_o        (xvisor_remap_bus_active),
    .alias_remap_clk_active_o         (alias_remap_clk_active),
    .alias_remap_bus_active_o         (alias_remap_bus_active)
  );

  ///////////////////////////
  // Data Accelerator Wrap //
  ///////////////////////////

  // Assertions to protect against truncation on casts
  `OCAH_OT_ASSERT_INIT(
      DmaCtrlBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR < (64'd1 << smc_pkg::SMC_LOCAL_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      DmaCtrlSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE < (64'd1 << smc_pkg::SMC_LOCAL_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      ZeroerCtrlBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR < (64'd1 << smc_pkg::SMC_LOCAL_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      ZeroerCtrlSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE < (64'd1 << smc_pkg::SMC_LOCAL_ADDR_WIDTH))

  // Contains DMA and Zeroer
  smc_data_accelerator_wrap #(
    .DMA_CTRL_REG_MAP_BASE_ADDR         (smc_pkg::SMC_LOCAL_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR)),
    .DMA_CTRL_REG_MAP_SIZE              (smc_pkg::SMC_LOCAL_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE)),
    .ZEROER_CTRL_REG_MAP_BASE_ADDR      (smc_pkg::SMC_LOCAL_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR)),
    .ZEROER_CTRL_REG_MAP_SIZE           (smc_pkg::SMC_LOCAL_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE))
  ) u_smc_data_accelerator_wrap (
    .clk_i                              (clk_smc_i),
    .rst_ni                             (rst_primary_smc_clk_ni),
    .test_en_i                          (test_en_i),

    .dma_cg_en_i                        (cg_ctrl_dma_cg_en),
    .zeroer_cg_en_i                     (cg_ctrl_zeroer_cg_en),
    .cg_hysteresis_i                    (cg_ctrl_hysteresis),

    .ctrl_axi_req_i                     (axi_data_accel_ctrl_req),
    .ctrl_axi_resp_o                    (axi_data_accel_ctrl_rsp),

    .mst_axi_req_o                      (axi_data_accel_req),
    .mst_axi_resp_i                     (axi_data_accel_resp),

    .dma_busy_o                         (dma_busy),
    .dma_intp_o                         (dma_intp),
    .zeroer_busy_o                      (zeroer_busy),
    .zeroer_intp_o                      (zeroer_intp),

    // Clock gater activity indicators
    .dma_frontend_clk_active_o          (dma_frontend_clk_active),
    .dma_frontend_bus_active_o          (dma_frontend_bus_active),
    .zeroer_clk_active_o                (zeroer_clk_active),
    .zeroer_bus_active_o                (zeroer_bus_active)
  );


  // ===========================================================================
  // AXI Hang Detectors (independent masters: sys_axi, sep_axi, data_accel)
  // ===========================================================================
  // One non-intrusive detector per independent master AXI into the fabric (CPU
  // is excluded -- covered by the watchdog). Snoop is local; config comes from
  // the cpu_ctrl register block (u_internal_regs). The three irqs are OR'd into
  // a single fault line on axi_hang_irq_o, which smc.sv feeds back into
  // smc_peripherals to land on peripheral_interrupts[30] -> PLIC source 287.
  // Software reads the per-detector HANG_DET_*_CTRL registers to tell which
  // master stalled.
  logic hang_irq_sys_axi, hang_irq_sep_axi, hang_irq_data_accel;

  axi_hang_detector #(
    .OutstandingTx(smc_pkg::FABRIC_OUTSTANDING_TX)
  ) u_hang_det_sys_axi (
    .clk_i            (clk_smc_i),
    .rst_ni           (rst_primary_smc_clk_ni),
    .snoop_aw_valid_i (sys_axi_in_req_i.aw_valid),
    .snoop_aw_ready_i (sys_axi_in_resp_o.aw_ready),
    .snoop_w_valid_i  (sys_axi_in_req_i.w_valid),
    .snoop_b_valid_i  (sys_axi_in_resp_o.b_valid),
    .snoop_b_ready_i  (sys_axi_in_req_i.b_ready),
    .snoop_ar_valid_i (sys_axi_in_req_i.ar_valid),
    .snoop_ar_ready_i (sys_axi_in_resp_o.ar_ready),
    .snoop_r_valid_i  (sys_axi_in_resp_o.r_valid),
    .snoop_r_ready_i  (sys_axi_in_req_i.r_ready),
    .snoop_r_last_i   (sys_axi_in_resp_o.r.last),
    .enable_i         (hang_det_sys_axi_enable),
    .irq_en_i         (hang_det_sys_axi_irq_en),
    .irq_test_i       (hang_det_sys_axi_irq_test),
    .threshold_i      (hang_det_sys_axi_threshold),
    .bus_active_o     (/* UNUSED */),
    .irq_o            (hang_irq_sys_axi)
  );

  axi_hang_detector #(
    .OutstandingTx(smc_pkg::FABRIC_OUTSTANDING_TX)
  ) u_hang_det_sep_axi (
    .clk_i            (clk_smc_i),
    .rst_ni           (rst_primary_smc_clk_ni),
    .snoop_aw_valid_i (sep_axi_in_req_i.aw_valid),
    .snoop_aw_ready_i (sep_axi_in_resp_o.aw_ready),
    .snoop_w_valid_i  (sep_axi_in_req_i.w_valid),
    .snoop_b_valid_i  (sep_axi_in_resp_o.b_valid),
    .snoop_b_ready_i  (sep_axi_in_req_i.b_ready),
    .snoop_ar_valid_i (sep_axi_in_req_i.ar_valid),
    .snoop_ar_ready_i (sep_axi_in_resp_o.ar_ready),
    .snoop_r_valid_i  (sep_axi_in_resp_o.r_valid),
    .snoop_r_ready_i  (sep_axi_in_req_i.r_ready),
    .snoop_r_last_i   (sep_axi_in_resp_o.r.last),
    .enable_i         (hang_det_sep_axi_enable),
    .irq_en_i         (hang_det_sep_axi_irq_en),
    .irq_test_i       (hang_det_sep_axi_irq_test),
    .threshold_i      (hang_det_sep_axi_threshold),
    .bus_active_o     (/* UNUSED */),
    .irq_o            (hang_irq_sep_axi)
  );

  axi_hang_detector #(
    .OutstandingTx(smc_pkg::FABRIC_OUTSTANDING_TX)
  ) u_hang_det_data_accel (
    .clk_i            (clk_smc_i),
    .rst_ni           (rst_primary_smc_clk_ni),
    .snoop_aw_valid_i (axi_data_accel_req.aw_valid),
    .snoop_aw_ready_i (axi_data_accel_resp.aw_ready),
    .snoop_w_valid_i  (axi_data_accel_req.w_valid),
    .snoop_b_valid_i  (axi_data_accel_resp.b_valid),
    .snoop_b_ready_i  (axi_data_accel_req.b_ready),
    .snoop_ar_valid_i (axi_data_accel_req.ar_valid),
    .snoop_ar_ready_i (axi_data_accel_resp.ar_ready),
    .snoop_r_valid_i  (axi_data_accel_resp.r_valid),
    .snoop_r_ready_i  (axi_data_accel_req.r_ready),
    .snoop_r_last_i   (axi_data_accel_resp.r.last),
    .enable_i         (hang_det_data_accel_enable),
    .irq_en_i         (hang_det_data_accel_irq_en),
    .irq_test_i       (hang_det_data_accel_irq_test),
    .threshold_i      (hang_det_data_accel_threshold),
    .bus_active_o     (/* UNUSED */),
    .irq_o            (hang_irq_data_accel)
  );

  // Combined fault out to smc.sv, which routes it to peripheral_interrupts[30]
  assign axi_hang_irq_o = hang_irq_sys_axi | hang_irq_sep_axi | hang_irq_data_accel;

endmodule

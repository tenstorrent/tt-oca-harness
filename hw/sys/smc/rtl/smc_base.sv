// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate the SMC fabric, internal registers and data accelerators; the CPU cluster is outside.
//
// Hosts smc_fabric, smc_internal_regs, smc_data_accelerator_wrap and three AXI hang detectors.
// Builds the CPU interrupt vector and the 1024-bit debug bus, and exchanges the front-port and
// MMIO AXI ports with smc_cpu_wrapper at the SMC top.
// Exports peripheral AXI-Lite, interrupts, and clock-gate enables to the SMC top.
// NO_ADDR_REMAP removes the M-mode and Xvisor output remap from the output fabric.

module smc_base #(
  parameter bit NO_ADDR_REMAP = 1'b1,   // Removes the M-mode and Xvisor output remap from the
                                        // output fabric, leaving only its AXI ID conversion;
                                        // the input-fabric alias remap is unaffected.

  localparam int unsigned NumCpuCores      = smc_4core_cpu_pkg::NumCpuCores,      // Number of cores in the SMC CPU
                                                                                  // cluster, from smc_4core_cpu_pkg;
                                                                                  // sizes the per-core PC and
                                                                                  // watchdog ports.
  localparam int unsigned NumCpuInterrupts = smc_4core_cpu_pkg::NumCpuInterrupts,      // Number of interrupt lines into
                                                                                       // the CPU cluster: external,
                                                                                       // peripheral, mailbox and
                                                                                       // internal.
  localparam int unsigned NumExtInterrupts = smc_4core_cpu_pkg::NumExtInterrupts      // Number of external interrupt
                                                                                      // lines on ext_interrupts_i; they
                                                                                      // occupy the lowest
                                                                                      // cpu_interrupts_o bits.

) (
  input  logic clk_smc_i,               // SMC core clock for the fabric, internal registers, data
                                        // accelerators and interrupt synchronizers.
  input  logic clk_ref_i,               // Reference clock for the CLA time-tick generator in the
                                        // internal register block.

  input  logic rst_primary_smc_clk_ni,  // Active-low primary reset in the SMC clock domain for the
                                        // fabric, internal registers, data accelerators and AXI
                                        // hang detectors.

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,  // Inbound system AXI request;
                                                                      // passes the inbound filters
                                                                      // to SMC local targets and is
                                                                      // watched by a hang detector.
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,  // Inbound system AXI
                                                                       // response; DECERR outside
                                                                       // the SMC address window.

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  jtag_axi_in_req_i,  // JTAG debug AXI request;
                                                                     // alias-remapped and routed
                                                                     // to SMC local targets or
                                                                     // output_axi_req_o.
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t jtag_axi_in_resp_o,  // JTAG debug AXI
                                                                      // response.

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,  // Inbound SEP AXI request,
                                                                      // routed to SMC local
                                                                      // targets and watched by a
                                                                      // hang detector.
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,  // Inbound SEP AXI
                                                                       // response; DECERR outside
                                                                       // the SMC address window.

  input  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_i,  // Log engine AXI-Lite request,
                                                                // converted to AXI and routed
                                                                // like jtag_axi_in_req_i.
  output smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_o,  // Log engine AXI-Lite
                                                                 // response.

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,  // Outbound AXI request
                                                                       // from the output fabric,
                                                                       // after the output remap
                                                                       // and outbound filters.
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,  // Outbound AXI response
                                                                        // into the output
                                                                        // fabric.

  output smc_pkg::smc_axil_32_32_req_t  axil_peripherals_req_o,  // Consolidated AXI-Lite
                                                                 // interface for all
                                                                 // peripherals request.
  input  smc_pkg::smc_axil_32_32_resp_t axil_peripherals_resp_i,  // Consolidated AXI-Lite
                                                                  // interface for all
                                                                  // peripherals response.

  output logic wdt_first_timeout_o,     // First-stage watchdog timeout: OR of the per-core CPU
                                        // watchdog timeouts.

  output logic [smc_pkg::NumMailboxes-1:0] ext_mailbox_interrupts_o,   // Outbound interrupts of
                                                                       // the internal mailboxes,
                                                                       // one per mailbox.

  input  logic [NumExtInterrupts-1:0] ext_interrupts_i,    // External interrupts, synchronized to
                                                           // clk_smc_i onto the lowest
                                                           // cpu_interrupts_o bits.
  input  logic [31:0]                   peripheral_interrupts_i,  // Interrupts from the SMC
                                                                  // peripherals, placed on
                                                                  // cpu_interrupts_o after the
                                                                  // external interrupts.

  output smc_pkg::smc_local_32_64_8_12_axi_req_t       cpu_axi_front_port_req_o,  // Local-fabric AXI request
                                                                                  // to smc_cpu_wrapper for
                                                                                  // the cluster L2 frontend
                                                                                  // and cpu_ctrl windows.
  input  wire smc_pkg::smc_local_32_64_8_12_axi_resp_t cpu_axi_front_port_resp_i,  // AXI response from
                                                                                   // smc_cpu_wrapper to the
                                                                                   // local fabric.
  output logic [NumCpuInterrupts-1:0]                cpu_interrupts_o,    // Interrupt vector to the CPU
                                                                          // cluster: synchronized
                                                                          // external, 32 peripheral, 32
                                                                          // inbound mailbox, then CLA
                                                                          // clock stop, CLA, DMA and
                                                                          // zeroer; upper bits are zero.

  input  wire smc_pkg::smc_cpu_mmio_axi_req_t cpu_axi_mmio_port_req_i,  // CPU cluster MMIO AXI
                                                                        // request from
                                                                        // smc_cpu_wrapper;
                                                                        // alias-remapped and routed
                                                                        // to SMC local targets or
                                                                        // output_axi_req_o.
  output smc_pkg::smc_cpu_mmio_axi_resp_t     cpu_axi_mmio_port_resp_o,  // CPU cluster MMIO AXI
                                                                         // response to
                                                                         // smc_cpu_wrapper.
  input  wire logic [NumCpuCores-1:0][57:0] cpu_wb_reg_pc_i,    // Per-core writeback program
                                                                // counter from smc_cpu_wrapper; the
                                                                // low 32 bits go onto the debug
                                                                // bus.
  input  wire logic [NumCpuCores-1:0]       cpu_wdt_timeout_cluster_i,    // Per-core first-stage watchdog
                                                                          // timeout from smc_cpu_wrapper,
                                                                          // ORed onto wdt_first_timeout_o.
  input  wire logic                           cpu_cluster_ded_i,  // Uncorrectable memory error from
                                                                  // the CPU cluster, placed on the
                                                                  // debug bus.
  input  wire logic                           wdt_second_timeout_i,  // Second-stage watchdog timeout
                                                                     // from the CPU control block,
                                                                     // placed on the debug bus.

  output smc_pkg::smc_axi_addr_t smc_global_base_o,  // SMC global base address from the GLOBAL_BASE
                                                     // register, also used by the fabric address
                                                     // decode.
  output logic [31:0]            smc_region_size_o,  // SMC region size from the REGION_SIZE
                                                     // register, also used by the fabric address
                                                     // decode.

  output logic cg_ctrl_i3c_cg_en_o,     // CLOCK_GATE_CONTROL.i3c_cg_en, reset 0, on clk_smc_i;
                                        // in smc, 1 stops the I3C peripheral clock (it drives the
                                        // clock-gate cell enable inverted).
  output logic cg_ctrl_avs_cg_en_o,     // CLOCK_GATE_CONTROL.avs_cg_en, reset 0, on clk_smc_i; in
                                        // smc, 1 stops the AVS bus controller peripheral and
                                        // reference clocks.
  output logic cg_ctrl_i2c_cg_en_o,     // CLOCK_GATE_CONTROL.i2c_cg_en, reset 0, on clk_smc_i; in
                                        // smc, 1 stops the I2C peripheral clock.
  output logic cg_ctrl_uart_cg_en_o,    // CLOCK_GATE_CONTROL.uart_cg_en, reset 0, on clk_smc_i; in
                                        // smc, 1 stops the UART peripheral clock.
  output logic cg_ctrl_tel_cg_en_o,     // CLOCK_GATE_CONTROL.telemetry_cg_en, reset 0, on
                                        // clk_smc_i; in smc, 1 stops the telemetry unit's gated
                                        // SMC and telemetry clocks.

  input  logic [511:0] ext_debug_bus_i,  // Adopter debug signals, synchronized to clk_smc_i into
                                         // the upper half of the debug bus; keep each signal 16-bit
                                         // aligned.
  input  logic [16:0]  avsbus_cur_state_debug_i,  // AVS bus controller state from the SMC
                                                  // peripherals; the low 16 bits go onto the debug
                                                  // bus.
  input  logic [8:0]   system_timer_octs_credits_debug_i,  // OCTS credit count from the system
                                                           // timer, placed on the debug bus.
  input  logic         system_timer_octs_credits_left_debug_i,  // OCTS credits-left status from the
                                                                // system timer, placed on the debug
                                                                // bus.

  input  logic [smc_config_pkg::NumTelemetryReceivers-1:0][3:0] telemetry_debug_i,    // Debug status from each telemetry
                                                                                      // receiver in the SMC peripherals,
                                                                                      // placed on the debug bus.
  input  logic [smc_config_pkg::NumI2c-1:0][3:0]                 i2c_debug_i,   // Debug status from each I2C
                                                                                // controller in the SMC
                                                                                // peripherals, placed on the debug
                                                                                // bus.
  input  logic [9:0]                                              efuse_debug_i,  // eFuse controller debug status
                                                                                  // from the SMC peripherals, placed
                                                                                  // on the debug bus.

  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,  // Custom CLA external-action outputs from the DFD block, one bit per custom action.

  output smc_pkg::xtrigger_t      xtrigger_ss_o,  // Cross-trigger lanes from the SMC core logic
                                                  // analyzer to the subsystem cross-trigger matrix,
                                                  // masked by the clock-halt trigger mask.
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,  // Cross-trigger lanes from the subsystem
                                                  // cross-trigger matrix into the SMC core logic
                                                  // analyzer.

  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,  // Enables reporting a CLA halt-clock action as a
                                                   // clock stop.
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,  // High while a CLA halt-clock action,
                                                           // enabled by bit 0 of the clock-halt
                                                           // trigger mask and
                                                           // tdr_dbg_ctrl_clock_stop_en_i, requests
                                                           // a clock stop; also CPU internal
                                                           // interrupt 0.

  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,  // Requests from the DFD
                                                                                          // trace sink to the
                                                                                          // external trace RAMs,
                                                                                          // one per RAM instance.
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,  // Read data from the
                                                                                           // external trace RAMs
                                                                                           // to the DFD trace
                                                                                           // sink.

  input  logic test_en_i,               // DFT test-mode enable, active-high, for the fabric,
                                        // internal registers and data accelerators.
  input  logic scan_rst_ni,             // DFT scan reset, active-low; used only by the DFD block in
                                        // the internal register block while test_en_i is high.

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

  output logic axi_hang_irq_o           // OR of the system AXI, SEP AXI and data-accelerator AXI
                                        // hang detector interrupts, configured through the
                                        // HANG_DET registers of the base-config block; in smc it
                                        // becomes peripheral interrupt 30.
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
  output_remap_reg_pkg::output_remap__out_t mR_ctrl [smc_pkg::NumMmodeOutputRemapRegions-1:0];
  output_remap_reg_pkg::output_remap__out_t xR_ctrl [smc_pkg::NumXvisorOutputRemapRegions-1:0];
  alias_remap_reg_pkg::alias_remap__out_t aR_ctrl [smc_pkg::NumAliasRemapRegions-1:0];


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
  logic [smc_pkg::NumMailboxes-1:0]  mailbox_interrupts;

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
  logic [NumExtInterrupts-1:0] ext_interrupts_smc_clk;
  prim_sync3 #(
    .WIDTH(NumExtInterrupts)
  ) u_ext_interrupts_sync3 (
    .clk_i (clk_smc_i),
    .d_i   (ext_interrupts_i),
    .q_o   (ext_interrupts_smc_clk)
  );

  // Interrupt distribution: N external interrupts, 32 peripheral interrupts,
  // 32 mailbox interrupts, 4 internal interrupts
  always_comb begin
    cpu_interrupts_o = '0;
    cpu_interrupts_o[NumExtInterrupts-1:0]        = ext_interrupts_smc_clk;
    cpu_interrupts_o[NumExtInterrupts+:32]        = peripheral_interrupts_i;               // 32 peripheral interrupts
    cpu_interrupts_o[(NumExtInterrupts+32)+:32]   = mailbox_interrupts;                    // 32 mailbox interrupts
    cpu_interrupts_o[(NumExtInterrupts+64)]       = tdr_dbg_ctrl_clocks_stopped_by_cla_o;  // internal interrupt 0
    cpu_interrupts_o[(NumExtInterrupts+64)+1]     = cla_interrupt;                         // internal interrupt 1
    cpu_interrupts_o[(NumExtInterrupts+64)+2]     = dma_intp;                              // internal interrupt 2
    cpu_interrupts_o[(NumExtInterrupts+64)+3]     = zeroer_intp;                           // internal interrupt 3
  end


  ///////////////
  // Debug Bus //
  ///////////////

  logic [511:0] ext_debug_bus_smc_clk;
  prim_sync3 #(
    .WIDTH(512)
  ) u_ext_debug_bus_sync3 (
    .clk_i (clk_smc_i),
    .d_i   (ext_debug_bus_i),
    .q_o   (ext_debug_bus_smc_clk)
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

  assign debug_bus[16*25-1:16*24]     = {{(16 - 4 * smc_config_pkg::NumI2c){1'b0}},
                                          i2c_debug_i};
  assign debug_bus[16*26-1:16*25]     = {{(16 - 4 * smc_config_pkg::NumTelemetryReceivers){1'b0}},
                                          telemetry_debug_i};
  assign debug_bus[16*27-1:16*26]     = avsbus_cur_state_debug_i[15:0];
  assign debug_bus[16*28-1:16*27]     = {6'h0, system_timer_octs_credits_left_debug_i, system_timer_octs_credits_debug_i};
  assign debug_bus[16*29-1:16*28]     = {zeroer_busy, dma_busy, cpu_cluster_ded_i, wdt_second_timeout_i,
                                          {{(4-NumCpuCores){1'b0}}, cpu_wdt_timeout_cluster_i},
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
    .NUM_INBOUND_FILTERS        (smc_pkg::NumInboundFilters),
    .NUM_OUTBOUND_FILTERS       (smc_pkg::NumOutboundFilters),
    .MAX_TRANS                  (smc_pkg::FabricMaxTrans),
    .FILTER_REQ_PIPELINE_ENABLE (1'b1),
    .FILTER_RSP_PIPELINE_ENABLE (1'b1)
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
    .NUM_OUTBOUND_FILTERS             (smc_pkg::NumOutboundFilters),
    .NUM_INBOUND_FILTERS              (smc_pkg::NumInboundFilters)
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

  // Contains DMA and Zeroer
  smc_data_accelerator_wrap u_smc_data_accelerator_wrap (
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
    .OUTSTANDING_TX(smc_pkg::FabricOutstandingTx)
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
    .OUTSTANDING_TX(smc_pkg::FabricOutstandingTx)
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
    .OUTSTANDING_TX(smc_pkg::FabricOutstandingTx)
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

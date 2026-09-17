// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC 4 core CPU cluster
// - built using Chipyard's Rocket-chip generator framework
//
//-----------------------------------------------------------------------------

module smc_4core_cpu (
  // Clock and reset
  input  logic                                            clk_i,
  input  logic                                            rst_isolate_ni,

  input  logic                                            mem_init_reset_ni,

  input  logic                                            rst_uncore_ni,
  input  logic  [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0]    rst_core_ni,
  input  logic                                            rst_debug_ni,

  // Reset-drain handshake (driven by smc_cpu_ctrl_wrap, always-on domain)
  input  logic                                            isolate_req_i,
  output logic                                            drained_o,

  // Reset vector inputs
  input  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0][55:0] reset_vector_i,

  // Interrupts input
  input  logic [smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS-1:0]      interrupts_i,

  // AXI interfaces
  output smc_pkg::smc_cpu_mmio_axi_req_t                  mmio_axi_req_o,
  input  smc_pkg::smc_cpu_mmio_axi_resp_t                 mmio_axi_resp_i,

  input  smc_pkg::smc_cpu_l2_frontend_axi_req_t           l2_frontend_axi_req_i,
  output smc_pkg::smc_cpu_l2_frontend_axi_resp_t          l2_frontend_axi_resp_o,

  // Debug interfaces (JTAG)
  input  logic                                            smc_cpu_jtag_TCK_i,
  input  logic                                            smc_cpu_jtag_TMS_i,
  input  logic                                            smc_cpu_jtag_TDI_i,
  output logic                                            smc_cpu_jtag_TDO_data_o,
  input  logic                                            smc_cpu_jtag_reset_i,
  input  logic [10:0]                                     smc_cpu_jtag_mfr_id_i,
  input  logic [15:0]                                     smc_cpu_jtag_part_number_i,
  input  logic [3:0]                                      smc_cpu_jtag_version_i,

  // Core status outputs
  output logic                                            cluster_ded_o,
  output logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0][1-1:0]    wb_pc_valid_o,
  output logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0][58-1:0]   wb_reg_pc_o,

  output logic  [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0]    wdt_reset_o,

  // Memory interface signals between DigitalTop and mems
  output chipyard_4core_mem_pkg::rom_tilelink_req_t             rom_intf_req_o,
  input  chipyard_4core_mem_pkg::rom_tilelink_rsp_t             rom_intf_rsp_i,
  output chipyard_4core_mem_pkg::scratch_ram_req_t              scratch_ram_intf_req_o     [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
  input  chipyard_4core_mem_pkg::scratch_ram_rsp_t              scratch_ram_intf_rsp_i     [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_icache_tag_req_t            l1_icache_tag_intf_req_o   [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_icache_tag_rsp_t            l1_icache_tag_intf_rsp_i   [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_icache_data_req_t           l1_icache_data_intf_req_o  [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_icache_data_rsp_t           l1_icache_data_intf_rsp_i  [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_dcache_tag_req_t            l1_dcache_tag_intf_req_o   [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t            l1_dcache_tag_intf_rsp_i   [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
  output chipyard_4core_mem_pkg::l1_dcache_data_req_t           l1_dcache_data_intf_req_o  [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],
  input  chipyard_4core_mem_pkg::l1_dcache_data_rsp_t           l1_dcache_data_intf_rsp_i  [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],

  input  logic                                            disable_sram_auto_init_i,

  output logic                                            init_mem_done_o,

  // Test related signals
  input  logic                                            test_en_i
);
  // Mem Init signals
  chipyard_4core_mem_pkg::scratch_ram_req_t scratch_ram_intf_req_pre_init [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
  chipyard_4core_mem_pkg::scratch_ram_rsp_t scratch_ram_intf_rsp_pre_init [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];

  typedef enum logic [2:0] {
    MEM_ZERO_IDLE = 3'b001,
    MEM_ZERO_BUSY = 3'b010,
    MEM_ZERO_DONE = 3'b100
  } zero_state_e;

  logic init_mem_enable;
  logic init_mem_complete, nxt_init_mem_complete;
  logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH-1:0] zero_addr, next_zero_addr;
  zero_state_e state, nxt_state;

  // ----------
  // Clock gate the debug module
  logic clock_en;
  logic debug_dmactive, debug_dmactiveAck;
  logic gated_debug_clock;

  prim_flop_3sync_r sync_debug_active (
    .clk_i(clk_i),
    .rst_ni(rst_debug_ni),
    .d_i(debug_dmactive),
    .q_o(debug_dmactiveAck)
  );

  always_ff @(posedge clk_i or negedge rst_debug_ni) begin
    if (~rst_debug_ni) begin
      clock_en <= 1'b1;
    end else begin
      clock_en <= debug_dmactiveAck;
    end
  end

  prim_clkgater debug_clock_gate (
    .clk_i    (clk_i),
    .en_i     (clock_en),
    .te_i     (test_en_i),
    .clk_o    (gated_debug_clock)
  );

  // cluster_ded has glitches because of uneven combo path, flop to mitigate CDC glitches
  logic [4-1:0][1-1:0] io_errors_uncorrectable_valid;
  logic [32-1:0][1-1:0] uncorrectable_2;

  always_ff @(posedge clk_i or negedge rst_uncore_ni) begin
    if (~rst_uncore_ni) begin
      cluster_ded_o <= 1'b0;
    end else begin
      cluster_ded_o <= |{io_errors_uncorrectable_valid, uncorrectable_2};
    end
  end

  // ----------
  // Cluster boundary isolation & clamping: isolate the L2-frontend AXI slave +
  // MMIO master and clamp wb_pc/wdt_reset so reset-domain glitches can't leak out.

  localparam int CLUSTER_ISOLATE_CYCLES = 4;

  logic cluster_boundary_isolate;
  logic cluster_boundary_ready;
  logic [CLUSTER_ISOLATE_CYCLES-1:0] cluster_boundary_isolate_shift;

  smc_pkg::smc_cpu_l2_frontend_axi_req_t  l2_frontend_axi_isolated_req;
  smc_pkg::smc_cpu_l2_frontend_axi_resp_t l2_frontend_axi_isolated_resp;
  logic l2_frontend_isolated;

  logic mmio_isolated;

  // MMIO AXI cache override - force modifiable bit for CPU transactions
  axi_pkg::cache_t mmio_aw_cache_raw;
  axi_pkg::cache_t mmio_ar_cache_raw;

  // CPU-side (pre-isolation) MMIO master signals fed into the isolate slave port
  smc_pkg::smc_cpu_mmio_axi_req_t  mmio_axi_cpu_req;
  smc_pkg::smc_cpu_mmio_axi_resp_t mmio_axi_cpu_resp;

  // Raw (pre-clamp) status crossings driven by DigitalTop
  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0][1-1:0]  wb_pc_valid_raw;
  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0][58-1:0] wb_reg_pc_raw;
  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0]         wdt_reset_raw;

  // Ready to connect: mem init, cores+uncore out of reset (HW/cold-boot backstop),
  // no isolate request -> immediate isolate, delayed de-isolate via shift below.
  assign cluster_boundary_ready = init_mem_complete & (&rst_core_ni) & rst_uncore_ni
                                  & ~isolate_req_i;

  // Delays de-isolation by CLUSTER_ISOLATE_CYCLES after the boundary is ready.
  always_ff @(posedge clk_i or negedge rst_uncore_ni) begin
    if (~rst_uncore_ni) begin
      cluster_boundary_isolate_shift <= '0;
    end else begin
      cluster_boundary_isolate_shift <= {
        cluster_boundary_isolate_shift[CLUSTER_ISOLATE_CYCLES-2:0], cluster_boundary_ready
      };
    end
  end

  // Isolate immediately when not ready; release only after ready holds for the full shift depth.
  assign cluster_boundary_isolate = ~cluster_boundary_ready
                                    | ~cluster_boundary_isolate_shift[CLUSTER_ISOLATE_CYCLES-1];

  axi_isolate #(
    .NumPending          (4),
    .TerminateTransaction(1'b0),  // Block transactions instead of terminating them
    .AtopSupport         (1'b0),
    .AxiAddrWidth        (smc_pkg::AXI_ADDR_WIDTH),
    .AxiDataWidth        (smc_pkg::AXI_DATA_WIDTH),
    .AxiIdWidth          (smc_pkg::SMC_CPU_L2_FRONTEND_AXI_ID_WIDTH),
    .AxiUserWidth        (smc_pkg::AXI_USER_WIDTH),
    .axi_req_t           (smc_pkg::smc_cpu_l2_frontend_axi_req_t),
    .axi_resp_t          (smc_pkg::smc_cpu_l2_frontend_axi_resp_t)
  ) u_l2_frontend_axi_isolate (
    .clk_i       (clk_i),
    .rst_ni      (rst_isolate_ni),
    .slv_req_i   (l2_frontend_axi_req_i),
    .slv_resp_o  (l2_frontend_axi_resp_o),
    .mst_req_o   (l2_frontend_axi_isolated_req),
    .mst_resp_i  (l2_frontend_axi_isolated_resp),
    .isolate_i   (cluster_boundary_isolate),
    .isolated_o  (l2_frontend_isolated)
  );

  // MMIO master AXI isolation (CPU = slave side, external fabric = master side)
  axi_isolate #(
    .NumPending          (4),
    .TerminateTransaction(1'b1),    // terminate MMIO in case of x prop issues during reset
    .AtopSupport         (1'b0),
    .AxiAddrWidth        (smc_pkg::AXI_ADDR_WIDTH),
    .AxiDataWidth        (smc_pkg::AXI_DATA_WIDTH),
    .AxiIdWidth          (smc_pkg::SMC_CPU_MMIO_AXI_ID_WIDTH),
    .AxiUserWidth        (smc_pkg::AXI_USER_WIDTH),
    .axi_req_t           (smc_pkg::smc_cpu_mmio_axi_req_t),
    .axi_resp_t          (smc_pkg::smc_cpu_mmio_axi_resp_t)
  ) u_mmio_axi_isolate (
    .clk_i       (clk_i),
    .rst_ni      (rst_isolate_ni),
    .slv_req_i   (mmio_axi_cpu_req),
    .slv_resp_o  (mmio_axi_cpu_resp),
    .mst_req_o   (mmio_axi_req_o),
    .mst_resp_i  (mmio_axi_resp_i),
    .isolate_i   (cluster_boundary_isolate),
    .isolated_o  (mmio_isolated)
  );

  // Clamp the non-AXI status crossings to safe constants while isolated.
  assign wb_pc_valid_o = cluster_boundary_isolate ? '0 : wb_pc_valid_raw;
  assign wb_reg_pc_o   = cluster_boundary_isolate ? '0 : wb_reg_pc_raw;
  assign wdt_reset_o   = cluster_boundary_isolate ? '0 : wdt_reset_raw;

  // Cluster boundary fully isolated when both AXI paths have drained & isolated.
  assign drained_o = l2_frontend_isolated & mmio_isolated;

  // Core Reset Logic (Wait until init_mem_complete is asserted)

  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0] int_rst_core_n;
  logic [smc_4core_cpu_pkg::NUM_CPU_CORES-1:0] hart_reset_req;

  assign int_rst_core_n = {smc_4core_cpu_pkg::NUM_CPU_CORES{init_mem_complete}} & rst_core_ni & ~hart_reset_req;

  // ----------
  // Instantiate DigitalTop
  OCAH4CORECluster_DigitalTop u_digital_top (
    // Memory interfaces (outputs from DigitalTop)
    .rom_intf_req(rom_intf_req_o),
    .rom_intf_rsp(rom_intf_rsp_i),
    .scratch_ram_intf_req(scratch_ram_intf_req_pre_init),
    .scratch_ram_intf_rsp(scratch_ram_intf_rsp_pre_init),
    .l1_icache_tag_intf_req(l1_icache_tag_intf_req_o),
    .l1_icache_tag_intf_rsp(l1_icache_tag_intf_rsp_i),
    .l1_icache_data_intf_req(l1_icache_data_intf_req_o),
    .l1_icache_data_intf_rsp(l1_icache_data_intf_rsp_i),
    .l1_dcache_tag_intf_req(l1_dcache_tag_intf_req_o),
    .l1_dcache_tag_intf_rsp(l1_dcache_tag_intf_rsp_i),
    .l1_dcache_data_intf_req(l1_dcache_data_intf_req_o),
    .l1_dcache_data_intf_rsp(l1_dcache_data_intf_rsp_i),

    // Status outputs
    .o_io_errors_uncorrectable_valid(io_errors_uncorrectable_valid),
    .o_uncorrectable_2(uncorrectable_2),
    .o_wb_pc_valid(wb_pc_valid_raw),
    .o_wb_reg_pc(wb_reg_pc_raw),

    // Clock and reset domains
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_uncore_clock(clk_i),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_uncore_reset(~rst_uncore_ni),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_3_clock(clk_i),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_3_reset(~int_rst_core_n[3]),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_2_clock(clk_i),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_2_reset(~int_rst_core_n[2]),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_1_clock(clk_i),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_1_reset(~int_rst_core_n[1]),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_0_clock(clk_i),
    .auto_chipyard_prcictrl_domain_resetSynchronizer_in_member_allClocks_core_0_reset(~int_rst_core_n[0]),

    // Clock outputs
    .auto_cbus_fixedClockNode_anon_out_clock(), // unused
    .auto_cbus_fixedClockNode_anon_out_reset(), // unused
    .auto_fbus_fixedClockNode_anon_out_clock(), // unused
    .auto_sbus_fixedClockNode_anon_out_clock(), // unused

    // Reset control
    .resetctrl_hartResetReq_3 (hart_reset_req[3]),
    .resetctrl_hartResetReq_2 (hart_reset_req[2]),
    .resetctrl_hartResetReq_1 (hart_reset_req[1]),
    .resetctrl_hartResetReq_0 (hart_reset_req[0]),
    .resetctrl_hartIsInReset_3(~int_rst_core_n[3]),
    .resetctrl_hartIsInReset_2(~int_rst_core_n[2]),
    .resetctrl_hartIsInReset_1(~int_rst_core_n[1]),
    .resetctrl_hartIsInReset_0(~int_rst_core_n[0]),

    // WDT reset control
    .wdt_0_corerst(~int_rst_core_n[0]),
    .wdt_0_rst    (wdt_reset_raw[0]),
    .wdt_1_corerst(~int_rst_core_n[1]),
    .wdt_1_rst    (wdt_reset_raw[1]),
    .wdt_2_corerst(~int_rst_core_n[2]),
    .wdt_2_rst    (wdt_reset_raw[2]),
    .wdt_3_corerst(~int_rst_core_n[3]),
    .wdt_3_rst    (wdt_reset_raw[3]),

    // Debug interface
    .debug_clock(gated_debug_clock),
    .debug_reset(~rst_debug_ni),
    .debug_dmactive(debug_dmactive),
    .debug_dmactiveAck(debug_dmactiveAck),

    .debug_systemjtag_jtag_TCK(smc_cpu_jtag_TCK_i),
    .debug_systemjtag_jtag_TMS(smc_cpu_jtag_TMS_i),
    .debug_systemjtag_jtag_TDI(smc_cpu_jtag_TDI_i),
    .debug_systemjtag_jtag_TDO_data(smc_cpu_jtag_TDO_data_o),
    .debug_systemjtag_reset(smc_cpu_jtag_reset_i),
    .debug_systemjtag_mfr_id(smc_cpu_jtag_mfr_id_i),
    .debug_systemjtag_part_number(smc_cpu_jtag_part_number_i),
    .debug_systemjtag_version(smc_cpu_jtag_version_i),

    // MMIO AXI interface (outputs from DigitalTop)
    .mmio_axi4_0_aw_ready(mmio_axi_cpu_resp.aw_ready),
    .mmio_axi4_0_aw_valid(mmio_axi_cpu_req.aw_valid),
    .mmio_axi4_0_aw_bits_id(mmio_axi_cpu_req.aw.id),
    .mmio_axi4_0_aw_bits_addr(mmio_axi_cpu_req.aw.addr),
    .mmio_axi4_0_aw_bits_len(mmio_axi_cpu_req.aw.len),
    .mmio_axi4_0_aw_bits_size(mmio_axi_cpu_req.aw.size),
    .mmio_axi4_0_aw_bits_burst(mmio_axi_cpu_req.aw.burst),
    .mmio_axi4_0_aw_bits_lock(mmio_axi_cpu_req.aw.lock),
    .mmio_axi4_0_aw_bits_cache(mmio_aw_cache_raw),
    .mmio_axi4_0_aw_bits_prot(mmio_axi_cpu_req.aw.prot),
    .mmio_axi4_0_aw_bits_qos(mmio_axi_cpu_req.aw.qos),
    .mmio_axi4_0_w_ready(mmio_axi_cpu_resp.w_ready),
    .mmio_axi4_0_w_valid(mmio_axi_cpu_req.w_valid),
    .mmio_axi4_0_w_bits_data(mmio_axi_cpu_req.w.data),
    .mmio_axi4_0_w_bits_strb(mmio_axi_cpu_req.w.strb),
    .mmio_axi4_0_w_bits_last(mmio_axi_cpu_req.w.last),
    .mmio_axi4_0_b_ready(mmio_axi_cpu_req.b_ready),
    .mmio_axi4_0_b_valid(mmio_axi_cpu_resp.b_valid),
    .mmio_axi4_0_b_bits_id(mmio_axi_cpu_resp.b.id),
    .mmio_axi4_0_b_bits_resp(mmio_axi_cpu_resp.b.resp),
    .mmio_axi4_0_ar_ready(mmio_axi_cpu_resp.ar_ready),
    .mmio_axi4_0_ar_valid(mmio_axi_cpu_req.ar_valid),
    .mmio_axi4_0_ar_bits_id(mmio_axi_cpu_req.ar.id),
    .mmio_axi4_0_ar_bits_addr(mmio_axi_cpu_req.ar.addr),
    .mmio_axi4_0_ar_bits_len(mmio_axi_cpu_req.ar.len),
    .mmio_axi4_0_ar_bits_size(mmio_axi_cpu_req.ar.size),
    .mmio_axi4_0_ar_bits_burst(mmio_axi_cpu_req.ar.burst),
    .mmio_axi4_0_ar_bits_lock(mmio_axi_cpu_req.ar.lock),
    .mmio_axi4_0_ar_bits_cache(mmio_ar_cache_raw),
    .mmio_axi4_0_ar_bits_prot(mmio_axi_cpu_req.ar.prot),
    .mmio_axi4_0_ar_bits_qos(mmio_axi_cpu_req.ar.qos),
    .mmio_axi4_0_r_ready(mmio_axi_cpu_req.r_ready),
    .mmio_axi4_0_r_valid(mmio_axi_cpu_resp.r_valid),
    .mmio_axi4_0_r_bits_id(mmio_axi_cpu_resp.r.id),
    .mmio_axi4_0_r_bits_data(mmio_axi_cpu_resp.r.data),
    .mmio_axi4_0_r_bits_resp(mmio_axi_cpu_resp.r.resp),
    .mmio_axi4_0_r_bits_last(mmio_axi_cpu_resp.r.last),

    // L2 Frontend Bus AXI interface (inputs to DigitalTop) - using isolated signals
    .l2_frontend_bus_axi4_0_aw_ready(l2_frontend_axi_isolated_resp.aw_ready),
    .l2_frontend_bus_axi4_0_aw_valid(l2_frontend_axi_isolated_req.aw_valid),
    .l2_frontend_bus_axi4_0_aw_bits_id(l2_frontend_axi_isolated_req.aw.id),
    .l2_frontend_bus_axi4_0_aw_bits_addr({24'b0, l2_frontend_axi_isolated_req.aw.addr}),
    .l2_frontend_bus_axi4_0_aw_bits_len(l2_frontend_axi_isolated_req.aw.len),
    .l2_frontend_bus_axi4_0_aw_bits_size(l2_frontend_axi_isolated_req.aw.size),
    .l2_frontend_bus_axi4_0_aw_bits_burst(l2_frontend_axi_isolated_req.aw.burst),
    .l2_frontend_bus_axi4_0_aw_bits_lock(l2_frontend_axi_isolated_req.aw.lock),
    .l2_frontend_bus_axi4_0_aw_bits_cache(l2_frontend_axi_isolated_req.aw.cache),
    .l2_frontend_bus_axi4_0_aw_bits_prot(l2_frontend_axi_isolated_req.aw.prot),
    .l2_frontend_bus_axi4_0_aw_bits_qos(l2_frontend_axi_isolated_req.aw.qos),
    .l2_frontend_bus_axi4_0_w_ready(l2_frontend_axi_isolated_resp.w_ready),
    .l2_frontend_bus_axi4_0_w_valid(l2_frontend_axi_isolated_req.w_valid),
    .l2_frontend_bus_axi4_0_w_bits_data(l2_frontend_axi_isolated_req.w.data),
    .l2_frontend_bus_axi4_0_w_bits_strb(l2_frontend_axi_isolated_req.w.strb),
    .l2_frontend_bus_axi4_0_w_bits_last(l2_frontend_axi_isolated_req.w.last),
    .l2_frontend_bus_axi4_0_b_ready(l2_frontend_axi_isolated_req.b_ready),
    .l2_frontend_bus_axi4_0_b_valid(l2_frontend_axi_isolated_resp.b_valid),
    .l2_frontend_bus_axi4_0_b_bits_id(l2_frontend_axi_isolated_resp.b.id),
    .l2_frontend_bus_axi4_0_b_bits_resp(l2_frontend_axi_isolated_resp.b.resp),
    .l2_frontend_bus_axi4_0_ar_ready(l2_frontend_axi_isolated_resp.ar_ready),
    .l2_frontend_bus_axi4_0_ar_valid(l2_frontend_axi_isolated_req.ar_valid),
    .l2_frontend_bus_axi4_0_ar_bits_id(l2_frontend_axi_isolated_req.ar.id),
    .l2_frontend_bus_axi4_0_ar_bits_addr({24'b0, l2_frontend_axi_isolated_req.ar.addr}),
    .l2_frontend_bus_axi4_0_ar_bits_len(l2_frontend_axi_isolated_req.ar.len),
    .l2_frontend_bus_axi4_0_ar_bits_size(l2_frontend_axi_isolated_req.ar.size),
    .l2_frontend_bus_axi4_0_ar_bits_burst(l2_frontend_axi_isolated_req.ar.burst),
    .l2_frontend_bus_axi4_0_ar_bits_lock(l2_frontend_axi_isolated_req.ar.lock),
    .l2_frontend_bus_axi4_0_ar_bits_cache(l2_frontend_axi_isolated_req.ar.cache),
    .l2_frontend_bus_axi4_0_ar_bits_prot(l2_frontend_axi_isolated_req.ar.prot),
    .l2_frontend_bus_axi4_0_ar_bits_qos(l2_frontend_axi_isolated_req.ar.qos),
    .l2_frontend_bus_axi4_0_r_ready(l2_frontend_axi_isolated_req.r_ready),
    .l2_frontend_bus_axi4_0_r_valid(l2_frontend_axi_isolated_resp.r_valid),
    .l2_frontend_bus_axi4_0_r_bits_id(l2_frontend_axi_isolated_resp.r.id),
    .l2_frontend_bus_axi4_0_r_bits_data(l2_frontend_axi_isolated_resp.r.data),
    .l2_frontend_bus_axi4_0_r_bits_resp(l2_frontend_axi_isolated_resp.r.resp),
    .l2_frontend_bus_axi4_0_r_bits_last(l2_frontend_axi_isolated_resp.r.last),

    // Reset vectors
    .reset_vector_0(reset_vector_i[0]),
    .reset_vector_1(reset_vector_i[1]),
    .reset_vector_2(reset_vector_i[2]),
    .reset_vector_3(reset_vector_i[3]),

    // Interrupts
    .interrupts(interrupts_i)
  );

  // MMIO CPU-side struct completion (feeds the isolate slave port)
  assign mmio_axi_cpu_req.aw.region = axi_pkg::region_t'(0);
  assign mmio_axi_cpu_req.aw.atop   = axi_pkg::atop_t'(0);
  assign mmio_axi_cpu_req.aw.user   = smc_pkg::smc_cpu_mmio_axi_id_t'(0);
  assign mmio_axi_cpu_req.w.user    = smc_pkg::smc_cpu_mmio_axi_id_t'(0);
  assign mmio_axi_cpu_req.ar.region = axi_pkg::region_t'(0);
  assign mmio_axi_cpu_req.ar.user   = smc_pkg::smc_cpu_mmio_axi_id_t'(0);
  // Force modifiable bit (AXCACHE[1]) for CPU-originated MMIO transactions
  assign mmio_axi_cpu_req.aw.cache  = mmio_aw_cache_raw | axi_pkg::CACHE_MODIFIABLE;
  assign mmio_axi_cpu_req.ar.cache  = mmio_ar_cache_raw | axi_pkg::CACHE_MODIFIABLE;

  // Connect unconnected L2 Frontend AXI response signals to safe defaults
  // These are signals that should be driven by DigitalTop but aren't connected to ports
  assign l2_frontend_axi_isolated_resp.b.user = smc_pkg::smc_cpu_l2_frontend_axi_id_t'(0);  // No user data
  assign l2_frontend_axi_isolated_resp.r.user = smc_pkg::smc_cpu_l2_frontend_axi_id_t'(0);  // No user data

  // RAM initialization

  always_ff @(posedge clk_i or negedge mem_init_reset_ni) begin
    if (!mem_init_reset_ni) begin
      state             <= MEM_ZERO_IDLE;
      zero_addr         <= '0;
      init_mem_complete <= 1'b0;
    end else begin
      state <= nxt_state;
      zero_addr <= next_zero_addr;
      init_mem_complete <= nxt_init_mem_complete;
    end
  end

  always_comb begin
    nxt_state = state;
    next_zero_addr = zero_addr;
    nxt_init_mem_complete = init_mem_complete;
    init_mem_enable = 1'b0;
    unique case (state)
      MEM_ZERO_IDLE: begin
        if (disable_sram_auto_init_i) begin
          nxt_state = MEM_ZERO_DONE;
        end else begin
          nxt_state = MEM_ZERO_BUSY;
          next_zero_addr = '0;
        end
      end
      MEM_ZERO_BUSY: begin
        if (disable_sram_auto_init_i) begin
          nxt_state = MEM_ZERO_DONE;
          init_mem_enable = 1'b0;
        end else begin
          init_mem_enable = 1'b1;
          if (&zero_addr) begin
            nxt_state = MEM_ZERO_DONE;
            nxt_init_mem_complete = 1'b1;
          end else begin
            next_zero_addr = zero_addr + chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH'(1);
          end
        end
      end
      MEM_ZERO_DONE: begin
        // Terminal State
        nxt_init_mem_complete = 1'b1;
        nxt_state = MEM_ZERO_DONE;
      end
      default: begin
        nxt_state = MEM_ZERO_IDLE;
      end
    endcase
  end

  for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_SRAM_BANKS; i++) begin : gen_scratch_rams
    // When PRST is de-asserted, we initialize the SMC scratch with all zeroes
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH-1:0] muxed_addr;
    logic [chipyard_4core_mem_pkg::SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] muxed_wdata;
    logic muxed_en;
    logic muxed_wmode;

    assign muxed_addr = init_mem_complete ? scratch_ram_intf_req_pre_init[i].addr : zero_addr;
    assign muxed_wdata = init_mem_complete ? scratch_ram_intf_req_pre_init[i].wdata : '0;
    assign muxed_en = init_mem_complete ? scratch_ram_intf_req_pre_init[i].en : init_mem_enable;
    assign muxed_wmode = init_mem_complete ? scratch_ram_intf_req_pre_init[i].wmode : 1'b1;

    assign scratch_ram_intf_req_o[i].addr         = muxed_addr;
    assign scratch_ram_intf_req_o[i].clk          = scratch_ram_intf_req_pre_init[i].clk;
    assign scratch_ram_intf_req_o[i].wdata        = muxed_wdata;
    assign scratch_ram_intf_rsp_pre_init[i].rdata = scratch_ram_intf_rsp_i[i].rdata;
    assign scratch_ram_intf_req_o[i].en           = muxed_en;
    assign scratch_ram_intf_req_o[i].wmode        = muxed_wmode;
    assign scratch_ram_intf_req_o[i].wmask        = scratch_ram_intf_req_pre_init[i].wmask;
  end

  assign init_mem_done_o = init_mem_complete;

`ifndef SYNTHESIS
  initial begin
    wait (mem_init_reset_ni == 1'b0);
    $display("%m: Initializing SMC Scratch Ram Banks (write zeros)");
    wait (init_mem_complete);
    $display("%m: Initializing complete");
  end
`endif

endmodule

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMC CPU Wrapper

module smc_cpu_wrapper #(
  parameter bit                       NO_ADDR_REMAP  = 1'b1,

  // Memory-interface types (cannot be localparams)
  parameter type rom_req_t            = chipyard_4core_mem_pkg::rom_req_t,
  parameter type rom_rsp_t            = chipyard_4core_mem_pkg::rom_rsp_t,
  parameter type scratch_ram_req_t    = chipyard_4core_mem_pkg::scratch_ram_req_t,
  parameter type scratch_ram_rsp_t    = chipyard_4core_mem_pkg::scratch_ram_rsp_t,
  parameter type l1_icache_tag_req_t  = chipyard_4core_mem_pkg::l1_icache_tag_req_t,
  parameter type l1_icache_tag_rsp_t  = chipyard_4core_mem_pkg::l1_icache_tag_rsp_t,
  parameter type l1_icache_data_req_t = chipyard_4core_mem_pkg::l1_icache_data_req_t,
  parameter type l1_icache_data_rsp_t = chipyard_4core_mem_pkg::l1_icache_data_rsp_t,
  parameter type l1_dcache_tag_req_t  = chipyard_4core_mem_pkg::l1_dcache_tag_req_t,
  parameter type l1_dcache_tag_rsp_t  = chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t,
  parameter type l1_dcache_data_req_t = chipyard_4core_mem_pkg::l1_dcache_data_req_t,
  parameter type l1_dcache_data_rsp_t = chipyard_4core_mem_pkg::l1_dcache_data_rsp_t,

  localparam int unsigned NUM_CPU_CORES      = smc_4core_cpu_pkg::NUM_CPU_CORES,
  localparam int unsigned NUM_CPU_INTERRUPTS = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,

  localparam int unsigned NUM_SRAM_BANKS        = chipyard_4core_mem_pkg::NUM_SRAM_BANKS,
  localparam int unsigned NUM_ICACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS,
  localparam int unsigned NUM_ICACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS,
  localparam int unsigned NUM_DCACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS,
  localparam int unsigned NUM_DCACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS

) (
  // Clocks and resets
  input  wire logic clk_i,
  input  wire logic clk_ref_i,
  input  wire logic rst_isolate_ni,
  input  wire logic rst_primary_smc_clk_ni,
  input  wire logic rst_warm_smc_clk_ni,
  input  wire logic fuse_reset_ni,
  input  wire logic scan_rst_ni,

  input  wire logic chiplet_is_primary_i,

  // AXI front port from smc_fabric (local crossbar to CPU L2 frontend and
  // the cpu_ctrl register block, demuxed by address below)
  input  wire smc_pkg::smc_local_32_64_8_12_axi_req_t axi_front_port_req_i,
  output smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_front_port_resp_o,

  // AXI MMIO port to smc_fabric (CPU MMIO master)
  output smc_pkg::smc_cpu_mmio_axi_req_t       axi_mmio_port_req_o,
  input  wire smc_pkg::smc_cpu_mmio_axi_resp_t axi_mmio_port_resp_i,

  // Interrupts from smc_base
  input  wire logic [NUM_CPU_INTERRUPTS-1:0] interrupts_i,

  // CPU status signals consumed in smc_base
  output logic [NUM_CPU_CORES-1:0][57:0] wb_reg_pc_o,
  output logic [NUM_CPU_CORES-1:0]       wdt_timeout_cluster_o,
  output logic                           wdt_second_timeout_o,

  // DED output
  output logic cluster_ded_o,

  // CPU Memory Signals
  output rom_req_t            rom_intf_req_o,
  input  rom_rsp_t            rom_intf_rsp_i,
  output scratch_ram_req_t    scratch_ram_intf_req_o [NUM_SRAM_BANKS-1:0],
  input  scratch_ram_rsp_t    scratch_ram_intf_rsp_i [NUM_SRAM_BANKS-1:0],
  output l1_icache_tag_req_t  l1_icache_tag_intf_req_o [NUM_ICACHE_TAG_BANKS-1:0],
  input  l1_icache_tag_rsp_t  l1_icache_tag_intf_rsp_i [NUM_ICACHE_TAG_BANKS-1:0],
  output l1_icache_data_req_t l1_icache_data_intf_req_o [NUM_ICACHE_DATA_BANKS-1:0],
  input  l1_icache_data_rsp_t l1_icache_data_intf_rsp_i [NUM_ICACHE_DATA_BANKS-1:0],
  output l1_dcache_tag_req_t  l1_dcache_tag_intf_req_o [NUM_DCACHE_TAG_BANKS-1:0],
  input  l1_dcache_tag_rsp_t  l1_dcache_tag_intf_rsp_i [NUM_DCACHE_TAG_BANKS-1:0],
  output l1_dcache_data_req_t l1_dcache_data_intf_req_o [NUM_DCACHE_DATA_BANKS-1:0],
  input  l1_dcache_data_rsp_t l1_dcache_data_intf_rsp_i [NUM_DCACHE_DATA_BANKS-1:0],

  input  wire logic disable_sram_auto_init_i,
  output logic      init_mem_done_o,

  // ROM Flip Endianness
  input  wire logic rom_flip_endianness_i,

  // Test mode
  input  wire logic test_en_i,

  // CPU Debug interfaces (JTAG)
  input  wire logic        smc_cpu_jtag_TCK_i,
  input  wire logic        smc_cpu_jtag_TMS_i,
  input  wire logic        smc_cpu_jtag_TDI_i,
  output logic             smc_cpu_jtag_TDO_data_o,
  input  wire logic        smc_cpu_jtag_reset_i,
  input  wire logic [10:0] smc_cpu_jtag_mfr_id_i,
  input  wire logic [15:0] smc_cpu_jtag_part_number_i,
  input  wire logic [3:0]  smc_cpu_jtag_version_i
);

  /////////////////////////
  // Internal Reset Nets //
  /////////////////////////

  // Reset / drain-handshake / status nets between cpu_ctrl_wrap and the CPU cluster
  logic                            cluster_uncore_reset_n;
  logic [NUM_CPU_CORES-1:0]        core_reset_n;
  logic                            debug_reset_n;
  logic                            isolate_req;
  logic                            drained;
  logic [NUM_CPU_CORES-1:0][55:0]  core_reset_vector;
  logic [NUM_CPU_CORES-1:0]        wb_pc_valid;
  logic [NUM_CPU_CORES-1:0][57:0]  wb_reg_pc;
  logic [NUM_CPU_CORES-1:0]        wdt_timeout_cluster;

  assign wb_reg_pc_o           = wb_reg_pc;
  assign wdt_timeout_cluster_o = wdt_timeout_cluster;

  /////////////////////////
  // Front Port Demux    //
  /////////////////////////

  // The front port carries both the L2-frontend window and the cpu_ctrl CSR
  // window. Peel cpu_ctrl off by address and convert it to AXI-Lite for the
  // register block; everything else goes to the CPU cluster.
  localparam bit FrontPortCluster = 1'b0;
  localparam bit FrontPortCpuCtrl = 1'b1;

  smc_pkg::smc_local_32_64_8_12_axi_req_t  [1:0] front_port_demux_req;
  smc_pkg::smc_local_32_64_8_12_axi_resp_t [1:0] front_port_demux_resp;
  logic front_port_aw_select;
  logic front_port_ar_select;

  smc_pkg::smc_axil_32_64_req_t  axil_cpu_ctrl_req;
  smc_pkg::smc_axil_32_64_resp_t axil_cpu_ctrl_resp;

  always_comb begin
    // Default to the CPU cluster (L2 frontend)
    front_port_aw_select = FrontPortCluster;
    front_port_ar_select = FrontPortCluster;
    // Check if address matches the cpu_ctrl CSR window
    if (axi_front_port_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR &&
            axi_front_port_req_i.aw.addr <  smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR +
                                            smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SIZE) begin
      front_port_aw_select = FrontPortCpuCtrl;
    end
    if (axi_front_port_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR &&
            axi_front_port_req_i.ar.addr <  smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR +
                                            smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SIZE) begin
      front_port_ar_select = FrontPortCpuCtrl;
    end
  end

  axi_demux #(
    .AxiIdWidth  (smc_pkg::SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (smc_pkg::smc_local_32_64_8_12_axi_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_local_32_64_8_12_axi_w_chan_t),
    .b_chan_t    (smc_pkg::smc_local_32_64_8_12_axi_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_local_32_64_8_12_axi_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_local_32_64_8_12_axi_r_chan_t),
    .axi_req_t   (smc_pkg::smc_local_32_64_8_12_axi_req_t),
    .axi_resp_t  (smc_pkg::smc_local_32_64_8_12_axi_resp_t),
    .NoMstPorts  (2),
    .MaxTrans    (smc_pkg::FABRIC_MAX_TRANS),
    .AxiLookBits (smc_pkg::FABRIC_ID_LOOKUP_BITS)
  ) u_front_port_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_primary_smc_clk_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'b00),
    .slv_req_i       (axi_front_port_req_i),
    .slv_aw_select_i (front_port_aw_select),
    .slv_ar_select_i (front_port_ar_select),
    .slv_resp_o      (axi_front_port_resp_o),
    .mst_reqs_o      (front_port_demux_req),
    .mst_resps_i     (front_port_demux_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
    .AxiDataWidth    (smc_pkg::AXI_DATA_WIDTH),
    .AxiIdWidth      (smc_pkg::SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH),
    .AxiUserWidth    (smc_pkg::AXI_USER_WIDTH),
    .AxiMaxWriteTxns (2),
    .AxiMaxReadTxns  (2),
    .full_req_t      (smc_pkg::smc_local_32_64_8_12_axi_req_t),
    .full_resp_t     (smc_pkg::smc_local_32_64_8_12_axi_resp_t),
    .lite_req_t      (smc_pkg::smc_axil_32_64_req_t),
    .lite_resp_t     (smc_pkg::smc_axil_32_64_resp_t)
  ) u_cpu_ctrl_axi_to_axi_lite (
    .clk_i      (clk_i),
    .rst_ni     (rst_primary_smc_clk_ni),
    .test_i     (test_en_i),
    .slv_req_i  (front_port_demux_req[FrontPortCpuCtrl]),
    .slv_resp_o (front_port_demux_resp[FrontPortCpuCtrl]),
    .mst_req_o  (axil_cpu_ctrl_req),
    .mst_resp_i (axil_cpu_ctrl_resp)
  );

  /////////////////////
  // SMC CPU Control //
  /////////////////////

  smc_cpu_ctrl_wrap #(
    .NO_ADDR_REMAP   (NO_ADDR_REMAP),
    .NumCPUCores     (NUM_CPU_CORES)
  ) u_smc_cpu_ctrl_wrap (
    .clk_ref_i                          (clk_ref_i),
    .clk_smc_i                          (clk_i),

    .rst_warm_smc_clk_ni                (rst_warm_smc_clk_ni),
    .rst_primary_ni                     (rst_primary_smc_clk_ni),

    .test_en_i                          (test_en_i),
    .scan_rst_ni                        (scan_rst_ni),

    .axil_req_i                         (axil_cpu_ctrl_req),
    .axil_resp_o                        (axil_cpu_ctrl_resp),

    .wb_reg_pc_i                        (wb_reg_pc),
    .wb_pc_valid_i                      (wb_pc_valid),
    .wdt_timeout_cluster_i              (wdt_timeout_cluster),
    .chiplet_is_primary_i               (chiplet_is_primary_i),
    .wdt_second_timeout_o               (wdt_second_timeout_o),

    .core_reset_n_n0_scan_o             (core_reset_n),
    .core_reset_vector_o                (core_reset_vector),
    .cluster_uncore_reset_n_n0_scan_o   (cluster_uncore_reset_n),
    .isolate_req_o                      (isolate_req),
    .drained_i                          (drained),
    .debug_reset_n_o                    (debug_reset_n)
  );

  /////////////
  // SMC CPU //
  /////////////

    chipyard_4core_mem_pkg::rom_tilelink_req_t rom_tilelink_intf_req;
    chipyard_4core_mem_pkg::rom_tilelink_rsp_t rom_tilelink_intf_rsp;

    smc_4core_cpu u_smc_cpu (
      .clk_i                        (clk_i),
      .rst_isolate_ni               (rst_isolate_ni),

      .mem_init_reset_ni            (fuse_reset_ni),

      .rst_uncore_ni                (cluster_uncore_reset_n),
      .rst_core_ni                  (core_reset_n),
      .rst_debug_ni                 (debug_reset_n),
      .isolate_req_i                (isolate_req),
      .drained_o                    (drained),

      .reset_vector_i               (core_reset_vector),
      .interrupts_i                 (interrupts_i),

      .mmio_axi_req_o               (axi_mmio_port_req_o),
      .mmio_axi_resp_i              (axi_mmio_port_resp_i),

      .l2_frontend_axi_req_i        (front_port_demux_req[FrontPortCluster]),
      .l2_frontend_axi_resp_o       (front_port_demux_resp[FrontPortCluster]),

      .smc_cpu_jtag_TCK_i           (smc_cpu_jtag_TCK_i),
      .smc_cpu_jtag_TMS_i           (smc_cpu_jtag_TMS_i),
      .smc_cpu_jtag_TDI_i           (smc_cpu_jtag_TDI_i),
      .smc_cpu_jtag_TDO_data_o      (smc_cpu_jtag_TDO_data_o),
      .smc_cpu_jtag_reset_i         (smc_cpu_jtag_reset_i),
      .smc_cpu_jtag_mfr_id_i        (smc_cpu_jtag_mfr_id_i),
      .smc_cpu_jtag_part_number_i   (smc_cpu_jtag_part_number_i),
      .smc_cpu_jtag_version_i       (smc_cpu_jtag_version_i),

      .cluster_ded_o                (cluster_ded_o),
      .wb_pc_valid_o                (wb_pc_valid),
      .wb_reg_pc_o                  (wb_reg_pc),
      .wdt_reset_o                  (wdt_timeout_cluster),

      .rom_intf_req_o               (rom_tilelink_intf_req),
      .rom_intf_rsp_i               (rom_tilelink_intf_rsp),
      .scratch_ram_intf_req_o       (scratch_ram_intf_req_o),
      .scratch_ram_intf_rsp_i       (scratch_ram_intf_rsp_i),
      .l1_icache_tag_intf_req_o     (l1_icache_tag_intf_req_o),
      .l1_icache_tag_intf_rsp_i     (l1_icache_tag_intf_rsp_i),
      .l1_icache_data_intf_req_o    (l1_icache_data_intf_req_o),
      .l1_icache_data_intf_rsp_i    (l1_icache_data_intf_rsp_i),
      .l1_dcache_tag_intf_req_o     (l1_dcache_tag_intf_req_o),
      .l1_dcache_tag_intf_rsp_i     (l1_dcache_tag_intf_rsp_i),
      .l1_dcache_data_intf_req_o    (l1_dcache_data_intf_req_o),
      .l1_dcache_data_intf_rsp_i    (l1_dcache_data_intf_rsp_i),

      .disable_sram_auto_init_i     (disable_sram_auto_init_i),
      .init_mem_done_o              (init_mem_done_o),

      .test_en_i                    (test_en_i)
    );

    // Convert ROM tilelink req to generic memory interface req

    tilelink_to_rom_mem #(
      .ADDR_WIDTH(14),
      .WORD_WIDTH(64)
    ) u_tilelink_to_rom_memory_convert (
      .clk_i(rom_tilelink_intf_req.clock),
      .rst_i(rom_tilelink_intf_req.reset),

      .auto_in_a_ready(rom_tilelink_intf_rsp.a_ready),

      .auto_in_a_valid(rom_tilelink_intf_req.a_valid),
      .auto_in_a_bits_size(rom_tilelink_intf_req.a_bits_size),
      .auto_in_a_bits_source(rom_tilelink_intf_req.a_bits_source),
      .auto_in_a_bits_address(rom_tilelink_intf_req.a_bits_address),
      .auto_in_d_ready(rom_tilelink_intf_req.d_ready),

      .auto_in_d_valid(rom_tilelink_intf_rsp.d_valid),
      .auto_in_d_bits_size(rom_tilelink_intf_rsp.d_bits_size),
      .auto_in_d_bits_source(rom_tilelink_intf_rsp.d_bits_source),
      .auto_in_d_bits_data(rom_tilelink_intf_rsp.d_bits_data),

      .rom_flip_endianness_i(rom_flip_endianness_i),

      .rom_address_o(rom_intf_req_o.addr),
      .mem_chip_en_o(rom_intf_req_o.en),
      .rom_bank_data_i(rom_intf_rsp_i.rdata)
    );

    // Connect ROM memory interface signals
    assign rom_intf_req_o.clk = clk_i;
    assign rom_intf_req_o.wdata = '0;          // ROM is read-only
    assign rom_intf_req_o.wmode = 1'b0;        // Read mode
    assign rom_intf_req_o.wmask = '0;          // No write mask

endmodule

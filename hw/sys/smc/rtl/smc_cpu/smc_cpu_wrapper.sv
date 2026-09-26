// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the four-core SMC CPU cluster with its cpu_ctrl register block and boot ROM bridge.
//
// Splits the fabric AXI front port by address between the cluster L2 frontend and cpu_ctrl,
// which it reaches through an AXI-to-AXI-Lite converter; the cluster MMIO master goes back out.
// Surfaces per-core PC, WDT, and cluster error status back to smc_base.
// Converts the cluster boot ROM TileLink port to the ROM memory interface, and exposes the
// scratch RAM and L1 cache bank interfaces; the memories themselves are outside this module.

module smc_cpu_wrapper #(
  parameter bit                       NO_ADDR_REMAP  = 1'b1,  // Reported by cpu_ctrl in
                                                              // SMC_ATTRIBUTES.no_output_remap;
                                                              // no other effect in this module.

  parameter type rom_req_t            = chipyard_4core_mem_pkg::rom_req_t,  // Boot ROM request type for
                                                                            // rom_intf_req_o.
  parameter type rom_rsp_t            = chipyard_4core_mem_pkg::rom_rsp_t,  // Boot ROM response type for
                                                                            // rom_intf_rsp_i.
  parameter type scratch_ram_req_t    = chipyard_4core_mem_pkg::scratch_ram_req_t,  // Scratch RAM bank request type
                                                                                    // for scratch_ram_intf_req_o.
  parameter type scratch_ram_rsp_t    = chipyard_4core_mem_pkg::scratch_ram_rsp_t,  // Scratch RAM bank response type
                                                                                    // for scratch_ram_intf_rsp_i.
  parameter type l1_icache_tag_req_t  = chipyard_4core_mem_pkg::l1_icache_tag_req_t,  // Instruction-cache tag bank
                                                                                      // request type.
  parameter type l1_icache_tag_rsp_t  = chipyard_4core_mem_pkg::l1_icache_tag_rsp_t,  // Instruction-cache tag bank
                                                                                      // response type.
  parameter type l1_icache_data_req_t = chipyard_4core_mem_pkg::l1_icache_data_req_t,  // Instruction-cache data bank
                                                                                       // request type.
  parameter type l1_icache_data_rsp_t = chipyard_4core_mem_pkg::l1_icache_data_rsp_t,  // Instruction-cache data bank
                                                                                       // response type.
  parameter type l1_dcache_tag_req_t  = chipyard_4core_mem_pkg::l1_dcache_tag_req_t,  // Data-cache tag bank request
                                                                                      // type.
  parameter type l1_dcache_tag_rsp_t  = chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t,  // Data-cache tag bank response
                                                                                      // type.
  parameter type l1_dcache_data_req_t = chipyard_4core_mem_pkg::l1_dcache_data_req_t,  // Data-cache data bank request
                                                                                       // type.
  parameter type l1_dcache_data_rsp_t = chipyard_4core_mem_pkg::l1_dcache_data_rsp_t,  // Data-cache data bank response
                                                                                       // type.

  localparam int unsigned NUM_CPU_CORES      = smc_4core_cpu_pkg::NUM_CPU_CORES,  // Number of cores in the cluster,
                                                                                  // from smc_4core_cpu_pkg; sizes
                                                                                  // the per-core PC and watchdog
                                                                                  // ports.
  localparam int unsigned NUM_CPU_INTERRUPTS = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,  // Number of interrupt lines into
                                                                                       // the cluster, from
                                                                                       // smc_4core_cpu_pkg.

  localparam int unsigned NUM_SRAM_BANKS        = chipyard_4core_mem_pkg::NUM_SRAM_BANKS,  // Number of scratch RAM banks;
                                                                                           // sizes the scratch RAM port
                                                                                           // arrays.
  localparam int unsigned NUM_ICACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS,  // Number of instruction-cache tag
                                                                                                 // banks; sizes the
                                                                                                 // instruction-cache tag port
                                                                                                 // arrays.
  localparam int unsigned NUM_ICACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS,  // Number of instruction-cache data
                                                                                                  // banks; sizes the
                                                                                                  // instruction-cache data port
                                                                                                  // arrays.
  localparam int unsigned NUM_DCACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS,  // Number of data-cache tag banks;
                                                                                                 // sizes the data-cache tag port
                                                                                                 // arrays.
  localparam int unsigned NUM_DCACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS  // Number of data-cache data banks;
                                                                                                 // sizes the data-cache data port
                                                                                                 // arrays.

) (
  input  wire logic clk_i,              // SMC core clock for the cluster, the front-port demux,
                                        // cpu_ctrl and the boot ROM interface.
  input  wire logic clk_ref_i,          // Reference clock for the cpu_ctrl reference counter.
  input  wire logic rst_isolate_ni,     // Active-low reset for the cluster-boundary AXI isolate
                                        // modules.
  input  wire logic rst_primary_smc_clk_ni,  // Active-low primary reset in the SMC clock domain for
                                             // the front-port demux, AXI-Lite converter and
                                             // cpu_ctrl.
  input  wire logic rst_warm_smc_clk_ni,  // Active-low warm reset in the SMC clock domain; holds
                                          // the cluster core and uncore resets asserted and
                                          // selects the default core reset vector.
  input  wire logic fuse_reset_ni,      // Active-low reset for the scratch RAM zero-fill sequencer;
                                        // its release starts the zero-fill.
  input  wire logic scan_rst_ni,        // Active-low scan reset, passed to cpu_ctrl, which does not
                                        // use it.

  input  wire logic chiplet_is_primary_i,  // High on the primary chiplet; reported by cpu_ctrl in
                                           // SMC_ATTRIBUTES.

  input  wire smc_pkg::smc_local_32_64_8_12_axi_req_t axi_front_port_req_i,  // Front-port AXI request
                                                                             // from the local fabric;
                                                                             // addresses in the
                                                                             // SMC_CPU_CTRL window go
                                                                             // to cpu_ctrl, all others
                                                                             // to the cluster L2
                                                                             // frontend.
  output smc_pkg::smc_local_32_64_8_12_axi_resp_t     axi_front_port_resp_o,  // Front-port AXI response
                                                                              // to the local fabric.

  output smc_pkg::smc_cpu_mmio_axi_req_t       axi_mmio_port_req_o,  // Cluster MMIO AXI master
                                                                     // request to the smc_fabric
                                                                     // input fabric.
  input  wire smc_pkg::smc_cpu_mmio_axi_resp_t axi_mmio_port_resp_i,  // Cluster MMIO AXI master
                                                                      // response from the
                                                                      // smc_fabric input fabric.

  input  wire logic [NUM_CPU_INTERRUPTS-1:0] interrupts_i,  // Interrupt vector from smc_base,
                                                            // passed unchanged to the cluster.

  output logic [NUM_CPU_CORES-1:0][57:0] wb_reg_pc_o,  // Per-core writeback program counter from
                                                       // the cluster, zero while the cluster
                                                       // boundary is isolated.
  output logic [NUM_CPU_CORES-1:0]       wdt_timeout_cluster_o,  // Per-core first-stage watchdog
                                                                 // timeout from the cluster, low
                                                                 // while the cluster boundary is
                                                                 // isolated.
  output logic                           wdt_second_timeout_o,  // Second-stage watchdog timeout
                                                                // from cpu_ctrl, registered on
                                                                // clk_i.

  output logic cluster_ded_o,           // Registered OR of the cluster's uncorrectable-error flags,
                                        // cleared while the cluster uncore reset is asserted.

  output rom_req_t            rom_intf_req_o,  // Boot ROM read request from the TileLink-to-ROM
                                               // bridge, clocked by clk_i, with the write
                                               // fields tied to zero.
  input  rom_rsp_t            rom_intf_rsp_i,  // Boot ROM read data for the TileLink-to-ROM bridge.
  output scratch_ram_req_t    scratch_ram_intf_req_o [NUM_SRAM_BANKS-1:0],  // Scratch RAM bank requests,
                                                                            // driven by the zero-fill
                                                                            // sequencer until the zero-fill
                                                                            // completes.
  input  scratch_ram_rsp_t    scratch_ram_intf_rsp_i [NUM_SRAM_BANKS-1:0],  // Scratch RAM bank read data.
  output l1_icache_tag_req_t  l1_icache_tag_intf_req_o [NUM_ICACHE_TAG_BANKS-1:0],  // Instruction-cache tag bank
                                                                                    // requests.
  input  l1_icache_tag_rsp_t  l1_icache_tag_intf_rsp_i [NUM_ICACHE_TAG_BANKS-1:0],  // Instruction-cache tag bank read
                                                                                    // data.
  output l1_icache_data_req_t l1_icache_data_intf_req_o [NUM_ICACHE_DATA_BANKS-1:0],  // Instruction-cache data bank
                                                                                      // requests.
  input  l1_icache_data_rsp_t l1_icache_data_intf_rsp_i [NUM_ICACHE_DATA_BANKS-1:0],  // Instruction-cache data bank read
                                                                                      // data.
  output l1_dcache_tag_req_t  l1_dcache_tag_intf_req_o [NUM_DCACHE_TAG_BANKS-1:0],  // Data-cache tag bank requests.
  input  l1_dcache_tag_rsp_t  l1_dcache_tag_intf_rsp_i [NUM_DCACHE_TAG_BANKS-1:0],  // Data-cache tag bank read data.
  output l1_dcache_data_req_t l1_dcache_data_intf_req_o [NUM_DCACHE_DATA_BANKS-1:0],  // Data-cache data bank requests.
  input  l1_dcache_data_rsp_t l1_dcache_data_intf_rsp_i [NUM_DCACHE_DATA_BANKS-1:0],  // Data-cache data bank read data.

  input  wire logic disable_sram_auto_init_i,  // High skips the scratch RAM zero-fill after
                                               // fuse_reset_ni releases.
  output logic      init_mem_done_o,    // High once the scratch RAM zero-fill has completed or been
                                        // skipped.

  input  wire logic rom_flip_endianness_i,  // High byte-reverses each ROM word returned to the
                                            // cluster.

  input  wire logic test_en_i,          // Scan test mode enable for the front-port demux, AXI-Lite
                                        // converter and cluster debug clock gate.

  input  wire logic        smc_cpu_jtag_TCK_i,  // JTAG test clock for the cluster debug transport
                                                // module.
  input  wire logic        smc_cpu_jtag_TMS_i,  // JTAG test mode select for the cluster debug
                                                // transport module.
  input  wire logic        smc_cpu_jtag_TDI_i,  // JTAG test data into the cluster debug transport
                                                // module.
  output logic             smc_cpu_jtag_TDO_data_o,  // JTAG test data out of the cluster debug
                                                     // transport module.
  input  wire logic        smc_cpu_jtag_reset_i,  // Active-high asynchronous reset of the cluster
                                                  // JTAG debug transport module (TAP) and of the
                                                  // debug module's DMI interface.
  input  wire logic [10:0] smc_cpu_jtag_mfr_id_i,  // Manufacturer ID reported in the cluster JTAG
                                                   // IDCODE.
  input  wire logic [15:0] smc_cpu_jtag_part_number_i,  // Part number reported in the cluster JTAG
                                                        // IDCODE.
  input  wire logic [3:0]  smc_cpu_jtag_version_i  // Version reported in the cluster JTAG IDCODE.
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
  logic                            isolate_flush;
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
    .isolate_flush_o                    (isolate_flush),
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
    .isolate_flush_i              (isolate_flush),

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

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP System CSRs

module sep_system_csr (
  input  logic clk_i,
  input  logic clk_ref_i,
  input  logic rst_ni,
  input  logic rst_warm_ni,
  input  logic test_en_i,
  input  logic scan_rst_ni,

  input  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  sep_system_csr_axil_req_i,
  output sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t sep_system_csr_axil_resp_o,

  // Alias Remap Register Interface
  output alias_remap_reg_pkg::alias_remap__out_t   local_masters_alias_remap_reg_ctrl_o [sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS-1:0],
  output output_remap_reg_pkg::output_remap__out_t ap_output_remap_reg_ctrl_o [sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS-1:0],
  output output_remap_reg_pkg::output_remap__out_t stee_output_remap_reg_ctrl_o [sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS-1:0],

  // Outbound Filter Register Interface
  output filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl_o [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0],
  input  filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status_i [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0],

  // Inbound Filter Register Interface
  output filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl_o [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0],
  input  filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status_i [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0],

  // Address/Size outputs
  output logic [55:0] sep_global_base_addr_o,
  output logic [55:0] sep_local_base_addr_o,
  output logic [55:0] sep_region_size_o,

  output logic [55:0] smu_global_base_addr_o,
  output logic [55:0] smu_region_size_o,

  // SMC Status inputs
  input  logic smc_fuse_sense_done_i,
  input  logic sep_fuse_sense_done_i,

  // SEP Straps inputs

  // SEP NMI VEC output
  output logic [31:1] nmi_vec_o,

  // External TRNG source selection (from sep_cpu_ctrl EXT_TRNG_SRC_SEL register)
  output logic [2:0] ext_trng_src_sel_o,

  // Key Manager emergency wipe control (from sep_cpu_ctrl KM_WIPE_CTRL register)
  output logic km_wipe_state_o,

  // Secure DMA bridge fault status/clear (sep_cpu_ctrl DMA_BUS_ERR_* registers)
  input  logic dma_reg_bus_err_i,
  input  logic dma_host_intg_err_i,
  output logic dma_err_clr_o,

  // Peripheral bridge fault status/clear (sep_cpu_ctrl PERIPH_BUS_ERR_* registers)
  input  logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err_i,
  output logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err_clr_o
);

  ////////////////////////////////////////////////////////////////////////////
  // Signal Declarations
  ////////////////////////////////////////////////////////////////////////////

  // AXI Demux signals
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::SYSTEM_CSR_DEMUX_PORTS-1:0] sep_system_csr_axil_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::SYSTEM_CSR_DEMUX_PORTS-1:0] sep_system_csr_axil_resps;

  sep_pkg::system_csr_demux_select_t system_csr_demux_select_aw;
  sep_pkg::system_csr_demux_select_t system_csr_demux_select_ar;

  // Outbound Filter signals
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0] outbound_filter_axil_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0] outbound_filter_axil_resps;

  sep_pkg::outbound_filter_select_t outbound_filter_aw_select;
  sep_pkg::outbound_filter_select_t outbound_filter_ar_select;

  // Inbound Filter signals
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0] inbound_filter_axil_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0] inbound_filter_axil_resps;

  sep_pkg::inbound_filter_select_t inbound_filter_aw_select;
  sep_pkg::inbound_filter_select_t inbound_filter_ar_select;

  // SEP CPU Control Register signals
  sep_cpu_ctrl_reg_pkg::sep_cpu_ctrl__in_t  sep_cpu_ctrl_hwif_in;
  sep_cpu_ctrl_reg_pkg::sep_cpu_ctrl__out_t sep_cpu_ctrl_hwif_out;

  // CLOCK_GATE_CTRL
  logic clock_gate_ctrl_rsvd;

  // TIMEOUT_INTERRUPT
  logic timeout_interrupt_rsvd;

  // TIMEOUT_ENABLE
  logic timeout_enable_rsvd;

  // TIMEOUT_COUNT
  logic timeout_count_rsvd [7:0];

  // TIMEOUT_CLEAR
  logic timeout_clear_rsvd;

  // TIMEOUT_MODE
  logic timeout_mode_rsvd;

  // SEP_SW_DEBUG output
  logic [31:0] sep_sw_debug;

  // REFERENCE_COUNTER
  logic [63:0] reference_counter;
  logic [63:0] ref_count_from_reg;
  logic        ref_count_wr_swacc;
  logic        ref_count_wr_swacc_q;

  // SEP_TEST_CTRL inputs
  logic sep_standalone;
  logic fast_pka_en;
  logic fast_sram_en;
  logic fast_dccm_en;
  logic fast_iccm_en;
  logic fast_spi_en;

  ////////////////////////////////////////////////////////////////////////////
  // AXI Demux
  ////////////////////////////////////////////////////////////////////////////

  always_comb begin
    // Default assignments
    system_csr_demux_select_aw = sep_pkg::LOCAL_MASTER_ALIAS_REMAP;
    system_csr_demux_select_ar = sep_pkg::LOCAL_MASTER_ALIAS_REMAP;

    if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.aw.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::LOCAL_MASTER_ALIAS_REMAP;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.aw.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::AP_OUTPUT_REMAP;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.aw.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::STEE_OUTPUT_REMAP;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.aw.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(
            31
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::OUTBOUND_FILTER;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.aw.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::INBOUND_FILTER;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_BASE_ADDR && sep_system_csr_axil_req_i.aw.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::SEP_CPU_CTRL;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR && sep_system_csr_axil_req_i.aw.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::SEP_SCRATCH_COLD;
    end else if (sep_system_csr_axil_req_i.aw.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR && sep_system_csr_axil_req_i.aw.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_SIZE) begin
      system_csr_demux_select_aw = sep_pkg::SEP_SCRATCH_WARM;
    end else begin
      system_csr_demux_select_aw = sep_pkg::ERR_SLV;
    end

    if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.ar.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::LOCAL_MASTER_ALIAS_REMAP;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.ar.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::AP_OUTPUT_REMAP;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.ar.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::STEE_OUTPUT_REMAP;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.ar.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(
            31
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::OUTBOUND_FILTER;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(
            0
        ) && sep_system_csr_axil_req_i.ar.addr <
            och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(
            15
        ) + och_sep_top_addrmap_pkg::OCH_SEP_TOP_INBOUND_FILTER_CTRL_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::INBOUND_FILTER;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_BASE_ADDR && sep_system_csr_axil_req_i.ar.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_CPU_CTRL_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::SEP_CPU_CTRL;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR && sep_system_csr_axil_req_i.ar.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_COLD_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::SEP_SCRATCH_COLD;
    end else if (sep_system_csr_axil_req_i.ar.addr >= och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR && sep_system_csr_axil_req_i.ar.addr < och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_SCRATCH_WARM_SIZE) begin
      system_csr_demux_select_ar = sep_pkg::SEP_SCRATCH_WARM;
    end else begin
      system_csr_demux_select_ar = sep_pkg::ERR_SLV;
    end
  end

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::SYSTEM_CSR_DEMUX_PORTS),
    .MaxTrans    (16),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_system_csr_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_req_i),
    .slv_aw_select_i (system_csr_demux_select_aw),
    .slv_ar_select_i (system_csr_demux_select_ar),
    .slv_resp_o      (sep_system_csr_axil_resp_o),
    .mst_reqs_o      (sep_system_csr_axil_reqs),
    .mst_resps_i     (sep_system_csr_axil_resps)
  );

  ////////////////////////////////////////////////////////////////////////////
  // Alias Remap Register Block - Local Masters
  ////////////////////////////////////////////////////////////////////////////

  localparam int unsigned alias_remap_sel_start_idx = $clog2(
      och_sep_top_addrmap_pkg::OCH_SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_SIZE
  );
  localparam int unsigned alias_remap_sel_end_idx = alias_remap_sel_start_idx + sep_pkg::ALIAS_REMAP_SEL_W - 1;

  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS-1:0] local_master_aR_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS-1:0] local_master_aR_resps;

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_local_master_alias_remap_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_reqs[sep_pkg::LOCAL_MASTER_ALIAS_REMAP]),
    .slv_aw_select_i (sep_system_csr_axil_reqs[sep_pkg::LOCAL_MASTER_ALIAS_REMAP].aw.addr[alias_remap_sel_end_idx:alias_remap_sel_start_idx]),  // 0x20 spacing: bits [8:5] for 16 regions
    .slv_ar_select_i (sep_system_csr_axil_reqs[sep_pkg::LOCAL_MASTER_ALIAS_REMAP].ar.addr[alias_remap_sel_end_idx:alias_remap_sel_start_idx]),  // 0x20 spacing: bits [8:5] for 16 regions
    .slv_resp_o      (sep_system_csr_axil_resps[sep_pkg::LOCAL_MASTER_ALIAS_REMAP]),
    .mst_reqs_o      (local_master_aR_reqs),
    .mst_resps_i     (local_master_aR_resps)
  );

  generate
    for (
        genvar i = 0; i < sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS; i++
    ) begin : gen_local_master_alias_remap_reg
      alias_remap_reg u_local_masters_alias_remap_reg (
        .clk            (clk_i),
        .arst_n         (rst_ni),
        .s_axil_awready (local_master_aR_resps[i].aw_ready),
        .s_axil_awvalid (local_master_aR_reqs[i].aw_valid),
        .s_axil_awaddr  (local_master_aR_reqs[i].aw.addr[4:0]),  // 0x20 spacing: bits [4:0] for register offset
        .s_axil_awprot  (local_master_aR_reqs[i].aw.prot),
        .s_axil_wready  (local_master_aR_resps[i].w_ready),
        .s_axil_wvalid  (local_master_aR_reqs[i].w_valid),
        .s_axil_wdata   (local_master_aR_reqs[i].w.data),
        .s_axil_wstrb   (local_master_aR_reqs[i].w.strb),
        .s_axil_bready  (local_master_aR_reqs[i].b_ready),
        .s_axil_bvalid  (local_master_aR_resps[i].b_valid),
        .s_axil_bresp   (local_master_aR_resps[i].b.resp),
        .s_axil_arready (local_master_aR_resps[i].ar_ready),
        .s_axil_arvalid (local_master_aR_reqs[i].ar_valid),
        .s_axil_araddr  (local_master_aR_reqs[i].ar.addr[4:0]),  // 0x20 spacing: bits [4:0] for register offset
        .s_axil_arprot  (local_master_aR_reqs[i].ar.prot),
        .s_axil_rready  (local_master_aR_reqs[i].r_ready),
        .s_axil_rvalid  (local_master_aR_resps[i].r_valid),
        .s_axil_rdata   (local_master_aR_resps[i].r.data),
        .s_axil_rresp   (local_master_aR_resps[i].r.resp),
        .hwif_out       (local_masters_alias_remap_reg_ctrl_o[i])
      );
    end
  endgenerate

  ////////////////////////////////////////////////////////////////////////////
  // Output Remap Register Block - AP
  ////////////////////////////////////////////////////////////////////////////

  localparam int unsigned ap_remap_sel_start_idx = $clog2(
      och_sep_top_addrmap_pkg::OCH_SEP_TOP_AP_OUTPUT_REMAP_CTRL_SIZE
  );
  localparam int unsigned ap_remap_sel_end_idx = ap_remap_sel_start_idx + sep_pkg::AP_REMAP_SEL_W - 1;

  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS-1:0] ap_output_remap_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS-1:0] ap_output_remap_resps;

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_ap_output_remap_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_reqs[sep_pkg::AP_OUTPUT_REMAP]),
    .slv_aw_select_i (sep_system_csr_axil_reqs[sep_pkg::AP_OUTPUT_REMAP].aw.addr[ap_remap_sel_end_idx:ap_remap_sel_start_idx]),  // 0x8 spacing: bits [6:3] for 16 regions
    .slv_ar_select_i (sep_system_csr_axil_reqs[sep_pkg::AP_OUTPUT_REMAP].ar.addr[ap_remap_sel_end_idx:ap_remap_sel_start_idx]),  // 0x8 spacing: bits [6:3] for 16 regions
    .slv_resp_o      (sep_system_csr_axil_resps[sep_pkg::AP_OUTPUT_REMAP]),
    .mst_reqs_o      (ap_output_remap_reqs),
    .mst_resps_i     (ap_output_remap_resps)
  );

  generate
    for (
        genvar i = 0; i < sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS; i++
    ) begin : gen_ap_output_remap_reg
      output_remap_reg u_ap_output_remap_reg (
        .clk            (clk_i),
        .arst_n         (rst_ni),
        .s_axil_awready (ap_output_remap_resps[i].aw_ready),
        .s_axil_awvalid (ap_output_remap_reqs[i].aw_valid),
        .s_axil_awaddr  ({1'b0, ap_output_remap_reqs[i].aw.addr[2:0]}),
        .s_axil_awprot  (ap_output_remap_reqs[i].aw.prot),
        .s_axil_wready  (ap_output_remap_resps[i].w_ready),
        .s_axil_wvalid  (ap_output_remap_reqs[i].w_valid),
        .s_axil_wdata   (ap_output_remap_reqs[i].w.data),
        .s_axil_wstrb   (ap_output_remap_reqs[i].w.strb),
        .s_axil_bready  (ap_output_remap_reqs[i].b_ready),
        .s_axil_bvalid  (ap_output_remap_resps[i].b_valid),
        .s_axil_bresp   (ap_output_remap_resps[i].b.resp),
        .s_axil_arready (ap_output_remap_resps[i].ar_ready),
        .s_axil_arvalid (ap_output_remap_reqs[i].ar_valid),
        .s_axil_araddr  ({1'b0, ap_output_remap_reqs[i].ar.addr[2:0]}),
        .s_axil_arprot  (ap_output_remap_reqs[i].ar.prot),
        .s_axil_rready  (ap_output_remap_reqs[i].r_ready),
        .s_axil_rvalid  (ap_output_remap_resps[i].r_valid),
        .s_axil_rdata   (ap_output_remap_resps[i].r.data),
        .s_axil_rresp   (ap_output_remap_resps[i].r.resp),
        .hwif_out       (ap_output_remap_reg_ctrl_o[i])
      );
    end
  endgenerate

  ////////////////////////////////////////////////////////////////////////////
  // Alias Remap Register Block - STEE
  ////////////////////////////////////////////////////////////////////////////

  localparam int unsigned stee_remap_sel_start_idx = $clog2(
      och_sep_top_addrmap_pkg::OCH_SEP_TOP_STEE_OUTPUT_REMAP_CTRL_SIZE
  );
  localparam int unsigned stee_remap_sel_end_idx = stee_remap_sel_start_idx + sep_pkg::STEE_REMAP_SEL_W - 1;

  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  [sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS-1:0] stee_output_remap_reqs;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t [sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS-1:0] stee_output_remap_resps;

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_stee_output_remap_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_reqs[sep_pkg::STEE_OUTPUT_REMAP]),
    .slv_aw_select_i (sep_system_csr_axil_reqs[sep_pkg::STEE_OUTPUT_REMAP].aw.addr[stee_remap_sel_end_idx:stee_remap_sel_start_idx]),  // 0x8 spacing: bits [6:3] for 16 regions
    .slv_ar_select_i (sep_system_csr_axil_reqs[sep_pkg::STEE_OUTPUT_REMAP].ar.addr[stee_remap_sel_end_idx:stee_remap_sel_start_idx]),  // 0x8 spacing: bits [6:3] for 16 regions
    .slv_resp_o      (sep_system_csr_axil_resps[sep_pkg::STEE_OUTPUT_REMAP]),
    .mst_reqs_o      (stee_output_remap_reqs),
    .mst_resps_i     (stee_output_remap_resps)
  );

  generate
    for (
        genvar i = 0; i < sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS; i++
    ) begin : gen_stee_output_remap_reg
      output_remap_reg u_stee_output_remap_reg (
        .clk            (clk_i),
        .arst_n         (rst_ni),
        .s_axil_awready (stee_output_remap_resps[i].aw_ready),
        .s_axil_awvalid (stee_output_remap_reqs[i].aw_valid),
        .s_axil_awaddr  ({1'b0, stee_output_remap_reqs[i].aw.addr[2:0]}),
        .s_axil_awprot  (stee_output_remap_reqs[i].aw.prot),
        .s_axil_wready  (stee_output_remap_resps[i].w_ready),
        .s_axil_wvalid  (stee_output_remap_reqs[i].w_valid),
        .s_axil_wdata   (stee_output_remap_reqs[i].w.data),
        .s_axil_wstrb   (stee_output_remap_reqs[i].w.strb),
        .s_axil_bready  (stee_output_remap_reqs[i].b_ready),
        .s_axil_bvalid  (stee_output_remap_resps[i].b_valid),
        .s_axil_bresp   (stee_output_remap_resps[i].b.resp),
        .s_axil_arready (stee_output_remap_resps[i].ar_ready),
        .s_axil_arvalid (stee_output_remap_reqs[i].ar_valid),
        .s_axil_araddr  ({1'b0, stee_output_remap_reqs[i].ar.addr[2:0]}),
        .s_axil_arprot  (stee_output_remap_reqs[i].ar.prot),
        .s_axil_rready  (stee_output_remap_reqs[i].r_ready),
        .s_axil_rvalid  (stee_output_remap_resps[i].r_valid),
        .s_axil_rdata   (stee_output_remap_resps[i].r.data),
        .s_axil_rresp   (stee_output_remap_resps[i].r.resp),
        .hwif_out       (stee_output_remap_reg_ctrl_o[i])
      );
    end
  endgenerate

  ////////////////////////////////////////////////////////////////////////////
  // Outbound Filter Register Block
  ////////////////////////////////////////////////////////////////////////////

  always_comb begin
    outbound_filter_aw_select = sep_system_csr_axil_reqs[sep_pkg::OUTBOUND_FILTER].aw.addr[5+:$clog2(sep_pkg::OUTBOUND_FILTER_NUM_FILTERS)];
    outbound_filter_ar_select = sep_system_csr_axil_reqs[sep_pkg::OUTBOUND_FILTER].ar.addr[5+:$clog2(sep_pkg::OUTBOUND_FILTER_NUM_FILTERS)];
  end

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::OUTBOUND_FILTER_NUM_FILTERS),
    .MaxTrans    (16),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_outbound_filter_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_reqs[sep_pkg::OUTBOUND_FILTER]),
    .slv_aw_select_i (outbound_filter_aw_select),
    .slv_ar_select_i (outbound_filter_ar_select),
    .slv_resp_o      (sep_system_csr_axil_resps[sep_pkg::OUTBOUND_FILTER]),
    .mst_reqs_o      (outbound_filter_axil_reqs),
    .mst_resps_i     (outbound_filter_axil_resps)
  );

  generate
    for (
        genvar f = 0; f < sep_pkg::OUTBOUND_FILTER_NUM_FILTERS; f = f + 1
    ) begin : gen_outbound_filter_reg

      // Intermediate signals for conditional connection based on locked status
      sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t filter_reg_req, locked_reg_req;
      sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t filter_reg_resp, locked_reg_resp;

      wire filter_reg_aw_select = outbound_filter_ctrl_o[f].FILTER_CONFIG.locked.value && (outbound_filter_axil_reqs[f].aw_valid || outbound_filter_axil_reqs[f].w_valid);

      axi_lite_demux #(
        .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
        .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
        .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
        .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
        .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
        .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
        .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
        .NoMstPorts  (2),
        .MaxTrans    (1),
        .FallThrough (1'b0),
        .SpillAw     (1'b1),
        .SpillW      (1'b0),
        .SpillB      (1'b0),
        .SpillAr     (1'b1),
        .SpillR      (1'b0)
      ) u_outbound_filter_axil_demux (
        .clk_i            (clk_i),
        .rst_ni           (rst_ni),
        .test_i           (test_en_i),
        .slv_req_i        (outbound_filter_axil_reqs[f]),
        .slv_resp_o       (outbound_filter_axil_resps[f]),
        .slv_aw_select_i  (filter_reg_aw_select),
        .slv_ar_select_i  (1'b0), // Always pass through reads
        .mst_reqs_o       ({locked_reg_req, filter_reg_req}),
        .mst_resps_i      ({locked_reg_resp, filter_reg_resp})
      );

      filter_ctrl_reg u_outbound_filter_reg (
        .clk            (clk_i),
        .arst_n         (rst_ni),
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
        .AXI_ADDR_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH),
        .AXI_DATA_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH),
        .axil_req_t     (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
        .axil_resp_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t)
      ) u_err_slv (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .axil_req_i  (locked_reg_req),
        .axil_resp_o (locked_reg_resp)
      );

    end
  endgenerate

  ////////////////////////////////////////////////////////////////////////////
  // Inbound Filter Register Block
  ////////////////////////////////////////////////////////////////////////////

  always_comb begin
    inbound_filter_aw_select = sep_system_csr_axil_reqs[sep_pkg::INBOUND_FILTER].aw.addr[5+:$clog2(sep_pkg::INBOUND_FILTER_NUM_FILTERS)];
    inbound_filter_ar_select = sep_system_csr_axil_reqs[sep_pkg::INBOUND_FILTER].ar.addr[5+:$clog2(sep_pkg::INBOUND_FILTER_NUM_FILTERS)];
  end

  axi_lite_demux #(
    .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .NoMstPorts  (sep_pkg::INBOUND_FILTER_NUM_FILTERS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_inbound_filter_axil_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_system_csr_axil_reqs[sep_pkg::INBOUND_FILTER]),
    .slv_aw_select_i (inbound_filter_aw_select),
    .slv_ar_select_i (inbound_filter_ar_select),
    .slv_resp_o      (sep_system_csr_axil_resps[sep_pkg::INBOUND_FILTER]),
    .mst_reqs_o      (inbound_filter_axil_reqs),
    .mst_resps_i     (inbound_filter_axil_resps)
  );

  generate
    for (
        genvar f = 0; f < sep_pkg::INBOUND_FILTER_NUM_FILTERS; f = f + 1
    ) begin : gen_inbound_filter_reg

      // Intermediate signals for conditional connection based on locked status
      sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t filter_reg_req, locked_reg_req;
      sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t filter_reg_resp, locked_reg_resp;

      wire filter_reg_aw_select = inbound_filter_ctrl_o[f].FILTER_CONFIG.locked.value && (inbound_filter_axil_reqs[f].aw_valid || inbound_filter_axil_reqs[f].w_valid);

      axi_lite_demux #(
        .aw_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_aw_chan_t),
        .w_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_w_chan_t),
        .b_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_b_chan_t),
        .ar_chan_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_ar_chan_t),
        .r_chan_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_r_chan_t),
        .axi_req_t   (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
        .axi_resp_t  (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
        .NoMstPorts  (2),
        .MaxTrans    (1),
        .FallThrough (1'b0),
        .SpillAw     (1'b1),
        .SpillW      (1'b0),
        .SpillB      (1'b0),
        .SpillAr     (1'b1),
        .SpillR      (1'b0)
      ) u_inbound_filter_axil_demux (
        .clk_i            (clk_i),
        .rst_ni           (rst_ni),
        .test_i           (test_en_i),
        .slv_req_i        (inbound_filter_axil_reqs[f]),
        .slv_resp_o       (inbound_filter_axil_resps[f]),
        .slv_aw_select_i  (filter_reg_aw_select),
        .slv_ar_select_i  (1'b0), // Always pass through reads
        .mst_reqs_o       ({locked_reg_req, filter_reg_req}),
        .mst_resps_i      ({locked_reg_resp, filter_reg_resp})
      );

      filter_ctrl_reg u_inbound_filter_reg (
        .clk            (clk_i),
        .arst_n         (rst_ni),
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
        .AXI_ADDR_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH),
        .AXI_DATA_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH),
        .axil_req_t     (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
        .axil_resp_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t)
      ) u_err_slv (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .axil_req_i  (locked_reg_req),
        .axil_resp_o (locked_reg_resp)
      );

    end
  endgenerate

  ////////////////////////////////////////////////////////////////////////////
  // SEP CPU Control Register Block
  ////////////////////////////////////////////////////////////////////////////

  sep_cpu_ctrl_reg u_sep_cpu_ctrl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),
    .s_axil_awready (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].aw_ready),
    .s_axil_awvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].aw_valid),
    .s_axil_awaddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].aw.addr[sep_cpu_ctrl_reg_pkg::SEP_CPU_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].aw.prot),
    .s_axil_wready  (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].w_ready),
    .s_axil_wvalid  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].w_valid),
    .s_axil_wdata   (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].w.data),
    .s_axil_wstrb   (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].w.strb),
    .s_axil_bready  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].b_ready),
    .s_axil_bvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].b_valid),
    .s_axil_bresp   (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].b.resp),
    .s_axil_arready (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].ar_ready),
    .s_axil_arvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].ar_valid),
    .s_axil_araddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].ar.addr[sep_cpu_ctrl_reg_pkg::SEP_CPU_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].ar.prot),
    .s_axil_rready  (sep_system_csr_axil_reqs[sep_pkg::SEP_CPU_CTRL].r_ready),
    .s_axil_rvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].r_valid),
    .s_axil_rdata   (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].r.data),
    .s_axil_rresp   (sep_system_csr_axil_resps[sep_pkg::SEP_CPU_CTRL].r.resp),

    .hwif_in        (sep_cpu_ctrl_hwif_in),
    .hwif_out       (sep_cpu_ctrl_hwif_out)
  );

  ////////////////////////////////////////////////////////////////////////////
  // hwif_out Signal Assignments
  ////////////////////////////////////////////////////////////////////////////

  // Reserved placeholder registers (clock-gate control / timeout monitors
  // unimplemented): outputs sunk into unused *_rsvd nets.
  assign clock_gate_ctrl_rsvd = sep_cpu_ctrl_hwif_out.CLOCK_GATE_CTRL.pka_cg_enable.value;

  assign timeout_count_rsvd[0] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_DMA.reserved.value;
  assign timeout_count_rsvd[1] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_SYS_IN.reserved.value;
  assign timeout_count_rsvd[2] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_MAILBOX_INBOUND.reserved.value;
  assign timeout_count_rsvd[3] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_MAILBOX_OUTBOUND.reserved.value;
  assign timeout_count_rsvd[4] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_ENTROPY_WRITE.reserved.value;
  assign timeout_count_rsvd[5] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_ENTROPY_READ.reserved.value;
  assign timeout_count_rsvd[6] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_FILTER_OUT.reserved.value;
  assign timeout_count_rsvd[7] = sep_cpu_ctrl_hwif_out.TIMEOUT_COUNT_ALIAS_REMAP.reserved.value;

  assign timeout_enable_rsvd = sep_cpu_ctrl_hwif_out.TIMEOUT_ENABLE.reserved.value;
  assign timeout_clear_rsvd  = sep_cpu_ctrl_hwif_out.TIMEOUT_CLEAR.reserved.value;
  assign timeout_mode_rsvd   = sep_cpu_ctrl_hwif_out.TIMEOUT_MODE.reserved.value;

  // Address/Size
  assign sep_global_base_addr_o   = sep_cpu_ctrl_hwif_out.SEP_GLOBAL_BASE_ADDR.addr.value;
  assign sep_local_base_addr_o    = sep_cpu_ctrl_hwif_out.SEP_LOCAL_BASE_ADDR.addr.value;
  assign sep_region_size_o        = 56'(sep_cpu_ctrl_hwif_out.SEP_REGION_SIZE.size.value);
  assign smu_global_base_addr_o   = sep_cpu_ctrl_hwif_out.SMU_GLOBAL_BASE_ADDR.addr.value;
  assign smu_region_size_o        = 56'(sep_cpu_ctrl_hwif_out.SMU_REGION_SIZE.size.value);

  // SEP_SW_DEBUG
  assign sep_sw_debug = sep_cpu_ctrl_hwif_out.SEP_SW_DEBUG.sep_sw_debug.value;

  ////////////////////////////////////////////////////////////////////////////
  // hwif_in Signal Assignments
  ////////////////////////////////////////////////////////////////////////////

  // Tie off all undriven signals to 0
  assign timeout_interrupt_rsvd = 0;

  assign sep_standalone = 0;
  assign fast_pka_en = 0;
  assign fast_sram_en = 0;
  assign fast_dccm_en = 0;
  assign fast_iccm_en = 0;
  assign fast_spi_en = 0;

  // REFERENCE_COUNTER
  // Delay wr_swacc one cycle so the update value is sampled after the CSR field
  // has captured the SW write data
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ref_count_wr_swacc_q <= 1'b0;
    end else begin
      ref_count_wr_swacc_q <= ref_count_wr_swacc;
    end
  end

  prim_refclk_count_w_cdc #(
    .REF_COUNT_WIDTH(64)
  ) u_reference_counter_counter (
    .refclk_i           (clk_ref_i),
    .prst_ni            (rst_ni),
    .cnt_en_i           (1'b1),
    .cnt_update_i       (ref_count_wr_swacc_q),
    .cnt_update_value_i (ref_count_from_reg),
    .out_clk_i          (clk_i),
    .count_o            (reference_counter)
  );

  assign ref_count_from_reg = sep_cpu_ctrl_hwif_out.REFERENCE_COUNTER.rc.value;
  assign ref_count_wr_swacc = sep_cpu_ctrl_hwif_out.REFERENCE_COUNTER.rc.wr_swacc;

  assign sep_cpu_ctrl_hwif_in.REFERENCE_COUNTER.rc.next = reference_counter;

  // TIMEOUT_INTERRUPT - RSVD (timeout monitors unimplemented)
  assign sep_cpu_ctrl_hwif_in.TIMEOUT_INTERRUPT.reserved.next = timeout_interrupt_rsvd;

  // SEP_TEST_CTRL
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.sep_standalone.next = sep_standalone;
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.fast_pka_en.next    = fast_pka_en;
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.fast_sram_en.next   = fast_sram_en;
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.fast_dccm_en.next   = fast_dccm_en;
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.fast_iccm_en.next   = fast_iccm_en;
  assign sep_cpu_ctrl_hwif_in.SEP_TEST_CTRL.fast_spi_en.next    = fast_spi_en;

  // SMC_FUSE_SENSE_STATUS
  assign sep_cpu_ctrl_hwif_in.SMC_FUSE_SENSE_STATUS.smc_fuse_sense_done.next = smc_fuse_sense_done_i;

  // SEP_FUSE_SENSE_STATUS
  assign sep_cpu_ctrl_hwif_in.SEP_FUSE_SENSE_STATUS.sep_fuse_sense_done.next = sep_fuse_sense_done_i;


  // SEP_NMI_VEC
  assign nmi_vec_o = sep_cpu_ctrl_hwif_out.SEP_NMI_VEC.nmi_vec.value;

  // EXT_TRNG_SRC_SEL
  assign ext_trng_src_sel_o = sep_cpu_ctrl_hwif_out.EXT_TRNG_SRC_SEL.sel.value;

  // KM_WIPE_CTRL
  assign km_wipe_state_o = sep_cpu_ctrl_hwif_out.KM_WIPE_CTRL.wipe_state.value;

  // DMA_BUS_ERR_STATUS / DMA_BUS_ERR_CLEAR
  assign sep_cpu_ctrl_hwif_in.DMA_BUS_ERR_STATUS.reg_path_err.next  = dma_reg_bus_err_i;
  assign sep_cpu_ctrl_hwif_in.DMA_BUS_ERR_STATUS.host_path_err.next = dma_host_intg_err_i;
  assign dma_err_clr_o = sep_cpu_ctrl_hwif_out.DMA_BUS_ERR_CLEAR.clr.value;

  // PERIPH_BUS_ERR_STATUS / PERIPH_BUS_ERR_CLEAR. Field order must match
  // sep_pkg::periph_bus_err_e.
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.aes.next  = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_AES];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.hmac.next = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_HMAC];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.kmac.next = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_KMAC];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.otbn.next = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_OTBN];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.csrng.next = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_CSRNG];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.edn.next  = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_EDN];
  assign sep_cpu_ctrl_hwif_in.PERIPH_BUS_ERR_STATUS.wdt.next  = periph_bus_err_i[sep_pkg::PERIPH_BUS_ERR_WDT];

  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_AES]  = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.aes.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_HMAC] = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.hmac.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_KMAC] = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.kmac.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_OTBN] = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.otbn.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_CSRNG] = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.csrng.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_EDN]  = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.edn.value;
  assign periph_bus_err_clr_o[sep_pkg::PERIPH_BUS_ERR_WDT]  = sep_cpu_ctrl_hwif_out.PERIPH_BUS_ERR_CLEAR.wdt.value;

  ///////////////////////
  // Scratch Registers //
  ///////////////////////

  sep_scratch_reg_pkg::sep_scratch__out_t hwif_out_cold, hwif_out_warm;

  logic [31:0] scratch_cold_data[8], scratch_warm_data[8];

  sep_scratch_reg u_sep_scratch_reg_cold (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].aw_ready),
    .s_axil_awvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].aw_valid),
    .s_axil_awaddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].aw.addr[sep_scratch_reg_pkg::SEP_SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].aw.prot),
    .s_axil_wready  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].w_ready),
    .s_axil_wvalid  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].w_valid),
    .s_axil_wdata   (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].w.data),
    .s_axil_wstrb   (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].w.strb),
    .s_axil_bready  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].b_ready),
    .s_axil_bvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].b_valid),
    .s_axil_bresp   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].b.resp),
    .s_axil_arready (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].ar_ready),
    .s_axil_arvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].ar_valid),
    .s_axil_araddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].ar.addr[sep_scratch_reg_pkg::SEP_SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].ar.prot),
    .s_axil_rready  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_COLD].r_ready),
    .s_axil_rvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].r_valid),
    .s_axil_rdata   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].r.data),
    .s_axil_rresp   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_COLD].r.resp),

    .hwif_out       (hwif_out_cold)
  );

  sep_scratch_reg u_sep_scratch_reg_warm (
    .clk            (clk_i),
    .arst_n         (rst_warm_ni),

    .s_axil_awready (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].aw_ready),
    .s_axil_awvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].aw_valid),
    .s_axil_awaddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].aw.addr[sep_scratch_reg_pkg::SEP_SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].aw.prot),
    .s_axil_wready  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].w_ready),
    .s_axil_wvalid  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].w_valid),
    .s_axil_wdata   (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].w.data),
    .s_axil_wstrb   (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].w.strb),
    .s_axil_bready  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].b_ready),
    .s_axil_bvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].b_valid),
    .s_axil_bresp   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].b.resp),
    .s_axil_arready (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].ar_ready),
    .s_axil_arvalid (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].ar_valid),
    .s_axil_araddr  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].ar.addr[sep_scratch_reg_pkg::SEP_SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].ar.prot),
    .s_axil_rready  (sep_system_csr_axil_reqs[sep_pkg::SEP_SCRATCH_WARM].r_ready),
    .s_axil_rvalid  (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].r_valid),
    .s_axil_rdata   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].r.data),
    .s_axil_rresp   (sep_system_csr_axil_resps[sep_pkg::SEP_SCRATCH_WARM].r.resp),

    .hwif_out       (hwif_out_warm)
  );

  for (genvar i = 0; i < 8; i++) begin : gen_scratch_data
    assign scratch_cold_data[i] = hwif_out_cold.SCRATCH[i].data.value;
    assign scratch_warm_data[i] = hwif_out_warm.SCRATCH[i].data.value;
  end

  /////////////
  // ERR_SLV //
  /////////////

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH),
    .AXI_DATA_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH),
    .axil_req_t     (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .axil_resp_t    (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t)
  ) u_err_slv (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .axil_req_i  (sep_system_csr_axil_reqs[sep_pkg::ERR_SLV]),
    .axil_resp_o (sep_system_csr_axil_resps[sep_pkg::ERR_SLV])
  );

endmodule

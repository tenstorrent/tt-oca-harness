// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP System Peripherals (Mailbox, Watchdog Timer, ...)

module sep_system_peripherals (
  // Global Interface
  input  logic clk_i,
  input  logic clk_ref_i,
  input  logic rst_ni,
  input  logic rst_warm_ni,

  input  logic test_en_i,
  input  logic scan_rst_ni,
  input  logic inbound_filter_skip_i,
  input  logic outbound_filter_skip_i,

  // AXI4 Slave Interface
  input  sep_pkg::sep_axi_xbar_slv_req_t  sep_system_peripheral_axi_req_i,
  output sep_pkg::sep_axi_xbar_slv_resp_t sep_system_peripheral_axi_resp_o,

  input  sep_pkg::sep_system_peripherals_internal_axi_req_t  smn_inbound_axi_req_i,
  output sep_pkg::sep_system_peripherals_internal_axi_resp_t smn_inbound_axi_resp_o,

  // AXI4 Master Interface
  output sep_pkg::sep_system_peripherals_inbound_to_sep_axi_req_t  smn_inbound_to_sep_axi_req_o,
  input  sep_pkg::sep_system_peripherals_inbound_to_sep_axi_resp_t smn_inbound_to_sep_axi_resp_i,

  output sep_pkg::sep_system_peripherals_outbound_axi_req_t  smn_outbound_axi_req_o,
  input  sep_pkg::sep_system_peripherals_outbound_axi_resp_t smn_outbound_axi_resp_i,

  output sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_ext_to_smc_axi_req_o,
  input  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_ext_to_smc_axi_resp_i,

  // Address Remap
  output sep_pkg::remap_debug_t local_masters_remap_debug_o,

  // Outbound Filter Interface
  output logic [$clog2(sep_pkg::OUTBOUND_FILTER_NUM_FILTERS)-1:0] outbound_write_filter_hit_debug_o,
  output logic [$clog2(sep_pkg::OUTBOUND_FILTER_NUM_FILTERS)-1:0] outbound_read_filter_hit_debug_o,
  output logic [$clog2(sep_pkg::INBOUND_FILTER_NUM_FILTERS)-1:0]  inbound_write_filter_hit_debug_o,
  output logic [$clog2(sep_pkg::INBOUND_FILTER_NUM_FILTERS)-1:0]  inbound_read_filter_hit_debug_o,

  // Mailbox Interface
  output logic [sep_pkg::NUM_MAILBOXES-1:0] mailbox_inbound_interrupt_o,
  output logic [sep_pkg::NUM_MAILBOXES-1:0] mailbox_outbound_interrupt_o,

  // SEP System CSR Interface
  input  logic smc_fuse_sense_done_i,
  input  logic sep_fuse_sense_done_i,


  output logic [31:1] nmi_vec_o,

  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smc_global_base_addr_i,
  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smc_region_size_i,

  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_local_base_addr_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_addr_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size_o,

  // External TRNG source selection (from sep_cpu_ctrl)
  output logic [2:0] ext_trng_src_sel_o,

  // Key Manager emergency wipe control (from sep_cpu_ctrl)
  output logic km_wipe_state_o,

  // Secure DMA bridge fault status/clear (from sep_cpu_ctrl)
  input  logic dma_reg_bus_err_i,
  input  logic dma_host_intg_err_i,
  output logic dma_err_clr_o,

  // Peripheral register-bridge fault status/clear (from sep_cpu_ctrl)
  input  logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err_i,
  output logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err_clr_o
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_system_peripheral_56_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_system_peripheral_56_axi_resp;
  sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_system_peripheral_56_remapped_precut_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_system_peripheral_56_remapped_precut_axi_resp;
  sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_system_peripheral_56_remapped_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_system_peripheral_56_remapped_axi_resp;

  sep_pkg::sep_system_peripherals_internal_axi_req_t [sep_pkg::ADDRESS_REMAP_DEMUX_PORTS-1:0]  sep_system_peripheral_56_remapped_from_demux_axi_reqs;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t [sep_pkg::ADDRESS_REMAP_DEMUX_PORTS-1:0] sep_system_peripheral_56_remapped_from_demux_axi_resps;

  sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_ap_remapped_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_ap_remapped_axi_resp;
  sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_stee_remapped_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_stee_remapped_axi_resp;

  sep_pkg::sep_system_peripherals_outbound_axi_req_t  pre_outbound_filter_axi_req;
  sep_pkg::sep_system_peripherals_outbound_axi_resp_t pre_outbound_filter_axi_resp;

  sep_pkg::sep_system_peripherals_internal_axi_req_t     smn_inbound_filtered_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t    smn_inbound_filtered_axi_resp;
  sep_pkg::sep_system_peripherals_internal_axi_req_t     smn_inbound_filtered_from_local_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t    smn_inbound_filtered_from_local_axi_resp;
  sep_pkg::sep_system_peripherals_xbar_slv_axi_req_t     smn_inbound_filtered_from_xbar_axi_req;
  sep_pkg::sep_system_peripherals_xbar_slv_axi_resp_t    smn_inbound_filtered_from_xbar_axi_resp;
  sep_pkg::sep_system_peripherals_xbar_slv_32_axi_req_t  smn_inbound_filtered_downsized_axi_req;
  sep_pkg::sep_system_peripherals_xbar_slv_32_axi_resp_t smn_inbound_filtered_downsized_axi_resp;

  alias_remap_reg_pkg::alias_remap__out_t   local_masters_alias_remap_reg_ctrl [sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS-1:0];
  output_remap_reg_pkg::output_remap__out_t ap_output_remap_reg_ctrl [sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS-1:0];
  output_remap_reg_pkg::output_remap__out_t stee_output_remap_reg_ctrl [sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS-1:0];

  // SEP System Peripherals Xbar outputs (6-bit ID, 56-bit addr)
  sep_pkg::sep_system_peripherals_mailbox_axi_lite_req_t     mailbox_axil_req;
  sep_pkg::sep_system_peripherals_mailbox_axi_lite_resp_t    mailbox_axil_resp;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  mailbox_from_csr_axil_req;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t mailbox_from_csr_axil_resp;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t  system_csr_axil_req;
  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t system_csr_axil_resp;

  // Filter Control and Status Signals
  filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status [sep_pkg::OUTBOUND_FILTER_NUM_FILTERS-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0];
  filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status [sep_pkg::INBOUND_FILTER_NUM_FILTERS-1:0];

  // SEP System CSR Address Configuration Signals
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_addr;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smu_global_base_addr;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smu_region_size;

  ///////////////////////////////////////////////////////
  // Address Expansion (from local masters 32->56 bit) //
  ///////////////////////////////////////////////////////

  prim_axi_addr_fixer #(
    .INPUT_ADDR_W                (sep_pkg::CPU_ADDR_WIDTH),
    .OUTPUT_ADDR_W               (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ADDR_WIDTH),
    .input_axi_req_t             (sep_pkg::sep_axi_xbar_slv_req_t),
    .input_axi_resp_t            (sep_pkg::sep_axi_xbar_slv_resp_t),
    .output_axi_req_t            (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .output_axi_resp_t           (sep_pkg::sep_system_peripherals_internal_axi_resp_t)
  ) u_local_master_addr_fixer (
    .axi_in_req_i                (sep_system_peripheral_axi_req_i),
    .axi_in_resp_o               (sep_system_peripheral_axi_resp_o),
    .axi_out_req_o               (sep_system_peripheral_56_axi_req),
    .axi_out_resp_i              (sep_system_peripheral_56_axi_resp)
  );

  ////////////////////////////////////////
  // Address Remap (from local masters) //
  ////////////////////////////////////////

  axi_alias_remap_wrap #(
    .axi_req_t                     (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t                    (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .remap_region_t                (sep_pkg::remap_region_t),
    .remap_debug_t                 (sep_pkg::remap_debug_t),
    .NUM_REGIONS                   (sep_pkg::NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS),
    .DEBUG_OUTPUT                  (1),
    .ALIAS_REMAP_IDX_START         (sep_pkg::ALIAS_REMAP_IDX_START),
    .AXI_ADDR_WIDTH                (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ADDR_WIDTH),
    .NUM_CHUNKS_CARRY_SELECT_ADDER (9) // 56-12+1 = 45, 45/9 = 5
  ) u_local_master_remap_wrap (
    .reg_ctrl_i                    (local_masters_alias_remap_reg_ctrl),
    .remap_debug_o                 (local_masters_remap_debug_o),
    .axi_in_req_i                  (sep_system_peripheral_56_axi_req),
    .axi_in_resp_o                 (sep_system_peripheral_56_axi_resp),
    .axi_out_req_o                 (sep_system_peripheral_56_remapped_precut_axi_req),
    .axi_out_resp_i                (sep_system_peripheral_56_remapped_precut_axi_resp)
  );

  axi_cut #(
    .Bypass     (1'b0),
    .aw_chan_t  (sep_pkg::sep_system_peripherals_internal_axi_aw_chan_t),
    .w_chan_t   (sep_pkg::sep_system_peripherals_internal_axi_w_chan_t),
    .b_chan_t   (sep_pkg::sep_system_peripherals_internal_axi_b_chan_t),
    .ar_chan_t  (sep_pkg::sep_system_peripherals_internal_axi_ar_chan_t),
    .r_chan_t   (sep_pkg::sep_system_peripherals_internal_axi_r_chan_t),
    .axi_req_t  (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t (sep_pkg::sep_system_peripherals_internal_axi_resp_t)
  ) u_local_master_remap_cut (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (sep_system_peripheral_56_remapped_precut_axi_req),
    .slv_resp_o (sep_system_peripheral_56_remapped_precut_axi_resp),
    .mst_req_o  (sep_system_peripheral_56_remapped_axi_req),
    .mst_resp_i (sep_system_peripheral_56_remapped_axi_resp)
  );

  ////////////////////////////////////
  // AXI Demux (from Address Remap) //
  ////////////////////////////////////

  sep_pkg::address_remap_demux_select_t address_remap_demux_select_aw;
  sep_pkg::address_remap_demux_select_t address_remap_demux_select_ar;

  // Direct binary address decode for AXI demux
  // Priority: SMC > SMU > AP > STEE > LOCAL (default)
  always_comb begin
    // Write address channel decode
    if (sep_system_peripheral_56_remapped_axi_req.aw.addr >= smc_global_base_addr_i && sep_system_peripheral_56_remapped_axi_req.aw.addr < smc_global_base_addr_i + smc_region_size_i) begin
      address_remap_demux_select_aw = sep_pkg::SEP_EXT_TO_SMC;
    end else if ((sep_system_peripheral_56_remapped_axi_req.aw.addr >= smu_global_base_addr && sep_system_peripheral_56_remapped_axi_req.aw.addr < smu_global_base_addr + smu_region_size) ||
                (sep_system_peripheral_56_remapped_axi_req.aw.addr >= sep_pkg::EXTERNAL_TO_CHIPLET_BASE_ADDR)) begin
      address_remap_demux_select_aw = sep_pkg::SEP_EXT_TO_SMU;
    end else if (sep_system_peripheral_56_remapped_axi_req.aw.addr >= sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR && sep_system_peripheral_56_remapped_axi_req.aw.addr < sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_AP_REGION_SIZE) begin
      address_remap_demux_select_aw = sep_pkg::SEP_EXT_AP_REMAP;
    end else if (sep_system_peripheral_56_remapped_axi_req.aw.addr >= sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR && sep_system_peripheral_56_remapped_axi_req.aw.addr < sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_SIZE) begin
      address_remap_demux_select_aw = sep_pkg::SEP_EXT_STEE_REMAP;
    end else begin
      // Default to local for: sep_local_base_addr, sep_global_base_addr, or unmapped addresses
      address_remap_demux_select_aw = sep_pkg::SEP_LOCAL;
    end

    // Read address channel decode
    if (sep_system_peripheral_56_remapped_axi_req.ar.addr >= smc_global_base_addr_i && sep_system_peripheral_56_remapped_axi_req.ar.addr < smc_global_base_addr_i + smc_region_size_i) begin
      address_remap_demux_select_ar = sep_pkg::SEP_EXT_TO_SMC;
    end else if ((sep_system_peripheral_56_remapped_axi_req.ar.addr >= smu_global_base_addr && sep_system_peripheral_56_remapped_axi_req.ar.addr < smu_global_base_addr + smu_region_size) ||
                (sep_system_peripheral_56_remapped_axi_req.ar.addr >= sep_pkg::EXTERNAL_TO_CHIPLET_BASE_ADDR)) begin
      address_remap_demux_select_ar = sep_pkg::SEP_EXT_TO_SMU;
    end else if (sep_system_peripheral_56_remapped_axi_req.ar.addr >= sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR && sep_system_peripheral_56_remapped_axi_req.ar.addr < sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_AP_REGION_SIZE) begin
      address_remap_demux_select_ar = sep_pkg::SEP_EXT_AP_REMAP;
    end else if (sep_system_peripheral_56_remapped_axi_req.ar.addr >= sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR && sep_system_peripheral_56_remapped_axi_req.ar.addr < sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_SIZE) begin
      address_remap_demux_select_ar = sep_pkg::SEP_EXT_STEE_REMAP;
    end else begin
      // Default to local for: sep_local_base_addr, sep_global_base_addr, or unmapped addresses
      address_remap_demux_select_ar = sep_pkg::SEP_LOCAL;
    end
  end

  axi_demux #(
    .AxiIdWidth  (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_pkg::sep_system_peripherals_internal_axi_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_system_peripherals_internal_axi_w_chan_t),
    .b_chan_t    (sep_pkg::sep_system_peripherals_internal_axi_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_system_peripherals_internal_axi_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_system_peripherals_internal_axi_r_chan_t),
    .axi_req_t   (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t  (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .NoMstPorts  (sep_pkg::ADDRESS_REMAP_DEMUX_PORTS),
    .MaxTrans    (16),
    .AxiLookBits (3),
    .UniqueIds   (1'b0),
    .SelHashIds  (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'h0),
    .slv_req_i       (sep_system_peripheral_56_remapped_axi_req),
    .slv_aw_select_i (address_remap_demux_select_aw),
    .slv_ar_select_i (address_remap_demux_select_ar),
    .slv_resp_o      (sep_system_peripheral_56_remapped_axi_resp),
    .mst_reqs_o      (sep_system_peripheral_56_remapped_from_demux_axi_reqs),
    .mst_resps_i     (sep_system_peripheral_56_remapped_from_demux_axi_resps)
  );

  assign sep_ext_to_smc_axi_req_o = sep_system_peripheral_56_remapped_from_demux_axi_reqs[sep_pkg::SEP_EXT_TO_SMC];
  assign sep_system_peripheral_56_remapped_from_demux_axi_resps[sep_pkg::SEP_EXT_TO_SMC] = sep_ext_to_smc_axi_resp_i;

  //////////////////////
  // AP Address Remap //
  //////////////////////

  output_remap #(
    .axi_req_t          (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t         (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .remap_addr_t       (sep_pkg::sep_56_64_6_12_axi_addr_t),
    .user_ovrd_t        (sep_pkg::sep_56_64_6_12_axi_user_t),
    .NumRegions         (sep_pkg::NUM_AP_OUTPUT_REMAP_REGIONS),
    .RegionBase         (sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR),
    .IdxStart           (sep_pkg::AP_OUTPUT_REMAP_IDX_START),
    .UserOverrideEn     (1'b1),
    .UserOverrideVal    (sep_pkg::OTHERS_SOURCE_ID)
  ) u_ap_remap (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .test_en_i          (test_en_i),

    .remap_ctrl_i       (ap_output_remap_reg_ctrl),

    .axi_req_i          (sep_system_peripheral_56_remapped_from_demux_axi_reqs[sep_pkg::SEP_EXT_AP_REMAP]),
    .axi_resp_o         (sep_system_peripheral_56_remapped_from_demux_axi_resps[sep_pkg::SEP_EXT_AP_REMAP]),
    .axi_remapped_req_o (sep_ap_remapped_axi_req),
    .axi_remapped_resp_i(sep_ap_remapped_axi_resp)
  );

  ////////////////////////
  // STEE Address Remap //
  ////////////////////////

  output_remap #(
    .axi_req_t          (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t         (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .remap_addr_t       (sep_pkg::sep_56_64_6_12_axi_addr_t),
    .user_ovrd_t        (sep_pkg::sep_56_64_6_12_axi_user_t),
    .NumRegions         (sep_pkg::NUM_STEE_OUTPUT_REMAP_REGIONS),
    .RegionBase         (sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR),
    .IdxStart           (sep_pkg::STEE_OUTPUT_REMAP_IDX_START),
    .UserOverrideEn     (1'b1),
    .UserOverrideVal    (sep_pkg::OTHERS_SOURCE_ID)
  ) u_stee_remap (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .test_en_i          (test_en_i),

    .remap_ctrl_i       (stee_output_remap_reg_ctrl),

    .axi_req_i          (sep_system_peripheral_56_remapped_from_demux_axi_reqs[sep_pkg::SEP_EXT_STEE_REMAP]),
    .axi_resp_o         (sep_system_peripheral_56_remapped_from_demux_axi_resps[sep_pkg::SEP_EXT_STEE_REMAP]),
    .axi_remapped_req_o (sep_stee_remapped_axi_req),
    .axi_remapped_resp_i(sep_stee_remapped_axi_resp)
  );

  ////////////////////////////////
  // AXI Mux to Outbound Filter //
  ////////////////////////////////

  axi_mux #(
    .slv_aw_chan_t               (sep_pkg::sep_system_peripherals_internal_axi_aw_chan_t),
    .mst_aw_chan_t               (sep_pkg::sep_system_peripherals_outbound_axi_aw_chan_t),
    .w_chan_t                    (sep_pkg::sep_system_peripherals_internal_axi_w_chan_t),
    .slv_b_chan_t                (sep_pkg::sep_system_peripherals_internal_axi_b_chan_t),
    .mst_b_chan_t                (sep_pkg::sep_system_peripherals_outbound_axi_b_chan_t),
    .slv_ar_chan_t               (sep_pkg::sep_system_peripherals_internal_axi_ar_chan_t),
    .mst_ar_chan_t               (sep_pkg::sep_system_peripherals_outbound_axi_ar_chan_t),
    .slv_r_chan_t                (sep_pkg::sep_system_peripherals_internal_axi_r_chan_t),
    .mst_r_chan_t                (sep_pkg::sep_system_peripherals_outbound_axi_r_chan_t),
    .slv_req_t                   (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .slv_resp_t                  (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .mst_req_t                   (sep_pkg::sep_system_peripherals_outbound_axi_req_t),
    .mst_resp_t                  (sep_pkg::sep_system_peripherals_outbound_axi_resp_t),
    .SlvAxiIDWidth               (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ID_WIDTH),
    .NoSlvPorts                  (sep_pkg::OUTBOUND_FILTER_MUX_PORTS),
    .MaxWTrans                   (16),
    .FallThrough                 (1'b0),
    .SpillAw                     (1'b0),
    .SpillW                      (1'b0),
    .SpillB                      (1'b0),
    .SpillAr                     (1'b0),
    .SpillR                      (1'b0)
  ) u_outbound_filter_mux (
    .clk_i                       (clk_i),
    .rst_ni                      (rst_ni),
    .test_i                      (test_en_i),
    .slv_reqs_i                  ({sep_ap_remapped_axi_req, sep_stee_remapped_axi_req, sep_system_peripheral_56_remapped_from_demux_axi_reqs[sep_pkg::SEP_EXT_TO_SMU]}),
    .slv_resps_o                 ({sep_ap_remapped_axi_resp, sep_stee_remapped_axi_resp, sep_system_peripheral_56_remapped_from_demux_axi_resps[sep_pkg::SEP_EXT_TO_SMU]}),
    .mst_req_o                   (pre_outbound_filter_axi_req),
    .mst_resp_i                  (pre_outbound_filter_axi_resp)
  );

  /////////////////////////
  // AXI Outbound Filter //
  /////////////////////////

  axi_filter_wrap #(
    .NumFilters                  (sep_pkg::OUTBOUND_FILTER_NUM_FILTERS),
    .DebugOutput                 (1),
    .BlockByDefault              (1'b1),
    .EnSrcIdFilter               (1'b1),
    .SrcIdUserBitStart           (0),
    .SrcIdWidth                  (4), // Matches the 4-bit FILTER_CONFIG.src_id CSR field
    .EnGroupIdFilter             (1'b0),
    .GroupIdUserBitStart         (4),
    .GroupIdWidth                (4),
    .EnNsFilter                  (1'b1),
    .AxiAddrWidth                (sep_pkg::SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_ADDR_WIDTH),
    .AxiIdWidth                  (sep_pkg::SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_ID_WIDTH),
    .AxiDataWidth                (sep_pkg::SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_DATA_WIDTH),
    .MaxTrans                    (16),
    .ErrSlvMaxTrans              (32),
    .FlopReqEn                   (1'b1),
    .FlopRespEn                  (1'b1),
    .filter_axi_req_t            (sep_pkg::sep_system_peripherals_outbound_axi_req_t),
    .filter_axi_resp_t           (sep_pkg::sep_system_peripherals_outbound_axi_resp_t),
    .filter_aw_chan_t            (sep_pkg::sep_system_peripherals_outbound_axi_aw_chan_t),
    .filter_w_chan_t             (sep_pkg::sep_system_peripherals_outbound_axi_w_chan_t),
    .filter_b_chan_t             (sep_pkg::sep_system_peripherals_outbound_axi_b_chan_t),
    .filter_ar_chan_t            (sep_pkg::sep_system_peripherals_outbound_axi_ar_chan_t),
    .filter_r_chan_t             (sep_pkg::sep_system_peripherals_outbound_axi_r_chan_t)
  ) u_outbound_filter (
    .clk_i                       (clk_i),
    .rst_ni                      (rst_ni),
    .test_en_i                   (test_en_i),
    .filter_skip_i               (outbound_filter_skip_i),

    .filter_ctrl_i               (outbound_filter_ctrl),
    .filter_status_o             (outbound_filter_status),

    .axi_in_req_i                (pre_outbound_filter_axi_req),
    .axi_in_resp_o               (pre_outbound_filter_axi_resp),

    .axi_filtered_out_req_o      (smn_outbound_axi_req_o),
    .axi_filtered_out_resp_i     (smn_outbound_axi_resp_i),

    .write_filter_hit_debug_o    (outbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o     (outbound_read_filter_hit_debug_o)
  );

  ////////////////////////
  // AXI Inbound Filter //
  ////////////////////////

  axi_filter_wrap #(
    .NumFilters                  (sep_pkg::INBOUND_FILTER_NUM_FILTERS),
    .DebugOutput                 (1),
    .BlockByDefault              (1'b1),
    .EnSrcIdFilter               (1'b1),
    .SrcIdUserBitStart           (0),
    .SrcIdWidth                  (4), // Matches the 4-bit FILTER_CONFIG.src_id CSR field
    .EnGroupIdFilter             (1'b0),
    .GroupIdUserBitStart         (4),
    .GroupIdWidth                (4),
    .EnNsFilter                  (1'b1),
    .AxiAddrWidth                (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ADDR_WIDTH),
    .AxiIdWidth                  (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ID_WIDTH),
    .AxiDataWidth                (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_DATA_WIDTH),
    .MaxTrans                    (16),
    .ErrSlvMaxTrans              (32),
    .FlopReqEn                   (1'b1),
    .FlopRespEn                  (1'b0),
    .filter_axi_req_t            (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .filter_axi_resp_t           (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .filter_aw_chan_t            (sep_pkg::sep_system_peripherals_internal_axi_aw_chan_t),
    .filter_w_chan_t             (sep_pkg::sep_system_peripherals_internal_axi_w_chan_t),
    .filter_b_chan_t             (sep_pkg::sep_system_peripherals_internal_axi_b_chan_t),
    .filter_ar_chan_t            (sep_pkg::sep_system_peripherals_internal_axi_ar_chan_t),
    .filter_r_chan_t             (sep_pkg::sep_system_peripherals_internal_axi_r_chan_t)
  ) u_inbound_filter (
    .clk_i                       (clk_i),
    .rst_ni                      (rst_ni),
    .test_en_i                   (test_en_i),
    .filter_skip_i               (inbound_filter_skip_i),

    .filter_ctrl_i               (inbound_filter_ctrl),
    .filter_status_o             (inbound_filter_status),

    .axi_in_req_i                (smn_inbound_axi_req_i),
    .axi_in_resp_o               (smn_inbound_axi_resp_o),
    .axi_filtered_out_req_o      (smn_inbound_filtered_axi_req),
    .axi_filtered_out_resp_i     (smn_inbound_filtered_axi_resp),
    .write_filter_hit_debug_o    (inbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o     (inbound_read_filter_hit_debug_o)
  );

  ///////////////////////////////////////////////
  // AXI Inbound Global -> Local Address Remap //
  ///////////////////////////////////////////////

  axi_window_remap #(
    .axi_req_t      (sep_pkg::sep_system_peripherals_internal_axi_req_t),
    .axi_resp_t     (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
    .AXI_ADDR_WIDTH (sep_pkg::SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ADDR_WIDTH)
  ) u_inbound_global_to_local_addr_remap (
    .slv_req_i          (smn_inbound_filtered_axi_req),
    .slv_resp_o         (smn_inbound_filtered_axi_resp),
    .mst_req_o          (smn_inbound_filtered_from_local_axi_req),
    .mst_resp_i         (smn_inbound_filtered_from_local_axi_resp),
    .local_alias_base_i (sep_global_base_addr),
    .region_size_i      (sep_region_size),
    .target_base_i      ('0)
  );

  /////////////
  // Mailbox //
  /////////////

  // Address width conversion (56->32 bits) for mailbox from crossbar
  prim_axil_addr_fixer #(
    .INPUT_ADDR_W                (sep_pkg::SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH),
    .OUTPUT_ADDR_W               (sep_pkg::SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_ADDR_WIDTH),
    .input_axi_req_t             (sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t),
    .input_axi_resp_t            (sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t),
    .output_axi_req_t            (sep_pkg::sep_system_peripherals_mailbox_axi_lite_req_t),
    .output_axi_resp_t           (sep_pkg::sep_system_peripherals_mailbox_axi_lite_resp_t)
  ) u_mailbox_addr_fixer (
    .axi_in_req_i                (mailbox_from_csr_axil_req),
    .axi_in_resp_o               (mailbox_from_csr_axil_resp),
    .axi_out_req_o               (mailbox_axil_req),
    .axi_out_resp_i              (mailbox_axil_resp)
  );

  axi_lite_mailbox_unit #(
    .NUM_MAILBOXES               (sep_pkg::NUM_MAILBOXES),
    .MAILBOX_DEPTH               (sep_pkg::MAILBOX_DEPTH),
    .MAX_TRANS                   (16),
    .MAILBOX_BASE_ADDR           (sep_top_addrmap_pkg::SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR),
    .MAILBOX_SIZE                (sep_pkg::MAILBOX_SIZE),

    .ADDR_WIDTH                  (sep_pkg::SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_ADDR_WIDTH),
    .DATA_WIDTH                  (sep_pkg::SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_DATA_WIDTH),
    .aw_chan_t                   (sep_pkg::sep_system_peripherals_mailbox_axi_lite_aw_chan_t),
    .w_chan_t                    (sep_pkg::sep_system_peripherals_mailbox_axi_lite_w_chan_t),
    .b_chan_t                    (sep_pkg::sep_system_peripherals_mailbox_axi_lite_b_chan_t),
    .ar_chan_t                   (sep_pkg::sep_system_peripherals_mailbox_axi_lite_ar_chan_t),
    .r_chan_t                    (sep_pkg::sep_system_peripherals_mailbox_axi_lite_r_chan_t),
    .axi_req_t                   (sep_pkg::sep_system_peripherals_mailbox_axi_lite_req_t),
    .axi_resp_t                  (sep_pkg::sep_system_peripherals_mailbox_axi_lite_resp_t)
  ) u_sep_axil_mailbox (
    .clk_i                       (clk_i),
    .rst_ni                      (rst_ni),
    .test_en_i                   (test_en_i),

    .mailbox_axi_req_i           (mailbox_axil_req),
    .mailbox_axi_resp_o          (mailbox_axil_resp),

    .inbound_interrupt_o         (mailbox_inbound_interrupt_o),
    .outbound_interrupt_o        (mailbox_outbound_interrupt_o)
  );

  /////////////////
  // System CSRs //
  /////////////////

  sep_system_csr u_sep_system_csr (
    .clk_i                                     (clk_i),
    .clk_ref_i                                 (clk_ref_i),
    .rst_ni                                    (rst_ni),
    .rst_warm_ni                               (rst_warm_ni),
    .test_en_i                                 (test_en_i),
    .scan_rst_ni                               (scan_rst_ni),

    .sep_system_csr_axil_req_i                 (system_csr_axil_req),
    .sep_system_csr_axil_resp_o                (system_csr_axil_resp),

    .local_masters_alias_remap_reg_ctrl_o      (local_masters_alias_remap_reg_ctrl),
    .ap_output_remap_reg_ctrl_o                (ap_output_remap_reg_ctrl),
    .stee_output_remap_reg_ctrl_o              (stee_output_remap_reg_ctrl),

    .outbound_filter_ctrl_o                    (outbound_filter_ctrl),
    .outbound_filter_status_i                  (outbound_filter_status),
    .inbound_filter_ctrl_o                     (inbound_filter_ctrl),
    .inbound_filter_status_i                   (inbound_filter_status),

    .sep_global_base_addr_o                    (sep_global_base_addr),
    .sep_local_base_addr_o                     (sep_local_base_addr_o),
    .sep_region_size_o                         (sep_region_size),
    .smu_global_base_addr_o                    (smu_global_base_addr),
    .smu_region_size_o                         (smu_region_size),

    .smc_fuse_sense_done_i                     (smc_fuse_sense_done_i),
    .sep_fuse_sense_done_i                     (sep_fuse_sense_done_i),


    .nmi_vec_o                                 (nmi_vec_o),

    .ext_trng_src_sel_o                        (ext_trng_src_sel_o),
    .km_wipe_state_o                           (km_wipe_state_o),
    .dma_reg_bus_err_i                         (dma_reg_bus_err_i),
    .dma_host_intg_err_i                       (dma_host_intg_err_i),
    .dma_err_clr_o                             (dma_err_clr_o),
    .periph_bus_err_i                          (periph_bus_err_i),
    .periph_bus_err_clr_o                      (periph_bus_err_clr_o)
  );

  ////////////////////
  // Local AXI Xbar //
  ////////////////////

  sep_system_peripherals_xbar_wrapper u_sep_system_peripherals_xbar_wrapper (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_i                             (test_en_i),

    // Input ports
    .sep_local_from_remap_req_i         (sep_system_peripheral_56_remapped_from_demux_axi_reqs[sep_pkg::SEP_LOCAL]),
    .sep_local_from_remap_resp_o        (sep_system_peripheral_56_remapped_from_demux_axi_resps[sep_pkg::SEP_LOCAL]),
    .smn_inbound_req_i                  (smn_inbound_filtered_from_local_axi_req),
    .smn_inbound_resp_o                 (smn_inbound_filtered_from_local_axi_resp),

    // Output ports
    .smn_inbound_from_xbar_axi_req_o    (smn_inbound_filtered_from_xbar_axi_req),
    .smn_inbound_from_xbar_axi_resp_i   (smn_inbound_filtered_from_xbar_axi_resp),
    .mailbox_req_o                      (mailbox_from_csr_axil_req),
    .mailbox_resp_i                     (mailbox_from_csr_axil_resp),
    .system_csr_req_o                   (system_csr_axil_req),
    .system_csr_resp_i                  (system_csr_axil_resp)
  );

  ///////////////////////////////////////////////////////////////////////////////
  // Inbound to SEP ID Remap (7->3 bits) & Addr width conversion (56->32 bits) //
  ///////////////////////////////////////////////////////////////////////////////

  // Addr truncation (56->32 bits)
  prim_axi_addr_fixer #(
    .INPUT_ADDR_W(sep_pkg::SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_ADDR_WIDTH),
    .OUTPUT_ADDR_W(sep_pkg::SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ADDR_WIDTH),
    .input_axi_req_t(sep_pkg::sep_system_peripherals_xbar_slv_axi_req_t),
    .input_axi_resp_t(sep_pkg::sep_system_peripherals_xbar_slv_axi_resp_t),
    .output_axi_req_t(sep_pkg::sep_system_peripherals_xbar_slv_32_axi_req_t),
    .output_axi_resp_t(sep_pkg::sep_system_peripherals_xbar_slv_32_axi_resp_t)
  ) u_inbound_filtered_downsized_addr_fixer (
    .axi_in_req_i(smn_inbound_filtered_from_xbar_axi_req),
    .axi_in_resp_o(smn_inbound_filtered_from_xbar_axi_resp),
    .axi_out_req_o(smn_inbound_filtered_downsized_axi_req),
    .axi_out_resp_i(smn_inbound_filtered_downsized_axi_resp)
  );

  // ID Remap (7->3 bits)
  prim_axi_id_converter #(
    .AXI_ADDR_WIDTH(sep_pkg::SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH(sep_pkg::SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_DATA_WIDTH),
    .AXI_USER_WIDTH(sep_pkg::SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_USER_WIDTH),
    .AXI_ID_WIDTH_IN(sep_pkg::SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ID_WIDTH),
    .AXI_ID_WIDTH_OUT(sep_pkg::SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_ID_WIDTH),

    .input_axi_req_t(sep_pkg::sep_system_peripherals_xbar_slv_32_axi_req_t),
    .input_axi_resp_t(sep_pkg::sep_system_peripherals_xbar_slv_32_axi_resp_t),
    .output_axi_req_t(sep_pkg::sep_system_peripherals_inbound_to_sep_axi_req_t),
    .output_axi_resp_t(sep_pkg::sep_system_peripherals_inbound_to_sep_axi_resp_t),

    .MAX_INFLIGHT_IDS(4),
    .MAX_TXNS_PER_ID(4)
  ) u_inbound_to_sep_id_remap (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_en_i(test_en_i),

    .axi_in_req_i(smn_inbound_filtered_downsized_axi_req),
    .axi_in_resp_o(smn_inbound_filtered_downsized_axi_resp),
    .axi_out_req_o(smn_inbound_to_sep_axi_req_o),
    .axi_out_resp_i(smn_inbound_to_sep_axi_resp_i)
  );

  // Export sep_region_size so SMU can size its SEP-aperture xbar rule.
  // (The local alias remap window is sized by sep_pkg::SEP_LOCAL_ALIAS_REGION_SIZE.)
  assign sep_region_size_o = sep_region_size;

  // Export sep_global_base_addr so parents can build the SMU xbar rule.
  assign sep_global_base_addr_o = sep_global_base_addr;

endmodule

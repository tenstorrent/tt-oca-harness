// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Input Fabric

module smc_input_fabric #(
  parameter bit          FilterReqPipelineEnable = 1'b0,
  parameter bit          FilterRspPipelineEnable = 1'b0,
  parameter int unsigned NumFilters              = 16
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,
  input  logic scan_rst_ni,

  input  logic                filter_axi_cg_en_i,
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,

  // Configuration Bits
  input  smc_pkg::smc_axi_addr_t global_base_addr_i,
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,
  input  logic [31:0]            region_size_i,

  // JTAG AXI Input
  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  axi_in_jtag_req_i,
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t axi_in_jtag_resp_o,

  // MMIO AXI Input
  input  smc_pkg::smc_cpu_mmio_axi_req_t  axi_in_mmio_req_i,
  output smc_pkg::smc_cpu_mmio_axi_resp_t axi_in_mmio_resp_o,

  // Data Accelerator AXI Input
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_data_accel_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_data_accel_resp_o,

  // Log AXI-Lite Input
  input  smc_pkg::smc_axil_56_64_req_t  axi_lite_log_req_i,
  output smc_pkg::smc_axil_56_64_resp_t axi_lite_log_resp_o,

  // Local AXI Output
  output smc_pkg::smc_local_32_64_6_12_axi_req_t  axi_local_out_req_o,
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t axi_local_out_resp_i,

  // Global AXI Output
  output smc_pkg::smc_56_64_6_12_axi_req_t  axi_out_req_o,
  input  smc_pkg::smc_56_64_6_12_axi_resp_t axi_out_resp_i,

  // System AXI Input
  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,
  output smc_pkg::smc_local_32_64_6_12_axi_req_t   filtered_sys_axi_out_req_o,
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t  filtered_sys_axi_out_resp_i,

  // SEP AXI Input
  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,
  output smc_pkg::smc_local_32_64_6_12_axi_req_t   sep_axi_id_remap_req_o,
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t  sep_axi_id_remap_resp_i,

  // Config struct from register block -- filter
  input  filter_ctrl_reg_pkg::filter_ctrl__out_t filter_ctrl_i [NumFilters-1:0],
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  filter_status_o [NumFilters-1:0],

  // Config struct from register block -- alias remap
  input  alias_remap_reg_pkg::alias_remap__out_t aR_ctrl_i [smc_pkg::NUM_ALIAS_REMAP_REGIONS-1:0],

  // debug structs
  output smc_pkg::remap_debug_t         remap_debug_mmio_o,
  output smc_pkg::remap_debug_t         remap_debug_jtag_o,
  output smc_pkg::remap_debug_t         remap_debug_log_o,
  output smc_pkg::remap_debug_t         remap_debug_dma_o,
  output logic [$clog2(NumFilters)-1:0] write_filter_hit_debug_o,
  output logic [$clog2(NumFilters)-1:0] read_filter_hit_debug_o,

  // Clock gater activity indicators
  output logic sys_in_filter_clk_active_o,
  output logic sys_in_filter_bus_active_o
);

  `include "axi/assign.svh"

  /////////////////////////
  // ID Conversion Logic //
  /////////////////////////

  // Convert MMIO AXI port from CPU to Fabric (ID: 3 -> 4)
  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_mmio_port_req_prepend_id;
  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_mmio_port_resp_prepend_id;

  prim_axi_id_converter #(
    .AXI_ADDR_WIDTH     (smc_pkg::AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH     (smc_pkg::AXI_DATA_WIDTH),
    .AXI_ID_WIDTH_IN    (smc_pkg::SMC_CPU_MMIO_AXI_ID_WIDTH),
    .AXI_ID_WIDTH_OUT   (smc_pkg::SMC_INPUT_FABRIC_SLAVE_ID_WIDTH),

    .input_axi_req_t    (smc_pkg::smc_cpu_mmio_axi_req_t),
    .input_axi_resp_t   (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .output_axi_req_t   (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .output_axi_resp_t  (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t)
  ) u_axi_mmio_id_converter (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .test_en_i          (test_en_i),

    .axi_in_req_i       (axi_in_mmio_req_i),
    .axi_in_resp_o      (axi_in_mmio_resp_o),
    .axi_out_req_o      (axi_mmio_port_req_prepend_id),
    .axi_out_resp_i     (axi_mmio_port_resp_prepend_id)
  );

  // Convert JTAG AXI port into Fabric (ID: 2 -> 4)
  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_jtag_port_req_prepend_id;
  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_jtag_port_resp_prepend_id;

  prim_axi_id_converter #(
    .AXI_ADDR_WIDTH    (smc_pkg::AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH    (smc_pkg::AXI_DATA_WIDTH),
    .AXI_ID_WIDTH_IN   (smc_pkg::JTAG_ID_WIDTH),
    .AXI_ID_WIDTH_OUT  (smc_pkg::SMC_INPUT_FABRIC_SLAVE_ID_WIDTH),

    .input_axi_req_t   (smc_pkg::smc_jtag_56_64_2_12_axi_req_t),
    .input_axi_resp_t  (smc_pkg::smc_jtag_56_64_2_12_axi_resp_t),
    .output_axi_req_t  (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .output_axi_resp_t (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t)
  ) u_axi_jtag_id_converter (
    .clk_i         (clk_i),
    .rst_ni        (rst_ni),
    .test_en_i     (test_en_i),

    .axi_in_req_i  (axi_in_jtag_req_i),
    .axi_in_resp_o (axi_in_jtag_resp_o),
    .axi_out_req_o (axi_jtag_port_req_prepend_id),
    .axi_out_resp_i(axi_jtag_port_resp_prepend_id)
  );

  ///////////////////////////////////
  // Log AXI-Lite to AXI Interface //
  ///////////////////////////////////

  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  log_axi_req;
  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t     log_axi_resp;

  axi_lite_to_axi #(
    .AxiDataWidth       (smc_pkg::AXI_DATA_WIDTH),
    .req_lite_t         (smc_pkg::smc_axil_56_64_req_t),
    .resp_lite_t        (smc_pkg::smc_axil_56_64_resp_t),
    .axi_req_t          (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t         (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t)
  ) log_axi_lite_to_axi (
    .slv_req_lite_i     (axi_lite_log_req_i),
    .slv_resp_lite_o    (axi_lite_log_resp_o),
    .slv_aw_cache_i     ('0),
    .slv_ar_cache_i     ('0),
    .mst_req_o          (log_axi_req),
    .mst_resp_i         (log_axi_resp)
  );

  /////////////////
  // Alias Remap //
  /////////////////

  smc_pkg::input_fabric_mux_axi_req_t         axi_to_input_mux_req;
  smc_pkg::input_fabric_mux_axi_resp_t        axi_to_input_mux_resp;

  smc_alias_remap_wrap smc_alias_remap_wrap (
    .axi_in_jtag_req_i(axi_jtag_port_req_prepend_id),
    .axi_in_jtag_resp_o(axi_jtag_port_resp_prepend_id),

    .axi_in_log_req_i(log_axi_req),
    .axi_in_log_resp_o(log_axi_resp),

    .axi_in_mmio_req_i(axi_mmio_port_req_prepend_id),
    .axi_in_mmio_resp_o(axi_mmio_port_resp_prepend_id),

    .axi_in_data_accel_req_i(axi_in_data_accel_req_i),
    .axi_in_data_accel_resp_o(axi_in_data_accel_resp_o),

    .axi_out_remapped_mmio_req_o(axi_to_input_mux_req.mmio),
    .axi_out_remapped_mmio_resp_i(axi_to_input_mux_resp.mmio),

    .axi_out_remapped_jtag_req_o(axi_to_input_mux_req.jtag),
    .axi_out_remapped_jtag_resp_i(axi_to_input_mux_resp.jtag),

    .axi_out_remapped_log_req_o(axi_to_input_mux_req.log),
    .axi_out_remapped_log_resp_i(axi_to_input_mux_resp.log),

    .axi_out_remapped_data_accel_req_o(axi_to_input_mux_req.data_accel),
    .axi_out_remapped_data_accel_resp_i(axi_to_input_mux_resp.data_accel),
    .aR_ctrl_i(aR_ctrl_i),

    .o_remap_debug_mmio(remap_debug_mmio_o),
    .o_remap_debug_jtag(remap_debug_jtag_o),
    .o_remap_debug_log(remap_debug_log_o),
    .o_remap_debug_dma(remap_debug_dma_o)
  );

  smc_pkg::smc_56_64_6_12_axi_req_t   axi_from_input_mux_req;
  smc_pkg::smc_56_64_6_12_axi_resp_t  axi_from_input_mux_resp;

  axi_mux #(
    .SlvAxiIDWidth      (smc_pkg::SMC_INPUT_FABRIC_SLAVE_ID_WIDTH),
    .slv_aw_chan_t      (smc_pkg::smc_input_fabric_56_64_4_12_axi_aw_chan_t),
    .mst_aw_chan_t      (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
    .w_chan_t           (smc_pkg::smc_input_fabric_56_64_4_12_axi_w_chan_t),
    .slv_b_chan_t       (smc_pkg::smc_input_fabric_56_64_4_12_axi_b_chan_t),
    .mst_b_chan_t       (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
    .slv_ar_chan_t      (smc_pkg::smc_input_fabric_56_64_4_12_axi_ar_chan_t),
    .mst_ar_chan_t      (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
    .slv_r_chan_t       (smc_pkg::smc_input_fabric_56_64_4_12_axi_r_chan_t),
    .mst_r_chan_t       (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
    .slv_req_t          (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .slv_resp_t         (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .mst_req_t          (smc_pkg::smc_56_64_6_12_axi_req_t),
    .mst_resp_t         (smc_pkg::smc_56_64_6_12_axi_resp_t),
    .NoSlvPorts         (smc_pkg::NUM_ALIAS_REMAP_INPUTS),
    .MaxWTrans          (smc_pkg::FABRIC_MAX_TRANS),
    .FallThrough        (1'b0),
    .SpillAw            (1'b1),
    .SpillW             (1'b1),
    .SpillB             (1'b1),
    .SpillAr            (1'b1),
    .SpillR             (1'b1)
  ) smc_input_axi_mux (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .test_i             (test_en_i),
    .slv_reqs_i         (axi_to_input_mux_req),
    .slv_resps_o        (axi_to_input_mux_resp),
    .mst_req_o          (axi_from_input_mux_req),
    .mst_resp_i         (axi_from_input_mux_resp)
  );

  logic local_space_write;
  logic local_space_read;

  // One bit wider than the address so a base near the top of the 56-bit space cannot
  // wrap the end address and make the window compare pass on unrelated addresses.
  logic [smc_pkg::AXI_ADDR_WIDTH:0] local_region_end;
  logic [smc_pkg::AXI_ADDR_WIDTH:0] global_region_end;

  assign local_region_end  = {1'b0, local_base_addr_i}  + region_size_i;
  assign global_region_end = {1'b0, global_base_addr_i} + region_size_i;

  always_comb begin
    local_space_write = (axi_from_input_mux_req.aw.addr >= local_base_addr_i)  && ({1'b0, axi_from_input_mux_req.aw.addr} < local_region_end) ||
                            (axi_from_input_mux_req.aw.addr >= global_base_addr_i) && ({1'b0, axi_from_input_mux_req.aw.addr} < global_region_end);
    local_space_read  = (axi_from_input_mux_req.ar.addr >= local_base_addr_i)  && ({1'b0, axi_from_input_mux_req.ar.addr} < local_region_end) ||
                            (axi_from_input_mux_req.ar.addr >= global_base_addr_i) && ({1'b0, axi_from_input_mux_req.ar.addr} < global_region_end);
  end

  // The demux should be 56 bit address width
  // Using struct to access local_fabric and output_fabric paths
  smc_pkg::input_fabric_demux_axi_req_t  axi_from_demux_req;
  smc_pkg::input_fabric_demux_axi_resp_t axi_from_demux_resp;

  axi_demux #(
    .AxiIdWidth     (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
    .AtopSupport    (1'b0),
    .aw_chan_t      (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
    .w_chan_t       (smc_pkg::smc_56_64_6_12_axi_w_chan_t),
    .b_chan_t       (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
    .ar_chan_t      (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
    .r_chan_t       (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
    .axi_req_t      (smc_pkg::smc_56_64_6_12_axi_req_t),
    .axi_resp_t     (smc_pkg::smc_56_64_6_12_axi_resp_t),
    .NoMstPorts     (2),
    .MaxTrans       (smc_pkg::FABRIC_MAX_TRANS),
    .AxiLookBits    (smc_pkg::FABRIC_ID_LOOKUP_BITS),
    .UniqueIds      (1'b0),
    .SpillAw        (1'b1),
    .SpillW         (1'b0),
    .SpillB         (1'b0),
    .SpillAr        (1'b1),
    .SpillR         (1'b0)
  ) smc_local_global_demux (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .test_i             (test_en_i),
    .sel_hash_i         (2'd0),  // unused
    .slv_req_i          (axi_from_input_mux_req),
    .slv_aw_select_i    (local_space_write),
    .slv_ar_select_i    (local_space_read),
    .slv_resp_o         (axi_from_input_mux_resp),
    .mst_reqs_o         (axi_from_demux_req),
    .mst_resps_i        (axi_from_demux_resp)
  );

  // Converting 56 -> 32 for local fabric
  prim_axi_addr_fixer #(
    .INPUT_ADDR_W       (smc_pkg::AXI_ADDR_WIDTH),
    .OUTPUT_ADDR_W      (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
    .input_axi_req_t    (smc_pkg::smc_56_64_6_12_axi_req_t),
    .input_axi_resp_t   (smc_pkg::smc_56_64_6_12_axi_resp_t),
    .output_axi_req_t   (smc_pkg::smc_local_32_64_6_12_axi_req_t),
    .output_axi_resp_t  (smc_pkg::smc_local_32_64_6_12_axi_resp_t)
  ) smc_axi_addr_fixer (
    .axi_in_req_i       (axi_from_demux_req.local_fabric),
    .axi_in_resp_o      (axi_from_demux_resp.local_fabric),
    .axi_out_req_o      (axi_local_out_req_o),
    .axi_out_resp_i     (axi_local_out_resp_i)
  );

  assign axi_out_req_o = axi_from_demux_req.output_fabric;
  assign axi_from_demux_resp.output_fabric = axi_out_resp_i;

  ///////////////////////////////////////////////////////////
  // Sys Input Filter + Address Width Converter (56 -> 32) //
  ///////////////////////////////////////////////////////////

  // System Input Filter
  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t    sys_axi_in_filtered_req;
  smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t   sys_axi_in_filtered_resp;

  logic filter_clk; // gated clock for AXI filter

  axi_cg_snoop #(
    // ALL IDs, both directions
    .OutstandingTx(smc_pkg::FABRIC_OUTSTANDING_TX),
    .DenyDelay(1),
    .HystWidth(smc_pkg::CG_HYSTERESIS_W)
  ) sys_in_filter_cg (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    .snoop_aw_valid_i(sys_axi_in_req_i.aw_valid),
    .snoop_aw_ready_i(sys_axi_in_resp_o.aw_ready),
    .snoop_w_valid_i (sys_axi_in_req_i.w_valid),
    .snoop_b_valid_i (sys_axi_in_resp_o.b_valid),
    .snoop_b_ready_i (sys_axi_in_req_i.b_ready),
    .snoop_ar_valid_i(sys_axi_in_req_i.ar_valid),
    .snoop_ar_ready_i(sys_axi_in_resp_o.ar_ready),
    .snoop_r_valid_i (sys_axi_in_resp_o.r_valid),
    .snoop_r_ready_i (sys_axi_in_req_i.r_ready),
    .snoop_r_last_i  (sys_axi_in_resp_o.r.last),

    .kick_i          (~filter_axi_cg_en_i), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_hysteresis_i),
    .clk_active_o    (sys_in_filter_clk_active_o),
    .gated_clk_o     (filter_clk),
    .bus_active_o    (sys_in_filter_bus_active_o)
  );

  axi_filter_wrap #(
    .NumFilters          (NumFilters),
    .DebugOutput         (0),
    .BlockByDefault      (1'b1),
    .EnSrcIdFilter       (1'b1),
    .SrcIdUserBitStart   (0),
    .SrcIdWidth          (4),
    .EnGroupIdFilter     (1'b0),
    .GroupIdUserBitStart (4),
    .GroupIdWidth        (4),
    .EnNsFilter          (1'b1),
    .AxiAddrWidth        (smc_pkg::AXI_ADDR_WIDTH),
    .AxiIdWidth          (smc_pkg::SYS_IN_ID_WIDTH),
    .AxiDataWidth        (smc_pkg::AXI_DATA_WIDTH),
    .MaxTrans            (smc_pkg::FABRIC_MAX_TRANS),
    .AxiLookBits         (smc_pkg::FABRIC_ID_LOOKUP_BITS),
    .ErrSlvMaxTrans      (smc_pkg::ERR_SLV_MAX_TRANS),
    .FlopReqEn           (FilterReqPipelineEnable),
    .FlopRespEn          (FilterRspPipelineEnable),
    .filter_axi_req_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
    .filter_axi_resp_t   (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
    .filter_aw_chan_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_aw_chan_t),
    .filter_w_chan_t     (smc_pkg::smc_sys_in_56_64_6_12_axi_w_chan_t),
    .filter_b_chan_t     (smc_pkg::smc_sys_in_56_64_6_12_axi_b_chan_t),
    .filter_ar_chan_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_ar_chan_t),
    .filter_r_chan_t     (smc_pkg::smc_sys_in_56_64_6_12_axi_r_chan_t)
  ) smc_sys_inbound_filter (
    .clk_i                      (filter_clk),
    .rst_ni                     (rst_ni),
    .test_en_i                  (test_en_i),

    .filter_skip_i              (1'b0),

    // Config struct from register block
    .filter_ctrl_i              (filter_ctrl_i),
    .filter_status_o            (filter_status_o),

    // AXI interface to the filter
    .axi_in_req_i               (sys_axi_in_req_i),
    .axi_in_resp_o              (sys_axi_in_resp_o),

    // AXI interface to the filtered output
    .axi_filtered_out_req_o     (sys_axi_in_filtered_req),
    .axi_filtered_out_resp_i    (sys_axi_in_filtered_resp),

    .write_filter_hit_debug_o   (write_filter_hit_debug_o),
    .read_filter_hit_debug_o    (read_filter_hit_debug_o)
  );


  // SYS IN AXI Address Width Converter (56 -> 32)
  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(filtered_sys_axi_out_req_o, filtered_sys_axi_out_resp_i,
                                     sys_axi_in_filtered_req, sys_axi_in_filtered_resp,
                                     smc_pkg::smc_axi_local_addr_t)

  // SEP AXI Address Width Converter (56 -> 32)
  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(sep_axi_id_remap_req_o, sep_axi_id_remap_resp_i,
                                     sep_axi_in_req_i, sep_axi_in_resp_o,
                                     smc_pkg::smc_axi_local_addr_t)

endmodule

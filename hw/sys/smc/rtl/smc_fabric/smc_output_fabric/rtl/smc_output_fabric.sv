// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Output Fabric

module smc_output_fabric #(
  parameter bit          NO_ADDR_REMAP           = 1'b1,
  parameter int unsigned NumFilters              = 16,
  parameter int unsigned MaxTrans                = smc_pkg::FABRIC_MAX_TRANS,
  parameter bit          FilterReqPipelineEnable = 1'b0,
  parameter bit          FilterRspPipelineEnable = 1'b0,
  parameter int unsigned MmodeBaseAddr           = smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_BASE_ADDR,
  parameter int unsigned XvisorBaseAddr          = smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_BASE_ADDR
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,

  input  smc_pkg::smc_axi_addr_t global_base_addr_i,
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,

  input  logic                filter_axi_cg_en_i,
  input  logic                fabric_cg_en_i,
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,

  // AXI interface
  input  smc_pkg::smc_56_64_6_12_axi_req_t  axi_req_i,
  output smc_pkg::smc_56_64_6_12_axi_resp_t axi_resp_o,

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  axi_filtered_remapped_req_o,
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t axi_filtered_remapped_resp_i,

  // Config struct from register block
  input  filter_ctrl_reg_pkg::filter_ctrl__out_t filter_ctrl_i [NumFilters-1:0],
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  filter_status_o [NumFilters-1:0],

  // CSR structs for remap configurations
  input  output_remap_reg_pkg::output_remap__out_t mR_ctrl_i [smc_pkg::NUM_MMODE_OUTPUT_REMAP_REGIONS-1:0],
  input  output_remap_reg_pkg::output_remap__out_t xR_ctrl_i [smc_pkg::NUM_XVISOR_OUTPUT_REMAP_REGIONS-1:0],

  output logic [$clog2(NumFilters)-1:0] write_filter_hit_debug_o,
  output logic [$clog2(NumFilters)-1:0] read_filter_hit_debug_o,

  // Clock gater activity indicators
  output logic fabric_clk_active_o,
  output logic fabric_bus_active_o,
  output logic sys_out_filter_clk_active_o,
  output logic sys_out_filter_bus_active_o
);

  `include "ocah_assert.svh"

  //////////////
  // Typedefs //
  //////////////

  // Internal AXI struct signals
  smc_pkg::smc_output_56_64_8_12_axi_req_t  axi_remapped_to_filter_req; // ID = 8
  smc_pkg::smc_output_56_64_8_12_axi_resp_t axi_remapped_to_filter_resp;

  /////////////////////////////
  // AXI-Lite Register Demux //
  /////////////////////////////

  if (NO_ADDR_REMAP == 1'b1) begin : gen_stub_remap

    // Pass through main AXI data path (no remapping), still need ID width conversion
    prim_axi_id_converter #(
      .AXI_ADDR_WIDTH   (smc_pkg::AXI_ADDR_WIDTH),
      .AXI_DATA_WIDTH   (smc_pkg::AXI_DATA_WIDTH),
      .AXI_ID_WIDTH_IN  (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
      .AXI_ID_WIDTH_OUT (smc_pkg::SMC_OUTPUT_FABRIC_MASTER_ID_WIDTH),

      .input_axi_req_t (smc_pkg::smc_56_64_6_12_axi_req_t),
      .input_axi_resp_t (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .output_axi_req_t (smc_pkg::smc_output_56_64_8_12_axi_req_t),
      .output_axi_resp_t (smc_pkg::smc_output_56_64_8_12_axi_resp_t)
    ) u_prim_axi_id_converter (
      .clk_i              (clk_i),
      .rst_ni             (rst_ni),
      .test_en_i          (test_en_i),

      .axi_in_req_i       (axi_req_i),
      .axi_in_resp_o      (axi_resp_o),
      .axi_out_req_o      (axi_remapped_to_filter_req),
      .axi_out_resp_i     (axi_remapped_to_filter_resp)
    );

    assign fabric_clk_active_o = 1'b0;
    assign fabric_bus_active_o  = 1'b0;

  end else begin : gen_remap

    ////////////////////////
    // Remap Clock Gating //
    ////////////////////////

    logic fabric_clk;  // gated clock for fabric demux + mux

    axi_cg_snoop #(
      // ALL IDs, both directions: tracks the remap demux/mux below, which are sized by the
      // MaxTrans parameter of this module (per ID bucket) rather than by smc_pkg
      .OutstandingTx(smc_pkg::FABRIC_ID_BUCKETS * MaxTrans),
      .DenyDelay(1),
      .HystWidth(smc_pkg::CG_HYSTERESIS_W)
    ) u_fabric_cg (
      .clk_i           (clk_i),
      .rst_ni          (rst_ni),

      .snoop_aw_valid_i(axi_req_i.aw_valid),
      .snoop_aw_ready_i(axi_resp_o.aw_ready),
      .snoop_w_valid_i (axi_req_i.w_valid),
      .snoop_b_valid_i (axi_resp_o.b_valid),
      .snoop_b_ready_i (axi_req_i.b_ready),
      .snoop_ar_valid_i(axi_req_i.ar_valid),
      .snoop_ar_ready_i(axi_resp_o.ar_ready),
      .snoop_r_valid_i (axi_resp_o.r_valid),
      .snoop_r_ready_i (axi_req_i.r_ready),
      .snoop_r_last_i  (axi_resp_o.r.last),

      .kick_i          (~fabric_cg_en_i), // continuously kick to keep clock awake when not gating

      .test_clk_en_i   (test_en_i),
      .hysteresis_i    (cg_hysteresis_i),
      .clk_active_o    (fabric_clk_active_o),
      .gated_clk_o     (fabric_clk),
      .bus_active_o    (fabric_bus_active_o)
    );

    /////////////////////////
    // Main AXI Data Demux //
    /////////////////////////

    logic is_mmode_write_global, is_mmode_read_global;
    logic is_mmode_write_local, is_mmode_read_local;
    logic is_xvisor_write_global, is_xvisor_read_global;
    logic is_xvisor_write_local, is_xvisor_read_local;

    logic [1:0] write_slv_sel, read_slv_sel;

    always_comb begin
      // decode whether it's mmode or xvisor based on address
      is_mmode_write_global  = ((axi_req_i.aw.addr >= global_base_addr_i + smc_pkg::MMODE_REMAP_START) & (axi_req_i.aw.addr < global_base_addr_i + smc_pkg::MMODE_REMAP_START + smc_pkg::MMODE_REMAP_SIZE));
      is_mmode_write_local   = ((axi_req_i.aw.addr >= local_base_addr_i  + smc_pkg::MMODE_REMAP_START) & (axi_req_i.aw.addr < local_base_addr_i  + smc_pkg::MMODE_REMAP_START + smc_pkg::MMODE_REMAP_SIZE));
      is_mmode_read_global   = ((axi_req_i.ar.addr >= global_base_addr_i + smc_pkg::MMODE_REMAP_START) & (axi_req_i.ar.addr < global_base_addr_i + smc_pkg::MMODE_REMAP_START + smc_pkg::MMODE_REMAP_SIZE));
      is_mmode_read_local    = ((axi_req_i.ar.addr >= local_base_addr_i  + smc_pkg::MMODE_REMAP_START) & (axi_req_i.ar.addr < local_base_addr_i  + smc_pkg::MMODE_REMAP_START + smc_pkg::MMODE_REMAP_SIZE));

      is_xvisor_write_global = ((axi_req_i.aw.addr >= global_base_addr_i + smc_pkg::XVISOR_REMAP_START) & (axi_req_i.aw.addr < global_base_addr_i + smc_pkg::XVISOR_REMAP_START + smc_pkg::XVISOR_REMAP_SIZE));
      is_xvisor_write_local  = ((axi_req_i.aw.addr >= local_base_addr_i  + smc_pkg::XVISOR_REMAP_START) & (axi_req_i.aw.addr < local_base_addr_i  + smc_pkg::XVISOR_REMAP_START + smc_pkg::XVISOR_REMAP_SIZE));
      is_xvisor_read_global  = ((axi_req_i.ar.addr >= global_base_addr_i + smc_pkg::XVISOR_REMAP_START) & (axi_req_i.ar.addr < global_base_addr_i + smc_pkg::XVISOR_REMAP_START + smc_pkg::XVISOR_REMAP_SIZE));
      is_xvisor_read_local   = ((axi_req_i.ar.addr >= local_base_addr_i  + smc_pkg::XVISOR_REMAP_START) & (axi_req_i.ar.addr < local_base_addr_i  + smc_pkg::XVISOR_REMAP_START + smc_pkg::XVISOR_REMAP_SIZE));

      write_slv_sel = {
                (is_xvisor_write_global | is_xvisor_write_local),
                (is_mmode_write_global | is_mmode_write_local)
            };
      read_slv_sel = {
                (is_xvisor_read_global | is_xvisor_read_local),
                (is_mmode_read_global | is_mmode_read_local)
            };
    end

    smc_pkg::output_fabric_axi_struct_req_t   axi_from_demux_req; // ID = 6
    smc_pkg::output_fabric_axi_struct_resp_t  axi_from_demux_resp;

    smc_pkg::output_fabric_axi_struct_req_t   axi_remap_out_req; // ID = 6
    smc_pkg::output_fabric_axi_struct_resp_t  axi_remap_out_resp;

    axi_demux #(
      .AxiIdWidth         (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
      .AtopSupport        (1'b0),
      .aw_chan_t          (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
      .w_chan_t           (smc_pkg::smc_56_64_6_12_axi_w_chan_t),
      .b_chan_t           (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
      .ar_chan_t          (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
      .r_chan_t           (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
      .axi_req_t          (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t         (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .NoMstPorts         (3),
      .MaxTrans           (MaxTrans),
      .AxiLookBits        (smc_pkg::FABRIC_ID_LOOKUP_BITS),
      .UniqueIds          (1'b0),
      .SelHashIds         (1'b0),
      .SpillAw            (1'b0),
      .SpillW             (1'b0),
      .SpillB             (1'b0),
      .SpillAr            (1'b0),
      .SpillR             (1'b0)
    ) u_output_axi_demux (
      .clk_i              (fabric_clk),
      .rst_ni             (rst_ni),
      .test_i             (test_en_i),
      .sel_hash_i         (2'd0),  // unused

      .slv_req_i          (axi_req_i),
      .slv_resp_o         (axi_resp_o),
      .slv_aw_select_i    (write_slv_sel),
      .slv_ar_select_i    (read_slv_sel),

      .mst_reqs_o         (axi_from_demux_req),
      .mst_resps_i        (axi_from_demux_resp)
    );

    prim_axi_user_override_struct #(
      .AxiAddrWidth   (smc_pkg::AXI_ADDR_WIDTH),
      .AxiDataWidth   (smc_pkg::AXI_DATA_WIDTH),
      .AxiIdWidth     (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
      .AxiUserWidth   (smc_pkg::AXI_USER_WIDTH),
      .AxiUserOverride(smc_pkg::SMC_SRC_ID),

      .axi_req_t      (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t     (smc_pkg::smc_56_64_6_12_axi_resp_t)
    ) u_prim_axi_user_override_struct (
      .axi_in_req_i   (axi_from_demux_req.filter),
      .axi_in_resp_o  (axi_from_demux_resp.filter),
      .axi_out_req_o  (axi_remap_out_req.filter),
      .axi_out_resp_i (axi_remap_out_resp.filter)
    );

    output_remap #(
      .axi_req_t          (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t         (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .remap_addr_t       (smc_pkg::smc_axi_addr_t),
      .user_ovrd_t        (smc_pkg::smc_axi_user_t),
      .NumRegions         (smc_pkg::NUM_MMODE_OUTPUT_REMAP_REGIONS),
      .RegionBase         (MmodeBaseAddr),
      .IdxStart           (smc_pkg::OUTPUT_REMAP_IDX_START),
      .UserOverrideEn     (1'b1),
      .UserOverrideVal    (smc_pkg::MMODE_SRC_ID)
    ) u_mmode_addr_remap (
      .clk_i              (clk_i),
      .rst_ni             (rst_ni),
      .test_en_i          (test_en_i),

      .remap_ctrl_i       (mR_ctrl_i),

      .axi_req_i          (axi_from_demux_req.mmode),
      .axi_resp_o         (axi_from_demux_resp.mmode),
      .axi_remapped_req_o (axi_remap_out_req.mmode),
      .axi_remapped_resp_i(axi_remap_out_resp.mmode)
    );

    output_remap #(
      .axi_req_t          (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t         (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .remap_addr_t       (smc_pkg::smc_axi_addr_t),
      .user_ovrd_t        (smc_pkg::smc_axi_user_t),
      .NumRegions         (smc_pkg::NUM_XVISOR_OUTPUT_REMAP_REGIONS),
      .RegionBase         (XvisorBaseAddr),
      .IdxStart           (smc_pkg::OUTPUT_REMAP_IDX_START),
      .UserOverrideEn     (1'b1),
      .UserOverrideVal    (smc_pkg::OTHERS_SRC_ID)
    ) u_xvisor_addr_remap (
      .clk_i              (clk_i),
      .rst_ni             (rst_ni),
      .test_en_i          (test_en_i),

      .remap_ctrl_i       (xR_ctrl_i),

      .axi_req_i          (axi_from_demux_req.xvisor),
      .axi_resp_o         (axi_from_demux_resp.xvisor),
      .axi_remapped_req_o (axi_remap_out_req.xvisor),
      .axi_remapped_resp_i(axi_remap_out_resp.xvisor)
    );

    axi_mux #(
      .slv_aw_chan_t  (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
      .mst_aw_chan_t  (smc_pkg::smc_output_56_64_8_12_axi_aw_chan_t),
      .w_chan_t       (smc_pkg::smc_56_64_6_12_axi_w_chan_t),
      .slv_b_chan_t   (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
      .mst_b_chan_t   (smc_pkg::smc_output_56_64_8_12_axi_b_chan_t),
      .slv_ar_chan_t  (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
      .mst_ar_chan_t  (smc_pkg::smc_output_56_64_8_12_axi_ar_chan_t),
      .slv_r_chan_t   (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
      .mst_r_chan_t   (smc_pkg::smc_output_56_64_8_12_axi_r_chan_t),
      .slv_req_t      (smc_pkg::smc_56_64_6_12_axi_req_t),
      .slv_resp_t     (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .mst_req_t      (smc_pkg::smc_output_56_64_8_12_axi_req_t),
      .mst_resp_t     (smc_pkg::smc_output_56_64_8_12_axi_resp_t),
      .SlvAxiIDWidth  (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
      .NoSlvPorts     (3),
      .MaxWTrans      (MaxTrans),
      .FallThrough    (1'b0),
      .SpillAw        (1'b0),
      .SpillW         (1'b0),
      .SpillB         (1'b0),
      .SpillAr        (1'b0),
      .SpillR         (1'b0)
    ) u_output_mux (
      .clk_i          (fabric_clk),
      .rst_ni         (rst_ni),
      .test_i         (test_en_i),

      .slv_reqs_i     (axi_remap_out_req),
      .slv_resps_o    (axi_remap_out_resp),

      .mst_req_o      (axi_remapped_to_filter_req),
      .mst_resp_i     (axi_remapped_to_filter_resp)
    );

    // assertions
    `OCAH_ASSERT(out_remap_write_one_hot_sel, (~(|write_slv_sel) || $onehot(write_slv_sel)), clk_i,
                 !rst_ni)
    `OCAH_ASSERT(out_remap_read_one_hot_sel, (~(|read_slv_sel) || $onehot(read_slv_sel)), clk_i,
                 !rst_ni)

  end

  //////////////////
  // Filter Logic //
  //////////////////

  logic filter_clk;  // gated clock for AXI filter

  axi_cg_snoop #(
    // ALL IDs, both directions: matches the outbound filter's demux below, which takes
    // MaxTrans from smc_pkg::FABRIC_MAX_TRANS (per ID bucket)
    .OutstandingTx(smc_pkg::FABRIC_OUTSTANDING_TX),
    .DenyDelay(1),
    .HystWidth(smc_pkg::CG_HYSTERESIS_W)
  ) u_sys_out_filter_cg (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    .snoop_aw_valid_i(axi_remapped_to_filter_req.aw_valid),
    .snoop_aw_ready_i(axi_remapped_to_filter_resp.aw_ready),
    .snoop_w_valid_i (axi_remapped_to_filter_req.w_valid),
    .snoop_b_valid_i (axi_remapped_to_filter_resp.b_valid),
    .snoop_b_ready_i (axi_remapped_to_filter_req.b_ready),
    .snoop_ar_valid_i(axi_remapped_to_filter_req.ar_valid),
    .snoop_ar_ready_i(axi_remapped_to_filter_resp.ar_ready),
    .snoop_r_valid_i (axi_remapped_to_filter_resp.r_valid),
    .snoop_r_ready_i (axi_remapped_to_filter_req.r_ready),
    .snoop_r_last_i  (axi_remapped_to_filter_resp.r.last),

    .kick_i          (~filter_axi_cg_en_i), // continuously kick to keep clock awake when not gating

    .test_clk_en_i   (test_en_i),
    .hysteresis_i    (cg_hysteresis_i),
    .clk_active_o    (sys_out_filter_clk_active_o),
    .gated_clk_o     (filter_clk),
    .bus_active_o    (sys_out_filter_bus_active_o)
  );

  axi_filter_wrap #(
    .NumFilters          (NumFilters),
    .DebugOutput         (0),
    .BlockByDefault      (1'b0),
    .EnSrcIdFilter       (1'b1),
    .SrcIdUserBitStart   (0),
    .SrcIdWidth          (4),
    .EnGroupIdFilter     (1'b0),
    .GroupIdUserBitStart (4),
    .GroupIdWidth        (4),
    .EnNsFilter          (1'b1),
    .AxiAddrWidth        (smc_pkg::AXI_ADDR_WIDTH),
    .AxiIdWidth          (smc_pkg::SMC_OUTPUT_FABRIC_MASTER_ID_WIDTH),
    .AxiDataWidth        (smc_pkg::AXI_DATA_WIDTH),
    .MaxTrans            (smc_pkg::FABRIC_MAX_TRANS),
    .AxiLookBits         (smc_pkg::FABRIC_ID_LOOKUP_BITS),
    .ErrSlvMaxTrans      (smc_pkg::ERR_SLV_MAX_TRANS),
    .FlopReqEn           (FilterReqPipelineEnable),
    .FlopRespEn          (FilterRspPipelineEnable),
    .filter_axi_req_t    (smc_pkg::smc_output_56_64_8_12_axi_req_t),
    .filter_axi_resp_t   (smc_pkg::smc_output_56_64_8_12_axi_resp_t),
    .filter_aw_chan_t    (smc_pkg::smc_output_56_64_8_12_axi_aw_chan_t),
    .filter_w_chan_t     (smc_pkg::smc_output_56_64_8_12_axi_w_chan_t),
    .filter_b_chan_t     (smc_pkg::smc_output_56_64_8_12_axi_b_chan_t),
    .filter_ar_chan_t    (smc_pkg::smc_output_56_64_8_12_axi_ar_chan_t),
    .filter_r_chan_t     (smc_pkg::smc_output_56_64_8_12_axi_r_chan_t)
  ) u_smc_sys_outbound_filter (
    .clk_i                      (filter_clk),
    .rst_ni                     (rst_ni),
    .test_en_i                  (test_en_i),

    .filter_skip_i              (1'b0),

    // Config struct from register block
    .filter_ctrl_i              (filter_ctrl_i),
    .filter_status_o            (filter_status_o),

    // AXI interface to the filter
    .axi_in_req_i               (axi_remapped_to_filter_req),
    .axi_in_resp_o              (axi_remapped_to_filter_resp),

    // AXI interface to the filtered output
    .axi_filtered_out_req_o     (axi_filtered_remapped_req_o),
    .axi_filtered_out_resp_i    (axi_filtered_remapped_resp_i),

    .write_filter_hit_debug_o   (write_filter_hit_debug_o),
    .read_filter_hit_debug_o    (read_filter_hit_debug_o)
  );


endmodule

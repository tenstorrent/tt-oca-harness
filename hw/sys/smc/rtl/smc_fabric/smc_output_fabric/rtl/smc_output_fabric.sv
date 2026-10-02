// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route the SMC's outbound AXI through the output remap and filter to the system AXI port.
//
// With NO_ADDR_REMAP clear, requests inside the M-mode or Xvisor remap window at either SMC base go
// through the matching output_remap, which rewrites the address and replaces AxUSER with the M-mode
// or the other source ID; all other requests have AxUSER replaced with the SMC source ID; a mux
// merges the three paths and widens the ID. With NO_ADDR_REMAP set, only the ID widening remains. A
// clock-gated outbound access filter, which allows traffic that hits no rule, then guards the port.

module smc_output_fabric #(
  parameter bit          NO_ADDR_REMAP              = 1'b1,  // Removes the M-mode and Xvisor
                                                             // output remap when the integration
                                                             // map is fixed, leaving an ID-width
                                                             // converter in its place.
  parameter int unsigned NUM_FILTERS                = 16,  // Number of system outbound filter
                                                           // entries; sizes the filter CSR arrays
                                                           // and the hit-index outputs.
  parameter int unsigned MAX_TRANS                  = smc_pkg::FabricMaxTrans,    // Outstanding transactions per ID bucket in
                                                                                  // the remap demux and mux, which also sizes
                                                                                  // their clock-gate snoop; unused when
                                                                                  // NO_ADDR_REMAP is set.
  parameter bit          FILTER_REQ_PIPELINE_ENABLE = 1'b0,  // Adds spill registers on the request
                                                             // channels at the system outbound
                                                             // filter boundary.
  parameter bit          FILTER_RSP_PIPELINE_ENABLE = 1'b0,  // Adds spill registers on the response
                                                             // channels at the system outbound
                                                             // filter boundary.
  parameter int unsigned MMODE_BASE_ADDR            = smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_BASE_ADDR,  // Base of the M-mode remap region,
                                                                                                            // subtracted from request addresses before
                                                                                                            // the M-mode remap region lookup; unused
                                                                                                            // when NO_ADDR_REMAP is set.
  parameter int unsigned XVISOR_BASE_ADDR           = smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_BASE_ADDR  // Base of the Xvisor remap region,
                                                                                                            // subtracted from request addresses before
                                                                                                            // the Xvisor remap region lookup; unused
                                                                                                            // when NO_ADDR_REMAP is set.
) (
  input  logic clk_i,                   // SMC core clock.
  input  logic rst_ni,                  // Primary reset, active-low, synchronized to the SMC core
                                        // clock.
  input  logic test_en_i,               // Scan test mode enable, active-high; forwarded to the AXI
                                        // primitives and forces the fabric and filter clock gates
                                        // on.

  input  smc_pkg::smc_axi_addr_t global_base_addr_i,  // Global base address of the SMC address
                                                      // window; requests inside the M-mode or
                                                      // Xvisor remap window at this base go to that
                                                      // remap. Unused when NO_ADDR_REMAP is set.
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,  // Local base address of the SMC address
                                                     // window; requests inside the M-mode or Xvisor
                                                     // remap window at this base go to that remap.
                                                     // Unused when NO_ADDR_REMAP is set.

  input  logic                filter_axi_cg_en_i,  // Enables clock gating of the system outbound
                                                   // filter, active-high; low keeps the filter
                                                   // clock running.
  input  logic                fabric_cg_en_i,  // Enables clock gating of the remap demux and mux,
                                               // active-high; low keeps their clock running. Unused
                                               // when NO_ADDR_REMAP is set.
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,  // Idle SMC core clock cycles the remap fabric and
                                                // outbound filter clock gates wait after their bus
                                                // goes quiet before stopping the gated clock.

  input  smc_pkg::smc_56_64_6_12_axi_req_t  axi_req_i,  // Outbound request from the input fabric's
                                                        // global output port.
  output smc_pkg::smc_56_64_6_12_axi_resp_t axi_resp_o,  // Response to the input fabric's global
                                                         // output port.

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  axi_filtered_remapped_req_o,  // Request to the system
                                                                                  // AXI output after remap
                                                                                  // and the outbound filter.
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t axi_filtered_remapped_resp_i,  // Response from the
                                                                                   // system AXI output.

  input  filter_ctrl_reg_pkg::filter_ctrl__out_t filter_ctrl_i [NUM_FILTERS-1:0],  // Per-entry system outbound
                                                                                   // filter configuration from
                                                                                   // the register block; the
                                                                                   // filter matches source ID
                                                                                   // and the non-secure flag.
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  filter_status_o [NUM_FILTERS-1:0],  // Per-entry system outbound
                                                                                     // filter status returned to
                                                                                     // the register block.

  input  output_remap_reg_pkg::output_remap__out_t mR_ctrl_i [smc_pkg::NumMmodeOutputRemapRegions-1:0],      // M-mode output remap
                                                                                                             // region configuration;
                                                                                                             // unused when
                                                                                                             // NO_ADDR_REMAP is set.
  input  output_remap_reg_pkg::output_remap__out_t xR_ctrl_i [smc_pkg::NumXvisorOutputRemapRegions-1:0],      // Xvisor output remap
                                                                                                              // region configuration;
                                                                                                              // unused when
                                                                                                              // NO_ADDR_REMAP is set.

  output logic [$clog2(NUM_FILTERS)-1:0] write_filter_hit_debug_o,  // Filter entry index hit by
                                                                    // outbound writes; tied to zero
                                                                    // because the filter instance
                                                                    // disables its debug output.
  output logic [$clog2(NUM_FILTERS)-1:0] read_filter_hit_debug_o,  // Filter entry index hit by
                                                                   // outbound reads; tied to zero
                                                                   // because the filter instance
                                                                   // disables its debug output.

  output logic fabric_clk_active_o,     // High while the remap demux and mux clock runs; tied low
                                        // when NO_ADDR_REMAP is set.
  output logic fabric_bus_active_o,     // High while axi_req_i has a request valid or a
                                        // transaction outstanding; tied low when NO_ADDR_REMAP is
                                        // set.
  output logic sys_out_filter_clk_active_o,  // High while the system outbound filter clock runs.
  output logic sys_out_filter_bus_active_o  // High while the filter input has a request valid or a
                                            // transaction outstanding.
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
      .AXI_ADDR_WIDTH   (smc_pkg::AxiAddrWidth),
      .AXI_DATA_WIDTH   (smc_pkg::AxiDataWidth),
      .AXI_ID_WIDTH_IN  (smc_pkg::SmcLocalOutputFabricSlaveIdWidth),
      .AXI_ID_WIDTH_OUT (smc_pkg::SmcOutputFabricMasterIdWidth),

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
      // MAX_TRANS parameter of this module (per ID bucket) rather than by smc_pkg
      .OUTSTANDING_TX(smc_pkg::FabricIdBuckets * MAX_TRANS),
      .DENY_DELAY(1),
      .HYST_WIDTH(smc_pkg::CgHysteresisW)
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
      is_mmode_write_global  = ((axi_req_i.aw.addr >= global_base_addr_i + smc_pkg::MmodeRemapStart) & (axi_req_i.aw.addr < global_base_addr_i + smc_pkg::MmodeRemapStart + smc_pkg::MmodeRemapSize));
      is_mmode_write_local   = ((axi_req_i.aw.addr >= local_base_addr_i  + smc_pkg::MmodeRemapStart) & (axi_req_i.aw.addr < local_base_addr_i  + smc_pkg::MmodeRemapStart + smc_pkg::MmodeRemapSize));
      is_mmode_read_global   = ((axi_req_i.ar.addr >= global_base_addr_i + smc_pkg::MmodeRemapStart) & (axi_req_i.ar.addr < global_base_addr_i + smc_pkg::MmodeRemapStart + smc_pkg::MmodeRemapSize));
      is_mmode_read_local    = ((axi_req_i.ar.addr >= local_base_addr_i  + smc_pkg::MmodeRemapStart) & (axi_req_i.ar.addr < local_base_addr_i  + smc_pkg::MmodeRemapStart + smc_pkg::MmodeRemapSize));

      is_xvisor_write_global = ((axi_req_i.aw.addr >= global_base_addr_i + smc_pkg::XvisorRemapStart) & (axi_req_i.aw.addr < global_base_addr_i + smc_pkg::XvisorRemapStart + smc_pkg::XvisorRemapSize));
      is_xvisor_write_local  = ((axi_req_i.aw.addr >= local_base_addr_i  + smc_pkg::XvisorRemapStart) & (axi_req_i.aw.addr < local_base_addr_i  + smc_pkg::XvisorRemapStart + smc_pkg::XvisorRemapSize));
      is_xvisor_read_global  = ((axi_req_i.ar.addr >= global_base_addr_i + smc_pkg::XvisorRemapStart) & (axi_req_i.ar.addr < global_base_addr_i + smc_pkg::XvisorRemapStart + smc_pkg::XvisorRemapSize));
      is_xvisor_read_local   = ((axi_req_i.ar.addr >= local_base_addr_i  + smc_pkg::XvisorRemapStart) & (axi_req_i.ar.addr < local_base_addr_i  + smc_pkg::XvisorRemapStart + smc_pkg::XvisorRemapSize));

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
      .AxiIdWidth         (smc_pkg::SmcLocalOutputFabricSlaveIdWidth),
      .AtopSupport        (1'b0),
      .aw_chan_t          (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
      .w_chan_t           (smc_pkg::smc_56_64_6_12_axi_w_chan_t),
      .b_chan_t           (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
      .ar_chan_t          (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
      .r_chan_t           (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
      .axi_req_t          (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t         (smc_pkg::smc_56_64_6_12_axi_resp_t),
      .NoMstPorts         (3),
      .MaxTrans           (MAX_TRANS),
      .AxiLookBits        (smc_pkg::FabricIdLookupBits),
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
      .AXI_ADDR_WIDTH   (smc_pkg::AxiAddrWidth),
      .AXI_DATA_WIDTH   (smc_pkg::AxiDataWidth),
      .AXI_ID_WIDTH     (smc_pkg::SmcLocalOutputFabricSlaveIdWidth),
      .AXI_USER_WIDTH   (smc_pkg::AxiUserWidth),
      .AXI_USER_OVERRIDE(smc_pkg::SmcSrcId),

      .axi_req_t        (smc_pkg::smc_56_64_6_12_axi_req_t),
      .axi_resp_t       (smc_pkg::smc_56_64_6_12_axi_resp_t)
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
      .NUM_REGIONS        (smc_pkg::NumMmodeOutputRemapRegions),
      .REGION_BASE        (MMODE_BASE_ADDR),
      .IDX_START          (smc_pkg::OutputRemapIdxStart),
      .USER_OVERRIDE_EN   (1'b1),
      .USER_OVERRIDE_VAL  (smc_pkg::MmodeSrcId)
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
      .NUM_REGIONS        (smc_pkg::NumXvisorOutputRemapRegions),
      .REGION_BASE        (XVISOR_BASE_ADDR),
      .IDX_START          (smc_pkg::OutputRemapIdxStart),
      .USER_OVERRIDE_EN   (1'b1),
      .USER_OVERRIDE_VAL  (smc_pkg::OthersSrcId)
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
      .SlvAxiIDWidth  (smc_pkg::SmcLocalOutputFabricSlaveIdWidth),
      .NoSlvPorts     (3),
      .MaxWTrans      (MAX_TRANS),
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
    // MaxTrans from smc_pkg::FabricMaxTrans (per ID bucket)
    .OUTSTANDING_TX(smc_pkg::FabricOutstandingTx),
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
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
    .NUM_FILTERS             (NUM_FILTERS),
    .DEBUG_OUTPUT            (0),
    .BLOCK_BY_DEFAULT        (1'b0),
    .EN_SRC_ID_FILTER        (1'b1),
    .SRC_ID_USER_BIT_START   (0),
    .SRC_ID_WIDTH            (4),
    .EN_GROUP_ID_FILTER      (1'b0),
    .GROUP_ID_USER_BIT_START (4),
    .GROUP_ID_WIDTH          (4),
    .EN_NS_FILTER            (1'b1),
    .AXI_ADDR_WIDTH          (smc_pkg::AxiAddrWidth),
    .AXI_ID_WIDTH            (smc_pkg::SmcOutputFabricMasterIdWidth),
    .AXI_DATA_WIDTH          (smc_pkg::AxiDataWidth),
    .MAX_TRANS               (smc_pkg::FabricMaxTrans),
    .AXI_LOOK_BITS           (smc_pkg::FabricIdLookupBits),
    .ERR_SLV_MAX_TRANS       (smc_pkg::ErrSlvMaxTrans),
    .FLOP_REQ_EN             (FILTER_REQ_PIPELINE_ENABLE),
    .FLOP_RESP_EN            (FILTER_RSP_PIPELINE_ENABLE),
    .filter_axi_req_t        (smc_pkg::smc_output_56_64_8_12_axi_req_t),
    .filter_axi_resp_t       (smc_pkg::smc_output_56_64_8_12_axi_resp_t),
    .filter_aw_chan_t        (smc_pkg::smc_output_56_64_8_12_axi_aw_chan_t),
    .filter_w_chan_t         (smc_pkg::smc_output_56_64_8_12_axi_w_chan_t),
    .filter_b_chan_t         (smc_pkg::smc_output_56_64_8_12_axi_b_chan_t),
    .filter_ar_chan_t        (smc_pkg::smc_output_56_64_8_12_axi_ar_chan_t),
    .filter_r_chan_t         (smc_pkg::smc_output_56_64_8_12_axi_r_chan_t)
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

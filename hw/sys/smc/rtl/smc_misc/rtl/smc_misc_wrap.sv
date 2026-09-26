// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap SMC miscellaneous register targets on the misc AXI-Lite map.
//
// Demultiplexes the misc map onto version, base-config, and DFX helpers.
// Aggregates scratch and status registers used by firmware and debug.

module smc_misc_wrap #(
  parameter int unsigned CHIP_ID        = 0,  // CHIP ID.
  parameter int unsigned LC_STATE_WIDTH = 8  // LC STATE WIDTH.
) (
  input  logic clk_i,                   // Clock.
  input  logic rst_ni,                  // Reset.
  input  logic rst_warm_ni,             // Rst warm.
  input  logic test_en_i,               // Test en.

  input  smc_pkg::smc_axil_32_32_req_t  reg_axi_lite_req_i,  // AXI-Lite Register
                                                             // Interface request.
  output smc_pkg::smc_axil_32_32_resp_t reg_axi_lite_resp_o,  // AXI-Lite Register
                                                              // Interface response.

  input  logic [LC_STATE_WIDTH-1:0] lc_state_i,  // Lifecycle state.

  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_request_i,  // NDM Reset signals
                                                                            // (connected to SMU).
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_process_o  // NDM Reset signals
                                                                           // (connected to SMU).
);

  ////////////////////
  // AXI-Lite Demux //
  ////////////////////

  smc_misc_pkg::select_t reg_axi_lite_aw_select;
  smc_misc_pkg::select_t reg_axi_lite_ar_select;

  smc_pkg::smc_axil_32_32_req_t  [smc_misc_pkg::NumRegMaps-1:0] from_demux_reg_axi_lite_req;
  smc_pkg::smc_axil_32_32_resp_t [smc_misc_pkg::NumRegMaps-1:0] from_demux_reg_axi_lite_resp;

  /* add new choice to connect ndm to ndm_reset. Modify below demux to accept new NDM_RESET ENUM*/
  // Address decoding logic
  // Uses unique if to avoid priority mux since address ranges are non-overlapping
  always_comb begin
    unique if (reg_axi_lite_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR && reg_axi_lite_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE) begin
      reg_axi_lite_aw_select = smc_misc_pkg::SCRATCH_COLD;
    end else if (reg_axi_lite_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR && reg_axi_lite_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SIZE) begin
      reg_axi_lite_aw_select = smc_misc_pkg::SCRATCH_COLD_WARM;
    end else if (reg_axi_lite_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR && reg_axi_lite_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_SIZE) begin
      reg_axi_lite_aw_select = smc_misc_pkg::CHIP_CONFIG;
    end else if (reg_axi_lite_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_BASE_ADDR && reg_axi_lite_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_SIZE) begin
      reg_axi_lite_aw_select = smc_misc_pkg::NDM_RESET;
    end else begin
      reg_axi_lite_aw_select = smc_misc_pkg::ERR_SLV;
    end

    unique if (reg_axi_lite_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR && reg_axi_lite_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE) begin
      reg_axi_lite_ar_select = smc_misc_pkg::SCRATCH_COLD;
    end else if (reg_axi_lite_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR && reg_axi_lite_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SIZE) begin
      reg_axi_lite_ar_select = smc_misc_pkg::SCRATCH_COLD_WARM;
    end else if (reg_axi_lite_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR && reg_axi_lite_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_SIZE) begin
      reg_axi_lite_ar_select = smc_misc_pkg::CHIP_CONFIG;
    end else if (reg_axi_lite_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_BASE_ADDR && reg_axi_lite_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_NDM_RESET_SIZE) begin
      reg_axi_lite_ar_select = smc_misc_pkg::NDM_RESET;
    end else begin
      reg_axi_lite_ar_select = smc_misc_pkg::ERR_SLV;
    end
  end

  axi_lite_demux #(
    .aw_chan_t   (smc_pkg::smc_axil_32_32_aw_chan_t),
    .w_chan_t    (smc_pkg::smc_axil_32_32_w_chan_t),
    .b_chan_t    (smc_pkg::smc_axil_32_32_b_chan_t),
    .ar_chan_t   (smc_pkg::smc_axil_32_32_ar_chan_t),
    .r_chan_t    (smc_pkg::smc_axil_32_32_r_chan_t),
    .axi_req_t   (smc_pkg::smc_axil_32_32_req_t),
    .axi_resp_t  (smc_pkg::smc_axil_32_32_resp_t),
    .NoMstPorts  (smc_misc_pkg::NumRegMaps),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_axi_lite_demux (
    .clk_i            (clk_i),
    .rst_ni           (rst_ni),
    .test_i           (test_en_i),

    .slv_req_i        (reg_axi_lite_req_i),
    .slv_resp_o       (reg_axi_lite_resp_o),

    .slv_aw_select_i  (reg_axi_lite_aw_select),
    .slv_ar_select_i  (reg_axi_lite_ar_select),

    .mst_reqs_o       (from_demux_reg_axi_lite_req),
    .mst_resps_i      (from_demux_reg_axi_lite_resp)
  );

  //////////////////////////
  // SMC Scratch Registers //
  //////////////////////////

  // 8 scratch registers that are reset by cold reset
  scratch_reg u_smc_scratch_reg_cold (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].aw_valid),
    .s_axil_awaddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].aw.addr[scratch_reg_pkg::SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].aw.prot),
    .s_axil_wvalid  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].w_valid),
    .s_axil_wdata   (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].w.data),
    .s_axil_wstrb   (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].w.strb),
    .s_axil_bready  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].b_ready),
    .s_axil_arvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].ar_valid),
    .s_axil_araddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].ar.addr[scratch_reg_pkg::SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].ar.prot),
    .s_axil_rready  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD].r_ready),

    .s_axil_awready (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].aw_ready),
    .s_axil_wready  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].w_ready),
    .s_axil_bvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].b_valid),
    .s_axil_bresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].b.resp),
    .s_axil_arready (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].ar_ready),
    .s_axil_rvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].r_valid),
    .s_axil_rdata   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].r.data),
    .s_axil_rresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD].r.resp)
  );

  // 8 scratch registers that are reset by cold and warm reset
  scratch_reg u_smc_scratch_reg_cold_warm (
    .clk            (clk_i),
    .arst_n         (rst_warm_ni),

    .s_axil_awvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].aw_valid),
    .s_axil_awaddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].aw.addr[scratch_reg_pkg::SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].aw.prot),
    .s_axil_wvalid  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].w_valid),
    .s_axil_wdata   (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].w.data),
    .s_axil_wstrb   (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].w.strb),
    .s_axil_bready  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].b_ready),
    .s_axil_arvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].ar_valid),
    .s_axil_araddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].ar.addr[scratch_reg_pkg::SCRATCH_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].ar.prot),
    .s_axil_rready  (from_demux_reg_axi_lite_req[smc_misc_pkg::SCRATCH_COLD_WARM].r_ready),

    .s_axil_awready (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].aw_ready),
    .s_axil_wready  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].w_ready),
    .s_axil_bvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].b_valid),
    .s_axil_bresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].b.resp),
    .s_axil_arready (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].ar_ready),
    .s_axil_rvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].r_valid),
    .s_axil_rdata   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].r.data),
    .s_axil_rresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::SCRATCH_COLD_WARM].r.resp)
  );

  //////////////////////////
  // Version ID Rev Cells //
  //////////////////////////

  logic [63:0] version_id;

  smc_version_id_wrap u_smc_version_id_wrap (.version_id_o(version_id));

  ///////////////////////////
  // Chip Config Registers //
  ///////////////////////////

  chip_config_reg_pkg::chip_config__in_t hwif_in;

  chip_config_reg u_smc_chip_config_reg (
    .clk(clk_i),
    .arst_n(rst_ni),

    .s_axil_awvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].aw_valid),
    .s_axil_awaddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].aw.addr[chip_config_reg_pkg::CHIP_CONFIG_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].aw.prot),
    .s_axil_wvalid  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].w_valid),
    .s_axil_wdata   (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].w.data),
    .s_axil_wstrb   (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].w.strb),
    .s_axil_bready  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].b_ready),
    .s_axil_arvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].ar_valid),
    .s_axil_araddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].ar.addr[chip_config_reg_pkg::CHIP_CONFIG_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].ar.prot),
    .s_axil_rready  (from_demux_reg_axi_lite_req[smc_misc_pkg::CHIP_CONFIG].r_ready),

    .s_axil_awready (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].aw_ready),
    .s_axil_wready  (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].w_ready),
    .s_axil_bvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].b_valid),
    .s_axil_bresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].b.resp),
    .s_axil_arready (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].ar_ready),
    .s_axil_rvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].r_valid),
    .s_axil_rdata   (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].r.data),
    .s_axil_rresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::CHIP_CONFIG].r.resp),

    .hwif_in(hwif_in)
  );

  assign hwif_in.VERSION_LO.version_lo.next = version_id[31:0];
  assign hwif_in.VERSION_HI.version_hi.next = version_id[63:32];
  assign hwif_in.CHIP_ID.chip_id.next = CHIP_ID;
  assign hwif_in.LC_STATE.lc_state.next = lc_state_i;

  ///////////////////////
  // NDM Reset Control //
  ///////////////////////

  ndm_reset_reg_pkg::ndm_reset__in_t  ndm_hwif_in;
  ndm_reset_reg_pkg::ndm_reset__out_t ndm_hwif_out;

  ndm_reset_reg u_smc_ndm_reset_reg (
    .clk(clk_i),
    .arst_n(rst_ni),

    .s_axil_awvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].aw_valid),
    .s_axil_awaddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].aw.addr[ndm_reset_reg_pkg::NDM_RESET_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].aw.prot),
    .s_axil_wvalid  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].w_valid),
    .s_axil_wdata   (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].w.data),
    .s_axil_wstrb   (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].w.strb),
    .s_axil_bready  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].b_ready),
    .s_axil_arvalid (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].ar_valid),
    .s_axil_araddr  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].ar.addr[ndm_reset_reg_pkg::NDM_RESET_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].ar.prot),
    .s_axil_rready  (from_demux_reg_axi_lite_req[smc_misc_pkg::NDM_RESET].r_ready),

    .s_axil_awready (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].aw_ready),
    .s_axil_wready  (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].w_ready),
    .s_axil_bvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].b_valid),
    .s_axil_bresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].b.resp),
    .s_axil_arready (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].ar_ready),
    .s_axil_rvalid  (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].r_valid),
    .s_axil_rdata   (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].r.data),
    .s_axil_rresp   (from_demux_reg_axi_lite_resp[smc_misc_pkg::NDM_RESET].r.resp),

    .hwif_in(ndm_hwif_in),
    .hwif_out(ndm_hwif_out)
  );

  assign ndm_hwif_in.NDMRESET_REQUEST.ndmreset_request.next = ndm_reset_reg_pkg::NDM_RESET_REG_DATA_WIDTH'(ndmreset_request_i);
  assign ndm_hwif_in.NDMRESET_CLUSTER_COUNT.ndmreset_cluster_count.next = smc_config_pkg::CPU_CLUSTER_COUNT;

  // Output: ndmreset_process goes to reset control logic (via SMU)
  assign ndmreset_process_o = ndm_hwif_out.NDMRESET_PROCESS.ndmreset_process.value[smc_config_pkg::CPU_CLUSTER_COUNT - 1:0];

  //////////////////////////
  // AXI-Lite Error Slave //
  //////////////////////////

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (32),
    .AXI_DATA_WIDTH (32),
    .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
    .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (32),
    .RESP_DATA      (32'hBADCAB1E)
  ) u_prim_axi_lite_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .axil_req_i (from_demux_reg_axi_lite_req[smc_misc_pkg::ERR_SLV]),
    .axil_resp_o(from_demux_reg_axi_lite_resp[smc_misc_pkg::ERR_SLV])
  );

endmodule

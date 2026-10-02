// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route the SMC's inbound AXI initiators toward the local and output fabrics.
//
// Widens the JTAG and MMIO IDs and converts the log AXI-Lite port to AXI, applies the alias
// remap to those and the data accelerator port, muxes the four, and sends requests inside
// the local or global SMC window to the local output port truncated to 32 bits and all
// others to the global output port. System inbound AXI passes a clock-gated access filter
// that blocks by default; system and SEP requests outside the SMC window receive DECERR,
// and the rest are truncated to 32 bits for the local fabric.

module smc_input_fabric #(
  parameter bit          FILTER_REQ_PIPELINE_ENABLE = 1'b0,  // Adds spill registers on the request
                                                             // channels at the system inbound
                                                             // filter boundary.
  parameter bit          FILTER_RSP_PIPELINE_ENABLE = 1'b0,  // Adds spill registers on the response
                                                             // channels at the system inbound
                                                             // filter boundary.
  parameter int unsigned NUM_FILTERS                = 16  // Number of system inbound filter
                                                          // entries; sizes the filter CSR arrays
                                                          // and the hit-index outputs.
) (
  input  logic clk_i,                   // SMC core clock.
  input  logic rst_ni,                  // Primary reset, active-low, synchronized to the SMC core
                                        // clock.
  input  logic test_en_i,               // Scan test mode enable, active-high; forwarded to the AXI
                                        // primitives and forces the filter clock gate on.
  input  logic scan_rst_ni,             // Scan reset, active-low; not used in this module.

  input  logic                filter_axi_cg_en_i,  // Enables clock gating of the system inbound
                                                   // filter, active-high; low keeps the filter
                                                   // clock running.
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,  // Idle SMC core clock cycles the system inbound
                                                // filter clock gate waits after the bus goes quiet
                                                // before stopping the filter clock.

  input  smc_pkg::smc_axi_addr_t global_base_addr_i,  // Global base address of the SMC window;
                                                      // requests in [base, base + region_size_i)
                                                      // count as SMC
                                                      // accesses.
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,  // Local base address of the SMC window; requests
                                                     // in [base, base + region_size_i) count as SMC
                                                     // accesses.
  input  logic [31:0]            region_size_i,  // Size in bytes of the SMC window at either base; the
                                                 // window end is computed one bit wider than the
                                                 // address so it cannot wrap.

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  axi_in_jtag_req_i,  // JTAG AXI Input
                                                                     // request.
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t axi_in_jtag_resp_o,  // JTAG AXI Input
                                                                      // response.

  input  smc_pkg::smc_cpu_mmio_axi_req_t  axi_in_mmio_req_i,  // MMIO AXI Input request.
  output smc_pkg::smc_cpu_mmio_axi_resp_t axi_in_mmio_resp_o,  // MMIO AXI Input response.

  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_data_accel_req_i,  // Data Accelerator AXI
                                                                                   // Input request.
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_data_accel_resp_o,  // Data Accelerator AXI
                                                                                    // Input response.

  input  smc_pkg::smc_axil_56_64_req_t  axi_lite_log_req_i,  // Log AXI-Lite Input
                                                             // request.
  output smc_pkg::smc_axil_56_64_resp_t axi_lite_log_resp_o,  // Log AXI-Lite Input
                                                              // response.

  output smc_pkg::smc_local_32_64_6_12_axi_req_t  axi_local_out_req_o,  // Request from the alias-remapped JTAG,
                                                                        // MMIO, log and data accelerator paths
                                                                        // that hits the local or global SMC window,
                                                                        // truncated to the 32-bit local address.
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t axi_local_out_resp_i,  // Response to requests on the local output
                                                                         // port.

  output smc_pkg::smc_56_64_6_12_axi_req_t  axi_out_req_o,  // Request from the alias-remapped JTAG, MMIO,
                                                            // log and data accelerator paths that misses
                                                            // the SMC window, with its full 56-bit address.
  input  smc_pkg::smc_56_64_6_12_axi_resp_t axi_out_resp_i,  // Response to requests on the global output
                                                             // port.

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,  // System AXI Input
                                                                      // request.
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,  // System AXI Input
                                                                       // response.
  output smc_pkg::smc_local_32_64_6_12_axi_req_t   filtered_sys_axi_out_req_o,  // System request that passed the
                                                                                // inbound filter and hits the SMC
                                                                                // window, truncated to the 32-bit
                                                                                // local address.
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t  filtered_sys_axi_out_resp_i,  // Response to the filtered system
                                                                                 // request.

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,  // SEP AXI Input
                                                                      // request.
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,  // SEP AXI Input
                                                                       // response.
  output smc_pkg::smc_local_32_64_6_12_axi_req_t   sep_axi_id_remap_req_o,  // SEP request that hits the SMC
                                                                            // window, truncated to the 32-bit
                                                                            // local address; the ID passes
                                                                            // through unchanged.
  input  smc_pkg::smc_local_32_64_6_12_axi_resp_t  sep_axi_id_remap_resp_i,  // Response to the SEP request.

  input  filter_ctrl_reg_pkg::filter_ctrl__out_t filter_ctrl_i [NUM_FILTERS-1:0],  // Per-entry system inbound
                                                                                   // filter configuration from
                                                                                   // the register block; the
                                                                                   // filter matches source ID
                                                                                   // and the non-secure flag.
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  filter_status_o [NUM_FILTERS-1:0],  // Per-entry system inbound
                                                                                     // filter status returned to
                                                                                     // the register block.

  input  alias_remap_reg_pkg::alias_remap__out_t aR_ctrl_i [smc_pkg::NumAliasRemapRegions-1:0],     // Alias remap region
                                                                                                    // configuration from
                                                                                                    // the register block.

  output smc_pkg::remap_debug_t          remap_debug_mmio_o,  // Alias region index hit by the MMIO path.
  output smc_pkg::remap_debug_t          remap_debug_jtag_o,  // Alias region index hit by the JTAG path.
  output smc_pkg::remap_debug_t          remap_debug_log_o,  // Alias region index hit by the log path.
  output smc_pkg::remap_debug_t          remap_debug_dma_o,  // Alias region index hit by the data accelerator
                                                             // path.
  output logic [$clog2(NUM_FILTERS)-1:0] write_filter_hit_debug_o,  // Lowest system inbound filter entry
                                                                    // hit by a write.
  output logic [$clog2(NUM_FILTERS)-1:0] read_filter_hit_debug_o,  // Lowest system inbound filter entry
                                                                   // hit by a read.

  output logic sys_in_filter_clk_active_o,  // High while the system inbound filter clock runs.
  output logic sys_in_filter_bus_active_o  // High while the system AXI input has a request valid or
                                           // a transaction outstanding.
);

  `include "axi/assign.svh"

  /////////////////////////
  // ID Conversion Logic //
  /////////////////////////

  // Convert MMIO AXI port from CPU to Fabric (ID: 3 -> 4)
  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_mmio_port_req_prepend_id;
  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_mmio_port_resp_prepend_id;

  prim_axi_id_converter #(
    .AXI_ADDR_WIDTH     (smc_pkg::AxiAddrWidth),
    .AXI_DATA_WIDTH     (smc_pkg::AxiDataWidth),
    .AXI_ID_WIDTH_IN    (smc_pkg::SmcCpuMmioAxiIdWidth),
    .AXI_ID_WIDTH_OUT   (smc_pkg::SmcInputFabricSlaveIdWidth),

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
    .AXI_ADDR_WIDTH    (smc_pkg::AxiAddrWidth),
    .AXI_DATA_WIDTH    (smc_pkg::AxiDataWidth),
    .AXI_ID_WIDTH_IN   (smc_pkg::JtagIdWidth),
    .AXI_ID_WIDTH_OUT  (smc_pkg::SmcInputFabricSlaveIdWidth),

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
    .AxiDataWidth       (smc_pkg::AxiDataWidth),
    .req_lite_t         (smc_pkg::smc_axil_56_64_req_t),
    .resp_lite_t        (smc_pkg::smc_axil_56_64_resp_t),
    .axi_req_t          (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .axi_resp_t         (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t)
  ) u_log_axi_lite_to_axi (
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

  smc_alias_remap_wrap u_smc_alias_remap_wrap (
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

    .remap_debug_mmio_o(remap_debug_mmio_o),
    .remap_debug_jtag_o(remap_debug_jtag_o),
    .remap_debug_log_o(remap_debug_log_o),
    .remap_debug_dma_o(remap_debug_dma_o)
  );

  smc_pkg::smc_56_64_6_12_axi_req_t   axi_from_input_mux_req;
  smc_pkg::smc_56_64_6_12_axi_resp_t  axi_from_input_mux_resp;

  axi_mux #(
    .SlvAxiIDWidth      (smc_pkg::SmcInputFabricSlaveIdWidth),
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
    .NoSlvPorts         (smc_pkg::NumAliasRemapInputs),
    .MaxWTrans          (smc_pkg::FabricMaxTrans),
    .FallThrough        (1'b0),
    .SpillAw            (1'b1),
    .SpillW             (1'b1),
    .SpillB             (1'b1),
    .SpillAr            (1'b1),
    .SpillR             (1'b1)
  ) u_smc_input_axi_mux (
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
  logic [smc_pkg::AxiAddrWidth:0] local_region_end;
  logic [smc_pkg::AxiAddrWidth:0] global_region_end;

  assign local_region_end  = {1'b0, local_base_addr_i}  + region_size_i;
  assign global_region_end = {1'b0, global_base_addr_i} + region_size_i;

  // Takes the bounds as arguments: a continuous assign is not sensitive to module signals a
  // function reads implicitly.
  function automatic logic in_smc_region(
      smc_pkg::smc_axi_addr_t addr, smc_pkg::smc_axi_addr_t local_base,
      logic [smc_pkg::AxiAddrWidth:0] local_end, smc_pkg::smc_axi_addr_t global_base,
      logic [smc_pkg::AxiAddrWidth:0] global_end);
    return (addr >= local_base)  && ({1'b0, addr} < local_end) ||
           (addr >= global_base) && ({1'b0, addr} < global_end);
  endfunction

  assign local_space_write = in_smc_region(axi_from_input_mux_req.aw.addr, local_base_addr_i,
                                           local_region_end, global_base_addr_i, global_region_end);
  assign local_space_read  = in_smc_region(axi_from_input_mux_req.ar.addr, local_base_addr_i,
                                           local_region_end, global_base_addr_i, global_region_end);

  // The demux should be 56 bit address width
  // Using struct to access local_fabric and output_fabric paths
  smc_pkg::input_fabric_demux_axi_req_t  axi_from_demux_req;
  smc_pkg::input_fabric_demux_axi_resp_t axi_from_demux_resp;

  axi_demux #(
    .AxiIdWidth     (smc_pkg::SmcLocalOutputFabricSlaveIdWidth),
    .AtopSupport    (1'b0),
    .aw_chan_t      (smc_pkg::smc_56_64_6_12_axi_aw_chan_t),
    .w_chan_t       (smc_pkg::smc_56_64_6_12_axi_w_chan_t),
    .b_chan_t       (smc_pkg::smc_56_64_6_12_axi_b_chan_t),
    .ar_chan_t      (smc_pkg::smc_56_64_6_12_axi_ar_chan_t),
    .r_chan_t       (smc_pkg::smc_56_64_6_12_axi_r_chan_t),
    .axi_req_t      (smc_pkg::smc_56_64_6_12_axi_req_t),
    .axi_resp_t     (smc_pkg::smc_56_64_6_12_axi_resp_t),
    .NoMstPorts     (2),
    .MaxTrans       (smc_pkg::FabricMaxTrans),
    .AxiLookBits    (smc_pkg::FabricIdLookupBits),
    .UniqueIds      (1'b0),
    .SpillAw        (1'b1),
    .SpillW         (1'b0),
    .SpillB         (1'b0),
    .SpillAr        (1'b1),
    .SpillR         (1'b0)
  ) u_smc_local_global_demux (
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
    .INPUT_ADDR_W       (smc_pkg::AxiAddrWidth),
    .OUTPUT_ADDR_W      (smc_pkg::SmcLocalAddrWidth),
    .input_axi_req_t    (smc_pkg::smc_56_64_6_12_axi_req_t),
    .input_axi_resp_t   (smc_pkg::smc_56_64_6_12_axi_resp_t),
    .output_axi_req_t   (smc_pkg::smc_local_32_64_6_12_axi_req_t),
    .output_axi_resp_t  (smc_pkg::smc_local_32_64_6_12_axi_resp_t)
  ) u_smc_axi_addr_fixer (
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
    .OUTSTANDING_TX(smc_pkg::FabricOutstandingTx),
    .DENY_DELAY(1),
    .HYST_WIDTH(smc_pkg::CgHysteresisW)
  ) u_sys_in_filter_cg (
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
    .NUM_FILTERS             (NUM_FILTERS),
    .DEBUG_OUTPUT            (1),
    .BLOCK_BY_DEFAULT        (1'b1),
    .EN_SRC_ID_FILTER        (1'b1),
    .SRC_ID_USER_BIT_START   (0),
    .SRC_ID_WIDTH            (4),
    .EN_GROUP_ID_FILTER      (1'b0),
    .GROUP_ID_USER_BIT_START (4),
    .GROUP_ID_WIDTH          (4),
    .EN_NS_FILTER            (1'b1),
    .AXI_ADDR_WIDTH          (smc_pkg::AxiAddrWidth),
    .AXI_ID_WIDTH            (smc_pkg::SysInIdWidth),
    .AXI_DATA_WIDTH          (smc_pkg::AxiDataWidth),
    .MAX_TRANS               (smc_pkg::FabricMaxTrans),
    .AXI_LOOK_BITS           (smc_pkg::FabricIdLookupBits),
    .ERR_SLV_MAX_TRANS       (smc_pkg::ErrSlvMaxTrans),
    .FLOP_REQ_EN             (FILTER_REQ_PIPELINE_ENABLE),
    .FLOP_RESP_EN            (FILTER_RSP_PIPELINE_ENABLE),
    .filter_axi_req_t        (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
    .filter_axi_resp_t       (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
    .filter_aw_chan_t        (smc_pkg::smc_sys_in_56_64_6_12_axi_aw_chan_t),
    .filter_w_chan_t         (smc_pkg::smc_sys_in_56_64_6_12_axi_w_chan_t),
    .filter_b_chan_t         (smc_pkg::smc_sys_in_56_64_6_12_axi_b_chan_t),
    .filter_ar_chan_t        (smc_pkg::smc_sys_in_56_64_6_12_axi_ar_chan_t),
    .filter_r_chan_t         (smc_pkg::smc_sys_in_56_64_6_12_axi_r_chan_t)
  ) u_smc_sys_inbound_filter (
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


  ////////////////////////////
  // SYS / SEP Region Check //
  ////////////////////////////

  // Both paths truncate to the 32-bit local fabric, so an address outside the local and global
  // windows would otherwise alias into the local map. Port 0 of each demux takes those to DECERR.

  logic sys_space_write;
  logic sys_space_read;

  assign sys_space_write = in_smc_region(sys_axi_in_filtered_req.aw.addr, local_base_addr_i,
                                         local_region_end, global_base_addr_i, global_region_end);
  assign sys_space_read  = in_smc_region(sys_axi_in_filtered_req.ar.addr, local_base_addr_i,
                                         local_region_end, global_base_addr_i, global_region_end);

  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_region_req;
  smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_region_resp;
  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_err_slv_req;
  smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_err_slv_resp;

  axi_demux #(
    .AxiIdWidth     (smc_pkg::SysInIdWidth),
    .AtopSupport    (1'b0),
    .aw_chan_t      (smc_pkg::smc_sys_in_56_64_6_12_axi_aw_chan_t),
    .w_chan_t       (smc_pkg::smc_sys_in_56_64_6_12_axi_w_chan_t),
    .b_chan_t       (smc_pkg::smc_sys_in_56_64_6_12_axi_b_chan_t),
    .ar_chan_t      (smc_pkg::smc_sys_in_56_64_6_12_axi_ar_chan_t),
    .r_chan_t       (smc_pkg::smc_sys_in_56_64_6_12_axi_r_chan_t),
    .axi_req_t      (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
    .axi_resp_t     (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
    .NoMstPorts     (2),
    .MaxTrans       (smc_pkg::FabricMaxTrans),
    .AxiLookBits    (smc_pkg::FabricIdLookupBits),
    .UniqueIds      (1'b0),
    .SpillAw        (1'b0),
    .SpillW         (1'b0),
    .SpillB         (1'b0),
    .SpillAr        (1'b0),
    .SpillR         (1'b0)
  ) u_sys_region_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'd0),  // unused
    .slv_req_i       (sys_axi_in_filtered_req),
    .slv_aw_select_i (sys_space_write),
    .slv_ar_select_i (sys_space_read),
    .slv_resp_o      (sys_axi_in_filtered_resp),
    .mst_reqs_o      ({sys_axi_in_region_req, sys_err_slv_req}),
    .mst_resps_i     ({sys_axi_in_region_resp, sys_err_slv_resp})
  );

  axi_err_slv #(
    .AxiIdWidth (smc_pkg::SysInIdWidth),
    .axi_req_t  (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
    .axi_resp_t (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .ATOPs      (1'b0),
    .MaxTrans   (smc_pkg::ErrSlvMaxTrans)
  ) u_sys_region_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (sys_err_slv_req),
    .slv_resp_o (sys_err_slv_resp)
  );

  logic sep_space_write;
  logic sep_space_read;

  assign sep_space_write = in_smc_region(sep_axi_in_req_i.aw.addr, local_base_addr_i,
                                         local_region_end, global_base_addr_i, global_region_end);
  assign sep_space_read  = in_smc_region(sep_axi_in_req_i.ar.addr, local_base_addr_i,
                                         local_region_end, global_base_addr_i, global_region_end);

  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_region_req;
  smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_region_resp;
  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_err_slv_req;
  smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_err_slv_resp;

  axi_demux #(
    .AxiIdWidth     (smc_pkg::SepInIdWidth),
    .AtopSupport    (1'b0),
    .aw_chan_t      (smc_pkg::smc_sep_in_56_64_6_12_axi_aw_chan_t),
    .w_chan_t       (smc_pkg::smc_sep_in_56_64_6_12_axi_w_chan_t),
    .b_chan_t       (smc_pkg::smc_sep_in_56_64_6_12_axi_b_chan_t),
    .ar_chan_t      (smc_pkg::smc_sep_in_56_64_6_12_axi_ar_chan_t),
    .r_chan_t       (smc_pkg::smc_sep_in_56_64_6_12_axi_r_chan_t),
    .axi_req_t      (smc_pkg::smc_sep_in_56_64_6_12_axi_req_t),
    .axi_resp_t     (smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t),
    .NoMstPorts     (2),
    .MaxTrans       (smc_pkg::FabricMaxTrans),
    .AxiLookBits    (smc_pkg::FabricIdLookupBits),
    .UniqueIds      (1'b0),
    .SpillAw        (1'b0),
    .SpillW         (1'b0),
    .SpillB         (1'b0),
    .SpillAr        (1'b0),
    .SpillR         (1'b0)
  ) u_sep_region_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'd0),  // unused
    .slv_req_i       (sep_axi_in_req_i),
    .slv_aw_select_i (sep_space_write),
    .slv_ar_select_i (sep_space_read),
    .slv_resp_o      (sep_axi_in_resp_o),
    .mst_reqs_o      ({sep_axi_in_region_req, sep_err_slv_req}),
    .mst_resps_i     ({sep_axi_in_region_resp, sep_err_slv_resp})
  );

  axi_err_slv #(
    .AxiIdWidth (smc_pkg::SepInIdWidth),
    .axi_req_t  (smc_pkg::smc_sep_in_56_64_6_12_axi_req_t),
    .axi_resp_t (smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .ATOPs      (1'b0),
    .MaxTrans   (smc_pkg::ErrSlvMaxTrans)
  ) u_sep_region_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (sep_err_slv_req),
    .slv_resp_o (sep_err_slv_resp)
  );

  // SYS IN AXI Address Width Converter (56 -> 32)
  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(filtered_sys_axi_out_req_o, filtered_sys_axi_out_resp_i,
                                     sys_axi_in_region_req, sys_axi_in_region_resp,
                                     smc_pkg::smc_axi_local_addr_t)

  // SEP AXI Address Width Converter (56 -> 32)
  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(sep_axi_id_remap_req_o, sep_axi_id_remap_resp_i,
                                     sep_axi_in_region_req, sep_axi_in_region_resp,
                                     smc_pkg::smc_axi_local_addr_t)

endmodule

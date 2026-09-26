// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Block AXI-Lite accesses whose AxPROT fails a programmable requirement.
//
// write_filter_enable_i and read_filter_enable_i arm the AW and AR checks against
// awprot_requirement_i and arprot_requirement_i.
// Complete failing writes or reads locally with an error and do not forward them to the
// subordinate.
// MAX_TRANS bounds outstanding filtered traffic.

module prim_axil_prot_filter #(
  parameter int unsigned ADDR_WIDTH = 32,  // AXI-Lite address width.
  parameter int unsigned DATA_WIDTH = 32,  // AXI-Lite data width.
  parameter int unsigned MAX_TRANS = 32,  // Outstanding transactions tracked by the filter.

  parameter type axil_req_t     = logic,  // AXI-Lite request struct.
  parameter type axil_resp_t    = logic,  // AXI-Lite response struct.
  parameter type axil_aw_chan_t = logic,  // AW channel type.
  parameter type axil_w_chan_t  = logic,  // W channel type.
  parameter type axil_b_chan_t  = logic,  // B channel type.
  parameter type axil_ar_chan_t = logic,  // AR channel type.
  parameter type axil_r_chan_t  = logic  // R channel type.
) (
  input logic clk_i,  // AXI-Lite clock.
  input logic rst_ni,  // Async reset, active-low.
  input logic test_en_i,  // DFT/test enable.

  input logic       write_filter_enable_i,  // Enables AWPROT filtering.
  input logic       read_filter_enable_i,  // Enables ARPROT filtering.
  input logic [2:0] awprot_requirement_i,  // Required AWPROT when write filter is on.
  input logic [2:0] arprot_requirement_i,  // Required ARPROT when read filter is on.

  input  axil_req_t  axil_req_i,  // Unfiltered request from the manager.
  output axil_resp_t axil_resp_o,  // Response toward the manager.

  output axil_req_t  filtered_axil_req_o,  // Request toward the subordinate after filtering.
  input  axil_resp_t filtered_axil_resp_i  // Response from the subordinate.
);

  //==========================================================================
  // AXI4-Lite Filter Implementation
  //==========================================================================

  axil_req_t  axil_req_to_filter;
  axil_resp_t axil_resp_from_filter;

  axil_req_t  [1:0] axil_reqs_filtered;
  axil_resp_t [1:0] axil_resps_filtered;

  // Transaction detection signals
  logic read_req_valid, write_req_valid;
  logic read_txn_complete, write_txn_complete;
  logic read_prot_check_pass, write_prot_check_pass;

  assign read_req_valid  = axil_req_i.ar_valid;
  assign write_req_valid = axil_req_i.aw_valid;

  // Transaction completion detection
  assign read_txn_complete  = axil_resp_o.r_valid && axil_req_i.r_ready;
  assign write_txn_complete = axil_resp_o.b_valid && axil_req_i.b_ready;

  // Protection requirement checks
  assign read_prot_check_pass  = read_filter_enable_i  ? (axil_req_i.ar.prot == arprot_requirement_i) : 1'b1;
  assign write_prot_check_pass = write_filter_enable_i ? (axil_req_i.aw.prot == awprot_requirement_i) : 1'b1;

  assign axil_req_to_filter = axil_req_i;
  assign axil_resp_o = axil_resp_from_filter;

  logic aw_filter_pass;
  logic ar_filter_pass;

  // "close" filter by passing to err (index 0)
  // "open"  filter by passing to IO (index 1)
  assign aw_filter_pass = write_req_valid & write_prot_check_pass;
  assign ar_filter_pass = read_req_valid  & read_prot_check_pass;

  axi_lite_demux #(
    .aw_chan_t   (axil_aw_chan_t),
    .w_chan_t    (axil_w_chan_t),
    .b_chan_t    (axil_b_chan_t),
    .ar_chan_t   (axil_ar_chan_t),
    .r_chan_t    (axil_r_chan_t),
    .axi_req_t   (axil_req_t),
    .axi_resp_t  (axil_resp_t),
    .NoMstPorts  (2),
    .MaxTrans    (MAX_TRANS),
    .FallThrough (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0)
  ) u_axil_filter (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_i(test_en_i),
    .slv_req_i(axil_req_to_filter),
    .slv_aw_select_i(aw_filter_pass),
    .slv_ar_select_i(ar_filter_pass),
    .slv_resp_o(axil_resp_from_filter),
    .mst_reqs_o(axil_reqs_filtered),
    .mst_resps_i(axil_resps_filtered)
  );

  // Connect demuxed port [0] to AXI-Lite error slave
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(ADDR_WIDTH),
    .AXI_DATA_WIDTH(DATA_WIDTH),
    .axil_req_t(axil_req_t),
    .axil_resp_t(axil_resp_t),
    .RESP(axi_pkg::RESP_DECERR),
    .RESP_WIDTH(DATA_WIDTH),
    .RESP_DATA(DATA_WIDTH'('hBADCAB1E)),
    .MAX_TRANS(1)
  ) u_filter_err_slv (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .axil_req_i(axil_reqs_filtered[0]),
    .axil_resp_o(axil_resps_filtered[0])
  );


  always_comb begin
    filtered_axil_req_o = axil_reqs_filtered[1];
    axil_resps_filtered[1] = filtered_axil_resp_i;
  end


endmodule

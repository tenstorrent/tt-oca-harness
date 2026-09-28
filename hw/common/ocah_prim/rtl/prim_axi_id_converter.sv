// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Adapt AXI IDs between an upstream and a downstream port of different ID widths.
//
// When AXI_ID_WIDTH_IN exceeds AXI_ID_WIDTH_OUT, remap IDs through axi_id_remap within the
// MAX_INFLIGHT_IDS and MAX_TXNS_PER_ID limits.
// When AXI_ID_WIDTH_IN is less than AXI_ID_WIDTH_OUT, zero-extend IDs combinationally
// through prim_axi_id_prepend_wrap.
// When the widths are equal, pass requests and responses straight through.
// test_en_i is not used.

module prim_axi_id_converter #(

  parameter int unsigned AXI_ADDR_WIDTH = 64,  // Address width of both AXI ports; forwarded to the
                                               // ID-padding path.
  parameter int unsigned AXI_DATA_WIDTH = 64,  // Data-channel width of both AXI ports; forwarded to
                                               // the ID-padding path.
  parameter int unsigned AXI_USER_WIDTH = 1,  // User-signal width of both AXI ports; forwarded to
                                              // the ID-padding path.

  parameter int unsigned AXI_ID_WIDTH_IN  = 16,  // Upstream AXI ID width.
  parameter int unsigned AXI_ID_WIDTH_OUT = 8,  // Downstream AXI ID width.

  parameter type input_axi_req_t = logic,  // Upstream request struct.
  parameter type input_axi_resp_t = logic,  // Upstream response struct.
  parameter type output_axi_req_t = logic,  // Downstream request struct.
  parameter type output_axi_resp_t = logic,  // Downstream response struct.

  parameter int unsigned MAX_INFLIGHT_IDS = 4,  // Max distinct upstream IDs in flight; used only by
                                                // the remap path.
  parameter int unsigned MAX_TXNS_PER_ID  = 4  // Max outstanding transactions per upstream ID; used
                                               // only by the remap path.
) (
  input logic clk_i,  // AXI clock; used only by the remap path.
  input logic rst_ni,  // Async reset, active-low; used only by the remap path.
  input logic test_en_i,  // Not used.

  input  input_axi_req_t  axi_in_req_i,  // Upstream AXI request.
  output input_axi_resp_t axi_in_resp_o,  // Upstream AXI response.
  output output_axi_req_t  axi_out_req_o,  // Downstream AXI request.
  input  output_axi_resp_t axi_out_resp_i  // Downstream AXI response.

);

  if (AXI_ID_WIDTH_IN > AXI_ID_WIDTH_OUT) begin : gen_id_remap
    axi_id_remap #(
      .AxiSlvPortIdWidth(AXI_ID_WIDTH_IN),
      .AxiSlvPortMaxUniqIds(MAX_INFLIGHT_IDS),
      .AxiMaxTxnsPerId(MAX_TXNS_PER_ID),
      .AxiMstPortIdWidth(AXI_ID_WIDTH_OUT),
      .slv_req_t(input_axi_req_t),
      .slv_resp_t(input_axi_resp_t),
      .mst_req_t(output_axi_req_t),
      .mst_resp_t(output_axi_resp_t)
    ) u_axi_id_remap (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .slv_req_i(axi_in_req_i),
      .slv_resp_o(axi_in_resp_o),
      .mst_req_o(axi_out_req_o),
      .mst_resp_i(axi_out_resp_i)
    );
  end else if (AXI_ID_WIDTH_IN < AXI_ID_WIDTH_OUT) begin : gen_id_padding
    prim_axi_id_prepend_wrap #(
      .AxiInIdWidth  (AXI_ID_WIDTH_IN),
      .AxiOutIdWidth (AXI_ID_WIDTH_OUT),
      .AxiDataWidth  (AXI_DATA_WIDTH),
      .AxiAddrWidth  (AXI_ADDR_WIDTH),
      .AxiUserWidth  (AXI_USER_WIDTH),

      .axi_in_req_t   (input_axi_req_t),
      .axi_in_resp_t  (input_axi_resp_t),
      .axi_out_req_t  (output_axi_req_t),
      .axi_out_resp_t (output_axi_resp_t)
    ) u_smc_axi_id_prepend_wrap (
      .axi_in_req_i   (axi_in_req_i),
      .axi_in_resp_o  (axi_in_resp_o),
      .axi_out_req_o  (axi_out_req_o),
      .axi_out_resp_i (axi_out_resp_i)
    );
  end else begin : gen_no_remap
    // assign input directly to output if no remapping needed
    assign axi_out_req_o  = axi_in_req_i;
    assign axi_in_resp_o = axi_out_resp_i;
  end

endmodule

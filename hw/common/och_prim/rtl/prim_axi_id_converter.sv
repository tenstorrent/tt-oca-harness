// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Remap AXI IDs when the upstream ID width exceeds the downstream width.
//
// When AXI_ID_WIDTH_IN is not greater than AXI_ID_WIDTH_OUT, pass requests through.
// Otherwise prepend IDs through prim_axi_id_prepend_wrap with MAX_INFLIGHT_IDS and
// MAX_TXNS_PER_ID limits.
// test_en_i is the DFT enable on the remap path.

module prim_axi_id_converter #(

  parameter int unsigned AXI_ADDR_WIDTH = 64,  // AXI address width.
  parameter int unsigned AXI_DATA_WIDTH = 64,  // AXI data width.
  parameter int unsigned AXI_USER_WIDTH = 1,  // AXI user width.

  parameter int unsigned AXI_ID_WIDTH_IN  = 16,  // Upstream AXI ID width.
  parameter int unsigned AXI_ID_WIDTH_OUT = 8,  // Downstream AXI ID width.

  parameter type input_axi_req_t = logic,  // Upstream request struct.
  parameter type input_axi_resp_t = logic,  // Upstream response struct.
  parameter type output_axi_req_t = logic,  // Downstream request struct.
  parameter type output_axi_resp_t = logic,  // Downstream response struct.

  parameter int unsigned MAX_INFLIGHT_IDS = 4,  // Max distinct remapped IDs in flight.
  parameter int unsigned MAX_TXNS_PER_ID  = 4  // Max outstanding beats per remapped ID.
) (
  input logic clk_i,  // AXI clock.
  input logic rst_ni,  // Async reset, active-low.
  input logic test_en_i,  // DFT/test enable.

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

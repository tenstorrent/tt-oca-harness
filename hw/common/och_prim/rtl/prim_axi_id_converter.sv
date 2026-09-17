// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AXI ID Converter
//
//--------------------------------------------------
module prim_axi_id_converter #(

  parameter int unsigned AXI_ADDR_WIDTH = 64,
  parameter int unsigned AXI_DATA_WIDTH = 64,
  parameter int unsigned AXI_USER_WIDTH = 1,

  parameter int unsigned AXI_ID_WIDTH_IN  = 16,
  parameter int unsigned AXI_ID_WIDTH_OUT = 8,

  parameter type input_axi_req_t = logic,
  parameter type input_axi_resp_t = logic,
  parameter type output_axi_req_t = logic,
  parameter type output_axi_resp_t = logic,

  parameter int unsigned MAX_INFLIGHT_IDS = 4,
  parameter int unsigned MAX_TXNS_PER_ID  = 4
) (
  input logic clk_i,
  input logic rst_ni,
  input logic test_en_i,

  input  input_axi_req_t  axi_in_req_i,
  output input_axi_resp_t axi_in_resp_o,
  output output_axi_req_t  axi_out_req_o,
  input  output_axi_resp_t axi_out_resp_i

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
    ) axi_id_remap (
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

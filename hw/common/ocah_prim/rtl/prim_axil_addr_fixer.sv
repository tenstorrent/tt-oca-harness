// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Widen or truncate AXI-Lite AW and AR addresses between two struct interfaces.
//
// Pass every other AXI-Lite field through unchanged.
// INPUT_ADDR_W and OUTPUT_ADDR_W set whether the path zero-pads the upper address bits or
// drops them. The module is purely combinational.

module prim_axil_addr_fixer #(
  parameter int unsigned INPUT_ADDR_W  = 64,  // Address width on the input AXI-Lite side.
  parameter int unsigned OUTPUT_ADDR_W = 64,  // Address width on the output AXI-Lite side.

  parameter type input_axi_req_t = logic,  // Input-side AXI-Lite request struct.
  parameter type input_axi_resp_t = logic,  // Input-side AXI-Lite response struct.
  parameter type output_axi_req_t = logic,  // Output-side AXI-Lite request struct.
  parameter type output_axi_resp_t = logic  // Output-side AXI-Lite response struct.
) (
  input  input_axi_req_t  axi_in_req_i,  // Upstream AXI-Lite request.
  output input_axi_resp_t axi_in_resp_o,  // Upstream AXI-Lite response.

  output output_axi_req_t  axi_out_req_o,  // Downstream AXI-Lite request with fixed address.
  input  output_axi_resp_t axi_out_resp_i  // Downstream AXI-Lite response.
);

  // If addresses are the same, then we don't need to do anything
  // If input > output, then we need to trim the address
  // If input < output, then we need to pad the address

  // AW Channel - Write Address
  assign axi_out_req_o.aw_valid  = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.prot   = axi_in_req_i.aw.prot;

  // W Channel - Write Data
  assign axi_out_req_o.w_valid   = axi_in_req_i.w_valid;
  assign axi_out_req_o.w.data    = axi_in_req_i.w.data;
  assign axi_out_req_o.w.strb    = axi_in_req_i.w.strb;

  // B Channel - Write Response
  assign axi_out_req_o.b_ready   = axi_in_req_i.b_ready;

  // AR Channel - Read Address
  assign axi_out_req_o.ar_valid  = axi_in_req_i.ar_valid;
  assign axi_out_req_o.ar.prot   = axi_in_req_i.ar.prot;

  // R Channel - Read Data
  assign axi_out_req_o.r_ready   = axi_in_req_i.r_ready;

  // Response mapping from output back to input
  assign axi_in_resp_o.aw_ready  = axi_out_resp_i.aw_ready;
  assign axi_in_resp_o.w_ready   = axi_out_resp_i.w_ready;
  assign axi_in_resp_o.b_valid   = axi_out_resp_i.b_valid;
  assign axi_in_resp_o.b.resp    = axi_out_resp_i.b.resp;
  assign axi_in_resp_o.ar_ready  = axi_out_resp_i.ar_ready;
  assign axi_in_resp_o.r_valid   = axi_out_resp_i.r_valid;
  assign axi_in_resp_o.r.data    = axi_out_resp_i.r.data;
  assign axi_in_resp_o.r.resp    = axi_out_resp_i.r.resp;

  // Address conversion logic
  if (INPUT_ADDR_W == OUTPUT_ADDR_W) begin : gen_passthrough
    assign axi_out_req_o.aw.addr = axi_in_req_i.aw.addr;
    assign axi_out_req_o.ar.addr = axi_in_req_i.ar.addr;
  end else if (INPUT_ADDR_W > OUTPUT_ADDR_W) begin : gen_addr_trim
    assign axi_out_req_o.aw.addr = axi_in_req_i.aw.addr[OUTPUT_ADDR_W-1:0];
    assign axi_out_req_o.ar.addr = axi_in_req_i.ar.addr[OUTPUT_ADDR_W-1:0];
  end else begin : gen_addr_pad
    assign axi_out_req_o.aw.addr = {{(OUTPUT_ADDR_W - INPUT_ADDR_W) {1'b0}}, axi_in_req_i.aw.addr};
    assign axi_out_req_o.ar.addr = {{(OUTPUT_ADDR_W - INPUT_ADDR_W) {1'b0}}, axi_in_req_i.ar.addr};
  end

endmodule

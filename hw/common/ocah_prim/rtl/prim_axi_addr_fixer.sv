// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Widen or truncate AXI AW and AR addresses between two struct interfaces.
//
// Pass every other AXI channel field through unchanged.
// INPUT_ADDR_W and OUTPUT_ADDR_W set whether the path zero-pads the upper address bits or
// drops them. The module is purely combinational.

module prim_axi_addr_fixer #(
  parameter int unsigned INPUT_ADDR_W  = 64,  // Address width on the input AXI side.
  parameter int unsigned OUTPUT_ADDR_W = 64,  // Address width on the output AXI side.

  parameter type input_axi_req_t = logic,  // Input-side AXI request struct.
  parameter type input_axi_resp_t = logic,  // Input-side AXI response struct.
  parameter type output_axi_req_t = logic,  // Output-side AXI request struct.
  parameter type output_axi_resp_t = logic  // Output-side AXI response struct.
) (
  input  input_axi_req_t  axi_in_req_i,  // Upstream AXI request.
  output input_axi_resp_t axi_in_resp_o,  // Upstream AXI response.

  output output_axi_req_t  axi_out_req_o,  // Downstream AXI request with fixed address.
  input  output_axi_resp_t axi_out_resp_i  // Downstream AXI response.
);

  // If addresses are the same, then we don't need to do anything
  // If input > output, then we need to trim the address
  // If input < output, then we need to pad the address

  // AW Channel - Write Address
  assign axi_out_req_o.aw_valid  = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.id     = axi_in_req_i.aw.id;
  assign axi_out_req_o.aw.atop   = axi_in_req_i.aw.atop;
  assign axi_out_req_o.aw.region = axi_in_req_i.aw.region;
  assign axi_out_req_o.aw.user   = axi_in_req_i.aw.user;
  assign axi_out_req_o.aw.len    = axi_in_req_i.aw.len;
  assign axi_out_req_o.aw.size   = axi_in_req_i.aw.size;
  assign axi_out_req_o.aw.burst  = axi_in_req_i.aw.burst;
  assign axi_out_req_o.aw.lock   = axi_in_req_i.aw.lock;
  assign axi_out_req_o.aw.cache  = axi_in_req_i.aw.cache;
  assign axi_out_req_o.aw.prot   = axi_in_req_i.aw.prot;
  assign axi_out_req_o.aw.qos    = axi_in_req_i.aw.qos;

  // W Channel - Write Data
  assign axi_out_req_o.w_valid   = axi_in_req_i.w_valid;
  assign axi_out_req_o.w.data    = axi_in_req_i.w.data;
  assign axi_out_req_o.w.strb    = axi_in_req_i.w.strb;
  assign axi_out_req_o.w.user    = axi_in_req_i.w.user;
  assign axi_out_req_o.w.last    = axi_in_req_i.w.last;

  // B Channel - Write Response
  assign axi_out_req_o.b_ready   = axi_in_req_i.b_ready;

  // AR Channel - Read Address
  assign axi_out_req_o.ar_valid  = axi_in_req_i.ar_valid;
  assign axi_out_req_o.ar.id     = axi_in_req_i.ar.id;
  assign axi_out_req_o.ar.len    = axi_in_req_i.ar.len;
  assign axi_out_req_o.ar.size   = axi_in_req_i.ar.size;
  assign axi_out_req_o.ar.burst  = axi_in_req_i.ar.burst;
  assign axi_out_req_o.ar.lock   = axi_in_req_i.ar.lock;
  assign axi_out_req_o.ar.cache  = axi_in_req_i.ar.cache;
  assign axi_out_req_o.ar.prot   = axi_in_req_i.ar.prot;
  assign axi_out_req_o.ar.qos    = axi_in_req_i.ar.qos;
  assign axi_out_req_o.ar.user   = axi_in_req_i.ar.user;
  assign axi_out_req_o.ar.region = axi_in_req_i.ar.region;

  // R Channel - Read Data
  assign axi_out_req_o.r_ready   = axi_in_req_i.r_ready;

  // Response mapping from output back to input
  assign axi_in_resp_o.aw_ready  = axi_out_resp_i.aw_ready;
  assign axi_in_resp_o.w_ready   = axi_out_resp_i.w_ready;
  assign axi_in_resp_o.b_valid   = axi_out_resp_i.b_valid;
  assign axi_in_resp_o.b.id      = axi_out_resp_i.b.id;
  assign axi_in_resp_o.b.resp    = axi_out_resp_i.b.resp;
  assign axi_in_resp_o.b.user    = axi_out_resp_i.b.user;
  assign axi_in_resp_o.ar_ready  = axi_out_resp_i.ar_ready;
  assign axi_in_resp_o.r_valid   = axi_out_resp_i.r_valid;
  assign axi_in_resp_o.r.id      = axi_out_resp_i.r.id;
  assign axi_in_resp_o.r.data    = axi_out_resp_i.r.data;
  assign axi_in_resp_o.r.resp    = axi_out_resp_i.r.resp;
  assign axi_in_resp_o.r.last    = axi_out_resp_i.r.last;
  assign axi_in_resp_o.r.user    = axi_out_resp_i.r.user;

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

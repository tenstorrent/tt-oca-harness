// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2025 Tenstorrent Inc.

// Route cross-trigger pulses from CT_Dst inputs onto CT_Src outputs through programmable OR masks.
//
// NUM_CT_SRC and NUM_CT_DST are localparams from the RDL package so the map addresses
// every select bit; they are not module parameters.
// Past 32 destinations the RDL widens the select field across both register words; decode
// still sees one value.
// AXI-Lite CSRs program per-source selects; each CT_Src path registers its OR result.

module cross_trigger_matrix
  import cross_trigger_matrix_pkg::*;
#(
  parameter type axil_req_t = cross_trigger_matrix_pkg::ctm_axil_req_t,  // CTM AXI-Lite request type.
  parameter type axil_resp_t = cross_trigger_matrix_pkg::ctm_axil_resp_t  // CTM AXI-Lite response type.
) (
  input  logic                    clk_i,  // System clock for the AXI-Lite CSRs and the routing
                                          // logic.
  input  logic                    rst_ni,  // Active-low asynchronous system reset.

  input  axil_req_t               axil_req_i,  // AXI-Lite CSR request that programs the per-source
                                               // routing masks; only the address bits the
                                               // register map spans are decoded.
  output axil_resp_t              axil_resp_o,  // AXI-Lite CSR response.

  input  logic [NUM_CT_DST-1:0]   ct_dst_i,  // Cross-trigger pulses into the routing matrix, one
                                             // bit per CT_Dst port.

  output logic [NUM_CT_SRC-1:0]   ct_src_o  // Routed cross-trigger pulses, one registered bit per
                                            // CT_Src port.
);

  `include "prim_assert.sv"

  // Register interface (no hwif_in needed - all registers are write-only from software)
  cross_trigger_matrix_reg_pkg::cross_trigger_matrix__out_t reg_out;

  // NUM_CT_DST comes from the register map's own parameter; check it against the
  // width the map actually generated for the select field.
  localparam int unsigned CT_DST_SELECT_WIDTH = $bits(
      reg_out.CT_SRC[0].CONFIG_0.CT_DST_SELECT.value
  );

  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumCtDstMatchesField_A, NUM_CT_DST == CT_DST_SELECT_WIDTH)

  localparam int unsigned REG_ADDR_WIDTH =
      cross_trigger_matrix_reg_pkg::CROSS_TRIGGER_MATRIX_REG_MIN_ADDR_WIDTH;

  // Register module instantiation - wire AXI-Lite structs directly
  cross_trigger_matrix_reg u_reg (
    .clk           (clk_i),
    .arst_n        (rst_ni),

    // Write address channel
    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr[REG_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (axil_req_i.aw.prot),

    // Write data channel
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),

    // Write response channel
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),

    // Read address channel
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr[REG_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (axil_req_i.ar.prot),

    // Read data channel
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_out      (reg_out)
  );

  // Generate selector modules for each CT_Src port
  for (genvar i = 0; i < NUM_CT_SRC; i++) begin : gen_src_selectors
    // Select mask for this CT_Src, one config register per port
    logic [NUM_CT_DST-1:0] select_mask;

    assign select_mask = reg_out.CT_SRC[i].CONFIG_0.CT_DST_SELECT.value;

    // Instantiate selector module for this CT_Src
    ctm_src_selector #(
      .NUM_CT_DST(NUM_CT_DST)
    ) u_src_selector (
      .clk_i      (clk_i),
      .rst_ni     (rst_ni),
      .ct_dst_i   (ct_dst_i),
      .select_i   (select_mask),
      .ct_src_o   (ct_src_o[i])
    );
  end

endmodule : cross_trigger_matrix

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stub for i3ccore_wrapper.
//
// Mirrors the i3ccore_wrapper port list exactly so it can be swapped in via a
// generate block. The AXI-Lite slave interface is terminated with a
// prim_axi_lite_err_slv so that any accidental access to the stubbed I3C
// returns a DECERR response instead of hanging the bus. All remaining outputs
// are driven to safe (zero) values and all remaining inputs are absorbed into a
// dummy "unused" signal to keep the design lint-clean.

module i3ccore_stub
  import i3ccore_wrap_pkg::*;
  import i3c_pkg::*;
#(
  parameter int unsigned NUM_I3C = 2,
  parameter int unsigned I3C_REG_ADDR_WIDTH = i3ccore_wrap_pkg::I3C_REG_ADDR_WIDTH,
  parameter int unsigned BASE_ADDR = 0,
  parameter int unsigned INSTANCE_SPACING = 32'h500,  // Address space per instance

  // I3C Core parameters
  parameter int unsigned DatAw = i3c_pkg::DatAw,
  parameter int unsigned DctAw = i3c_pkg::DctAw
) (
  input wire logic clk_i,
  input wire logic rst_ni,

  // AXI4-Lite slave interface
  // Write Address Channel
  input  wire logic            awvalid_i,
  output logic                 awready_o,
  input  wire reg_addr_t       awaddr_i,
  input  wire logic      [2:0] awprot_i,

  // Write Data Channel
  input  wire logic      wvalid_i,
  output logic           wready_o,
  input  wire reg_data_t wdata_i,
  input  wire reg_strb_t wstrb_i,

  // Write Response Channel
  output logic            bvalid_o,
  input  wire logic       bready_i,
  output logic      [1:0] bresp_o,

  // Read Address Channel
  input  wire logic            arvalid_i,
  output logic                 arready_o,
  input  wire reg_addr_t       araddr_i,
  input  wire logic      [2:0] arprot_i,

  // Read Data Channel
  output logic            rvalid_o,
  input  wire logic       rready_i,
  output reg_data_t       rdata_o,
  output logic      [1:0] rresp_o,

  // Interrupts - one per I3C instance
  output logic [NUM_I3C-1:0] irq_o,

  // I3C bus signals - one set per instance
  input wire logic [NUM_I3C-1:0] scl_i,
  input wire logic [NUM_I3C-1:0] sda_i,
  output logic [NUM_I3C-1:0] scl_o,
  output logic [NUM_I3C-1:0] sda_o,
  output logic [NUM_I3C-1:0] scl_oe_o,
  output logic [NUM_I3C-1:0] sda_oe_o,
  output logic [NUM_I3C-1:0] sel_od_pp_o,

  // Recovery interface signals
  output logic [NUM_I3C-1:0] recovery_payload_available_o,
  output logic [NUM_I3C-1:0] recovery_image_activated_o,
  output logic [NUM_I3C-1:0] peripheral_reset_o,
  input wire logic [NUM_I3C-1:0] peripheral_reset_done_i,
  output logic [NUM_I3C-1:0] escalated_reset_o,

  // I3C DAT/DCT memory interfaces (NUM_I3C instances)
  input  wire i3c_pkg::dat_mem_src_t [NUM_I3C-1:0] dat_mem_src_i,
  output i3c_pkg::dat_mem_sink_t     [NUM_I3C-1:0] dat_mem_sink_o,
  input  wire i3c_pkg::dct_mem_src_t [NUM_I3C-1:0] dct_mem_src_i,
  output i3c_pkg::dct_mem_sink_t     [NUM_I3C-1:0] dct_mem_sink_o
);

  ///////////////////////////////
  // AXI-Lite Error Termination //
  ///////////////////////////////

  // Pack the flat AXI-Lite inputs into the request struct (mirrors the wrapper)
  i3ccore_wrap_pkg::axil_req_t  axil_req;
  i3ccore_wrap_pkg::axil_resp_t axil_resp;

  assign axil_req = '{
          aw: '{addr: awaddr_i, prot: awprot_i},
          aw_valid: awvalid_i,
          w: '{data: wdata_i, strb: wstrb_i},
          w_valid: wvalid_i,
          b_ready: bready_i,
          ar: '{addr: araddr_i, prot: arprot_i},
          ar_valid: arvalid_i,
          r_ready: rready_i
      };

  // Error slave: completes any access with an SLVERR response so the bus never
  // hangs (SLVERR lets the CPU continue executing past the access)
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(i3ccore_wrap_pkg::REG_ADDR_WIDTH),
    .AXI_DATA_WIDTH(i3ccore_wrap_pkg::REG_DATA_WIDTH),
    .axil_req_t    (i3ccore_wrap_pkg::axil_req_t),
    .axil_resp_t   (i3ccore_wrap_pkg::axil_resp_t),
    .RESP          (axi_pkg::RESP_SLVERR),
    .RESP_WIDTH    (i3ccore_wrap_pkg::REG_DATA_WIDTH),
    .RESP_DATA     (32'hBADCAB1E)
  ) u_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .axil_req_i (axil_req),
    .axil_resp_o(axil_resp)
  );

  // Unpack response struct to the flat AXI-Lite outputs (mirrors the wrapper)
  assign awready_o                    = axil_resp.aw_ready;
  assign wready_o                     = axil_resp.w_ready;
  assign bvalid_o                     = axil_resp.b_valid;
  assign bresp_o                      = axil_resp.b.resp;
  assign arready_o                    = axil_resp.ar_ready;
  assign rvalid_o                     = axil_resp.r_valid;
  assign rdata_o                      = axil_resp.r.data;
  assign rresp_o                      = axil_resp.r.resp;

  ///////////////////////
  // Tie-off / Defaults //
  ///////////////////////

  // Drive all remaining outputs to safe (zero) values
  assign irq_o                        = '0;
  assign scl_o                        = '0;
  assign sda_o                        = '0;
  assign scl_oe_o                     = '0;
  assign sda_oe_o                     = '0;
  assign sel_od_pp_o                  = '0;
  assign recovery_payload_available_o = '0;
  assign recovery_image_activated_o   = '0;
  assign peripheral_reset_o           = '0;
  assign escalated_reset_o            = '0;
  assign dat_mem_sink_o               = '0;
  assign dct_mem_sink_o               = '0;

  // Absorb remaining unused inputs into a dummy signal to avoid lint warnings
  logic unused_signals;
  assign unused_signals = ^{scl_i, sda_i, peripheral_reset_done_i, dat_mem_src_i, dct_mem_src_i};

endmodule

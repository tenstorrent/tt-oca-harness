// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the SMU AXI crossbar: a disabled aperture routes nothing, every response
// answers an accepted request, and the routing table of the SMU chapter is reachable cell by cell.
// Attached to smu_axi_xbar by smu_axi_xbar_bind.sv and checked with smu_axi_xbar as the formal
// top. Every property body is a boolean over current values and helper flops
// (hw/common/dv/docs/formal-property-style.adoc). The expected behaviour comes from the "AXI
// Crossbar" section of hw/sys/smu/doc/index.adoc: the ports table, the aperture decode (an
// aperture is [base, base + size) on 57 bits, and a region size of 0 disables it) and the routing
// table by initiator and decoded aperture, whose DECERR responses the crossbar generates itself.
//
// Ports are indexed 0 to 5 as sep_out, smc_out and ext_in (initiators), then sep_in, smc_in and
// ext_out (targets). The AXI handshake rules of every port are the shared checker's, bound by
// smu_axi_xbar_axi_fv_bind.sv; this module states the crossbar's own behaviour.

`include "ocah_fv_macros.svh"

module smu_axi_xbar_props
  import smu_axi_xbar_pkg::axi_56_64_req_t;
  import smu_axi_xbar_pkg::axi_56_64_resp_t;
  import smu_axi_xbar_pkg::axi_out_req_t;
  import smu_axi_xbar_pkg::axi_out_resp_t;
#(
  parameter int unsigned MAX_OUTSTANDING = 8,  // Requests per direction a port may hold open.
  localparam int unsigned CntW = $clog2(MAX_OUTSTANDING + 2)  // Width of the open-request counts.
) (
  input logic            clk_i,                   // Crossbar clock; every check samples here.
  input logic            rst_ni,                  // Active-low crossbar reset, masking every check.
  input logic [55:0]     sep_global_base_addr_i,  // First byte address of the SEP aperture.
  input logic [31:0]     sep_region_size_i,       // SEP aperture size in bytes; 0 disables it.
  input logic [55:0]     smc_global_base_addr_i,  // First byte address of the SMC aperture.
  input logic [31:0]     smc_region_size_i,       // SMC aperture size in bytes; 0 disables it.
  input axi_56_64_req_t  sep_out_req_i,           // SEP initiator request into the crossbar.
  input axi_56_64_resp_t sep_out_resp_i,          // Crossbar response to the SEP initiator.
  input axi_56_64_req_t  smc_out_req_i,           // SMC initiator request into the crossbar.
  input axi_56_64_resp_t smc_out_resp_i,          // Crossbar response to the SMC initiator.
  input axi_56_64_req_t  ext_in_req_i,            // External initiator request into the crossbar.
  input axi_56_64_resp_t ext_in_resp_i,           // Crossbar response to the external initiator.
  input axi_out_req_t    sep_in_req_i,            // Crossbar request toward the SEP target.
  input axi_out_resp_t   sep_in_resp_i,           // SEP target response into the crossbar.
  input axi_out_req_t    smc_in_req_i,            // Crossbar request toward the SMC target.
  input axi_out_resp_t   smc_in_resp_i,           // SMC target response into the crossbar.
  input axi_out_req_t    ext_out_req_i,           // Crossbar request toward the external target.
  input axi_out_resp_t   ext_out_resp_i           // External target response into the crossbar.
);

  localparam int unsigned NumPorts = 6;
  localparam int unsigned NumInitiators = 3;
  localparam int unsigned SepOut = 0;
  localparam int unsigned SmcOut = 1;
  localparam int unsigned ExtIn = 2;
  localparam int unsigned SepIn = 3;
  localparam int unsigned SmcIn = 4;
  localparam int unsigned ExtOut = 5;

  localparam logic [1:0] RespDecerr = 2'b11;
  localparam logic [CntW-1:0] Capacity = CntW'(MAX_OUTSTANDING);

  // An aperture holds [base, base + size), the sum on 57 bits; a size of 0 holds no address.
  function automatic logic in_aperture(input logic [55:0] addr, input logic [55:0] base,
                                       input logic [31:0] size);
    return size != '0 && {1'b0, addr} >= {1'b0, base} && {1'b0, addr} < ({1'b0, base} + 57'(size));
  endfunction

  // The routing table's DECERR cell of each initiator: sep_out in the SEP aperture, smc_out in the
  // SMC aperture, ext_in in neither.
  function automatic logic in_decerr_cell(input int unsigned initiator, input logic [55:0] addr,
                                          input logic [55:0] sep_base, input logic [31:0] sep_size,
                                          input logic [55:0] smc_base, input logic [31:0] smc_size);
    logic sep_hit, smc_hit;
    sep_hit = in_aperture(addr, sep_base, sep_size);
    smc_hit = in_aperture(addr, smc_base, smc_size);
    case (initiator)
      SepOut:  return sep_hit && !smc_hit;
      SmcOut:  return smc_hit && !sep_hit;
      default: return !sep_hit && !smc_hit;
    endcase
  endfunction

  logic [NumPorts-1:0] aw_hs, b_hs, ar_hs, rlast_hs, ax_valid;
  assign aw_hs[SepOut] = sep_out_req_i.aw_valid && sep_out_resp_i.aw_ready;
  assign aw_hs[SmcOut] = smc_out_req_i.aw_valid && smc_out_resp_i.aw_ready;
  assign aw_hs[ExtIn]  = ext_in_req_i.aw_valid && ext_in_resp_i.aw_ready;
  assign aw_hs[SepIn]  = sep_in_req_i.aw_valid && sep_in_resp_i.aw_ready;
  assign aw_hs[SmcIn]  = smc_in_req_i.aw_valid && smc_in_resp_i.aw_ready;
  assign aw_hs[ExtOut] = ext_out_req_i.aw_valid && ext_out_resp_i.aw_ready;

  assign b_hs[SepOut] = sep_out_resp_i.b_valid && sep_out_req_i.b_ready;
  assign b_hs[SmcOut] = smc_out_resp_i.b_valid && smc_out_req_i.b_ready;
  assign b_hs[ExtIn]  = ext_in_resp_i.b_valid && ext_in_req_i.b_ready;
  assign b_hs[SepIn]  = sep_in_resp_i.b_valid && sep_in_req_i.b_ready;
  assign b_hs[SmcIn]  = smc_in_resp_i.b_valid && smc_in_req_i.b_ready;
  assign b_hs[ExtOut] = ext_out_resp_i.b_valid && ext_out_req_i.b_ready;

  assign ar_hs[SepOut] = sep_out_req_i.ar_valid && sep_out_resp_i.ar_ready;
  assign ar_hs[SmcOut] = smc_out_req_i.ar_valid && smc_out_resp_i.ar_ready;
  assign ar_hs[ExtIn]  = ext_in_req_i.ar_valid && ext_in_resp_i.ar_ready;
  assign ar_hs[SepIn]  = sep_in_req_i.ar_valid && sep_in_resp_i.ar_ready;
  assign ar_hs[SmcIn]  = smc_in_req_i.ar_valid && smc_in_resp_i.ar_ready;
  assign ar_hs[ExtOut] = ext_out_req_i.ar_valid && ext_out_resp_i.ar_ready;

  assign rlast_hs[SepOut] = sep_out_resp_i.r_valid && sep_out_req_i.r_ready &&
                            sep_out_resp_i.r.last;
  assign rlast_hs[SmcOut] = smc_out_resp_i.r_valid && smc_out_req_i.r_ready &&
                            smc_out_resp_i.r.last;
  assign rlast_hs[ExtIn]  = ext_in_resp_i.r_valid && ext_in_req_i.r_ready && ext_in_resp_i.r.last;
  assign rlast_hs[SepIn]  = sep_in_resp_i.r_valid && sep_in_req_i.r_ready && sep_in_resp_i.r.last;
  assign rlast_hs[SmcIn]  = smc_in_resp_i.r_valid && smc_in_req_i.r_ready && smc_in_resp_i.r.last;
  assign rlast_hs[ExtOut] = ext_out_resp_i.r_valid && ext_out_req_i.r_ready &&
                            ext_out_resp_i.r.last;

  assign ax_valid[SepOut] = sep_out_req_i.aw_valid || sep_out_req_i.ar_valid;
  assign ax_valid[SmcOut] = smc_out_req_i.aw_valid || smc_out_req_i.ar_valid;
  assign ax_valid[ExtIn]  = ext_in_req_i.aw_valid || ext_in_req_i.ar_valid;
  assign ax_valid[SepIn]  = sep_in_req_i.aw_valid || sep_in_req_i.ar_valid;
  assign ax_valid[SmcIn]  = smc_in_req_i.aw_valid || smc_in_req_i.ar_valid;
  assign ax_valid[ExtOut] = ext_out_req_i.aw_valid || ext_out_req_i.ar_valid;

  logic [NumInitiators-1:0][55:0] init_awaddr, init_araddr;
  logic [NumInitiators-1:0][1:0] init_bresp, init_rresp;
  assign init_awaddr = {ext_in_req_i.aw.addr, smc_out_req_i.aw.addr, sep_out_req_i.aw.addr};
  assign init_araddr = {ext_in_req_i.ar.addr, smc_out_req_i.ar.addr, sep_out_req_i.ar.addr};
  assign init_bresp  = {ext_in_resp_i.b.resp, smc_out_resp_i.b.resp, sep_out_resp_i.b.resp};
  assign init_rresp  = {ext_in_resp_i.r.resp, smc_out_resp_i.r.resp, sep_out_resp_i.r.resp};

  logic [NumInitiators-1:0] aw_in_decerr_cell, ar_in_decerr_cell;
  for (genvar i = 0; i < NumInitiators; i++) begin : gen_decerr_cell
    assign aw_in_decerr_cell[i] = in_decerr_cell(i, init_awaddr[i],
                                                 sep_global_base_addr_i, sep_region_size_i,
                                                 smc_global_base_addr_i, smc_region_size_i);
    assign ar_in_decerr_cell[i] = in_decerr_cell(i, init_araddr[i],
                                                 sep_global_base_addr_i, sep_region_size_i,
                                                 smc_global_base_addr_i, smc_region_size_i);
  end

  // Helper flops, all cleared by reset:
  //   writes_open_q / reads_open_q: accepted AW minus B handshakes, accepted AR minus R-last
  //     handshakes, per port.
  //   sep_off_q / smc_off_q: the region size has been 0 at every edge since reset.
  //   aw_seen_q / ar_seen_q: the initiator has had an AW (AR) accepted since reset.
  //   aw_all_decerr_q / ar_all_decerr_q: every AW (AR) the initiator had accepted fell in its
  //     DECERR cell.
  //   targets_idle_q: no target port has raised AW or AR valid since reset.
  logic [NumPorts-1:0][CntW-1:0] writes_open_q, reads_open_q;
  logic sep_off_q, smc_off_q, targets_idle_q;
  logic [NumInitiators-1:0] aw_seen_q, ar_seen_q, aw_all_decerr_q, ar_all_decerr_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      writes_open_q   <= '0;
      reads_open_q    <= '0;
      sep_off_q       <= 1'b1;
      smc_off_q       <= 1'b1;
      targets_idle_q  <= 1'b1;
      aw_seen_q       <= '0;
      ar_seen_q       <= '0;
      aw_all_decerr_q <= '1;
      ar_all_decerr_q <= '1;
    end else begin
      for (int p = 0; p < NumPorts; p++) begin
        writes_open_q[p] <= writes_open_q[p] + CntW'(aw_hs[p]) - CntW'(b_hs[p]);
        reads_open_q[p]  <= reads_open_q[p] + CntW'(ar_hs[p]) - CntW'(rlast_hs[p]);
      end
      sep_off_q      <= sep_off_q && sep_region_size_i == '0;
      smc_off_q      <= smc_off_q && smc_region_size_i == '0;
      targets_idle_q <= targets_idle_q && !ax_valid[SepIn] && !ax_valid[SmcIn] &&
                        !ax_valid[ExtOut];
      for (int i = 0; i < NumInitiators; i++) begin
        aw_seen_q[i]       <= aw_seen_q[i] || aw_hs[i];
        ar_seen_q[i]       <= ar_seen_q[i] || ar_hs[i];
        aw_all_decerr_q[i] <= aw_all_decerr_q[i] && (!aw_hs[i] || aw_in_decerr_cell[i]);
        ar_all_decerr_q[i] <= ar_all_decerr_q[i] && (!ar_hs[i] || ar_in_decerr_cell[i]);
      end
    end
  end

  // The initiators with an address accepted since reset, this cycle's handshakes included.
  logic [NumInitiators-1:0] addr_seen;
  assign addr_seen = aw_seen_q | ar_seen_q | aw_hs[ExtIn:SepOut] | ar_hs[ExtIn:SepOut];

  logic targets_idle;
  assign targets_idle = targets_idle_q && !ax_valid[SepIn] && !ax_valid[SmcIn] && !ax_valid[ExtOut];

  logic sep_disabled, smc_disabled;
  assign sep_disabled = sep_off_q && sep_region_size_i == '0;
  assign smc_disabled = smc_off_q && smc_region_size_i == '0;

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  // ---- A region size of 0 disables its aperture (index.adoc, aperture decode) -----------------
  // Only an address in the SEP aperture reaches sep_in and only one in the SMC aperture reaches
  // smc_in (routing table); with the size 0 since reset no request ever decoded into it.
  `OCAH_FV_ASSERT(ast_xbar_zero_sep_aperture_routes_nothing,
                  `OCAH_FV_IMPLIES(sep_disabled,
                                   !sep_in_req_i.aw_valid && !sep_in_req_i.ar_valid),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_xbar_zero_smc_aperture_routes_nothing,
                  `OCAH_FV_IMPLIES(smc_disabled,
                                   !smc_in_req_i.aw_valid && !smc_in_req_i.ar_valid),
                  clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_zero_sep_aperture_request,
                 sep_disabled && (aw_hs[SmcOut] || ar_hs[SmcOut] || aw_hs[ExtIn] || ar_hs[ExtIn]),
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_zero_smc_aperture_request,
                 smc_disabled && (aw_hs[SepOut] || ar_hs[SepOut] || aw_hs[ExtIn] || ar_hs[ExtIn]),
                 clk_i, rst_ni)

  // ---- Every response answers an accepted request, per port ----------------------------------
  // A B handshake needs an accepted AW without its B, an R-last handshake an accepted AR without
  // its last beat, the address handshake of the same cycle included, as in the shared checker's
  // reading of A3.3.1; neither count exceeds MAX_OUTSTANDING. The covers are the liveness half:
  // a response does follow an accepted request.
  for (genvar p = 0; p < NumPorts; p++) begin : gen_port
    `OCAH_FV_ASSERT(ast_xbar_one_response_per_request,
                    `OCAH_FV_IMPLIES(b_hs[p], writes_open_q[p] != '0 || aw_hs[p]) &&
                    `OCAH_FV_IMPLIES(rlast_hs[p], reads_open_q[p] != '0 || ar_hs[p]) &&
                    writes_open_q[p] <= Capacity && reads_open_q[p] <= Capacity,
                    clk_i, rst_ni)
    `OCAH_FV_COVER(cov_xbar_b_after_aw, b_hs[p] && writes_open_q[p] != '0, clk_i, rst_ni)
    `OCAH_FV_COVER(cov_xbar_rlast_after_ar, rlast_hs[p] && reads_open_q[p] != '0, clk_i, rst_ni)
  end

  // ---- Routed requests: the six legal pairs of the ports table -------------------------------
  // A target raises a request while one initiator alone has had an address accepted since reset.
  `OCAH_FV_COVER(cov_xbar_route_sep_out_to_smc_in,
                 ax_valid[SmcIn] && addr_seen == 3'b001, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_route_sep_out_to_ext_out,
                 ax_valid[ExtOut] && addr_seen == 3'b001, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_route_smc_out_to_sep_in,
                 ax_valid[SepIn] && addr_seen == 3'b010, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_route_smc_out_to_ext_out,
                 ax_valid[ExtOut] && addr_seen == 3'b010, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_route_ext_in_to_sep_in,
                 ax_valid[SepIn] && addr_seen == 3'b100, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_route_ext_in_to_smc_in,
                 ax_valid[SmcIn] && addr_seen == 3'b100, clk_i, rst_ni)

  // ---- DECERR cells of the routing table -----------------------------------------------------
  // The initiator receives DECERR for requests that all fell in its DECERR cell while no target
  // has seen a request, so the crossbar generated the response itself.
  `OCAH_FV_COVER(cov_xbar_decerr_sep_out_sep_aperture_write,
                 b_hs[SepOut] && init_bresp[SepOut] == RespDecerr && aw_seen_q[SepOut] &&
                 aw_all_decerr_q[SepOut] && targets_idle, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_decerr_sep_out_sep_aperture_read,
                 rlast_hs[SepOut] && init_rresp[SepOut] == RespDecerr && ar_seen_q[SepOut] &&
                 ar_all_decerr_q[SepOut] && targets_idle, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_decerr_smc_out_smc_aperture_write,
                 b_hs[SmcOut] && init_bresp[SmcOut] == RespDecerr && aw_seen_q[SmcOut] &&
                 aw_all_decerr_q[SmcOut] && targets_idle, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_decerr_smc_out_smc_aperture_read,
                 rlast_hs[SmcOut] && init_rresp[SmcOut] == RespDecerr && ar_seen_q[SmcOut] &&
                 ar_all_decerr_q[SmcOut] && targets_idle, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_decerr_ext_in_no_aperture_write,
                 b_hs[ExtIn] && init_bresp[ExtIn] == RespDecerr && aw_seen_q[ExtIn] &&
                 aw_all_decerr_q[ExtIn] && targets_idle, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_xbar_decerr_ext_in_no_aperture_read,
                 rlast_hs[ExtIn] && init_rresp[ExtIn] == RespDecerr && ar_seen_q[ExtIn] &&
                 ar_all_decerr_q[ExtIn] && targets_idle, clk_i, rst_ni)
  // verilog_format: on

endmodule : smu_axi_xbar_props

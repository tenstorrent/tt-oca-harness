// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment of the JTAG2AXI bridge item on the dtp formal top, read beside
// dtp_sby_env.sv: the request port of the System Bus Access engine inside each tdr2axi, and the
// responder facts of each manager port that the shared AXI checker has no history for. Bound to
// jtag_ptap once per bridge by the statements at the end of this file and read only by the task
// file.
//
// The task file cuts the engine's request outputs and the access size, so a request reaches the
// AXI converter without a DMI scan and its clock-domain crossing. The assumptions state what
// dm_sba does on that port: it raises a request in its Read or Write state and holds it, with its
// address, data, byte enables and direction, until the grant, and it never requests in reset. It
// issues no size above the bus width, and the Debug Module keeps sbaccess while the engine is
// busy, from the request to the response.
//
// Every request a bridge issues is a single beat, so every read returns one, and a target answers
// with the ID of the request it answers.

`include "ocah_fv_macros.svh"

module dtp_j2a_sby_env #(
  parameter int unsigned ADDR_WIDTH = 32,
  parameter int unsigned DATA_WIDTH = 32,
  parameter int unsigned ID_WIDTH   = 1
) (
  // System Bus Access request port of tdr2axi, a cutpoint in the task file
  input logic                    sba_clk_i,        // u_tdr2axi.i_clk
  input logic                    sba_rst_ni,       // u_tdr2axi.arst_clk_n
  input logic                    mem_req_i,        // u_tdr2axi.mem_req
  input logic                    mem_gnt_i,        // u_tdr2axi.mem_gnt
  input logic                    mem_we_i,         // u_tdr2axi.mem_we
  input logic [ADDR_WIDTH-1:0]   mem_addr_i,       // u_tdr2axi.mem_addr
  input logic [DATA_WIDTH-1:0]   mem_wdata_i,      // u_tdr2axi.mem_wdata
  input logic [DATA_WIDTH/8-1:0] mem_be_i,         // u_tdr2axi.mem_be
  input logic                    mem_rsp_valid_i,  // u_tdr2axi.mem_rsp_valid
  input logic [2:0]              sbaccess_i,       // u_tdr2axi.sbaccess
  // Manager port
  input logic                    clk_i,
  input logic                    rst_ni,
  input logic                    aw_hs_i,          // AW handshake
  input logic [ID_WIDTH-1:0]     aw_id_i,
  input logic                    b_valid_i,
  input logic [ID_WIDTH-1:0]     b_id_i,
  input logic                    ar_hs_i,          // AR handshake
  input logic [ID_WIDTH-1:0]     ar_id_i,
  input logic                    r_valid_i,
  input logic [ID_WIDTH-1:0]     r_id_i,
  input logic                    r_last_i
);

`ifdef FORMAL
  localparam logic [2:0] MaxSbaccess = 3'($clog2(DATA_WIDTH / 8));

  // The engine has a granted request whose response is pending.
  logic mem_open_q;
  always_ff @(posedge sba_clk_i or negedge sba_rst_ni) begin
    if (!sba_rst_ni) mem_open_q <= 1'b0;
    else if (mem_req_i && mem_gnt_i) mem_open_q <= 1'b1;
    else if (mem_rsp_valid_i) mem_open_q <= 1'b0;
  end

  logic [ID_WIDTH-1:0] aw_id_q, ar_id_q;
  always_ff @(posedge clk_i) begin
    if (aw_hs_i) aw_id_q <= aw_id_i;
    if (ar_hs_i) ar_id_q <= ar_id_i;
  end

  always_comb begin
    asm_env_mem_idle_in_reset : assume (sba_rst_ni || !mem_req_i);
  end

  // verilog_format: off
  `OCAH_FV_ASSUME(asm_env_mem_req_held,
                  `OCAH_FV_IMPLIES($past(sba_rst_ni) && $past(mem_req_i && !mem_gnt_i),
                                   mem_req_i && mem_we_i == $past(mem_we_i) &&
                                   mem_addr_i == $past(mem_addr_i) &&
                                   mem_wdata_i == $past(mem_wdata_i) &&
                                   mem_be_i == $past(mem_be_i)),
                  sba_clk_i, sba_rst_ni)
  `OCAH_FV_ASSUME(asm_env_mem_size_legal,
                  `OCAH_FV_IMPLIES(mem_req_i || mem_open_q, sbaccess_i <= MaxSbaccess),
                  sba_clk_i, sba_rst_ni)
  `OCAH_FV_ASSUME(asm_env_mem_size_held,
                  `OCAH_FV_IMPLIES($past(sba_rst_ni) && $past(mem_req_i || mem_open_q),
                                   sbaccess_i == $past(sbaccess_i)),
                  sba_clk_i, sba_rst_ni)
  `OCAH_FV_ASSUME(asm_env_r_single_beat, `OCAH_FV_IMPLIES(r_valid_i, r_last_i), clk_i, rst_ni)
  `OCAH_FV_ASSUME(asm_env_resp_id_matches,
                  `OCAH_FV_IMPLIES(b_valid_i, b_id_i == aw_id_q) &&
                  `OCAH_FV_IMPLIES(r_valid_i, r_id_i == ar_id_q),
                  clk_i, rst_ni)
  // verilog_format: on
`endif

endmodule : dtp_j2a_sby_env

bind jtag_ptap dtp_j2a_sby_env #(
  .ADDR_WIDTH ($bits(axil_smc_otp_jtag_req_o.aw.addr)),
  .DATA_WIDTH ($bits(axil_smc_otp_jtag_req_o.w.data))
) u_dtp_j2a_sby_env_smc_otp (
  .sba_clk_i       (clk_i),
  .sba_rst_ni      (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.arst_clk_n),
  .mem_req_i       (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_req),
  .mem_gnt_i       (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_gnt),
  .mem_we_i        (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_we),
  .mem_addr_i      (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_addr),
  .mem_wdata_i     (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_wdata),
  .mem_be_i        (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_be),
  .mem_rsp_valid_i (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_rsp_valid),
  .sbaccess_i      (gen_smc_otp_jtag2axi.u_smc_otp_jtag2axi.gen_axi_lite.u_tdr2axi.sbaccess),
  .clk_i           (clk_i),
  .rst_ni          (rst_n_i),
  .aw_hs_i         (1'b0),
  .aw_id_i         ('0),
  .b_valid_i       (axil_smc_otp_jtag_resp_i.b_valid),
  .b_id_i          ('0),
  .ar_hs_i         (1'b0),
  .ar_id_i         ('0),
  .r_valid_i       (axil_smc_otp_jtag_resp_i.r_valid),
  .r_id_i          ('0),
  .r_last_i        (1'b1)
);

bind jtag_ptap dtp_j2a_sby_env #(
  .ADDR_WIDTH ($bits(axil_sep_otp_jtag_req_o.aw.addr)),
  .DATA_WIDTH ($bits(axil_sep_otp_jtag_req_o.w.data))
) u_dtp_j2a_sby_env_sep_otp (
  .sba_clk_i       (clk_i),
  .sba_rst_ni      (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.arst_clk_n),
  .mem_req_i       (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_req),
  .mem_gnt_i       (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_gnt),
  .mem_we_i        (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_we),
  .mem_addr_i      (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_addr),
  .mem_wdata_i     (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_wdata),
  .mem_be_i        (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_be),
  .mem_rsp_valid_i (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.mem_rsp_valid),
  .sbaccess_i      (gen_sep_otp_jtag2axi.u_sep_otp_jtag2axi.gen_axi_lite.u_tdr2axi.sbaccess),
  .clk_i           (clk_i),
  .rst_ni          (rst_n_i),
  .aw_hs_i         (1'b0),
  .aw_id_i         ('0),
  .b_valid_i       (axil_sep_otp_jtag_resp_i.b_valid),
  .b_id_i          ('0),
  .ar_hs_i         (1'b0),
  .ar_id_i         ('0),
  .r_valid_i       (axil_sep_otp_jtag_resp_i.r_valid),
  .r_id_i          ('0),
  .r_last_i        (1'b1)
);

bind jtag_ptap dtp_j2a_sby_env #(
  .ADDR_WIDTH ($bits(axi_smc_dbg_req_o.aw.addr)),
  .DATA_WIDTH ($bits(axi_smc_dbg_req_o.w.data)),
  .ID_WIDTH   ($bits(axi_smc_dbg_req_o.aw.id))
) u_dtp_j2a_sby_env_smc (
  .sba_clk_i       (clk_i),
  .sba_rst_ni      (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.arst_clk_n),
  .mem_req_i       (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_req),
  .mem_gnt_i       (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_gnt),
  .mem_we_i        (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_we),
  .mem_addr_i      (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_addr),
  .mem_wdata_i     (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_wdata),
  .mem_be_i        (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_be),
  .mem_rsp_valid_i (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.mem_rsp_valid),
  .sbaccess_i      (gen_smc_jtag2axi.u_smc_jtag2axi.gen_axi.u_tdr2axi.sbaccess),
  .clk_i           (clk_i),
  .rst_ni          (rst_n_i),
  .aw_hs_i         (axi_smc_dbg_req_o.aw_valid && axi_smc_dbg_resp_i.aw_ready),
  .aw_id_i         (axi_smc_dbg_req_o.aw.id),
  .b_valid_i       (axi_smc_dbg_resp_i.b_valid),
  .b_id_i          (axi_smc_dbg_resp_i.b.id),
  .ar_hs_i         (axi_smc_dbg_req_o.ar_valid && axi_smc_dbg_resp_i.ar_ready),
  .ar_id_i         (axi_smc_dbg_req_o.ar.id),
  .r_valid_i       (axi_smc_dbg_resp_i.r_valid),
  .r_id_i          (axi_smc_dbg_resp_i.r.id),
  .r_last_i        (axi_smc_dbg_resp_i.r.last)
);

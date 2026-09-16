// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the CSR access contract of the cross-trigger network: the address map
// into the AXI-Lite crossbar and its error subordinate, and the field access, strobes and reset
// values of one port register block and the matrix register block. Attached to
// cross_trigger_network by dtp_ctn_csr_bind.sv and checked with cross_trigger_network as the formal
// top. Every property body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc).
//
// The manager issues one write and one read at a time (dtp_cross_trigger_network_sby_env.sv), so
// the address of the request a response answers is the one the helper flops recorded at the
// last address handshake.

`include "ocah_fv_macros.svh"

module dtp_ctn_csr_props
  import cross_trigger_network_pkg::*;
  import cross_trigger_port_reg_pkg::*;
  import cross_trigger_matrix_reg_pkg::*;
#(
  parameter int unsigned NUM_CTP = 16,
  parameter int unsigned NUM_MST = NUM_CTP + 1
) (
  input logic                          clk_i,
  input logic                          rst_ni,
  input ctn_axil_req_t                 req_i,          // axil_req_i
  input ctn_axil_resp_t                resp_i,         // axil_resp_o
  input ctn_axil_req_t [NUM_MST-1:0]   mst_req_i,      // xbar_mst_req
  // Port 0 register block
  input cross_trigger_port__out_t      ctp0_regs_i,    // gen_ext_ctp[0].u_ctp.reg_out
  input cross_trigger_port__in_t       ctp0_status_i,  // gen_ext_ctp[0].u_ctp.reg_in
  input logic                          ctp0_req_i,     // u_reg.cpuif_req_masked
  input logic                          ctp0_req_is_wr_i, // u_reg.cpuif_req_is_wr
  input logic [3:0]                    ctp0_addr_i,    // u_reg.cpuif_addr
  input logic [31:0]                   ctp0_wr_data_i, // u_reg.cpuif_wr_data
  input logic [31:0]                   ctp0_wr_biten_i,// u_reg.cpuif_wr_biten
  input logic [31:0]                   ctp0_rd_data_i, // u_reg.cpuif_rd_data
  // Matrix register block
  input cross_trigger_matrix__out_t    ctm_regs_i,     // u_ctm.reg_out
  input logic                          ctm_req_i,      // u_reg.cpuif_req_masked
  input logic                          ctm_req_is_wr_i,// u_reg.cpuif_req_is_wr
  input logic [7:0]                    ctm_addr_i,     // u_reg.cpuif_addr
  input logic [31:0]                   ctm_rd_data_i   // u_reg.cpuif_rd_data
);

  localparam logic [1:0] RESP_OKAY = 2'b00;
  localparam logic [1:0] RESP_DECERR = 2'b11;
  localparam logic [31:0] CTP_BASE = 32'h200;
  localparam logic [31:0] MAP_END = CTP_BASE + 32'(NUM_CTP) * 32'h10;

  // The network lists each window's end address as its last byte while the crossbar decoder
  // treats the end address as exclusive, so the last byte address of every window (0x1FF,
  // 0x20F and so on up to 0x2FF) decodes as unmapped; word-aligned accesses never reach it.
  function automatic logic mapped(input logic [31:0] addr);
    if (addr < CTP_BASE) return addr != CTP_BASE - 32'h1;
    return addr < MAP_END && addr[3:0] != 4'hF;
  endfunction

  // Crossbar master port of a mapped address: the matrix at 0, port n at n + 1.
  function automatic int unsigned port_of(input logic [31:0] addr);
    if (addr < CTP_BASE) return 0;
    return 1 + int'((addr - CTP_BASE) >> 4);
  endfunction

  // The matrix block decodes address bits 7:2 only: CONFIG_0 of source k at 8k, nothing at 8k+4.
  function automatic logic [31:0] ctm_readback(input logic [7:0] addr);
    if (addr[2:0] == 3'b000 && (addr[7:3] < 8'(NUM_CT_SRC))) begin
      return 32'(ctm_regs_i.CT_SRC[addr[7:3]].CONFIG_0.CT_DST_SELECT.value);
    end
    return 32'h0;
  endfunction

  logic aw_hs, ar_hs, b_hs, r_hs;
  assign aw_hs = req_i.aw_valid && resp_i.aw_ready;
  assign ar_hs = req_i.ar_valid && resp_i.ar_ready;
  assign b_hs  = resp_i.b_valid && req_i.b_ready;
  assign r_hs  = resp_i.r_valid && req_i.r_ready;

  // Address of the write and of the read in flight, recorded at the address handshake.
  logic [31:0] wr_addr_q, rd_addr_q;
  logic wr_pending_q, rd_pending_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wr_addr_q    <= '0;
      rd_addr_q    <= '0;
      wr_pending_q <= 1'b0;
      rd_pending_q <= 1'b0;
    end else begin
      if (aw_hs) begin
        wr_addr_q    <= req_i.aw.addr;
        wr_pending_q <= 1'b1;
      end else if (b_hs) begin
        wr_pending_q <= 1'b0;
      end
      if (ar_hs) begin
        rd_addr_q    <= req_i.ar.addr;
        rd_pending_q <= 1'b1;
      end else if (r_hs) begin
        rd_pending_q <= 1'b0;
      end
    end
  end

  // Readback data the port 0 block and the matrix block dispatched for the read in flight.
  logic [31:0] ctp0_rd_data_q, ctm_rd_data_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ctp0_rd_data_q <= '0;
      ctm_rd_data_q  <= '0;
    end else begin
      if (ctp0_req_i && !ctp0_req_is_wr_i) ctp0_rd_data_q <= ctp0_rd_data_i;
      if (ctm_req_i && !ctm_req_is_wr_i) ctm_rd_data_q <= ctm_rd_data_i;
    end
  end

  logic ctp0_config_write, ctp0_stretch_write, ctp0_status_write;
  assign ctp0_config_write  = ctp0_req_i && ctp0_req_is_wr_i && ctp0_addr_i == 4'h0;
  assign ctp0_stretch_write = ctp0_req_i && ctp0_req_is_wr_i && ctp0_addr_i == 4'h8;
  assign ctp0_status_write  = ctp0_req_i && ctp0_req_is_wr_i && ctp0_addr_i == 4'h4;

  logic [2:0]  ctp0_config;
  logic [15:0] ctp0_stretch;
  assign ctp0_config  = {ctp0_regs_i.CONFIG.RESET.value, ctp0_regs_i.CONFIG.INVERT.value,
                         ctp0_regs_i.CONFIG.MODE.value};
  assign ctp0_stretch = ctp0_regs_i.STRETCH_MULT.STRETCH_MULT.value;

  logic ctm_all_zero;
  always_comb begin
    ctm_all_zero = 1'b1;
    for (int unsigned k = 0; k < NUM_CT_SRC; k++) begin
      ctm_all_zero &= (ctm_regs_i.CT_SRC[k].CONFIG_0.CT_DST_SELECT.value == '0);
    end
  end

  // Every crossbar master port carries a request only while the subordinate port does, and only
  // the port the address map names.
  logic aw_mapped, ar_mapped;
  int unsigned aw_port, ar_port;
  assign aw_mapped = req_i.aw_valid && mapped(req_i.aw.addr);
  assign ar_mapped = req_i.ar_valid && mapped(req_i.ar.addr);
  assign aw_port   = port_of(req_i.aw.addr);
  assign ar_port   = port_of(req_i.ar.addr);

  logic aw_routed_alone, ar_routed_alone;
  always_comb begin
    aw_routed_alone = 1'b1;
    ar_routed_alone = 1'b1;
    for (int unsigned p = 0; p < NUM_MST; p++) begin
      aw_routed_alone &= !mst_req_i[p].aw_valid || (aw_mapped && aw_port == p);
      ar_routed_alone &= !mst_req_i[p].ar_valid || (ar_mapped && ar_port == p);
    end
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  // ---- Address map --------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_csr_unmapped_decerr,
                  `OCAH_FV_IMPLIES(b_hs && wr_pending_q,
                                   resp_i.b.resp == (mapped(wr_addr_q) ? RESP_OKAY : RESP_DECERR)) &&
                  `OCAH_FV_IMPLIES(r_hs && rd_pending_q,
                                   resp_i.r.resp == (mapped(rd_addr_q) ? RESP_OKAY : RESP_DECERR)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_ctp_window, aw_routed_alone && ar_routed_alone, clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_ctm_aliases,
                  `OCAH_FV_IMPLIES(ctm_req_i && !ctm_req_is_wr_i,
                                   ctm_rd_data_i == ctm_readback(ctm_addr_i)) &&
                  `OCAH_FV_IMPLIES(ctm_req_i && !ctm_req_is_wr_i && rd_pending_q,
                                   ctm_addr_i == {rd_addr_q[7:2], 2'b00}) &&
                  `OCAH_FV_IMPLIES(ctm_req_i && ctm_req_is_wr_i && wr_pending_q,
                                   ctm_addr_i == {wr_addr_q[7:2], 2'b00}) &&
                  `OCAH_FV_IMPLIES(r_hs && rd_pending_q && mapped(rd_addr_q) && rd_addr_q < CTP_BASE,
                                   resp_i.r.data == ctm_rd_data_q),
                  clk_i, rst_ni)

  // ---- Field access -------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_csr_reset_values,
                  `OCAH_FV_IMPLIES(!rst_ni, ctp0_config == '0 && ctp0_stretch == '0 && ctm_all_zero),
                  clk_i, 1'b1)
  `OCAH_FV_ASSERT(ast_csr_status_write_ignored,
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_config_write),
                                   ctp0_config == $past(ctp0_config)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_stretch_write),
                                   ctp0_stretch == $past(ctp0_stretch)) &&
                  `OCAH_FV_IMPLIES(b_hs && wr_pending_q && mapped(wr_addr_q),
                                   resp_i.b.resp == RESP_OKAY),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_strobe_masks_bytes,
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ctp0_config_write),
                                   ctp0_config == (($past(ctp0_config) & ~$past(ctp0_wr_biten_i[2:0])) |
                                                   ($past(ctp0_wr_data_i[2:0]) & $past(ctp0_wr_biten_i[2:0])))) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ctp0_stretch_write),
                                   ctp0_stretch == (($past(ctp0_stretch) & ~$past(ctp0_wr_biten_i[15:0])) |
                                                    ($past(ctp0_wr_data_i[15:0]) & $past(ctp0_wr_biten_i[15:0])))),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_read_after_write,
                  `OCAH_FV_IMPLIES(ctp0_req_i && !ctp0_req_is_wr_i && ctp0_addr_i == 4'h0,
                                   ctp0_rd_data_i == 32'(ctp0_config)) &&
                  `OCAH_FV_IMPLIES(ctp0_req_i && !ctp0_req_is_wr_i && ctp0_addr_i == 4'h8,
                                   ctp0_rd_data_i == 32'(ctp0_stretch)) &&
                  `OCAH_FV_IMPLIES(ctp0_req_i && !ctp0_req_is_wr_i && ctp0_addr_i == 4'h4,
                                   ctp0_rd_data_i == {24'h0,
                                                      ctp0_status_i.STATUS.ACK_OUT.next,
                                                      ctp0_status_i.STATUS.REQ_IN.next,
                                                      ctp0_status_i.STATUS.ACK_IN.next,
                                                      ctp0_status_i.STATUS.REQ_OUT.next,
                                                      3'b000,
                                                      ctp0_status_i.STATUS.BUSY.next}) &&
                  `OCAH_FV_IMPLIES(r_hs && rd_pending_q && mapped(rd_addr_q) &&
                                   rd_addr_q >= CTP_BASE && rd_addr_q < CTP_BASE + 32'h10,
                                   resp_i.r.data == ctp0_rd_data_q),
                  clk_i, rst_ni)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_csr_decerr_write, b_hs && resp_i.b.resp == RESP_DECERR, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_decerr_read, r_hs && resp_i.r.resp == RESP_DECERR, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctp_read_after_write,
                 r_hs && rd_pending_q && rd_addr_q == CTP_BASE && resp_i.r.data[0], clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctm_read_after_write,
                 r_hs && rd_pending_q && rd_addr_q < CTP_BASE && resp_i.r.data != '0, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctm_alias_read,
                 r_hs && rd_pending_q && rd_addr_q[8] && rd_addr_q < CTP_BASE, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_masked_write,
                 $past(ctp0_stretch_write) && $past(ctp0_wr_biten_i[15:0]) != '1 &&
                 $past(ctp0_wr_biten_i[15:0]) != '0, clk_i, rst_ni)
  // verilog_format: on

endmodule : dtp_ctn_csr_props

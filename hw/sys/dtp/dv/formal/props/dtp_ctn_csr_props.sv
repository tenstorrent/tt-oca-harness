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
// the address of the request a response answers, and of the request a crossbar master port
// carries, is the one the helper flops recorded at the last address handshake, and the data and
// strobes a register block writes are the ones recorded at the last W handshake.

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

  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [1:0] RespDecerr = 2'b11;
  localparam logic [31:0] CtmEnd = 32'(CsrAddrCtmRegSize);
  localparam logic [31:0] CtpBase = 32'h200;
  localparam logic [31:0] MapEnd = CtpBase + 32'(NUM_CTP) * 32'h10;

  function automatic logic mapped(input logic [31:0] addr);
    return addr < CtmEnd || (addr >= CtpBase && addr < MapEnd);
  endfunction

  // Crossbar master port of a mapped address: the matrix at 0, port n at n + 1.
  function automatic int unsigned port_of(input logic [31:0] addr);
    if (addr < CtpBase) return 0;
    return 1 + int'((addr - CtpBase) >> 4);
  endfunction

  // The matrix block decodes address bits 7:2 only: CONFIG_0 of source k at 8k, nothing at 8k+4.
  function automatic logic [31:0] ctm_readback(input logic [7:0] addr);
    if (addr[2:0] == 3'b000 && (addr[7:3] < 8'(NUM_CT_SRC))) begin
      return 32'(ctm_regs_i.CT_SRC[addr[7:3]].CONFIG_0.CT_DST_SELECT.value);
    end
    return 32'h0;
  endfunction

  logic aw_hs, w_hs, ar_hs, b_hs, r_hs;
  assign aw_hs = req_i.aw_valid && resp_i.aw_ready;
  assign w_hs  = req_i.w_valid && resp_i.w_ready;
  assign ar_hs = req_i.ar_valid && resp_i.ar_ready;
  assign b_hs  = resp_i.b_valid && req_i.b_ready;
  assign r_hs  = resp_i.r_valid && req_i.r_ready;

  // Address of the write and of the read in flight, recorded at the address handshake, and data
  // and strobes of the write, recorded at the W handshake.
  logic [31:0] wr_addr_q, rd_addr_q, wr_data_q;
  logic [3:0] wr_strb_q;
  logic wr_pending_q, wr_data_pending_q, rd_pending_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wr_addr_q         <= '0;
      rd_addr_q         <= '0;
      wr_data_q         <= '0;
      wr_strb_q         <= '0;
      wr_pending_q      <= 1'b0;
      wr_data_pending_q <= 1'b0;
      rd_pending_q      <= 1'b0;
    end else begin
      if (aw_hs) begin
        wr_addr_q    <= req_i.aw.addr;
        wr_pending_q <= 1'b1;
      end else if (b_hs) begin
        wr_pending_q <= 1'b0;
      end
      if (w_hs) begin
        wr_data_q         <= req_i.w.data;
        wr_strb_q         <= req_i.w.strb;
        wr_data_pending_q <= 1'b1;
      end else if (b_hs) begin
        wr_data_pending_q <= 1'b0;
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

  // The bit-enable of each byte lane is that lane's strobe.
  logic [31:0] wr_biten;
  always_comb begin
    for (int unsigned b = 0; b < 4; b++) wr_biten[8*b+:8] = {8{wr_strb_q[b]}};
  end

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

  // A master port holds VALID until its subordinate accepts the request, so the pending write
  // or read has left the crossbar once a master port drops its AW or AR. Each forwarded flag
  // holds from the cycle after that drop until the next address or response handshake of the
  // subordinate port.
  logic mst_aw_valid, mst_ar_valid, mst_aw_valid_q, mst_ar_valid_q;
  logic wr_forwarded_q, rd_forwarded_q;
  always_comb begin
    mst_aw_valid = 1'b0;
    mst_ar_valid = 1'b0;
    for (int unsigned p = 0; p < NUM_MST; p++) begin
      mst_aw_valid |= mst_req_i[p].aw_valid;
      mst_ar_valid |= mst_req_i[p].ar_valid;
    end
  end
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      mst_aw_valid_q <= 1'b0;
      mst_ar_valid_q <= 1'b0;
      wr_forwarded_q <= 1'b0;
      rd_forwarded_q <= 1'b0;
    end else begin
      mst_aw_valid_q <= mst_aw_valid;
      mst_ar_valid_q <= mst_ar_valid;
      if (aw_hs || b_hs) wr_forwarded_q <= 1'b0;
      else if (wr_pending_q && mst_aw_valid_q && !mst_aw_valid) wr_forwarded_q <= 1'b1;
      if (ar_hs || r_hs) rd_forwarded_q <= 1'b0;
      else if (rd_pending_q && mst_ar_valid_q && !mst_ar_valid) rd_forwarded_q <= 1'b1;
    end
  end

  // Every crossbar master port carries a request only while the subordinate port holds an
  // accepted request that it has not answered and that the crossbar has not forwarded, and only
  // the port the address map names for it. The subordinate-port spill registers present an
  // accepted request from the cycle after its handshake.
  logic aw_mapped, ar_mapped;
  int unsigned aw_port, ar_port;
  assign aw_mapped = wr_pending_q && !wr_forwarded_q && mapped(wr_addr_q);
  assign ar_mapped = rd_pending_q && !rd_forwarded_q && mapped(rd_addr_q);
  assign aw_port   = port_of(wr_addr_q);
  assign ar_port   = port_of(rd_addr_q);

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
                                   resp_i.b.resp == (mapped(wr_addr_q) ? RespOkay : RespDecerr)) &&
                  `OCAH_FV_IMPLIES(r_hs && rd_pending_q,
                                   resp_i.r.resp == (mapped(rd_addr_q) ? RespOkay : RespDecerr)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_ctp_window, aw_routed_alone && ar_routed_alone, clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_ctm_readback,
                  `OCAH_FV_IMPLIES(ctm_req_i && !ctm_req_is_wr_i,
                                   ctm_rd_data_i == ctm_readback(ctm_addr_i)) &&
                  `OCAH_FV_IMPLIES(ctm_req_i && !ctm_req_is_wr_i && rd_pending_q,
                                   ctm_addr_i == {rd_addr_q[7:2], 2'b00}) &&
                  `OCAH_FV_IMPLIES(ctm_req_i && ctm_req_is_wr_i && wr_pending_q,
                                   ctm_addr_i == {wr_addr_q[7:2], 2'b00}) &&
                  `OCAH_FV_IMPLIES(r_hs && rd_pending_q && mapped(rd_addr_q) && rd_addr_q < CtpBase,
                                   resp_i.r.data == ctm_rd_data_q),
                  clk_i, rst_ni)

  // ---- Field access -------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_csr_write_reaches_regblock,
                  `OCAH_FV_IMPLIES(ctp0_req_i && ctp0_req_is_wr_i,
                                   wr_pending_q && wr_data_pending_q &&
                                   ctp0_addr_i == {wr_addr_q[3:2], 2'b00} &&
                                   ctp0_wr_data_i == wr_data_q && ctp0_wr_biten_i == wr_biten),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_csr_reset_values,
                  `OCAH_FV_IMPLIES(!rst_ni, ctp0_config == '0 && ctp0_stretch == '0 && ctm_all_zero),
                  clk_i, 1'b1)
  `OCAH_FV_ASSERT(ast_csr_status_write_ignored,
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_config_write),
                                   ctp0_config == $past(ctp0_config)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_stretch_write),
                                   ctp0_stretch == $past(ctp0_stretch)) &&
                  `OCAH_FV_IMPLIES(b_hs && wr_pending_q && mapped(wr_addr_q),
                                   resp_i.b.resp == RespOkay),
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
                                   rd_addr_q >= CtpBase && rd_addr_q < CtpBase + 32'h10,
                                   resp_i.r.data == ctp0_rd_data_q),
                  clk_i, rst_ni)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_csr_decerr_write, b_hs && resp_i.b.resp == RespDecerr, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_decerr_read, r_hs && resp_i.r.resp == RespDecerr, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctp_read_after_write,
                 r_hs && rd_pending_q && rd_addr_q == CtpBase && resp_i.r.data[0], clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctm_read_after_write,
                 r_hs && rd_pending_q && rd_addr_q < CtpBase && resp_i.r.data != '0, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_ctm_past_extent_decerr,
                 r_hs && rd_pending_q && rd_addr_q >= CtmEnd && rd_addr_q < CtpBase &&
                 resp_i.r.resp == RespDecerr, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_masked_write,
                 $past(ctp0_stretch_write) && $past(ctp0_wr_biten_i[15:0]) != '1 &&
                 $past(ctp0_wr_biten_i[15:0]) != '0, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_wr_forwarded, wr_pending_q && wr_forwarded_q && !b_hs, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_csr_rd_forwarded, rd_pending_q && rd_forwarded_q && !r_hs, clk_i, rst_ni)
  // verilog_format: on

endmodule : dtp_ctn_csr_props

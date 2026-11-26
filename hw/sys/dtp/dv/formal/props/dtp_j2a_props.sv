// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for one JTAG2AXI bridge, a jtag_dmi2axi instance: the op-3 update a DTMCS
// dmireset gives tdr2axi, the DTMCS capture word, the security select, the routing of requests to
// the manager port or the error slave, the error slave's response, and the request attributes on
// the port. Attached to jtag_ptap once per bridge by dtp_j2a_bind.sv and checked with dtp as the
// formal top. Every property body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc).
//
// The TDR side is sampled at the tck posedge that leaves Capture-DR or Update-DR; the update
// register, a negedge flop, holds the scanned value there. The select, the demultiplexer, the
// error slave and the port are clk_i flops.
//
// tdr2axi keeps at most one transfer open, and the next request follows the response of the
// last, so the port carries a request only while the request the bridge presented last saw the
// target select in every cycle it was presented. Reset counts as a request that saw the error
// slave.

`include "ocah_fv_macros.svh"

module dtp_j2a_props #(
  parameter bit          IS_AXI4_LITE = 1'b1,
  parameter int unsigned DATA_WIDTH   = 32,
  parameter int unsigned ID_WIDTH     = 1,
  parameter int unsigned USER_WIDTH   = 1
) (
  // TDR side
  input logic                  tck_i,                // dmi_scan_ctrl_i.tck
  input logic                  tap_rst_ni,           // dtmcs_scan_ctrl_i.rst_n
  input logic                  dtmcs_select_i,       // dtmcs_scan_ctrl_i.select
  input logic                  dtmcs_capture_en_i,   // dtmcs_scan_ctrl_i.capture_en
  input logic                  dtmcs_update_en_i,    // dtmcs_scan_ctrl_i.update_en
  input logic                  dtmcs_dmireset_i,     // dtmcs_update[16]
  input logic [31:0]           dtmcs_capture_i,      // u_dtmcs_scan_reg.data_in_i
  input logic                  dmi_select_i,         // dmi_scan_ctrl_i.select
  input logic                  dmi_update_en_i,      // dmi_scan_ctrl_i.update_en
  input logic [40:0]           dmi_capture_i,        // u_tdr2axi.o_dmi_tdr
  input logic                  tdr_update_i,         // u_tdr2axi.i_dmi_tdr_update
  input logic [40:0]           tdr_data_i,           // u_tdr2axi.i_dmi_tdr
  // Select and demultiplexer
  input logic                  clk_i,
  input logic                  rst_ni,
  input logic                  select_i,             // security_select_q, 1 for the error slave
  input logic                  requesting_i,         // bridge_requesting
  // Error slave port of the demultiplexer
  input logic                  err_b_valid_i,
  input logic [1:0]            err_b_resp_i,
  input logic                  err_r_valid_i,
  input logic [1:0]            err_r_resp_i,
  input logic [DATA_WIDTH-1:0] err_r_data_i,
  // Manager port
  input logic                  aw_valid_i,
  input logic                  aw_ready_i,
  input logic [2:0]            aw_prot_i,
  input logic                  w_valid_i,
  input logic                  b_valid_i,
  input logic                  b_ready_i,
  input logic                  ar_valid_i,
  input logic                  ar_ready_i,
  input logic [2:0]            ar_prot_i,
  input logic                  r_valid_i,
  input logic                  r_ready_i,
  // Manager port, AXI4 only
  input logic [ID_WIDTH-1:0]   aw_id_i,
  input logic [7:0]            aw_len_i,
  input logic [1:0]            aw_burst_i,
  input logic                  aw_lock_i,
  input logic [3:0]            aw_cache_i,
  input logic [3:0]            aw_qos_i,
  input logic [3:0]            aw_region_i,
  input logic [5:0]            aw_atop_i,
  input logic [USER_WIDTH-1:0] aw_user_i,
  input logic                  w_last_i,
  input logic [USER_WIDTH-1:0] w_user_i,
  input logic [ID_WIDTH-1:0]   ar_id_i,
  input logic [7:0]            ar_len_i,
  input logic [1:0]            ar_burst_i,
  input logic                  ar_lock_i,
  input logic [3:0]            ar_cache_i,
  input logic [3:0]            ar_qos_i,
  input logic [3:0]            ar_region_i,
  input logic [USER_WIDTH-1:0] ar_user_i
);

  // The DTMCS fields the DTP reports and the request attributes of every DTP bridge.
  localparam logic [2:0] DtmcsIdle = 3'd7;
  localparam logic [5:0] DtmcsAbits = 6'd7;
  localparam logic [3:0] DtmcsVersion = 4'd1;
  localparam logic [1:0] DmiOpClear = 2'd3;
  localparam logic [2:0] Prot = 3'b000;
  localparam logic [3:0] Cache = 4'b0010;
  localparam logic [1:0] BurstIncr = 2'b01;
  localparam logic [1:0] RespDecerr = 2'b11;
  localparam logic [DATA_WIDTH-1:0] ErrSlvData = {(DATA_WIDTH / 32) {32'hBADCAB1E}};

  logic dmireset;
  assign dmireset = dtmcs_select_i && dtmcs_update_en_i && dtmcs_dmireset_i;

  logic aw_attrs_ok, ar_attrs_ok, w_attrs_ok;
  assign aw_attrs_ok = aw_prot_i == Prot &&
                       (IS_AXI4_LITE ||
                        (aw_id_i == '0 && aw_len_i == '0 && aw_burst_i == BurstIncr && !aw_lock_i &&
                         aw_cache_i == Cache && aw_qos_i == '0 && aw_region_i == '0 &&
                         aw_atop_i == '0 && aw_user_i == '0));
  assign ar_attrs_ok = ar_prot_i == Prot &&
                       (IS_AXI4_LITE ||
                        (ar_id_i == '0 && ar_len_i == '0 && ar_burst_i == BurstIncr && !ar_lock_i &&
                         ar_cache_i == Cache && ar_qos_i == '0 && ar_region_i == '0 &&
                         ar_user_i == '0));
  assign w_attrs_ok = IS_AXI4_LITE || (w_last_i && w_user_i == '0);

  // A request is presented while requesting_i is high; err_request is high when the request
  // presented last, or the one presented now, saw the error-slave select in any presented cycle.
  logic presenting_q, err_request_q, err_request;
  assign err_request = requesting_i ? ((presenting_q && err_request_q) || select_i) : err_request_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      presenting_q  <= 1'b0;
      err_request_q <= 1'b1;
    end else begin
      presenting_q  <= requesting_i;
      err_request_q <= err_request;
    end
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  // ---- DTMCS and the tdr2axi update strobe --------------------------------------------------
  `OCAH_FV_ASSERT(ast_j2a_dmireset_op3,
                  `OCAH_FV_IMPLIES(dmireset,
                                   tdr_update_i && tdr_data_i == {dmi_capture_i[40:2], DmiOpClear}),
                  tck_i, tap_rst_ni)
  // Update-DR lasts one tck cycle, so one dmireset gives one op-3 update.
  `OCAH_FV_ASSERT(ast_j2a_update_sources,
                  `OCAH_FV_IMPLIES(tdr_update_i, dmireset || (dmi_select_i && dmi_update_en_i)) &&
                  `OCAH_FV_IMPLIES($past(tap_rst_ni) && $past(dmireset), !dmireset),
                  tck_i, tap_rst_ni)
  `OCAH_FV_ASSERT(ast_j2a_dtmcs_capture_const,
                  `OCAH_FV_IMPLIES(dtmcs_select_i && dtmcs_capture_en_i,
                                   dtmcs_capture_i[31:15] == '0 &&
                                   dtmcs_capture_i[14:12] == DtmcsIdle &&
                                   dtmcs_capture_i[11:10] != 2'd1 &&
                                   dtmcs_capture_i[9:4] == DtmcsAbits &&
                                   dtmcs_capture_i[3:0] == DtmcsVersion),
                  tck_i, tap_rst_ni)

  // ---- Security select and routing ----------------------------------------------------------
  `OCAH_FV_ASSERT(ast_j2a_select_err_slv_in_reset, `OCAH_FV_IMPLIES(!rst_ni, select_i), clk_i, 1'b1)
  `OCAH_FV_ASSERT(ast_j2a_select_changes_only_idle,
                  `OCAH_FV_IMPLIES($past(rst_ni) && select_i != $past(select_i),
                                   !$past(requesting_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_j2a_disabled_port_quiet,
                  `OCAH_FV_IMPLIES(err_request, !aw_valid_i && !w_valid_i && !ar_valid_i),
                  clk_i, rst_ni)

  // ---- Error slave and port attributes ------------------------------------------------------
  `OCAH_FV_ASSERT(ast_j2a_err_slv_decerr,
                  `OCAH_FV_IMPLIES(err_b_valid_i, err_b_resp_i == RespDecerr) &&
                  `OCAH_FV_IMPLIES(err_r_valid_i,
                                   err_r_resp_i == RespDecerr && err_r_data_i == ErrSlvData),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_j2a_port_attrs_const,
                  `OCAH_FV_IMPLIES(aw_valid_i, aw_attrs_ok) &&
                  `OCAH_FV_IMPLIES(w_valid_i, w_attrs_ok) &&
                  `OCAH_FV_IMPLIES(ar_valid_i, ar_attrs_ok),
                  clk_i, rst_ni)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_j2a_dmireset, dmireset, tck_i, tap_rst_ni)
  `OCAH_FV_COVER(cov_j2a_dtmcs_capture, dtmcs_select_i && dtmcs_capture_en_i, tck_i, tap_rst_ni)
  `OCAH_FV_COVER(cov_j2a_port_write, aw_valid_i && aw_ready_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_j2a_port_read, ar_valid_i && ar_ready_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_j2a_err_slv_write, err_b_valid_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_j2a_err_slv_read, err_r_valid_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_j2a_select_to_err_slv, $past(rst_ni) && select_i && !$past(select_i),
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_j2a_select_to_target, $past(rst_ni) && !select_i && $past(select_i),
                 clk_i, rst_ni)
  // A transfer the port took before the select moved to the error slave completes on the port.
  `OCAH_FV_COVER(cov_j2a_port_completes_after_disable,
                 select_i && ((b_valid_i && b_ready_i) || (r_valid_i && r_ready_i)),
                 clk_i, rst_ni)
  // verilog_format: on

endmodule : dtp_j2a_props

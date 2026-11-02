// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the lock of one outbound filter-control entry, observed on the
// filter-control AXI-Lite port of smc_internal_regs. Attached by smc_filter_lock_props_bind.sv and
// checked with smc_internal_regs as the formal top. Every property body is a boolean over current
// and one-cycle-past values (hw/common/dv/docs/formal-property-style.adoc).
//
// Expected values come from hw/ip/axi_filter/regs/filter_ctrl.rdl only: FILTER_CONFIG.locked
// (bit 63, woset) is write-once; once set, every write to the entry's FILTER_CONFIG, START_ADDR
// and END_ADDR terminates with DECERR, and reads still return the locked configuration. The entry
// address map is filter_ctrl_wrap.rdl (sixteen entries at a 0x20 stride, registers at 0x00, 0x08
// and 0x10) inside a window that hw/sys/smc/regs/smc.rdl places on a 0x200-aligned offset, so
// address bits 8:5 select the entry and bits 4:0 the register.
//
// The lock write is a write to the entry's FILTER_CONFIG with bit 63 set whose B response is OKAY;
// the configuration it locks is its write data on the software-writable FILTER_CONFIG fields.
// START_ADDR and END_ADDR are hardware-writable (hw = rw) and follow the filter status input,
// which is free on this top, so their values are not compared; writes to them are checked for
// the DECERR response only.
//
// Claims: (P1) a write whose AW is accepted after the lock write's B, addressed to one of the
// entry's three registers, answers DECERR and leaves the locked configuration unchanged;
// (P2) a read of the entry's FILTER_CONFIG accepted after the lock write's B returns the locked
// configuration on the software-writable fields. The read's response code is open (SF-009) and
// is not asserted. A write queued before the lock write's B is open (SF-008): the
// one-write-at-a-time assumption below excludes it, so P1 claims only writes accepted after that
// B. No per-ID, per-beat, WLAST, strobe-lane or exclusive rule is stated here.

`include "ocah_fv_macros.svh"

module smc_filter_lock_props #(
  parameter int unsigned ENTRY = 0
) (
  input logic                                    clk_i,      // clk_smc_i
  input logic                                    rst_ni,     // rst_primary_smc_clk_ni
  input logic                                    test_en_i,  // test_en_i
  input smc_pkg::smc_axil_32_64_req_t            req_i,      // axil_outbound_filter_ctrl_req_i
  input smc_pkg::smc_axil_32_64_resp_t           resp_i,     // axil_outbound_filter_ctrl_resp_o
  input filter_ctrl_reg_pkg::filter_ctrl__out_t  cfg_i       // outbound_filter_ctrl_o[ENTRY]
);

  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [1:0] RespDecerr = 2'b11;
  localparam logic [4:0] OffConfig = 5'h00;
  localparam logic [4:0] OffStart = 5'h08;
  localparam logic [4:0] OffEnd = 5'h10;
  // Software-writable FILTER_CONFIG fields (filter_ctrl.rdl): read_allowed[0], write_allowed[1],
  // entry_enabled[4], allow_ns[8], src_id[19:16], group_id[23:20], allow_burst[24], locked[63].
  localparam logic [63:0] CfgSwMask = 64'h8000_0000_01FF_0113;

  function automatic logic is_entry(input logic [31:0] addr);
    return addr[8:5] == 4'(ENTRY);
  endfunction

  function automatic logic is_entry_reg(input logic [31:0] addr);
    return is_entry(addr) &&
        (addr[4:0] == OffConfig || addr[4:0] == OffStart || addr[4:0] == OffEnd);
  endfunction

  function automatic logic is_entry_config(input logic [31:0] addr);
    return is_entry(addr) && addr[4:0] == OffConfig;
  endfunction

  logic [63:0] cfg_sw;
  always_comb begin
    cfg_sw      = '0;
    cfg_sw[0]   = cfg_i.FILTER_CONFIG.read_allowed.value;
    cfg_sw[1]   = cfg_i.FILTER_CONFIG.write_allowed.value;
    cfg_sw[4]   = cfg_i.FILTER_CONFIG.entry_enabled.value;
    cfg_sw[8]   = cfg_i.FILTER_CONFIG.allow_ns.value;
    cfg_sw[19:16] = cfg_i.FILTER_CONFIG.src_id.value;
    cfg_sw[23:20] = cfg_i.FILTER_CONFIG.group_id.value;
    cfg_sw[24]  = cfg_i.FILTER_CONFIG.allow_burst.value;
    cfg_sw[63]  = cfg_i.FILTER_CONFIG.locked.value;
  end

  logic aw_hs, w_hs, ar_hs, b_hs, r_hs;
  assign aw_hs = req_i.aw_valid && resp_i.aw_ready;
  assign w_hs  = req_i.w_valid && resp_i.w_ready;
  assign ar_hs = req_i.ar_valid && resp_i.ar_ready;
  assign b_hs  = resp_i.b_valid && req_i.b_ready;
  assign r_hs  = resp_i.r_valid && req_i.r_ready;

  // The write and the read in flight: address recorded at the address handshake, data at the W
  // handshake, each held until the response handshake.
  logic [31:0] wr_addr_q, rd_addr_q;
  logic [63:0] wr_data_q;
  logic aw_pending_q, w_pending_q, rd_pending_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wr_addr_q    <= '0;
      rd_addr_q    <= '0;
      wr_data_q    <= '0;
      aw_pending_q <= 1'b0;
      w_pending_q  <= 1'b0;
      rd_pending_q <= 1'b0;
    end else begin
      if (aw_hs) begin
        wr_addr_q    <= req_i.aw.addr;
        aw_pending_q <= 1'b1;
      end else if (b_hs) begin
        aw_pending_q <= 1'b0;
      end
      if (w_hs) begin
        wr_data_q   <= req_i.w.data;
        w_pending_q <= 1'b1;
      end else if (b_hs) begin
        w_pending_q <= 1'b0;
      end
      if (ar_hs) begin
        rd_addr_q    <= req_i.ar.addr;
        rd_pending_q <= 1'b1;
      end else if (r_hs) begin
        rd_pending_q <= 1'b0;
      end
    end
  end

  // Lock state: set at the B handshake of the lock write and held to reset, with the locked
  // configuration captured from that write's data. A write or a read whose address handshake
  // falls after that B is marked at the handshake.
  logic lock_set;
  logic locked_q, wr_after_lock_q, rd_after_lock_q;
  logic [63:0] locked_cfg_q;
  assign lock_set = b_hs && aw_pending_q && w_pending_q && !locked_q && is_entry_config(
      wr_addr_q
  ) && wr_data_q[63] && resp_i.b.resp == RespOkay;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      locked_q        <= 1'b0;
      locked_cfg_q    <= '0;
      wr_after_lock_q <= 1'b0;
      rd_after_lock_q <= 1'b0;
    end else begin
      if (lock_set) begin
        locked_q     <= 1'b1;
        locked_cfg_q <= wr_data_q & CfgSwMask;
      end
      if (aw_hs) wr_after_lock_q <= locked_q;
      else if (b_hs) wr_after_lock_q <= 1'b0;
      if (ar_hs) rd_after_lock_q <= locked_q;
      else if (r_hs) rd_after_lock_q <= 1'b0;
    end
  end

  logic refused_write_b, locked_read_r;
  assign refused_write_b = b_hs && aw_pending_q && wr_after_lock_q && is_entry_reg(wr_addr_q);
  assign locked_read_r   = r_hs && rd_pending_q && rd_after_lock_q && is_entry_config(rd_addr_q);

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

`ifdef FORMAL
  // ---- Environment ----------------------------------------------------------------------------
  // The reset is asserted up to the first clock edge and released there for the rest of the
  // trace, so the register blocks start from their reset state; scan test mode stays off, the
  // functional configuration of the CSR clock gates.
  logic env_released_q = 1'b0;
  always @(posedge clk_i) env_released_q <= 1'b1;
  always_comb begin
    asm_env_reset_asserted : assume (env_released_q || !rst_ni);
    asm_env_reset_released : assume (!env_released_q || rst_ni);
    asm_env_test_mode_off  : assume (!test_en_i);
  end
`endif

  // One write at a time: the next AW and W wait for the previous write's B. A write queued before
  // the lock write's B is the open question SF-008, so this assumption excludes it rather than
  // claiming its outcome.
  `OCAH_FV_ASSUME(asm_env_one_write_aw, `OCAH_FV_IMPLIES(aw_pending_q, !req_i.aw_valid), clk_i, rst_ni)
  `OCAH_FV_ASSUME(asm_env_one_write_w, `OCAH_FV_IMPLIES(w_pending_q, !req_i.w_valid), clk_i, rst_ni)
  // One read at a time, so the read a response answers is the recorded one.
  `OCAH_FV_ASSUME(asm_env_one_read, `OCAH_FV_IMPLIES(rd_pending_q, !req_i.ar_valid), clk_i, rst_ni)
  // filter_ctrl.rdl sets accesswidth = 64 on every register: each software write is a full
  // 64-bit access.
  `OCAH_FV_ASSUME(asm_env_full_width_write, `OCAH_FV_IMPLIES(req_i.w_valid, req_i.w.strb == '1),
                  clk_i, rst_ni)

  // ---- P1: a write after the lock is refused ---------------------------------------------------
  `OCAH_FV_ASSERT(ast_filter_lock_write_decerr,
                  `OCAH_FV_IMPLIES(refused_write_b, resp_i.b.resp == RespDecerr), clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_filter_lock_write_no_change,
                  `OCAH_FV_IMPLIES(refused_write_b, cfg_sw == locked_cfg_q), clk_i, rst_ni)

  // ---- P2: a read after the lock returns the locked configuration -------------------------------
  `OCAH_FV_ASSERT(ast_filter_lock_read_data,
                  `OCAH_FV_IMPLIES(locked_read_r, (resp_i.r.data & CfgSwMask) == locked_cfg_q),
                  clk_i, rst_ni)

  // ---- Covers -----------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_filter_lock_write, lock_set, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_filter_lock_write_refused, refused_write_b, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_filter_lock_read, locked_read_r, clk_i, rst_ni)
  // verilog_format: on

endmodule : smc_filter_lock_props

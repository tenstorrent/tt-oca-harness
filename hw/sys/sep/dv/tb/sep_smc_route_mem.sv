// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC responder of the BH-SMC bench hook (docs/SEP_TB_ARCH.adoc, HDL Top port
// table). It answers the SEP->SMC AXI port when the hook is enabled and stays
// idle (every READY and VALID low) when it is not, so a build that does not
// enable it sees the same port as a tied-off responder.
//
// Behaviour:
//   * One write and one read in flight. AW, W and AR are accepted one burst at
//     a time; a burst may be INCR or FIXED of any AxLEN.
//   * Every response is OKAY with the request ID.
//   * A write beat merges its strobed bytes into a sparse 64-bit word store
//     keyed by address bits [55:3], so a later read returns the written data.
//   * The read data of a beat is taken from the store when the beat is loaded:
//     at the AR handshake for the first beat, and at the R handshake of the
//     previous beat for each later beat. A write that lands after that load
//     does not change the beat.
//   * An INCR burst aligns every beat after the first to its AxSIZE (IHI 0022
//     A3.4.1), so an unaligned start does not shift the later beats.
//   * A word that no write has touched reads {~a, a}, where a is the low 32
//     bits of the 8-byte-aligned address. The value is known, so a VCS X check
//     on the SMC read data cannot be satisfied by an unwritten word.
//
// The store is a testbench model of SMC memory. It makes no claim about the
// SMC fabric decode; a test that needs that decode does not use this model.

module sep_smc_route_mem #(
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic
) (
  input  logic      clk_i,
  input  logic      rst_ni,
  input  logic      en_i,
  input  axi_req_t  req_i,
  output axi_resp_t resp_o
);

  logic [63:0] mem[logic [52:0]];

  function automatic logic [63:0] rd_word(input logic [55:0] addr);
    logic [52:0] key;
    logic [31:0] a;
    key = addr[55:3];
    a   = {addr[31:3], 3'b000};
    if (mem.exists(key)) rd_word = mem[key];
    else rd_word = {~a, a};
  endfunction

  function automatic logic [55:0] next_addr(input logic [55:0] addr, input logic [2:0] size,
                                            input logic [1:0] burst);
    logic [55:0] step;
    step = 56'd1 << size;
    next_addr = (burst == axi_pkg::BURST_FIXED) ? addr : (addr & ~(step - 56'd1)) + step;
  endfunction

  // Write channel.
  typedef enum logic [1:0] {
    W_IDLE,
    W_DATA,
    W_RESP
  } w_state_e;
  w_state_e    w_state_q;
  logic [55:0] w_addr_q;
  logic [2:0]  w_size_q;
  logic [1:0]  w_burst_q;
  logic [$bits(req_i.aw.id)-1:0] w_id_q;

  // Read channel.
  typedef enum logic [0:0] {
    R_IDLE,
    R_DATA
  } r_state_e;
  r_state_e    r_state_q;
  logic [55:0] r_addr_q;
  logic [2:0]  r_size_q;
  logic [1:0]  r_burst_q;
  logic [7:0]  r_left_q;
  logic [63:0] r_data_q;
  logic [$bits(req_i.ar.id)-1:0] r_id_q;

  always_comb begin
    resp_o          = '0;
    resp_o.aw_ready = en_i && (w_state_q == W_IDLE);
    resp_o.w_ready  = en_i && (w_state_q == W_DATA);
    resp_o.b_valid  = en_i && (w_state_q == W_RESP);
    resp_o.b.id     = w_id_q;
    resp_o.b.resp   = axi_pkg::RESP_OKAY;
    resp_o.ar_ready = en_i && (r_state_q == R_IDLE);
    resp_o.r_valid  = en_i && (r_state_q == R_DATA);
    resp_o.r.id     = r_id_q;
    resp_o.r.resp   = axi_pkg::RESP_OKAY;
    resp_o.r.data   = r_data_q;
    resp_o.r.last   = (r_left_q == 8'd0);
  end

  // A behavioural model: the store write is blocking, so a read of the same
  // word on the same edge returns the merged data.
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      w_state_q <= W_IDLE;
      w_addr_q  <= '0;
      w_size_q  <= '0;
      w_burst_q <= '0;
      w_id_q    <= '0;
      r_state_q <= R_IDLE;
      r_addr_q  <= '0;
      r_size_q  <= '0;
      r_burst_q <= '0;
      r_left_q  <= '0;
      r_data_q  <= '0;
      r_id_q    <= '0;
    end else if (en_i) begin
      unique case (w_state_q)
        W_IDLE:
        if (req_i.aw_valid) begin
          w_addr_q  <= req_i.aw.addr;
          w_size_q  <= req_i.aw.size;
          w_burst_q <= req_i.aw.burst;
          w_id_q    <= req_i.aw.id;
          w_state_q <= W_DATA;
        end
        W_DATA:
        if (req_i.w_valid) begin
          logic [63:0] word;
          word = rd_word(w_addr_q);
          for (int b = 0; b < 8; b++) begin
            if (req_i.w.strb[b]) word[8*b+:8] = req_i.w.data[8*b+:8];
          end
          mem[w_addr_q[55:3]] = word;
          w_addr_q <= next_addr(w_addr_q, w_size_q, w_burst_q);
          if (req_i.w.last) w_state_q <= W_RESP;
        end
        W_RESP: if (req_i.b_ready) w_state_q <= W_IDLE;
        default: w_state_q <= W_IDLE;
      endcase
      unique case (r_state_q)
        R_IDLE:
        if (req_i.ar_valid) begin
          r_addr_q  <= req_i.ar.addr;
          r_size_q  <= req_i.ar.size;
          r_burst_q <= req_i.ar.burst;
          r_left_q  <= req_i.ar.len;
          r_data_q  <= rd_word(req_i.ar.addr);
          r_id_q    <= req_i.ar.id;
          r_state_q <= R_DATA;
        end
        R_DATA:
        if (req_i.r_ready) begin
          if (r_left_q == 8'd0) begin
            r_state_q <= R_IDLE;
          end else begin
            r_left_q <= r_left_q - 8'd1;
            r_addr_q <= next_addr(r_addr_q, r_size_q, r_burst_q);
            r_data_q <= rd_word(next_addr(r_addr_q, r_size_q, r_burst_q));
          end
        end
        default: r_state_q <= R_IDLE;
      endcase
    end
  end

endmodule : sep_smc_route_mem

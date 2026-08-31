// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Synchronous AXI4 slave for the SMU outbound (ext_out) boundary.
//
// Accepts one write or read burst at a time, answers OKAY, and backs reads with
// whatever was previously written; addresses never written read as zero. It is a
// bus terminator, not a checker -- observation of the traffic belongs to the
// testbench snoops on the same wires.
//
// The logic is entirely clocked, with no `#` delays, so acceptance does not
// depend on simulator scheduling order or on the clock period, both of which the
// SMU environments vary.

`timescale 1ps/1fs

module smu_axi_out_sim_slave #(
    parameter type axi_req_t  = logic,
    parameter type axi_resp_t = logic,
    parameter int unsigned AddrWidth = 56
) (
    input  logic      clk_i,
    input  logic      rst_ni,
    input  axi_req_t  axi_req_i,
    output axi_resp_t axi_resp_o
);

    localparam int unsigned WordIdxWidth = AddrWidth - 3;

    logic [63:0] store [logic [WordIdxWidth-1:0]];

    typedef enum logic [1:0] { WR_IDLE, WR_DATA, WR_RESP } wr_state_e;
    typedef enum logic [0:0] { RD_IDLE, RD_DATA } rd_state_e;

    wr_state_e             wr_state;
    rd_state_e             rd_state;
    logic [7:0]            wr_id, rd_id;
    logic [7:0]            wr_len, rd_len;
    logic [2:0]            wr_size, rd_size;
    logic [1:0]            wr_burst, rd_burst;
    logic [AddrWidth-1:0]  wr_addr, rd_addr;
    logic [7:0]            rd_beat;

    // FIXED bursts hold the address; INCR advances by the transfer size. WRAP is
    // not generated on this port and is treated as INCR.
    function automatic logic [AddrWidth-1:0] next_addr(logic [AddrWidth-1:0] a,
                                                       logic [2:0]           sz,
                                                       logic [1:0]           bt);
        return (bt == 2'b00) ? a : (a + (AddrWidth'(1) << sz));
    endfunction

    always_comb begin
        axi_resp_o           = '0;
        axi_resp_o.aw_ready  = (wr_state == WR_IDLE);
        axi_resp_o.w_ready   = (wr_state == WR_DATA);
        axi_resp_o.b_valid   = (wr_state == WR_RESP);
        axi_resp_o.b.id      = wr_id;
        axi_resp_o.b.resp    = axi_pkg::RESP_OKAY;
        axi_resp_o.ar_ready  = (rd_state == RD_IDLE);
        axi_resp_o.r_valid   = (rd_state == RD_DATA);
        axi_resp_o.r.id      = rd_id;
        axi_resp_o.r.data    = store.exists(rd_addr[AddrWidth-1:3])
                             ? store[rd_addr[AddrWidth-1:3]] : '0;
        axi_resp_o.r.resp    = axi_pkg::RESP_OKAY;
        axi_resp_o.r.last    = (rd_beat == rd_len);
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            wr_state <= WR_IDLE;
            rd_state <= RD_IDLE;
            wr_id    <= '0;
            rd_id    <= '0;
            wr_len   <= '0;
            rd_len   <= '0;
            wr_size  <= '0;
            rd_size  <= '0;
            wr_burst <= '0;
            rd_burst <= '0;
            wr_addr  <= '0;
            rd_addr  <= '0;
            rd_beat  <= '0;
            store.delete();
        end else begin
            unique case (wr_state)
                WR_IDLE: if (axi_req_i.aw_valid) begin
                    wr_id    <= axi_req_i.aw.id;
                    wr_len   <= axi_req_i.aw.len;
                    wr_size  <= axi_req_i.aw.size;
                    wr_burst <= axi_req_i.aw.burst;
                    wr_addr  <= axi_req_i.aw.addr;
                    wr_state <= WR_DATA;
                end
                WR_DATA: if (axi_req_i.w_valid) begin
                    for (int unsigned b = 0; b < 8; b++) begin
                        if (axi_req_i.w.strb[b]) begin
                            store[wr_addr[AddrWidth-1:3]][b*8 +: 8] <=
                                axi_req_i.w.data[b*8 +: 8];
                        end
                    end
                    if (axi_req_i.w.last) begin
                        wr_state <= WR_RESP;
                    end else begin
                        wr_addr <= next_addr(wr_addr, wr_size, wr_burst);
                    end
                end
                WR_RESP: if (axi_req_i.b_ready) begin
                    wr_state <= WR_IDLE;
                end
                default: wr_state <= WR_IDLE;
            endcase

            unique case (rd_state)
                RD_IDLE: if (axi_req_i.ar_valid) begin
                    rd_id    <= axi_req_i.ar.id;
                    rd_len   <= axi_req_i.ar.len;
                    rd_size  <= axi_req_i.ar.size;
                    rd_burst <= axi_req_i.ar.burst;
                    rd_addr  <= axi_req_i.ar.addr;
                    rd_beat  <= '0;
                    rd_state <= RD_DATA;
                end
                RD_DATA: if (axi_req_i.r_ready) begin
                    if (rd_beat == rd_len) begin
                        rd_state <= RD_IDLE;
                    end else begin
                        rd_addr <= next_addr(rd_addr, rd_size, rd_burst);
                        rd_beat <= rd_beat + 8'd1;
                    end
                end
                default: rd_state <= RD_IDLE;
            endcase
        end
    end

endmodule

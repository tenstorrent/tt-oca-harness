// SPDX-License-Identifier: Apache-2.0
//
// Always-completing SMU external AXI responder with firmware-console decode.

`timescale 1ps/1fs

module tb_smu_axi_responder
    import smu_axi_xbar_pkg::*;
(
    input  wire logic clk_i,
    input  wire logic rst_ni,
    input  axi_out_req_t  req_i,
    output axi_out_resp_t resp_o,
    output logic [31:0] write_count_o,
    output logic [31:0] read_count_o,
    output logic        fw_done_o,
    output logic        fw_pass_o,
    output logic [7:0]  fw_char_o,
    output logic        fw_char_valid_o
);

    localparam logic [31:0] STDOUT_ADDR = 32'h8000_0000;
    localparam logic [31:0] MAGIC0       = 32'hA5A5_5A5A;
    localparam logic [31:0] MAGIC_PASS   = 32'hCAFE_BABE;
    localparam logic [31:0] MAGIC_FAIL   = 32'hDEAD_BEEF;

    localparam int unsigned ADDR_WIDTH = $bits(req_i.aw.addr);
    localparam int unsigned ID_WIDTH   = $bits(req_i.aw.id);

    logic [ID_WIDTH-1:0]   aw_id_q;
    logic [ADDR_WIDTH-1:0] aw_addr_q;
    logic                  aw_pending_q;
    logic [63:0]           w_data_q;
    logic [7:0]            w_strb_q;
    logic                  w_last_q;
    logic                  w_pending_q;
    logic                  b_valid_q;
    logic                  read_active_q;
    logic [ID_WIDTH-1:0]   read_id_q;
    logic [8:0]            read_beats_q;
    logic                  magic0_seen_q;

    wire aw_fire = req_i.aw_valid & resp_o.aw_ready;
    wire w_fire = req_i.w_valid & resp_o.w_ready;
    wire pair_fire =
        !b_valid_q && (aw_pending_q || aw_fire) && (w_pending_q || w_fire);
    wire [ADDR_WIDTH-1:0] write_addr =
        aw_pending_q ? aw_addr_q : req_i.aw.addr;
    wire [63:0] write_data = w_pending_q ? w_data_q : req_i.w.data;
    wire [7:0] write_strb = w_pending_q ? w_strb_q : req_i.w.strb;
    wire write_last = w_pending_q ? w_last_q : req_i.w.last;
    wire [31:0] write_word =
        (write_strb[7:4] != 4'h0) ? write_data[63:32] : write_data[31:0];

    always_comb begin
        resp_o          = '0;
        resp_o.aw_ready = !aw_pending_q && !b_valid_q;
        resp_o.w_ready  = !w_pending_q && !b_valid_q;
        resp_o.b_valid  = b_valid_q;
        resp_o.b.id     = aw_id_q;
        resp_o.b.resp   = axi_pkg::RESP_OKAY;
        resp_o.ar_ready = !read_active_q;
        resp_o.r_valid  = read_active_q;
        resp_o.r.id     = read_id_q;
        resp_o.r.data   = '0;
        resp_o.r.resp   = axi_pkg::RESP_OKAY;
        resp_o.r.last   = read_beats_q == 9'd1;
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            aw_id_q        <= '0;
            aw_addr_q      <= '0;
            aw_pending_q   <= 1'b0;
            w_data_q       <= '0;
            w_strb_q       <= '0;
            w_last_q       <= 1'b0;
            w_pending_q    <= 1'b0;
            b_valid_q      <= 1'b0;
            read_active_q  <= 1'b0;
            read_id_q      <= '0;
            read_beats_q   <= '0;
            magic0_seen_q  <= 1'b0;
            write_count_o  <= '0;
            read_count_o   <= '0;
            fw_done_o      <= 1'b0;
            fw_pass_o      <= 1'b0;
            fw_char_o      <= '0;
            fw_char_valid_o <= 1'b0;
        end else begin
            fw_char_valid_o <= 1'b0;

            if (aw_fire) begin
                aw_id_q   <= req_i.aw.id;
                aw_addr_q <= req_i.aw.addr;
                aw_pending_q <= 1'b1;
            end
            if (w_fire) begin
                w_data_q    <= req_i.w.data;
                w_strb_q    <= req_i.w.strb;
                w_last_q    <= req_i.w.last;
                w_pending_q <= 1'b1;
            end
            if (pair_fire) begin
                if (!write_last) begin
                    $error(
                        "[tb_smu_axi_responder] multi-beat write unsupported addr=0x%0h",
                        write_addr
                    );
                end
                aw_pending_q <= 1'b0;
                w_pending_q  <= 1'b0;
                b_valid_q     <= 1'b1;
                write_count_o <= write_count_o + 32'd1;
            end else if (b_valid_q & req_i.b_ready) begin
                b_valid_q <= 1'b0;
            end

            if (req_i.ar_valid & resp_o.ar_ready) begin
                read_active_q <= 1'b1;
                read_id_q     <= req_i.ar.id;
                read_beats_q  <= req_i.ar.len + 9'd1;
                read_count_o  <= read_count_o + 32'd1;
            end else if (read_active_q & req_i.r_ready) begin
                if (read_beats_q <= 9'd1) begin
                    read_active_q <= 1'b0;
                end else begin
                    read_beats_q <= read_beats_q - 9'd1;
                end
            end

            if (pair_fire && write_last && write_addr[31:0] == STDOUT_ADDR) begin
                if (write_strb == 8'h01) begin
                    fw_char_o       <= write_data[7:0];
                    fw_char_valid_o <= 1'b1;
                end
                if (write_strb == 8'h0F || write_strb == 8'hF0) begin
                    if (!magic0_seen_q) begin
                        magic0_seen_q <= write_word == MAGIC0;
                    end else if (write_word == MAGIC_PASS) begin
                        fw_done_o     <= 1'b1;
                        fw_pass_o     <= 1'b1;
                        magic0_seen_q <= 1'b0;
                    end else if (write_word == MAGIC_FAIL) begin
                        fw_done_o     <= 1'b1;
                        fw_pass_o     <= 1'b0;
                        magic0_seen_q <= 1'b0;
                    end else if (write_word != MAGIC0) begin
                        magic0_seen_q <= 1'b0;
                    end
                end
            end
        end
    end

endmodule : tb_smu_axi_responder

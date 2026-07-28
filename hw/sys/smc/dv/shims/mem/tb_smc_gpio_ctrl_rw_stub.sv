// SPDX-License-Identifier: Apache-2.0
//
// OSS DV AXI-Lite RW stub for the adopter-padring GPIO control plane
// (smc.axil_req_gpio_ctrl_o). Replaces the former DECERR terminator so CSR
// sweeps can prove address-discriminating WR->RD storage.
//
// DEFENDS: OKAY AXI-Lite handshake + sparse word storage for the GPIO_CTRL /
//          REFCLK window (0xC000_4440 .. 0xC000_4FFF).
// DOES NOT DEFEND: Real padring pinmux / GPIO pad function / REFCLK analog.

`timescale 1ps/1fs

module tb_smc_gpio_ctrl_rw_stub
    import gpio_pkg::*;
#(
    parameter logic [31:0] BASE_ADDR  = 32'hC000_4440,
    parameter int unsigned MEM_WORDS  = 1024
) (
    input  wire logic        clk_i,
    input  wire logic        rst_ni,
    input  gpio_axil_req_t   axil_req_i,
    output gpio_axil_resp_t  axil_resp_o
);

    logic        aw_pending;
    logic [31:0] aw_addr_q;
    logic        w_pending;
    logic [31:0] w_data_q;
    logic [3:0]  w_strb_q;

    logic [31:0] mem [0:MEM_WORDS-1];

    function automatic logic [$clog2(MEM_WORDS)-1:0] word_idx(
        input logic [31:0] addr
    );
        logic [31:0] offset;
        offset = addr - BASE_ADDR;
        return offset[2 +: $clog2(MEM_WORDS)];
    endfunction

    assign axil_resp_o.aw_ready = !axil_resp_o.b_valid && !aw_pending;
    assign axil_resp_o.w_ready  = !axil_resp_o.b_valid && !w_pending;
    assign axil_resp_o.ar_ready = !axil_resp_o.r_valid;

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            aw_pending         <= 1'b0;
            aw_addr_q          <= '0;
            w_pending          <= 1'b0;
            w_data_q           <= '0;
            w_strb_q           <= '0;
            axil_resp_o.b      <= '0;
            axil_resp_o.b_valid <= 1'b0;
            axil_resp_o.r      <= '0;
            axil_resp_o.r_valid <= 1'b0;
            for (int unsigned i = 0; i < MEM_WORDS; i++) begin
                mem[i] <= '0;
            end
        end else begin
            if (axil_resp_o.b_valid && axil_req_i.b_ready) begin
                axil_resp_o.b_valid <= 1'b0;
            end
            if (axil_resp_o.r_valid && axil_req_i.r_ready) begin
                axil_resp_o.r_valid <= 1'b0;
            end

            if (axil_req_i.aw_valid && axil_resp_o.aw_ready) begin
                aw_pending <= 1'b1;
                aw_addr_q  <= axil_req_i.aw.addr;
            end
            if (axil_req_i.w_valid && axil_resp_o.w_ready) begin
                w_pending <= 1'b1;
                w_data_q  <= axil_req_i.w.data;
                w_strb_q  <= axil_req_i.w.strb;
            end

            if (!axil_resp_o.b_valid && aw_pending && w_pending) begin
                axil_resp_o.b.resp  <= 2'b00;
                axil_resp_o.b_valid <= 1'b1;
                for (int unsigned i = 0; i < 4; i++) begin
                    if (w_strb_q[i]) begin
                        mem[word_idx(aw_addr_q)][8*i +: 8] <= w_data_q[8*i +: 8];
                    end
                end
                aw_pending <= 1'b0;
                w_pending  <= 1'b0;
            end

            if (axil_req_i.ar_valid && axil_resp_o.ar_ready) begin
                axil_resp_o.r.data  <= mem[word_idx(axil_req_i.ar.addr)];
                axil_resp_o.r.resp  <= 2'b00;
                axil_resp_o.r_valid <= 1'b1;
            end
        end
    end

endmodule : tb_smc_gpio_ctrl_rw_stub

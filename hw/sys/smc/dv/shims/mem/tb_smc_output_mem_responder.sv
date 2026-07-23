// SPDX-License-Identifier: Apache-2.0
//
// SMC output-fabric AXI memory responder (OSS DV shim).
//
// Extracted from the former inline tb_top output_mem so the fabric slave can
// follow the SEP-style memory-shim pattern: optional hex preload via
// +smc_output_hex=<path>, byte-strobe writes, and transaction counters for
// DMA / zeroer / filter tests.
//
// DEFENDS: OKAY AXI responses + retained memory for the SMC output fabric
//          master port (output_axi_req_o / output_axi_resp_i); optional
//          programmable SLVERR inject (U1-2) without updating mem on write.
// DOES NOT DEFEND: SoC-level fabric security policy, remap, or real DRAM.
//                  Filter DECERR is DUT-side (see smc_output_filter_* tests).

`timescale 1ps/1fs

module tb_smc_output_mem_responder
    import smc_pkg::*;
#(
    parameter int unsigned MEM_WORDS = 8192,
    // VCS requires a scanf-style format for $value$plusargs (e.g. name=%s).
    parameter string PLUSARG_NAME = "smc_output_hex=%s",
    parameter string DEFAULT_IMAGE = ""
) (
    input  wire logic clk_i,
    input  wire logic rst_ni,

    input  smc_sys_out_56_64_8_12_axi_req_t  axi_req_i,
    output smc_sys_out_56_64_8_12_axi_resp_t axi_resp_o,

    // When set, complete the next WR/RD with SLVERR (resp=2'b10). Writes do
    // not update mem[]; reads return poison data. Counters still advance.
    input  wire logic force_slverr_i,

    output logic [31:0] write_count_o,
    output logic [31:0] read_count_o,
    output logic [55:0] last_addr_o,
    output logic [63:0] last_wdata_o
);

    logic        aw_pending;
    logic [7:0]  aw_id_q;
    logic [55:0] aw_addr_q;
    logic        w_pending;
    logic [63:0] w_data_q;
    logic [7:0]  w_strb_q;
    logic [11:0] w_user_q;

    logic [63:0] mem [0:MEM_WORDS-1];
    string       image_path;
    int          image_fd;

    // Word index: keep the same [15:3] slice the inline tb_top used (64 KiB
    // window into MEM_WORDS). Addresses outside wrap naturally via the slice.
    function automatic logic [$clog2(MEM_WORDS)-1:0] word_idx(input logic [55:0] addr);
        return addr[15:3];
    endfunction

    initial begin
        for (int unsigned i = 0; i < MEM_WORDS; i++) begin
            mem[i] = '0;
        end
        if ((PLUSARG_NAME != "") && $value$plusargs(PLUSARG_NAME, image_path)) begin
            $readmemh(image_path, mem);
            $display("[tb_smc_output_mem_responder] loaded %s", image_path);
        end else if (DEFAULT_IMAGE != "") begin
            image_fd = $fopen(DEFAULT_IMAGE, "r");
            if (image_fd != 0) begin
                $fclose(image_fd);
                $readmemh(DEFAULT_IMAGE, mem);
                $display("[tb_smc_output_mem_responder] loaded %s", DEFAULT_IMAGE);
            end
        end
    end

    assign axi_resp_o.aw_ready = !axi_resp_o.b_valid && !aw_pending;
    assign axi_resp_o.w_ready  = !axi_resp_o.b_valid && !w_pending;
    assign axi_resp_o.ar_ready = !axi_resp_o.r_valid;

    // Use always (not always_ff): mem[] is also written by the initial
    // preload/$readmemh block. VCS rejects initial + always_ff dual drivers
    // (ICPD); Verilator is more permissive. Protocol state still follows the
    // same posedge/async-reset schedule.
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            aw_pending    <= 1'b0;
            aw_id_q       <= '0;
            aw_addr_q     <= '0;
            w_pending     <= 1'b0;
            w_data_q      <= '0;
            w_strb_q      <= '0;
            w_user_q      <= '0;
            axi_resp_o.b       <= '0;
            axi_resp_o.b_valid <= 1'b0;
            axi_resp_o.r       <= '0;
            axi_resp_o.r_valid <= 1'b0;
            write_count_o <= '0;
            read_count_o  <= '0;
            last_addr_o   <= '0;
            last_wdata_o  <= '0;
            // Do NOT clear mem[] on reset — matches preload semantics and
            // avoids wiping a hex image across warm resets.
        end else begin
            if (axi_resp_o.b_valid && axi_req_i.b_ready) begin
                axi_resp_o.b_valid <= 1'b0;
            end
            if (axi_resp_o.r_valid && axi_req_i.r_ready) begin
                axi_resp_o.r_valid <= 1'b0;
            end

            if (axi_req_i.aw_valid && axi_resp_o.aw_ready) begin
                aw_pending <= 1'b1;
                aw_id_q    <= axi_req_i.aw.id;
                aw_addr_q  <= axi_req_i.aw.addr;
            end
            if (axi_req_i.w_valid && axi_resp_o.w_ready) begin
                w_pending <= 1'b1;
                w_data_q  <= axi_req_i.w.data;
                w_strb_q  <= axi_req_i.w.strb;
                w_user_q  <= axi_req_i.w.user;
            end

            if (!axi_resp_o.b_valid && aw_pending && w_pending) begin
                axi_resp_o.b.id     <= aw_id_q;
                axi_resp_o.b.resp   <= force_slverr_i ? 2'b10 : 2'b00;
                axi_resp_o.b.user   <= w_user_q;
                axi_resp_o.b_valid  <= 1'b1;
                write_count_o       <= write_count_o + 32'd1;
                last_addr_o         <= aw_addr_q;
                last_wdata_o        <= w_data_q;
                if (!force_slverr_i) begin
                    for (int unsigned i = 0; i < 8; i++) begin
                        if (w_strb_q[i]) begin
                            mem[word_idx(aw_addr_q)][8*i +: 8] <=
                                w_data_q[8*i +: 8];
                        end
                    end
                end
                aw_pending <= 1'b0;
                w_pending  <= 1'b0;
            end

            if (axi_req_i.ar_valid && axi_resp_o.ar_ready) begin
                axi_resp_o.r.id     <= axi_req_i.ar.id;
                axi_resp_o.r.data   <= force_slverr_i
                    ? 64'hDEAD_BEEF_DEAD_BEEF
                    : mem[word_idx(axi_req_i.ar.addr)];
                axi_resp_o.r.resp   <= force_slverr_i ? 2'b10 : 2'b00;
                axi_resp_o.r.last   <= 1'b1;
                axi_resp_o.r.user   <= axi_req_i.ar.user;
                axi_resp_o.r_valid  <= 1'b1;
                read_count_o        <= read_count_o + 32'd1;
                last_addr_o         <= axi_req_i.ar.addr;
            end
        end
    end

endmodule : tb_smc_output_mem_responder

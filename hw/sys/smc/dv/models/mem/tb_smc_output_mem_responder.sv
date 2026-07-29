// SPDX-License-Identifier: Apache-2.0
//
// SMC output-fabric AXI memory responder (OSS DV shim).
//
// SYS_OUT stays a TB boundary slave (SEP keeps outbound AXI outside the
// wrapper). Storage uses prim_ram_1p so the macro matches SEP / CPU mem;
// AXI front-end keeps SLVERR inject, counters, and +smc_output_hex preload
// (backdoor into prim.mem after #0).
//
// Read path: prim_ram_1p returns data one cycle after req; R channel
// completes on the following cycle (vs combo mem[] previously).
//
// DEFENDS: OKAY AXI responses + retained memory for the SMC output fabric
//          master port; optional programmable SLVERR inject (U1-2).
// DOES NOT DEFEND: SoC-level fabric security policy, remap, or real DRAM.

`timescale 1ps/1fs

module tb_smc_output_mem_responder
    import smc_pkg::*;
    import prim_ram_1p_pkg::*;
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
    // not update mem; reads return poison data. Counters still advance.
    input  wire logic force_slverr_i,

    output logic [31:0] write_count_o,
    output logic [31:0] read_count_o,
    output logic [55:0] last_addr_o,
    output logic [63:0] last_wdata_o
);

    localparam int unsigned ADDR_W = $clog2(MEM_WORDS);

    logic        aw_pending;
    logic [7:0]  aw_id_q;
    logic [55:0] aw_addr_q;
    logic        w_pending;
    logic [63:0] w_data_q;
    logic [7:0]  w_strb_q;
    logic [11:0] w_user_q;

    // Read pipeline: AR accepted -> prim req this cycle -> R next cycle.
    logic        rd_pending;
    logic [7:0]  rd_id_q;
    logic [11:0] rd_user_q;
    logic        rd_slverr_q;
    logic [55:0] rd_addr_q;

    logic             mem_req;
    logic             mem_write;
    logic [ADDR_W-1:0] mem_addr;
    logic [63:0]      mem_wdata;
    logic [63:0]      mem_wmask;
    logic [63:0]      mem_rdata;

    string image_path;
    int    image_fd;

    function automatic logic [ADDR_W-1:0] word_idx(input logic [55:0] addr);
        return addr[15:3];
    endfunction

    function automatic logic [63:0] strb_to_wmask(input logic [7:0] strb);
        logic [63:0] m;
        m = '0;
        for (int unsigned i = 0; i < 8; i++) begin
            if (strb[i]) begin
                m[8*i +: 8] = 8'hFF;
            end
        end
        return m;
    endfunction

    prim_ram_1p #(
        .Width          (64),
        .Depth          (MEM_WORDS),
        .DataBitsPerMask(8),
        .MemInitFile    ("")
    ) u_mem (
        .clk_i,
        .rst_ni,
        .req_i   (mem_req),
        .write_i (mem_write),
        .addr_i  (mem_addr),
        .wdata_i (mem_wdata),
        .wmask_i (mem_wmask),
        .rdata_o (mem_rdata),
        .cfg_i   ('0),
        .cfg_rsp_o()
    );

    // Time-zero preload into prim_ram_1p.mem (SEP tb_backdoor_mem posture).
    initial begin
        #0;
        for (int unsigned i = 0; i < MEM_WORDS; i++) begin
            u_mem.mem[i] = '0;
        end
        if ((PLUSARG_NAME != "") && $value$plusargs(PLUSARG_NAME, image_path)) begin
            $readmemh(image_path, u_mem.mem);
            $display("[tb_smc_output_mem_responder] loaded %s into prim_ram_1p", image_path);
        end else if (DEFAULT_IMAGE != "") begin
            image_fd = $fopen(DEFAULT_IMAGE, "r");
            if (image_fd != 0) begin
                $fclose(image_fd);
                $readmemh(DEFAULT_IMAGE, u_mem.mem);
                $display("[tb_smc_output_mem_responder] loaded %s into prim_ram_1p",
                         DEFAULT_IMAGE);
            end
        end
    end

    // Single-port: prefer completing a write commit over accepting AR when both
    // would need the RAM in the same cycle (WR path also drives mem_req).
    wire wr_commit = !axi_resp_o.b_valid && aw_pending && w_pending;

    assign axi_resp_o.aw_ready = !axi_resp_o.b_valid && !aw_pending;
    assign axi_resp_o.w_ready  = !axi_resp_o.b_valid && !w_pending;
    assign axi_resp_o.ar_ready = !axi_resp_o.r_valid && !rd_pending && !wr_commit;

    always_comb begin
        mem_req   = 1'b0;
        mem_write = 1'b0;
        mem_addr  = '0;
        mem_wdata = '0;
        mem_wmask = '0;
        if (wr_commit && !force_slverr_i) begin
            mem_req   = 1'b1;
            mem_write = 1'b1;
            mem_addr  = word_idx(aw_addr_q);
            mem_wdata = w_data_q;
            mem_wmask = strb_to_wmask(w_strb_q);
        end else if (axi_req_i.ar_valid && axi_resp_o.ar_ready && !force_slverr_i) begin
            mem_req   = 1'b1;
            mem_write = 1'b0;
            mem_addr  = word_idx(axi_req_i.ar.addr);
        end
    end

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            aw_pending         <= 1'b0;
            aw_id_q            <= '0;
            aw_addr_q          <= '0;
            w_pending          <= 1'b0;
            w_data_q           <= '0;
            w_strb_q           <= '0;
            w_user_q           <= '0;
            rd_pending         <= 1'b0;
            rd_id_q            <= '0;
            rd_user_q          <= '0;
            rd_slverr_q        <= 1'b0;
            rd_addr_q          <= '0;
            axi_resp_o.b       <= '0;
            axi_resp_o.b_valid <= 1'b0;
            axi_resp_o.r       <= '0;
            axi_resp_o.r_valid <= 1'b0;
            write_count_o      <= '0;
            read_count_o       <= '0;
            last_addr_o        <= '0;
            last_wdata_o       <= '0;
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

            if (wr_commit) begin
                axi_resp_o.b.id     <= aw_id_q;
                axi_resp_o.b.resp   <= force_slverr_i ? 2'b10 : 2'b00;
                axi_resp_o.b.user   <= w_user_q;
                axi_resp_o.b_valid  <= 1'b1;
                write_count_o       <= write_count_o + 32'd1;
                last_addr_o         <= aw_addr_q;
                last_wdata_o        <= w_data_q;
                aw_pending          <= 1'b0;
                w_pending           <= 1'b0;
            end

            // Complete prior AR after prim read latency (or same-cycle SLVERR).
            if (rd_pending && !axi_resp_o.r_valid) begin
                axi_resp_o.r.id     <= rd_id_q;
                axi_resp_o.r.data   <= rd_slverr_q ? 64'hDEAD_BEEF_DEAD_BEEF : mem_rdata;
                axi_resp_o.r.resp   <= rd_slverr_q ? 2'b10 : 2'b00;
                axi_resp_o.r.last   <= 1'b1;
                axi_resp_o.r.user   <= rd_user_q;
                axi_resp_o.r_valid  <= 1'b1;
                read_count_o        <= read_count_o + 32'd1;
                last_addr_o         <= rd_addr_q;
                rd_pending          <= 1'b0;
            end

            if (axi_req_i.ar_valid && axi_resp_o.ar_ready) begin
                rd_pending  <= 1'b1;
                rd_id_q     <= axi_req_i.ar.id;
                rd_user_q   <= axi_req_i.ar.user;
                rd_slverr_q <= force_slverr_i;
                rd_addr_q   <= axi_req_i.ar.addr;
            end
        end
    end

endmodule : tb_smc_output_mem_responder

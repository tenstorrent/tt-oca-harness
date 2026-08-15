// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Behavioral AXI4 RAM responder with deterministic error injection.
//
// SystemVerilog analogue of the cocotb OcahFaultAxiRam: a zero-initialized
// byte memory supporting FIXED/INCR/WRAP single- and multi-beat bursts, ID
// echo (BID/RID), per-ARLEN RLAST generation, per-beat error matching, and
// port-driven error controls. One outstanding transaction per direction —
// sufficient for the serialized OCAH debug bridges; document before reusing
// behind a fabric that pipelines requests.
//
// While `err_arm_i` is high and a beat's aligned word address matches
// `err_addr_i`, the enabled direction responds `err_resp_i` for that beat
// (worst response wins for the write burst's single B), skips the memory
// update (writes), and returns zero data (reads).
//
// Simulation TB collateral for the SV-UVM flow. Not for synthesis/Verilator.

module ocah_axi_ram_responder #(
    parameter int unsigned ADDR_WIDTH = 56,
    parameter int unsigned DATA_WIDTH = 64,
    parameter int unsigned ID_WIDTH   = 2,
    parameter int unsigned MEM_BYTES  = 65536  // power of two
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_ni,

    // Write address channel.
    input  wire logic [ID_WIDTH-1:0]     awid,
    input  wire logic [ADDR_WIDTH-1:0]   awaddr,
    input  wire logic [7:0]              awlen,
    input  wire logic [2:0]              awsize,
    input  wire logic [1:0]              awburst,
    input  wire logic [2:0]              awprot,
    input  wire logic                    awvalid,
    output logic                         awready,

    // Write data channel.
    input  wire logic [DATA_WIDTH-1:0]   wdata,
    input  wire logic [DATA_WIDTH/8-1:0] wstrb,
    input  wire logic                    wlast,
    input  wire logic                    wvalid,
    output logic                         wready,

    // Write response channel.
    output logic [ID_WIDTH-1:0]          bid,
    output logic [1:0]                   bresp,
    output logic                         bvalid,
    input  wire logic                    bready,

    // Read address channel.
    input  wire logic [ID_WIDTH-1:0]     arid,
    input  wire logic [ADDR_WIDTH-1:0]   araddr,
    input  wire logic [7:0]              arlen,
    input  wire logic [2:0]              arsize,
    input  wire logic [1:0]              arburst,
    input  wire logic [2:0]              arprot,
    input  wire logic                    arvalid,
    output logic                         arready,

    // Read data channel.
    output logic [ID_WIDTH-1:0]          rid,
    output logic [DATA_WIDTH-1:0]        rdata,
    output logic [1:0]                   rresp,
    output logic                         rlast,
    output logic                         rvalid,
    input  wire logic                    rready,

    // Error-injection controls (driven from a TB interface).
    input  wire logic                    err_arm_i,
    input  wire logic [ADDR_WIDTH-1:0]   err_addr_i,
    input  wire logic [1:0]              err_resp_i,
    input  wire logic                    err_on_read_i,
    input  wire logic                    err_on_write_i
);

    localparam int unsigned StrbWidth = DATA_WIDTH / 8;
    localparam logic [1:0] RespOkay  = 2'b00;
    localparam logic [1:0] BurstFixed = 2'b00;
    localparam logic [1:0] BurstWrap  = 2'b10;

    logic [7:0] mem [0:MEM_BYTES-1];
    initial begin
        for (int unsigned i = 0; i < MEM_BYTES; i++) mem[i] = '0;
    end

    function automatic logic [ADDR_WIDTH-1:0] word_align(input logic [ADDR_WIDTH-1:0] addr);
        return (addr & ~ADDR_WIDTH'(StrbWidth - 1)) & ADDR_WIDTH'(MEM_BYTES - 1);
    endfunction

    function automatic logic err_match(
        input logic [ADDR_WIDTH-1:0] addr,
        input logic                  dir_en
    );
        return err_arm_i && dir_en && (word_align(addr) == word_align(err_addr_i));
    endfunction

    // Next beat address for FIXED/INCR/WRAP (IHI 0022 A3.4.1 arithmetic).
    function automatic logic [ADDR_WIDTH-1:0] next_beat_addr(
        input logic [ADDR_WIDTH-1:0] cur,
        input logic [ADDR_WIDTH-1:0] start,
        input logic [2:0]            size,
        input logic [7:0]            len,
        input logic [1:0]            burst
    );
        logic [ADDR_WIDTH-1:0] nxt;
        logic [ADDR_WIDTH-1:0] transfer;
        logic [ADDR_WIDTH-1:0] lower_wrap;
        if (burst == BurstFixed)
            return cur;
        nxt = cur + (ADDR_WIDTH'(1) << size);
        if (burst == BurstWrap) begin
            transfer   = (ADDR_WIDTH'(len) + ADDR_WIDTH'(1)) << size;
            lower_wrap = (start / transfer) * transfer;
            if (nxt == lower_wrap + transfer)
                nxt = lower_wrap;
        end
        return nxt;
    endfunction

    // ------------------------------------------------------------------
    // Write path: one outstanding burst.
    // ------------------------------------------------------------------
    logic                  wr_active;
    logic [ID_WIDTH-1:0]   wr_id_q;
    logic [ADDR_WIDTH-1:0] wr_addr_q, wr_start_q;
    logic [7:0]            wr_len_q;
    logic [2:0]            wr_size_q;
    logic [1:0]            wr_burst_q;
    logic [1:0]            wr_resp_q;

    assign awready = rst_ni && !wr_active && !bvalid;
    assign wready  = rst_ni && wr_active;

    // Plain `always`: `mem` is also zero-filled by the time-0 initial block,
    // and always_ff forbids a variable written by any other process.
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            wr_active <= 1'b0;
            bvalid    <= 1'b0;
            bid       <= '0;
            bresp     <= RespOkay;
            wr_id_q   <= '0;
            wr_addr_q <= '0;
            wr_start_q <= '0;
            wr_len_q  <= '0;
            wr_size_q <= '0;
            wr_burst_q <= '0;
            wr_resp_q <= RespOkay;
        end else begin
            if (awvalid && awready) begin
                wr_id_q    <= awid;
                wr_addr_q  <= (awaddr >> awsize) << awsize;
                wr_start_q <= awaddr;
                wr_len_q   <= awlen;
                wr_size_q  <= awsize;
                wr_burst_q <= awburst;
                wr_resp_q  <= RespOkay;
                wr_active  <= 1'b1;
            end
            if (wr_active && wvalid && wready) begin
                if (err_match(wr_addr_q, err_on_write_i)) begin
                    if (err_resp_i > wr_resp_q)
                        wr_resp_q <= err_resp_i;
                end else begin
                    for (int unsigned lane = 0; lane < StrbWidth; lane++) begin
                        if (wstrb[lane])
                            mem[int'(word_align(wr_addr_q)) + lane] <= wdata[8*lane +: 8];
                    end
                end
                wr_addr_q <= next_beat_addr(wr_addr_q, wr_start_q, wr_size_q, wr_len_q, wr_burst_q);
                if (wlast) begin
                    bid    <= wr_id_q;
                    bresp  <= (err_match(wr_addr_q, err_on_write_i) && err_resp_i > wr_resp_q)
                              ? err_resp_i : wr_resp_q;
                    bvalid <= 1'b1;
                    wr_active <= 1'b0;
                end
            end
            if (bvalid && bready)
                bvalid <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // Read path: one outstanding burst, one beat per cycle when accepted.
    // ------------------------------------------------------------------
    logic                  rd_active;
    logic [ID_WIDTH-1:0]   rd_id_q;
    logic [ADDR_WIDTH-1:0] rd_addr_q, rd_start_q;
    logic [7:0]            rd_len_q, rd_beat_q;
    logic [2:0]            rd_size_q;
    logic [1:0]            rd_burst_q;

    assign arready = rst_ni && !rd_active && !rvalid;

    task automatic load_read_beat(input logic [ADDR_WIDTH-1:0] addr);
        if (err_match(addr, err_on_read_i)) begin
            rresp <= err_resp_i;
            rdata <= '0;
        end else begin
            rresp <= RespOkay;
            for (int unsigned lane = 0; lane < StrbWidth; lane++)
                rdata[8*lane +: 8] <= mem[int'(word_align(addr)) + lane];
        end
    endtask

    // Plain `always`: rdata/rresp are also assigned inside load_read_beat, a
    // task tools cannot prove is called only from this process (IEEE 9.2.2.4).
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            rd_active <= 1'b0;
            rvalid    <= 1'b0;
            rid       <= '0;
            rdata     <= '0;
            rresp     <= RespOkay;
            rlast     <= 1'b0;
            rd_id_q   <= '0;
            rd_addr_q <= '0;
            rd_start_q <= '0;
            rd_len_q  <= '0;
            rd_beat_q <= '0;
            rd_size_q <= '0;
            rd_burst_q <= '0;
        end else begin
            if (arvalid && arready) begin
                rd_id_q    <= arid;
                rd_start_q <= araddr;
                rd_len_q   <= arlen;
                rd_beat_q  <= '0;
                rd_size_q  <= arsize;
                rd_burst_q <= arburst;
                rd_active  <= 1'b1;
                rid        <= arid;
                rlast      <= (arlen == '0);
                load_read_beat((araddr >> arsize) << arsize);
                rd_addr_q <= next_beat_addr((araddr >> arsize) << arsize, araddr,
                                            arsize, arlen, arburst);
                rvalid <= 1'b1;
            end
            if (rvalid && rready) begin
                if (rlast) begin
                    rvalid    <= 1'b0;
                    rd_active <= 1'b0;
                end else begin
                    rd_beat_q <= rd_beat_q + 8'd1;
                    rlast     <= (rd_beat_q + 8'd1 == rd_len_q);
                    load_read_beat(rd_addr_q);
                    rd_addr_q <= next_beat_addr(rd_addr_q, rd_start_q, rd_size_q,
                                                rd_len_q, rd_burst_q);
                end
            end
        end
    end

endmodule : ocah_axi_ram_responder

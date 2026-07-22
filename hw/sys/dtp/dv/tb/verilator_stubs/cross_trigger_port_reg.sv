// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for the PeakRDL-generated
// cross_trigger_port_reg CSR block.
//
// The generated register file uses a non-blocking assignment to a compound
// (struct) array element indexed by a dynamic pointer inside the AXI-Lite
// response buffer. Verilator rejects this with BLKLOOPINIT (an unsupported
// construct, not a waivable warning) once cocotb's --public-flat-rw keeps the
// otherwise dead-code-eliminated cross-trigger logic.
//
// The DTP OSS XTRIG tests need functional CSR behavior under Verilator. This
// module intentionally implements only the public CTP register map used by the
// RTL wrapper: CONFIG, STATUS, and STRETCH_MULT. It is selected ahead of the
// generated module via the -Wno-MODDUP "first definition wins" stub mechanism.
//
// To run real cross-trigger CSR tests, drop this stub and use a commercial
// simulator (Xcelium/VCS), or replace it with a Verilator-compatible register
// implementation.

module cross_trigger_port_reg (
    input  wire                                          clk,
    input  wire                                          arst_n,

    output logic                                         s_axil_awready,
    input  wire                                          s_axil_awvalid,
    input  wire  [3:0]                                   s_axil_awaddr,
    input  wire  [2:0]                                   s_axil_awprot,
    output logic                                         s_axil_wready,
    input  wire                                          s_axil_wvalid,
    input  wire  [31:0]                                  s_axil_wdata,
    input  wire  [3:0]                                   s_axil_wstrb,
    input  wire                                          s_axil_bready,
    output logic                                         s_axil_bvalid,
    output logic [1:0]                                   s_axil_bresp,
    output logic                                         s_axil_arready,
    input  wire                                          s_axil_arvalid,
    input  wire  [3:0]                                   s_axil_araddr,
    input  wire  [2:0]                                   s_axil_arprot,
    input  wire                                          s_axil_rready,
    output logic                                         s_axil_rvalid,
    output logic [31:0]                                  s_axil_rdata,
    output logic [1:0]                                   s_axil_rresp,

    input  cross_trigger_port_reg_pkg::cross_trigger_port__in_t   hwif_in,
    output cross_trigger_port_reg_pkg::cross_trigger_port__out_t  hwif_out
);

    localparam logic [3:0] ADDR_CONFIG       = 4'h0;
    localparam logic [3:0] ADDR_STATUS       = 4'h4;
    localparam logic [3:0] ADDR_STRETCH_MULT = 4'h8;

    logic        aw_pending;
    logic [3:0]  awaddr_q;
    logic        w_pending;
    logic [31:0] wdata_q;
    logic [3:0]  wstrb_q;
    logic [2:0]  config_q;
    logic [15:0] stretch_mult_q;

    function automatic logic [31:0] apply_wstrb(
        input logic [31:0] old_value,
        input logic [31:0] new_value,
        input logic [3:0]  strb
    );
        logic [31:0] merged;
        begin
            merged = old_value;
            for (int unsigned byte_idx = 0; byte_idx < 4; byte_idx++) begin
                if (strb[byte_idx]) begin
                    merged[8 * byte_idx +: 8] = new_value[8 * byte_idx +: 8];
                end
            end
            return merged;
        end
    endfunction

    function automatic logic [31:0] status_value();
        return {
            24'h0,
            hwif_in.STATUS.ACK_OUT.next,
            hwif_in.STATUS.REQ_IN.next,
            hwif_in.STATUS.ACK_IN.next,
            hwif_in.STATUS.REQ_OUT.next,
            3'h0,
            hwif_in.STATUS.BUSY.next
        };
    endfunction

    function automatic logic [31:0] read_data(input logic [3:0] addr);
        unique case (addr[3:0])
            ADDR_CONFIG:       return {29'h0, config_q};
            ADDR_STATUS:       return status_value();
            ADDR_STRETCH_MULT: return {16'h0, stretch_mult_q};
            default:           return 32'h0;
        endcase
    endfunction

    task automatic do_write(input logic [3:0] addr, input logic [31:0] data, input logic [3:0] strb);
        logic [31:0] merged;
        begin
            unique case (addr[3:0])
                ADDR_CONFIG: begin
                    merged = apply_wstrb({29'h0, config_q}, data, strb);
                    config_q <= merged[2:0];
                end
                ADDR_STRETCH_MULT: begin
                    merged = apply_wstrb({16'h0, stretch_mult_q}, data, strb);
                    stretch_mult_q <= merged[15:0];
                end
                default: begin
                    // STATUS is read-only and unmapped offsets are benign no-ops
                    // in this Verilator-safe behavioral model.
                end
            endcase
        end
    endtask

    assign s_axil_awready = !aw_pending;
    assign s_axil_wready  = !w_pending;
    assign s_axil_bresp   = 2'b00;
    assign s_axil_arready = !s_axil_rvalid;
    assign s_axil_rresp   = 2'b00;

    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            aw_pending     <= 1'b0;
            awaddr_q       <= '0;
            w_pending      <= 1'b0;
            wdata_q        <= '0;
            wstrb_q        <= '0;
            s_axil_bvalid  <= 1'b0;
            s_axil_rvalid  <= 1'b0;
            s_axil_rdata   <= '0;
            config_q       <= '0;
            stretch_mult_q <= '0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) begin
                s_axil_bvalid <= 1'b0;
            end
            if (s_axil_rvalid && s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end

            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending <= 1'b1;
                awaddr_q   <= s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending <= 1'b1;
                wdata_q   <= s_axil_wdata;
                wstrb_q   <= s_axil_wstrb;
            end

            if (!s_axil_bvalid &&
                ((aw_pending || (s_axil_awvalid && s_axil_awready)) &&
                 (w_pending || (s_axil_wvalid && s_axil_wready)))) begin
                do_write(
                    aw_pending ? awaddr_q : s_axil_awaddr,
                    w_pending ? wdata_q : s_axil_wdata,
                    w_pending ? wstrb_q : s_axil_wstrb
                );
                aw_pending    <= 1'b0;
                w_pending     <= 1'b0;
                s_axil_bvalid <= 1'b1;
            end

            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid <= 1'b1;
                s_axil_rdata  <= read_data(s_axil_araddr);
            end
        end
    end

    always_comb begin
        hwif_out = '{default: '0};
        hwif_out.CONFIG.MODE.value                 = config_q[0];
        hwif_out.CONFIG.INVERT.value               = config_q[1];
        hwif_out.CONFIG.RESET.value                = config_q[2];
        hwif_out.STRETCH_MULT.STRETCH_MULT.value   = stretch_mult_q;
    end

endmodule

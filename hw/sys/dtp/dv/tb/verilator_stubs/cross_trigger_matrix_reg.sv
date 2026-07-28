// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for the PeakRDL-generated
// cross_trigger_matrix_reg CSR block. See cross_trigger_port_reg.sv (the
// companion stub) for the rationale: the generated AXI-Lite response buffer
// uses a dynamically-indexed non-blocking assignment to a struct array that
// the Verilator backend rejects (BLKLOOPINIT) under cocotb's --public-flat-rw.
//
// The DTP OSS XTRIG tests need CTM CSR behavior under Verilator, but the
// generated block is not accepted by Verilator. This replacement implements the
// 26 CONFIG_0 destination-select registers used by the generated CTM RTL.

module cross_trigger_matrix_reg (
    input  wire                                              clk,
    input  wire                                              arst_n,

    output logic                                             s_axil_awready,
    input  wire                                              s_axil_awvalid,
    input  wire  [7:0]                                       s_axil_awaddr,
    input  wire  [2:0]                                       s_axil_awprot,
    output logic                                             s_axil_wready,
    input  wire                                              s_axil_wvalid,
    input  wire  [31:0]                                      s_axil_wdata,
    input  wire  [3:0]                                       s_axil_wstrb,
    input  wire                                              s_axil_bready,
    output logic                                             s_axil_bvalid,
    output logic [1:0]                                       s_axil_bresp,
    output logic                                             s_axil_arready,
    input  wire                                              s_axil_arvalid,
    input  wire  [7:0]                                       s_axil_araddr,
    input  wire  [2:0]                                       s_axil_arprot,
    input  wire                                              s_axil_rready,
    output logic                                             s_axil_rvalid,
    output logic [31:0]                                      s_axil_rdata,
    output logic [1:0]                                       s_axil_rresp,

    output cross_trigger_matrix_reg_pkg::cross_trigger_matrix__out_t  hwif_out
);

    localparam int unsigned NUM_CT_SRC = 26;

    logic        aw_pending;
    logic [7:0]  awaddr_q;
    logic        w_pending;
    logic [31:0] wdata_q;
    logic [3:0]  wstrb_q;
    logic [25:0] dst_select_q [NUM_CT_SRC];

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

    function automatic int unsigned src_index(input logic [7:0] addr);
        return addr[7:3];
    endfunction

    function automatic logic is_config0_addr(input logic [7:0] addr);
        return (addr[2:0] == 3'h0) && (src_index(addr) < NUM_CT_SRC);
    endfunction

    function automatic logic [31:0] read_data(input logic [7:0] addr);
        if (is_config0_addr(addr)) begin
            return {6'h0, dst_select_q[src_index(addr)]};
        end
        return 32'h0;
    endfunction

    task automatic do_write(input logic [7:0] addr, input logic [31:0] data, input logic [3:0] strb);
        logic [31:0] merged;
        begin
            if (is_config0_addr(addr)) begin
                merged = apply_wstrb({6'h0, dst_select_q[src_index(addr)]}, data, strb);
                dst_select_q[src_index(addr)] <= merged[25:0];
            end
        end
    endtask

    assign s_axil_awready = !aw_pending;
    assign s_axil_wready  = !w_pending;
    assign s_axil_bresp   = 2'b00;
    assign s_axil_arready = !s_axil_rvalid;
    assign s_axil_rresp   = 2'b00;

    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            aw_pending    <= 1'b0;
            awaddr_q      <= '0;
            w_pending     <= 1'b0;
            wdata_q       <= '0;
            wstrb_q       <= '0;
            s_axil_bvalid <= 1'b0;
            s_axil_rvalid <= 1'b0;
            s_axil_rdata  <= '0;
            for (int unsigned idx = 0; idx < NUM_CT_SRC; idx++) begin
                dst_select_q[idx] <= '0;
            end
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
        hwif_out.CT_SRC0_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[0];
        hwif_out.CT_SRC1_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[1];
        hwif_out.CT_SRC2_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[2];
        hwif_out.CT_SRC3_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[3];
        hwif_out.CT_SRC4_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[4];
        hwif_out.CT_SRC5_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[5];
        hwif_out.CT_SRC6_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[6];
        hwif_out.CT_SRC7_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[7];
        hwif_out.CT_SRC8_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[8];
        hwif_out.CT_SRC9_CONFIG_0.CT_DST_SELECT.value  = dst_select_q[9];
        hwif_out.CT_SRC10_CONFIG_0.CT_DST_SELECT.value = dst_select_q[10];
        hwif_out.CT_SRC11_CONFIG_0.CT_DST_SELECT.value = dst_select_q[11];
        hwif_out.CT_SRC12_CONFIG_0.CT_DST_SELECT.value = dst_select_q[12];
        hwif_out.CT_SRC13_CONFIG_0.CT_DST_SELECT.value = dst_select_q[13];
        hwif_out.CT_SRC14_CONFIG_0.CT_DST_SELECT.value = dst_select_q[14];
        hwif_out.CT_SRC15_CONFIG_0.CT_DST_SELECT.value = dst_select_q[15];
        hwif_out.CT_SRC16_CONFIG_0.CT_DST_SELECT.value = dst_select_q[16];
        hwif_out.CT_SRC17_CONFIG_0.CT_DST_SELECT.value = dst_select_q[17];
        hwif_out.CT_SRC18_CONFIG_0.CT_DST_SELECT.value = dst_select_q[18];
        hwif_out.CT_SRC19_CONFIG_0.CT_DST_SELECT.value = dst_select_q[19];
        hwif_out.CT_SRC20_CONFIG_0.CT_DST_SELECT.value = dst_select_q[20];
        hwif_out.CT_SRC21_CONFIG_0.CT_DST_SELECT.value = dst_select_q[21];
        hwif_out.CT_SRC22_CONFIG_0.CT_DST_SELECT.value = dst_select_q[22];
        hwif_out.CT_SRC23_CONFIG_0.CT_DST_SELECT.value = dst_select_q[23];
        hwif_out.CT_SRC24_CONFIG_0.CT_DST_SELECT.value = dst_select_q[24];
        hwif_out.CT_SRC25_CONFIG_0.CT_DST_SELECT.value = dst_select_q[25];
    end

endmodule

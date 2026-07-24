// SPDX-License-Identifier: Apache-2.0
//
// Vendor-free SEP ICCM/DCCM responder with time-zero firmware loading.
//
// Drop-in replacement for hw/sep/sep_tcm_wrapper.sv (foundry RAM macros):
// the sim config excludes that file from the filelist and compiles this
// module under the same name, so no hw/ source is modified. The write
// counters are hierarchically probed by tb_wrapper_top.sv as boot evidence.

`timescale 1ps/1fs

module sep_tcm_wrapper
    import el2_pkg::*;
    import sep_pkg::*;
#(
    `include "el2_param.vh"
) (
    input  sep_cpu_tcm_req_t tcm_req_i,
    output sep_cpu_tcm_rsp_t tcm_rsp_o
);

    localparam int unsigned IB = pt.ICCM_NUM_BANKS;
    localparam int unsigned DB = pt.DCCM_NUM_BANKS;
    localparam int unsigned ID = 1 << pt.ICCM_INDEX_BITS;
    localparam int unsigned DD = 1 << pt.DCCM_INDEX_BITS;
    localparam int unsigned IW = 32 + pt.ICCM_ECC_WIDTH;
    localparam int unsigned DW = pt.DCCM_DATA_WIDTH + pt.DCCM_ECC_WIDTH;
    localparam int unsigned ICCM_BYTES = 1 << pt.ICCM_BITS;
    localparam int unsigned DCCM_BYTES = 1 << pt.DCCM_BITS;

    logic [IW-1:0] iccm_mem [IB][ID];
    logic [DW-1:0] dccm_mem [DB][DD];
    logic [IW-1:0] iccm_q [IB];
    logic [DW-1:0] dccm_q [DB];
    logic [7:0] itcm_buf [ICCM_BYTES];
    logic [7:0] dtcm_buf [DCCM_BYTES];

    // Boot evidence counters, hierarchically probed from the TB top.
    int unsigned iccm_write_count;
    int unsigned dccm_write_count;

    wire tcm_clk = tcm_req_i.clk;

    for (genvar bank = 0; bank < IB; bank++) begin : gen_iccm
        always_ff @(posedge tcm_clk) begin
            if (tcm_req_i.iccm_clken[bank] && tcm_req_i.iccm_wren_bank[bank]) begin
                iccm_mem[bank][tcm_req_i.iccm_addr_bank[bank]] <=
                    {
                        tcm_req_i.iccm_bank_wr_ecc[bank],
                        tcm_req_i.iccm_bank_wr_data[bank]
                    };
                iccm_q[bank] <= 'x;
                iccm_write_count <= iccm_write_count + 1;
            end else if (tcm_req_i.iccm_clken[bank]) begin
                iccm_q[bank] <= iccm_mem[bank][tcm_req_i.iccm_addr_bank[bank]];
            end
        end
        assign tcm_rsp_o.iccm_bank_dout[bank] = iccm_q[bank][31:0];
        assign tcm_rsp_o.iccm_bank_ecc[bank] = iccm_q[bank][IW-1:32];
    end

    for (genvar bank = 0; bank < DB; bank++) begin : gen_dccm
        always_ff @(posedge tcm_clk) begin
            if (tcm_req_i.dccm_clken[bank] && tcm_req_i.dccm_wren_bank[bank]) begin
                dccm_mem[bank][tcm_req_i.dccm_addr_bank[bank]] <=
                    {
                        tcm_req_i.dccm_wr_ecc_bank[bank],
                        tcm_req_i.dccm_wr_data_bank[bank]
                    };
                dccm_q[bank] <= 'x;
                dccm_write_count <= dccm_write_count + 1;
            end else if (tcm_req_i.dccm_clken[bank]) begin
                dccm_q[bank] <= dccm_mem[bank][tcm_req_i.dccm_addr_bank[bank]];
            end
        end
        assign tcm_rsp_o.dccm_bank_dout[bank] =
            dccm_q[bank][pt.DCCM_DATA_WIDTH-1:0];
        assign tcm_rsp_o.dccm_bank_ecc[bank] =
            dccm_q[bank][DW-1:pt.DCCM_DATA_WIDTH];
    end

    function automatic logic [6:0] riscv_ecc32(input logic [31:0] data);
        logic [6:0] synd;
        synd[0] = ^(data & 32'h56aa_ad5b);
        synd[1] = ^(data & 32'h9b33_366d);
        synd[2] = ^(data & 32'he3c3_c78e);
        synd[3] = ^(data & 32'h03fc_07f0);
        synd[4] = ^(data & 32'h03ff_f800);
        synd[5] = ^(data & 32'hfc00_0000);
        synd[6] = ^{data, synd[5:0]};
        return synd;
    endfunction

    task automatic load_iccm(input string path);
        logic [31:0] word;
        logic [IW-1:0] full_word;
        for (int offset = 0; offset < int'(ICCM_BYTES); offset++) begin
            itcm_buf[offset] = 8'h00;
        end
        $readmemh(path, itcm_buf);
        for (int offset = 0; offset + 3 < int'(ICCM_BYTES); offset += 4) begin
            word = {
                itcm_buf[offset+3],
                itcm_buf[offset+2],
                itcm_buf[offset+1],
                itcm_buf[offset]
            };
            full_word = word == 32'h0 ? '0 : {riscv_ecc32(word), word};
            iccm_mem[offset[3:2]][offset[17:4]] = full_word;
        end
        $display("[sep_tcm_wrapper] loaded ICCM from %s", path);
    endtask

    task automatic load_dccm(input string path);
        logic [31:0] word;
        logic [DW-1:0] full_word;
        for (int offset = 0; offset < int'(DCCM_BYTES); offset++) begin
            dtcm_buf[offset] = 8'h00;
        end
        $readmemh(path, dtcm_buf);
        for (int offset = 0; offset + 3 < int'(DCCM_BYTES); offset += 4) begin
            word = {
                dtcm_buf[offset+3],
                dtcm_buf[offset+2],
                dtcm_buf[offset+1],
                dtcm_buf[offset]
            };
            full_word = word == 32'h0 ? '0 : {riscv_ecc32(word), word};
            dccm_mem[offset[2]][offset[16:3]] = full_word;
        end
        $display("[sep_tcm_wrapper] loaded DCCM from %s", path);
    endtask

    initial begin
        string itcm_path = "smu_sep_smoke.itcm.hex";
        string dtcm_path = "smu_sep_smoke.dtcm.hex";
        int itcm_fd;
        int dtcm_fd;
        iccm_write_count = 0;
        dccm_write_count = 0;
        void'($value$plusargs("sep_itcm_hex=%s", itcm_path));
        void'($value$plusargs("sep_dtcm_hex=%s", dtcm_path));
        itcm_fd = $fopen(itcm_path, "r");
        dtcm_fd = $fopen(dtcm_path, "r");
        if (itcm_fd == 0) begin
            $fatal(1, "[sep_tcm_wrapper] missing ICCM image %s", itcm_path);
        end
        if (dtcm_fd == 0) begin
            $fatal(1, "[sep_tcm_wrapper] missing DCCM image %s", dtcm_path);
        end
        $fclose(itcm_fd);
        $fclose(dtcm_fd);
        load_iccm(itcm_path);
        load_dccm(dtcm_path);
    end

endmodule : sep_tcm_wrapper

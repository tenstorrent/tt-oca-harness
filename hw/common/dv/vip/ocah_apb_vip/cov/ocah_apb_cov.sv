// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Tenstorrent Inc.
//
// Commercial-simulator APB functional coverage hook.
// Do not add this file to Verilator filelists; it intentionally uses covergroups.

interface ocah_apb_cov_if #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input wire logic clk_i,
    input wire logic rst_ni
);

    covergroup apb_access_cg with function sample(
        bit is_write,
        bit pslverr,
        int unsigned wait_cycles,
        bit has_strobe,
        bit [2:0] prot
    );
        option.per_instance = 1;
        cp_direction: coverpoint is_write {
            bins read = {1'b0};
            bins write = {1'b1};
        }
        cp_pslverr: coverpoint pslverr {
            bins okay = {1'b0};
            bins error = {1'b1};
        }
        cp_wait_cycles: coverpoint wait_cycles {
            bins zero = {0};
            bins short[] = {[1:3]};
            bins long = {[4:31]};
            bins very_long = {[32:$]};
        }
        cp_has_strobe: coverpoint has_strobe;
        cp_prot: coverpoint prot;
        cx_direction_resp: cross cp_direction, cp_pslverr;
    endgroup

    apb_access_cg access_cg = new();

    task automatic sample_access(
        input bit is_write,
        input logic [ADDR_WIDTH-1:0] addr,
        input logic [DATA_WIDTH-1:0] data,
        input logic [(DATA_WIDTH/8)-1:0] strobe,
        input logic [2:0] prot,
        input bit pslverr,
        input int unsigned wait_cycles
    );
        bit has_strobe;
        void'(addr);
        void'(data);
        if (!rst_ni) begin
            return;
        end
        has_strobe = |strobe;
        access_cg.sample(is_write, pslverr, wait_cycles, has_strobe, prot);
    endtask

endinterface

module ocah_apb_cov #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input wire logic clk_i,
    input wire logic rst_ni,
    input wire logic sample_valid_i,
    input wire logic is_write_i,
    input wire logic [ADDR_WIDTH-1:0] addr_i,
    input wire logic [DATA_WIDTH-1:0] data_i,
    input wire logic [(DATA_WIDTH/8)-1:0] strobe_i,
    input wire logic [2:0] prot_i,
    input wire logic pslverr_i,
    input wire logic [15:0] wait_cycles_i
);

    ocah_apb_cov_if #(
        .ADDR_WIDTH(ADDR_WIDTH),
        .DATA_WIDTH(DATA_WIDTH)
    ) cov_if (
        .clk_i(clk_i),
        .rst_ni(rst_ni)
    );

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            // Covergroups are sampled only when reset is deasserted.
        end else if (sample_valid_i) begin
            cov_if.sample_access(
                is_write_i,
                addr_i,
                data_i,
                strobe_i,
                prot_i,
                pslverr_i,
                wait_cycles_i
            );
        end
    end

endmodule

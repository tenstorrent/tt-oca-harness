// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Management Controller Output Remap
//
//-----------------------------------------------------------------------------


module output_remap
#(
    parameter type          axi_req_t        = logic,
    parameter type          axi_resp_t       = logic,
    parameter type          remap_addr_t     = logic,
    parameter type          user_ovrd_t      = logic,
    parameter int unsigned  NumRegions       = 8,
    parameter int unsigned  RegionBase       = 0,
    parameter int unsigned  IdxStart         = 20,
    parameter bit           UserOverrideEn   = 1'b1,
    parameter user_ovrd_t   UserOverrideVal  = '0,

    localparam int unsigned RemapIndexW      = $clog2(NumRegions)
) (
    input  logic                                       clk_i,
    input  logic                                       rst_ni,
    input  logic                                       test_en_i,

    // CSR structs for remap configuration
    input  output_remap_reg_pkg::output_remap__out_t   remap_ctrl_i [NumRegions-1:0],

    // Main data AXI interface
    input  axi_req_t           axi_req_i,
    output axi_resp_t          axi_resp_o,

    output axi_req_t           axi_remapped_req_o,
    input  axi_resp_t          axi_remapped_resp_i
);

    /////////////////////////
    // Signal declarations //
    /////////////////////////

    remap_addr_t adjusted_aw_addr, adjusted_ar_addr;
    logic [RemapIndexW-1:0] remap_aw_idx, remap_ar_idx;
    remap_addr_t remapped_aw_addr, remapped_ar_addr;

    /////
    // Convert struct to array
    /////

    typedef struct packed {
        logic [55:0] offset;
    } remap_attrs_t;
    remap_attrs_t remap_table[NumRegions];


    // Connect register outputs to remap_table array
    for (genvar i = 0; i < NumRegions; i++) begin : gen_remap_table
        assign remap_table[i].offset = remap_ctrl_i[i].REGION.region_attrs.offset.value;
    end

    /////////////////////////////
    // Address Remapping Logic //
    /////////////////////////////

    assign adjusted_aw_addr = axi_req_i.aw.addr - remap_addr_t'(RegionBase);
    assign adjusted_ar_addr = axi_req_i.ar.addr - remap_addr_t'(RegionBase);

    always_comb begin
        // Extract remap table index from relevant bits of adjusted address
        remap_aw_idx = adjusted_aw_addr[IdxStart+:RemapIndexW];
        remap_ar_idx = adjusted_ar_addr[IdxStart+:RemapIndexW];

        // Remap address: replace upper bits with table offset, preserve lower bits
        remapped_aw_addr = {
            remap_table[remap_aw_idx].offset[55:IdxStart], adjusted_aw_addr[IdxStart-1:0]
        };

        remapped_ar_addr = {
            remap_table[remap_ar_idx].offset[55:IdxStart], adjusted_ar_addr[IdxStart-1:0]
        };
    end

    /////////////////////
    // AXI Translation //
    /////////////////////

    assign axi_remapped_req_o.aw.id     = axi_req_i.aw.id;
    assign axi_remapped_req_o.aw.addr   = remapped_aw_addr;
    assign axi_remapped_req_o.aw.len    = axi_req_i.aw.len;
    assign axi_remapped_req_o.aw.size   = axi_req_i.aw.size;
    assign axi_remapped_req_o.aw.burst  = axi_req_i.aw.burst;
    assign axi_remapped_req_o.aw.lock   = axi_req_i.aw.lock;
    assign axi_remapped_req_o.aw.cache  = axi_req_i.aw.cache;
    assign axi_remapped_req_o.aw.prot   = axi_req_i.aw.prot;
    assign axi_remapped_req_o.aw.qos    = axi_req_i.aw.qos;
    assign axi_remapped_req_o.aw.region = axi_req_i.aw.region;
    assign axi_remapped_req_o.aw.user   = UserOverrideEn ? UserOverrideVal : axi_req_i.aw.user;
    assign axi_remapped_req_o.aw.atop   = axi_req_i.aw.atop;
    assign axi_remapped_req_o.aw_valid  = axi_req_i.aw_valid;
    assign axi_remapped_req_o.w.data    = axi_req_i.w.data;
    assign axi_remapped_req_o.w.strb    = axi_req_i.w.strb;
    assign axi_remapped_req_o.w.last    = axi_req_i.w.last;
    assign axi_remapped_req_o.w.user    = UserOverrideEn ? UserOverrideVal : axi_req_i.w.user;
    assign axi_remapped_req_o.w_valid   = axi_req_i.w_valid;
    assign axi_remapped_req_o.b_ready   = axi_req_i.b_ready;
    assign axi_remapped_req_o.ar.id     = axi_req_i.ar.id;
    assign axi_remapped_req_o.ar.addr   = remapped_ar_addr;
    assign axi_remapped_req_o.ar.len    = axi_req_i.ar.len;
    assign axi_remapped_req_o.ar.size   = axi_req_i.ar.size;
    assign axi_remapped_req_o.ar.burst  = axi_req_i.ar.burst;
    assign axi_remapped_req_o.ar.lock   = axi_req_i.ar.lock;
    assign axi_remapped_req_o.ar.cache  = axi_req_i.ar.cache;
    assign axi_remapped_req_o.ar.prot   = axi_req_i.ar.prot;
    assign axi_remapped_req_o.ar.qos    = axi_req_i.ar.qos;
    assign axi_remapped_req_o.ar.region = axi_req_i.ar.region;
    assign axi_remapped_req_o.ar.user   = UserOverrideEn ? UserOverrideVal : axi_req_i.ar.user;
    assign axi_remapped_req_o.ar_valid  = axi_req_i.ar_valid;
    assign axi_remapped_req_o.r_ready   = axi_req_i.r_ready;

    assign axi_resp_o.aw_ready          = axi_remapped_resp_i.aw_ready;
    assign axi_resp_o.w_ready           = axi_remapped_resp_i.w_ready;
    assign axi_resp_o.b_valid           = axi_remapped_resp_i.b_valid;
    assign axi_resp_o.b.id              = axi_remapped_resp_i.b.id;
    assign axi_resp_o.b.resp            = axi_remapped_resp_i.b.resp;
    assign axi_resp_o.b.user            = axi_remapped_resp_i.b.user;
    assign axi_resp_o.ar_ready          = axi_remapped_resp_i.ar_ready;
    assign axi_resp_o.r_valid           = axi_remapped_resp_i.r_valid;
    assign axi_resp_o.r.id              = axi_remapped_resp_i.r.id;
    assign axi_resp_o.r.data            = axi_remapped_resp_i.r.data;
    assign axi_resp_o.r.resp            = axi_remapped_resp_i.r.resp;
    assign axi_resp_o.r.last            = axi_remapped_resp_i.r.last;
    assign axi_resp_o.r.user            = axi_remapped_resp_i.r.user;

endmodule
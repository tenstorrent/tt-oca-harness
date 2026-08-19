// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------
// Local Alias Remap Interface
//
// This module translates the incoming AXI bus to a remapped address space. This can be used for
// doing local alias remapping, or global -> local address remapping.
// For example, if the local alias region is 0xC000_0000, and the remapped address base is 0x0000_0000,
// then the incoming address 0xC000_0000 will be remapped to 0x0000_0000.
//
// Copyright 2025 Tenstorrent Inc.
//------------------------------------------------------------

module axi_address_adjuster #(
    parameter type          axi_req_t               = logic,
    parameter type          axi_resp_t              = logic,

    parameter int unsigned  AXI_ADDR_WIDTH          = 32,
    parameter int unsigned  MST_BASE_ADDR           = 0
) (
    input  axi_req_t                  axi_slv_req_i,
    output axi_resp_t                 axi_slv_resp_o,

    input  logic [AXI_ADDR_WIDTH-1:0] slv_base_addr_i,

    output axi_req_t                  axi_mst_req_o,
    input  axi_resp_t                 axi_mst_resp_i
);

    // adjust amount = slv_base_addr_i - MST_BASE_ADDR (0xC000_0000 - 0x0000_0000 = 0xC000_0000)
    logic [AXI_ADDR_WIDTH-1:0] adjust_amount;
    assign adjust_amount = slv_base_addr_i - MST_BASE_ADDR;

    // Compute remapped addresses
    logic [AXI_ADDR_WIDTH-1:0] mst_aw_addr, mst_ar_addr;
    assign mst_aw_addr = axi_slv_req_i.aw.addr - adjust_amount;
    assign mst_ar_addr = axi_slv_req_i.ar.addr - adjust_amount;

    // Use axi_modify_address to properly remap addresses without multiple drivers
    axi_modify_address #(
        .slv_req_t     ( axi_req_t                  ),
        .mst_addr_t    ( logic [AXI_ADDR_WIDTH-1:0] ),
        .mst_req_t     ( axi_req_t                  ),
        .axi_resp_t    ( axi_resp_t                 )
    ) u_modify_addr (
        .slv_req_i     ( axi_slv_req_i  ),
        .slv_resp_o    ( axi_slv_resp_o ),
        .mst_aw_addr_i ( mst_aw_addr    ),
        .mst_ar_addr_i ( mst_ar_addr    ),
        .mst_req_o     ( axi_mst_req_o  ),
        .mst_resp_i    ( axi_mst_resp_i )
    );

endmodule
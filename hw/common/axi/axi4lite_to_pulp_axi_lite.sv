// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI4-Lite interface converter: AXI_LITE (deps/axi) -> axi4lite_intf (PeakRDL)
//-----------------------------------------------------------------------------


module axi4lite_to_pulp_axi_lite #(
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned ADDR_WIDTH = 32
) (
    // Source: AXI_LITE interface from deps/axi
    AXI_LITE.Slave axilite_in,

    // Destination: PeakRDL style axi4lite_intf master
    axi4lite_intf.master axi4lite_intf_out
);

    // Write address channel
    assign axi4lite_intf_out.AWVALID = axilite_in.aw_valid;
    assign axi4lite_intf_out.AWADDR  = axilite_in.aw_addr;
    assign axi4lite_intf_out.AWPROT  = axilite_in.aw_prot;
    assign axilite_in.aw_ready       = axi4lite_intf_out.AWREADY;

    // Write data channel
    assign axi4lite_intf_out.WVALID = axilite_in.w_valid;
    assign axi4lite_intf_out.WDATA  = axilite_in.w_data;
    assign axi4lite_intf_out.WSTRB  = axilite_in.w_strb;
    assign axilite_in.w_ready       = axi4lite_intf_out.WREADY;

    // Write response channel
    assign axilite_in.b_valid       = axi4lite_intf_out.BVALID;
    assign axilite_in.b_resp        = axi4lite_intf_out.BRESP;
    assign axi4lite_intf_out.BREADY = axilite_in.b_ready;

    // Read address channel
    assign axi4lite_intf_out.ARVALID = axilite_in.ar_valid;
    assign axi4lite_intf_out.ARADDR  = axilite_in.ar_addr;
    assign axi4lite_intf_out.ARPROT  = axilite_in.ar_prot;
    assign axilite_in.ar_ready       = axi4lite_intf_out.ARREADY;

    // Read data channel
    assign axilite_in.r_valid        = axi4lite_intf_out.RVALID;
    assign axilite_in.r_data         = axi4lite_intf_out.RDATA;
    assign axilite_in.r_resp         = axi4lite_intf_out.RRESP;
    assign axi4lite_intf_out.RREADY  = axilite_in.r_ready;

endmodule


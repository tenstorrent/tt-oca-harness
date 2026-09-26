// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Decode an AXI memory window and CSR port onto a simple mem_req/mem_rsp bank interface.
//
// Decodes MEM_BASE_ADDR versus CSR_BASE_ADDR on the AXI slave.
// csr_out_* forwards unclaimed CSR traffic; busy_o tracks outstanding memory ops.
// NUM_BANKS sizes split-bank configurations.

module memory_interface #(

  parameter int unsigned MEM_ADDR_WIDTH   = 0,              // Memory address width.
  parameter int unsigned MEM_DATA_WIDTH   = 0,              // Memory data width.
  parameter int unsigned MEM_ID_WIDTH     = 0,              // Memory ID width.
  parameter type mem_req_t                = logic,          // Memory request type.
  parameter type mem_rsp_t                = logic,          // Memory response type.
  parameter type mem_axi_req_t            = logic,          // AXI memory request type.
  parameter type mem_axi_resp_t           = logic,          // AXI memory response type.

  parameter int unsigned CSR_ADDR_WIDTH   = 0,              // CSR address width.
  parameter int unsigned CSR_DATA_WIDTH   = 0,              // CSR data width.
  parameter type csr_axil_req_t           = logic,          // CSR AXI-Lite request type.
  parameter type csr_axil_resp_t          = logic,          // CSR AXI-Lite response type.

  parameter logic [31:0] CSR_BASE_ADDR    = 0,              // CSR window base.
  parameter logic [31:0] MEM_BASE_ADDR    = 0,              // Memory (SRAM) window base.

  parameter int unsigned NUM_BANKS        = 1               // Number of memory banks for split banks.
) (
  input   logic                           clk_i,            // System clock.
  input   logic                           rst_ni,           // Async reset, active-low.

  input   mem_axi_req_t                   mem_axi_req_i,    // AXI memory slave request.
  output  mem_axi_resp_t                  mem_axi_resp_o,   // AXI memory slave response.

  input   csr_axil_req_t                  csr_in_axil_req_i, // Inbound CSR AXI-Lite request.
  output  csr_axil_resp_t                 csr_in_axil_resp_o, // Inbound CSR AXI-Lite response.

  output csr_axil_req_t                   csr_out_axil_req_o, // Forwarded CSR AXI-Lite request.
  input  csr_axil_resp_t                  csr_out_axil_resp_i, // Forwarded CSR AXI-Lite response.

  output mem_req_t                        mem_req_o,        // Bank memory request.
  input  mem_rsp_t                        mem_rsp_i,        // Bank memory response.
  output                                  busy_o            // Outstanding memory activity.
);

  `include "axi/typedef.svh"
  `include "ocah_assert.svh"

  ////////////////
  // Assertions //
  ////////////////

  // AXI4 Memory Interface Parameter Validation
  `OCAH_ASSERT_INIT(MemAddrWidthCheck_A, MEM_ADDR_WIDTH <= 64)
  `OCAH_ASSERT_INIT(MemDataWidthCheck_A, MEM_DATA_WIDTH inside {32, 64, 128, 256, 512, 1024})
  initial begin
    assert ($bits(mem_axi_req_i.aw.addr) == MEM_ADDR_WIDTH)
    else $error("mem_axi_req_i.aw.addr is not the correct width");
    assert ($bits(mem_axi_req_i.w.data) == MEM_DATA_WIDTH)
    else $error("mem_axi_req_i.w.data is not the correct width");
    assert ($bits(mem_axi_req_i.w.strb) == MEM_DATA_WIDTH / 8)
    else $error("mem_axi_req_i.w.strb is not the correct width");
    assert ($bits(mem_axi_req_i.aw.id) == MEM_ID_WIDTH)
    else $error("mem_axi_req_i.aw.id is not the correct width");
    assert ($bits(mem_axi_req_i.ar.id) == MEM_ID_WIDTH)
    else $error("mem_axi_req_i.ar.id is not the correct width");
    assert ($bits(mem_axi_req_i.ar.addr) == MEM_ADDR_WIDTH)
    else $error("mem_axi_req_i.ar.addr is not the correct width");
    assert ($bits(mem_axi_resp_o.b.id) == MEM_ID_WIDTH)
    else $error("mem_axi_resp_o.b.id is not the correct width");
    assert ($bits(mem_axi_resp_o.r.id) == MEM_ID_WIDTH)
    else $error("mem_axi_resp_o.r.id is not the correct width");
    assert ($bits(mem_axi_resp_o.r.data) == MEM_DATA_WIDTH)
    else $error("mem_axi_resp_o.r.data is not the correct width");
  end


  // AXI4-Lite CSR Interface Parameter Validation
  `OCAH_ASSERT_INIT(CsrAddrWidthCheck_A, CSR_ADDR_WIDTH <= 64)
  `OCAH_ASSERT_INIT(CsrDataWidthCheck_A, CSR_DATA_WIDTH inside {32, 64})
  initial begin
    assert ($bits(csr_in_axil_req_i.aw.addr) == CSR_ADDR_WIDTH)
    else $error("csr_in_axil_req_i.aw.addr is not the correct width");
    assert ($bits(csr_in_axil_req_i.w.data) == CSR_DATA_WIDTH)
    else $error("csr_in_axil_req_i.w.data is not the correct width");
    assert ($bits(csr_in_axil_req_i.w.strb) == CSR_DATA_WIDTH / 8)
    else $error("csr_in_axil_req_i.w.strb is not the correct width");
    assert ($bits(csr_in_axil_req_i.ar.addr) == CSR_ADDR_WIDTH)
    else $error("csr_in_axil_req_i.ar.addr is not the correct width");
    assert ($bits(csr_in_axil_resp_o.r.data) == CSR_DATA_WIDTH)
    else $error("csr_in_axil_resp_o.r.data is not the correct width");
    assert ($bits(csr_out_axil_resp_i.b.resp) == 2)
    else $error("csr_out_axil_resp_i.b.resp is not the correct width");
    assert ($bits(csr_out_axil_resp_i.r.resp) == 2)
    else $error("csr_out_axil_resp_i.r.resp is not the correct width");
    assert ($bits(csr_out_axil_resp_i.r.data) == CSR_DATA_WIDTH)
    else $error("csr_out_axil_resp_i.r.data is not the correct width");
    assert ($bits(csr_out_axil_req_o.aw.addr) == CSR_ADDR_WIDTH)
    else $error("csr_out_axil_req_o.aw.addr is not the correct width");
    assert ($bits(csr_out_axil_req_o.w.data) == CSR_DATA_WIDTH)
    else $error("csr_out_axil_req_o.w.data is not the correct width");
    assert ($bits(csr_out_axil_req_o.w.strb) == CSR_DATA_WIDTH / 8)
    else $error("csr_out_axil_req_o.w.strb is not the correct width");
    assert ($bits(csr_out_axil_req_o.ar.addr) == CSR_ADDR_WIDTH)
    else $error("csr_out_axil_req_o.ar.addr is not the correct width");
  end


  // General Parameter Validation
  `OCAH_ASSERT_INIT(NumBanksCheck_A, NUM_BANKS >= 1 && NUM_BANKS <= 16)
  `OCAH_ASSERT_INIT(BaseAddrAlignCheck_A, (MEM_BASE_ADDR & ((1 << $clog2(MEM_DATA_WIDTH / 8)
                    ) - 1)) == 0)
  `OCAH_ASSERT_INIT(CsrBaseAddrAlignCheck_A, (CSR_BASE_ADDR & ((1 << $clog2(CSR_DATA_WIDTH / 8)
                    ) - 1)) == 0)

  //////////////////////////////
  // AXI4 to Memory Interface //
  //////////////////////////////


  // Memory address translation - modify addresses directly in struct access
  mem_axi_req_t mem_axi_req_mem;

  // Pass through all signals but translate addresses
  always_comb begin
    mem_axi_req_mem             = mem_axi_req_i;
    mem_axi_req_mem.aw.addr     = mem_axi_req_i.aw.addr - MEM_BASE_ADDR;
    mem_axi_req_mem.ar.addr     = mem_axi_req_i.ar.addr - MEM_BASE_ADDR;
  end

  axi_to_mem #(
    .axi_req_t      (mem_axi_req_t),
    .axi_resp_t     (mem_axi_resp_t),
    .AddrWidth      (MEM_ADDR_WIDTH),
    .DataWidth      (MEM_DATA_WIDTH),
    .IdWidth        (MEM_ID_WIDTH),
    .NumBanks       (NUM_BANKS),
    .BufDepth       (1)
  ) u_axi_to_mem (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),

    .busy_o         (busy_o),

    .axi_req_i      (mem_axi_req_mem),
    .axi_resp_o     (mem_axi_resp_o),

    .mem_req_o      (mem_req_o.req),
    .mem_gnt_i      (mem_rsp_i.gnt),
    .mem_addr_o     (mem_req_o.addr),
    .mem_wdata_o    (mem_req_o.wdata),
    .mem_strb_o     (mem_req_o.strb),
    .mem_atop_o     (mem_req_o.atop),
    .mem_we_o       (mem_req_o.wenable),
    .mem_rvalid_i   (mem_rsp_i.rvalid),
    .mem_rdata_i    (mem_rsp_i.rdata)   // rdata stands for response data (not read data)
  );

  ///////////////////////////
  // CSR Port Translation //
  //////////////////////////

  // Pass through all signals but translate addresses
  always_comb begin
    csr_out_axil_req_o          = csr_in_axil_req_i;
    csr_out_axil_req_o.aw.addr  = csr_in_axil_req_i.aw.addr - CSR_BASE_ADDR;
    csr_out_axil_req_o.ar.addr  = csr_in_axil_req_i.ar.addr - CSR_BASE_ADDR;
  end

  assign csr_in_axil_resp_o = csr_out_axil_resp_i;

endmodule

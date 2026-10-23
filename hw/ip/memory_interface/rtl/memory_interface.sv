// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge an AXI memory port onto a memory macro and forward an AXI-Lite CSR port.
//
// The two ports are independent; there is no address decode between them.
// The memory port subtracts MEM_BASE_ADDR from AW and AR addresses and feeds axi_to_mem
// with a buffer depth of 1. Every request is accepted at once and the macro must return read
// data on the clock after the request; mem_req_o carries the clock the macro runs on.
// With READ_ONLY set, writes are acknowledged but never reach the macro, and mem_req_t needs
// only the clk, req and addr fields.
// The CSR port subtracts CSR_BASE_ADDR from AW and AR addresses and forwards all traffic to
// csr_out_*.
// busy_o is the axi_to_mem busy status.

module memory_interface #(

  parameter int unsigned MEM_ADDR_WIDTH   = 0,              // Memory AXI address width; at most 64.
  parameter int unsigned MEM_DATA_WIDTH   = 0,              // Memory AXI and bank data width; one
                                                            // of 32, 64, 128, 256, 512 or 1024.
  parameter int unsigned MEM_ID_WIDTH     = 0,              // Memory ID width.
  parameter type mem_req_t                = logic,          // Macro request type: clk, req and
                                                            // a word addr; we, wdata and a bit
                                                            // wmask unless READ_ONLY.
  parameter type mem_rsp_t                = logic,          // Macro response type: rdata.
  parameter bit  READ_ONLY                = 1'b0,           // Never forward writes to the macro.
  parameter type mem_axi_req_t            = logic,          // AXI memory request type.
  parameter type mem_axi_resp_t           = logic,          // AXI memory response type.

  parameter int unsigned CSR_ADDR_WIDTH   = 0,              // CSR AXI-Lite address width; at most
                                                            // 64.
  parameter int unsigned CSR_DATA_WIDTH   = 0,              // Data width of both CSR AXI-Lite
                                                            // ports; 32 or 64.
  parameter type csr_axil_req_t           = logic,          // CSR AXI-Lite request type.
  parameter type csr_axil_resp_t          = logic,          // CSR AXI-Lite response type.

  parameter logic [31:0] CSR_BASE_ADDR    = 0,              // Subtracted from CSR AW and AR
                                                            // addresses; must be aligned to
                                                            // CSR_DATA_WIDTH/8 bytes.
  parameter logic [31:0] MEM_BASE_ADDR    = 0               // Subtracted from memory AW and AR
                                                            // addresses; must be aligned to
                                                            // MEM_DATA_WIDTH/8 bytes.
) (
  input   logic                           clk_i,            // System clock.
  input   logic                           rst_ni,           // Async reset, active-low.

  input   mem_axi_req_t                   mem_axi_req_i,    // AXI memory slave request; addresses
                                                            // are offset by MEM_BASE_ADDR before
                                                            // axi_to_mem.
  output  mem_axi_resp_t                  mem_axi_resp_o,   // AXI memory slave response.

  input   csr_axil_req_t                  csr_in_axil_req_i, // Inbound CSR AXI-Lite request.
  output  csr_axil_resp_t                 csr_in_axil_resp_o, // Inbound CSR AXI-Lite response.

  output csr_axil_req_t                   csr_out_axil_req_o, // csr_in_axil_req_i with
                                                              // CSR_BASE_ADDR subtracted from the
                                                              // AW and AR addresses.
  input  csr_axil_resp_t                  csr_out_axil_resp_i, // Forwarded CSR AXI-Lite response.

  output mem_req_t                        mem_req_o,        // Macro request.
  input  mem_rsp_t                        mem_rsp_i,        // Macro read data, returned on the
                                                            // clock after mem_req_o.req.
  output                                  busy_o            // High while axi_to_mem has a
                                                            // memory-port transaction in progress.
);

  `include "axi/typedef.svh"
  `include "ocah_assert.svh"

  ////////////////
  // Assertions //
  ////////////////

  // AXI4 Memory Interface Parameter Validation
  `OCAH_ASSERT_STATIC(MemAddrWidthCheck_A, MEM_ADDR_WIDTH <= 64,
                      "MEM_ADDR_WIDTH must be at most 64")
  `OCAH_ASSERT_STATIC(MemDataWidthCheck_A, MEM_DATA_WIDTH inside {32, 64, 128, 256, 512, 1024},
                      "MEM_DATA_WIDTH must be a power of two from 32 to 1024")
  `OCAH_ASSERT_STATIC(MemAxiReqIAwAddrWidth_A, $bits(mem_axi_req_i.aw.addr) == MEM_ADDR_WIDTH,
                      "mem_axi_req_i.aw.addr is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiReqIWDataWidth_A, $bits(mem_axi_req_i.w.data) == MEM_DATA_WIDTH,
                      "mem_axi_req_i.w.data is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiReqIWStrbWidth_A, $bits(mem_axi_req_i.w.strb) == MEM_DATA_WIDTH / 8,
                      "mem_axi_req_i.w.strb is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiReqIAwIdWidth_A, $bits(mem_axi_req_i.aw.id) == MEM_ID_WIDTH,
                      "mem_axi_req_i.aw.id is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiReqIArIdWidth_A, $bits(mem_axi_req_i.ar.id) == MEM_ID_WIDTH,
                      "mem_axi_req_i.ar.id is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiReqIArAddrWidth_A, $bits(mem_axi_req_i.ar.addr) == MEM_ADDR_WIDTH,
                      "mem_axi_req_i.ar.addr is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiRespOBIdWidth_A, $bits(mem_axi_resp_o.b.id) == MEM_ID_WIDTH,
                      "mem_axi_resp_o.b.id is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiRespORIdWidth_A, $bits(mem_axi_resp_o.r.id) == MEM_ID_WIDTH,
                      "mem_axi_resp_o.r.id is not the correct width")
  `OCAH_ASSERT_STATIC(MemAxiRespORDataWidth_A, $bits(mem_axi_resp_o.r.data) == MEM_DATA_WIDTH,
                      "mem_axi_resp_o.r.data is not the correct width")


  // AXI4-Lite CSR Interface Parameter Validation
  `OCAH_ASSERT_STATIC(CsrAddrWidthCheck_A, CSR_ADDR_WIDTH <= 64,
                      "CSR_ADDR_WIDTH must be at most 64")
  `OCAH_ASSERT_STATIC(CsrDataWidthCheck_A, CSR_DATA_WIDTH inside {32, 64},
                      "CSR_DATA_WIDTH must be 32 or 64")
  `OCAH_ASSERT_STATIC(CsrInAxilReqIAwAddrWidth_A, $bits(csr_in_axil_req_i.aw.addr)
                      == CSR_ADDR_WIDTH, "csr_in_axil_req_i.aw.addr is not the correct width")
  `OCAH_ASSERT_STATIC(CsrInAxilReqIWDataWidth_A, $bits(csr_in_axil_req_i.w.data) == CSR_DATA_WIDTH,
                      "csr_in_axil_req_i.w.data is not the correct width")
  `OCAH_ASSERT_STATIC(CsrInAxilReqIWStrbWidth_A, $bits(csr_in_axil_req_i.w.strb)
                      == CSR_DATA_WIDTH / 8, "csr_in_axil_req_i.w.strb is not the correct width")
  `OCAH_ASSERT_STATIC(CsrInAxilReqIArAddrWidth_A, $bits(csr_in_axil_req_i.ar.addr)
                      == CSR_ADDR_WIDTH, "csr_in_axil_req_i.ar.addr is not the correct width")
  `OCAH_ASSERT_STATIC(CsrInAxilRespORDataWidth_A, $bits(csr_in_axil_resp_o.r.data)
                      == CSR_DATA_WIDTH, "csr_in_axil_resp_o.r.data is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilRespIBRespWidth_A, $bits(csr_out_axil_resp_i.b.resp) == 2,
                      "csr_out_axil_resp_i.b.resp is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilRespIRRespWidth_A, $bits(csr_out_axil_resp_i.r.resp) == 2,
                      "csr_out_axil_resp_i.r.resp is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilRespIRDataWidth_A, $bits(csr_out_axil_resp_i.r.data)
                      == CSR_DATA_WIDTH, "csr_out_axil_resp_i.r.data is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilReqOAwAddrWidth_A, $bits(csr_out_axil_req_o.aw.addr)
                      == CSR_ADDR_WIDTH, "csr_out_axil_req_o.aw.addr is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilReqOWDataWidth_A, $bits(csr_out_axil_req_o.w.data)
                      == CSR_DATA_WIDTH, "csr_out_axil_req_o.w.data is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilReqOWStrbWidth_A, $bits(csr_out_axil_req_o.w.strb)
                      == CSR_DATA_WIDTH / 8, "csr_out_axil_req_o.w.strb is not the correct width")
  `OCAH_ASSERT_STATIC(CsrOutAxilReqOArAddrWidth_A, $bits(csr_out_axil_req_o.ar.addr)
                      == CSR_ADDR_WIDTH, "csr_out_axil_req_o.ar.addr is not the correct width")


  // General Parameter Validation
  localparam int unsigned WordOffset = $clog2(MEM_DATA_WIDTH / 8);
  localparam int unsigned MacroAddrWidth = $bits(mem_req_o.addr);

  `OCAH_ASSERT_STATIC(MacroAddrWidthCheck_A, MacroAddrWidth + WordOffset <= MEM_ADDR_WIDTH,
                      "mem_req_o.addr is wider than the word address of the memory port")
  `OCAH_ASSERT_STATIC(MemRspRDataWidth_A, $bits(mem_rsp_i.rdata) == MEM_DATA_WIDTH,
                      "mem_rsp_i.rdata is not the correct width")
  `OCAH_ASSERT_STATIC(BaseAddrAlignCheck_A, (MEM_BASE_ADDR & ((1 << $clog2(MEM_DATA_WIDTH / 8)
                      ) - 1)) == 0, "MEM_BASE_ADDR must be aligned to the MEM_DATA_WIDTH bus width")
  `OCAH_ASSERT_STATIC(CsrBaseAddrAlignCheck_A, (CSR_BASE_ADDR & ((1 << $clog2(CSR_DATA_WIDTH / 8)
                      ) - 1)) == 0, "CSR_BASE_ADDR must be aligned to the CSR_DATA_WIDTH bus width")

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

  logic                        mem_req;
  logic                        mem_we;
  logic [MEM_ADDR_WIDTH-1:0]   mem_addr;
  logic [MEM_DATA_WIDTH-1:0]   mem_wdata;
  logic [MEM_DATA_WIDTH/8-1:0] mem_strb;
  logic                        mem_rvalid_q;

  axi_to_mem #(
    .axi_req_t      (mem_axi_req_t),
    .axi_resp_t     (mem_axi_resp_t),
    .AddrWidth      (MEM_ADDR_WIDTH),
    .DataWidth      (MEM_DATA_WIDTH),
    .IdWidth        (MEM_ID_WIDTH),
    .NumBanks       (1),
    .BufDepth       (1)
  ) u_axi_to_mem (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),

    .busy_o         (busy_o),

    .axi_req_i      (mem_axi_req_mem),
    .axi_resp_o     (mem_axi_resp_o),

    .mem_req_o      (mem_req),
    .mem_gnt_i      (1'b1),
    .mem_addr_o     (mem_addr),
    .mem_wdata_o    (mem_wdata),
    .mem_strb_o     (mem_strb),
    .mem_atop_o     (/* UNUSED */),
    .mem_we_o       (mem_we),
    .mem_rvalid_i   (mem_rvalid_q),
    .mem_rdata_i    (mem_rsp_i.rdata)
  );

  // axi_to_mem expects a response for writes as well as reads.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      mem_rvalid_q <= 1'b0;
    end else begin
      mem_rvalid_q <= mem_req;
    end
  end

  assign mem_req_o.clk  = clk_i;
  assign mem_req_o.addr = mem_addr[WordOffset +: MacroAddrWidth];

  if (READ_ONLY) begin : gen_read_only
    assign mem_req_o.req = mem_req & ~mem_we;
  end else begin : gen_read_write
    assign mem_req_o.req   = mem_req;
    assign mem_req_o.we    = mem_we;
    assign mem_req_o.wdata = mem_wdata;
    for (genvar i = 0; i < MEM_DATA_WIDTH / 8; i++) begin : gen_wmask
      assign mem_req_o.wmask[8*i+:8] = {8{mem_strb[i]}};
    end
  end

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

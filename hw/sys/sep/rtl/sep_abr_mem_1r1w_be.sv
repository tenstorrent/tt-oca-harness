// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// sep_abr_mem_1r1w_be : Adams Bridge 1R1W SRAM channel with byte enables
// -----------------------------------------------------------------------------
// Byte-enabled sibling of sep_abr_mem_1r1w, used by the two ABR memories that are
// written a dword at a time out of a wider row: sig_z_mem (160b row / 20 strobes)
// and pk_mem (320b row / 40 strobes).
//
// abr_top supplies one strobe bit per byte, while prim_ram_1r1w takes a full
// per-bit write mask and folds it down with DataBitsPerMask, so each strobe bit is
// expanded across its byte. sep_abr_mem_1r1w carries the shared rationale for
// idle-read zeroing, ReadLatency and the address range checks.

`include "prim_assert.sv"

module sep_abr_mem_1r1w_be #(
  parameter int unsigned Width       = 32,
  parameter int unsigned Depth       = 64,
  // Read latency in clocks: 1 is the bare SRAM, >1 appends (ReadLatency-1)
  // pipeline stages behind it.
  parameter int unsigned ReadLatency = 1,

  localparam int unsigned AddrWidth   = $clog2(Depth),
  localparam int unsigned StrobeWidth = Width / 8
) (
  input wire logic clk_i,
  input wire logic rst_ni,

  // Write port, one strobe bit per byte of wdata_i
  input wire logic                   we_i,
  input wire logic [AddrWidth-1:0]   waddr_i,
  input wire logic [Width-1:0]       wdata_i,
  input wire logic [StrobeWidth-1:0] wstrobe_i,

  // Read port
  input  wire logic                 re_i,
  input  wire logic [AddrWidth-1:0] raddr_i,
  output logic      [Width-1:0]     rdata_o
);

  if (ReadLatency == 0) begin : g_read_latency_check
    $error("ReadLatency must be at least 1; the SRAM read itself already costs a cycle");
  end

  if ((Width % 8) != 0) begin : g_width_byte_aligned_check
    $error("Width must be a whole number of bytes so each wstrobe_i bit covers one byte");
  end

  logic [Width-1:0] ram_wmask;
  logic [Width-1:0] ram_rdata;

  for (genvar b = 0; b < StrobeWidth; b++) begin : g_wmask
    assign ram_wmask[b*8+:8] = {8{wstrobe_i[b]}};
  end

  prim_ram_1r1w #(
    .Width           (Width),
    .Depth           (Depth),
    .DataBitsPerMask (8)
  ) u_ram (
    .clk_a_i  (clk_i),
    .clk_b_i  (clk_i),
    .rst_a_ni (rst_ni),
    .rst_b_ni (rst_ni),
    // Port A: write only
    .a_req_i  (we_i),
    .a_addr_i (waddr_i),
    .a_wdata_i(wdata_i),
    .a_wmask_i(ram_wmask),
    // Port B: read only
    .b_req_i  (re_i),
    .b_addr_i (raddr_i),
    .b_rdata_o(ram_rdata),
    .cfg_i    ('0),
    .cfg_rsp_o(/* unused */)
  );

  logic             re_q;
  logic [Width-1:0] rdata_stage1;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      re_q <= 1'b0;
    end else begin
      re_q <= re_i;
    end
  end

  assign rdata_stage1 = re_q ? ram_rdata : '0;

  if (ReadLatency == 1) begin : g_no_extra_latency
    assign rdata_o = rdata_stage1;
  end else begin : g_extra_latency
    logic [ReadLatency-1:1][Width-1:0] rdata_pipe;

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        rdata_pipe <= '0;
      end else begin
        rdata_pipe[1] <= rdata_stage1;
        for (int unsigned s = 2; s < ReadLatency; s++) begin
          rdata_pipe[s] <= rdata_pipe[s-1];
        end
      end
    end

    assign rdata_o = rdata_pipe[ReadLatency-1];
  end

  if (Depth != (1 << AddrWidth)) begin : g_addr_range_check
    localparam logic [AddrWidth-1:0] MaxAddr = AddrWidth'(Depth - 1);

    `OCAH_OT_ASSERT_NEVER(RdAddrInRange_A, re_i && (raddr_i > MaxAddr), clk_i, !rst_ni)
    `OCAH_OT_ASSERT_NEVER(WrAddrInRange_A, we_i && (waddr_i > MaxAddr), clk_i, !rst_ni)
  end

endmodule

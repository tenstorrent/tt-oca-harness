// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// sep_abr_mem_1r1w : Adams Bridge 1R1W SRAM channel (no byte enables)
// -----------------------------------------------------------------------------
// One SRAM channel of the Adams Bridge memory, built on `prim_ram_1r1w`.
//
// abr_top drives one write port and one read port per channel, never a shared
// address, so `prim_ram_1r1w` is a direct shape match: both clocks come from the
// single ABR memory clock and read data is registered, giving the one-cycle read
// latency the ABR controller schedules against. `ReadLatency` pipelines the read
// data further, so sep_crypto_pkg::SEP_CRYPTO_ABR_SRAM_LATENCY is a real knob.
//
// Around the primitive, read data is forced to zero on idle cycles and
// out-of-range addresses are flagged.

`include "prim_assert.sv"

module sep_abr_mem_1r1w #(
  parameter int unsigned Width       = 32,
  parameter int unsigned Depth       = 64,
  // Read latency in clocks: 1 is the bare SRAM, >1 appends (ReadLatency-1)
  // pipeline stages behind it.
  parameter int unsigned ReadLatency = 1,
  // Set 0 on channels where abr_ctrl is known to issue writes past the end of the
  // array.
  parameter bit          EnWriteRangeCheck = 1'b1,

  localparam int unsigned AddrWidth = $clog2(Depth)
) (
  input wire logic clk_i,
  input wire logic rst_ni,

  // Write port
  input wire logic                 we_i,
  input wire logic [AddrWidth-1:0] waddr_i,
  input wire logic [Width-1:0]     wdata_i,

  // Read port
  input  wire logic                 re_i,
  input  wire logic [AddrWidth-1:0] raddr_i,
  output logic      [Width-1:0]     rdata_o
);

  if (ReadLatency == 0) begin : g_read_latency_check
    $error("ReadLatency must be at least 1; the SRAM read itself already costs a cycle");
  end

  logic [Width-1:0] ram_rdata;

  prim_ram_1r1w #(
    .Width           (Width),
    .Depth           (Depth),
    .DataBitsPerMask (1)
  ) u_ram (
    .clk_a_i  (clk_i),
    .clk_b_i  (clk_i),
    .rst_a_ni (rst_ni),
    .rst_b_ni (rst_ni),
    // Port A: write only
    .a_req_i  (we_i),
    .a_addr_i (waddr_i),
    .a_wdata_i(wdata_i),
    .a_wmask_i({Width{1'b1}}),
    // Port B: read only
    .b_req_i  (re_i),
    .b_addr_i (raddr_i),
    .b_rdata_o(ram_rdata),
    .cfg_i    ('0),
    .cfg_rsp_o(/* unused */)
  );

  // prim_ram_1r1w holds its last read value when the read port is idle. Force the
  // data to zero instead, so a coefficient or secret-key word does not linger on
  // the bus between accesses.
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

  // Range checks only mean something for the ABR depths that are not powers of two
  // (832, 596, 224): there an address that fits in AddrWidth can still point past
  // the end of the array, and the read would return X. For the power-of-two depths
  // the comparison is constant-false, so skip it.
  if (Depth != (1 << AddrWidth)) begin : g_addr_range_check
    localparam logic [AddrWidth-1:0] MaxAddr = AddrWidth'(Depth - 1);

    `OCAH_OT_ASSERT_NEVER(RdAddrInRange_A, re_i && (raddr_i > MaxAddr), clk_i, !rst_ni)

    if (EnWriteRangeCheck) begin : g_write_range_check
      `OCAH_OT_ASSERT_NEVER(WrAddrInRange_A, we_i && (waddr_i > MaxAddr), clk_i, !rst_ni)
    end
  end

endmodule

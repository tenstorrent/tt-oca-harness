// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route an AXI-Lite port to NUM_RANGES address ranges and answer every other address with
// SLVERR.
//
// Range i holds the addresses from RANGE_BASE[i] up to, not including, RANGE_BASE[i] +
// RANGE_SIZE[i]. An access to range i leaves on mst_reqs_o[i] with its address unchanged;
// an access no range holds completes at an internal responder with SLVERR and read data 0.
// Ranges must not overlap, and each RANGE_BASE[i] is a multiple of RANGE_SIZE[i] rounded up
// to a power of two, so the low $clog2(RANGE_SIZE[i]) address bits are the offset into the
// range.
module prim_axil_addr_demux #(
  parameter int unsigned AXI_ADDR_WIDTH = 32,  // AXI-Lite address width.
  parameter int unsigned AXI_DATA_WIDTH = 32,  // AXI-Lite data width; a power of two of at
                                               // least 8.
  parameter int unsigned NUM_RANGES     = 1,   // Number of ranges; at least 1.
  parameter logic [AXI_ADDR_WIDTH-1:0] RANGE_BASE [NUM_RANGES] = '{default: '0},  // First address
                                                                                  // of each range.
  parameter logic [AXI_ADDR_WIDTH-1:0] RANGE_SIZE [NUM_RANGES] = '{default: '0},  // Range sizes in
                                                                                  // bytes; nonzero.
  parameter int unsigned MAX_TRANS      = 1,  // Outstanding transactions per channel.
  parameter type         aw_chan_t      = logic,  // AXI-Lite AW channel type.
  parameter type         w_chan_t       = logic,  // AXI-Lite W channel type.
  parameter type         b_chan_t       = logic,  // AXI-Lite B channel type.
  parameter type         ar_chan_t      = logic,  // AXI-Lite AR channel type.
  parameter type         r_chan_t       = logic,  // AXI-Lite R channel type.
  parameter type         axil_req_t     = logic,  // AXI-Lite request type.
  parameter type         axil_resp_t    = logic   // AXI-Lite response type.
) (
  input  logic                        clk_i,        // AXI-Lite clock.
  input  logic                        rst_ni,       // Asynchronous reset, active-low.
  input  logic                        test_en_i,    // DFT test mode to the demux and the
                                                    // responder.
  input  axil_req_t                   slv_req_i,    // Request from the manager.
  output axil_resp_t                  slv_resp_o,   // Response to the manager.
  output axil_req_t  [NUM_RANGES-1:0] mst_reqs_o,   // Request to each range.
  input  axil_resp_t [NUM_RANGES-1:0] mst_resps_i   // Response from each range.
);

  `include "ocah_assert.svh"

  localparam int unsigned NumPorts = NUM_RANGES + 1;
  localparam int unsigned ErrPort = NUM_RANGES;

  typedef logic [AXI_ADDR_WIDTH-1:0] addr_t;
  // One bit wider than addr_t, so the end of a range at the top of the address space does not
  // wrap to 0.
  typedef logic [AXI_ADDR_WIDTH:0] range_end_t;
  typedef logic [$clog2(NumPorts)-1:0] select_t;
  typedef struct packed {
    int unsigned idx;
    addr_t       start_addr;
    range_end_t  end_addr;
  } rule_t;

  ////////////////
  // Assertions //
  ////////////////

  `OCAH_ASSERT_STATIC(NumRangesValid_A, NUM_RANGES >= 1)

  for (genvar i = 0; i < NUM_RANGES; i++) begin : gen_range_checks
    localparam addr_t OffsetMask = (addr_t'(1) << $clog2(RANGE_SIZE[i])) - 1;

    `OCAH_ASSERT_STATIC(RangeSizeNonzero_A, RANGE_SIZE[i] != '0)
    `OCAH_ASSERT_STATIC(RangeBaseAligned_A, (RANGE_BASE[i] & OffsetMask) == '0)
    for (genvar j = i + 1; j < NUM_RANGES; j++) begin : gen_disjoint
      `OCAH_ASSERT_STATIC(RangesDisjoint_A,
                          range_end_t'(RANGE_BASE[i]) + RANGE_SIZE[i] <= RANGE_BASE[j] ||
                          range_end_t'(RANGE_BASE[j]) + RANGE_SIZE[j] <= RANGE_BASE[i])
    end
  end

  ////////////////////
  // Address Decode //
  ////////////////////

  rule_t [NUM_RANGES-1:0] addr_map;

  for (genvar i = 0; i < NUM_RANGES; i++) begin : gen_rules
    assign addr_map[i].idx        = i;
    assign addr_map[i].start_addr = RANGE_BASE[i];
    assign addr_map[i].end_addr   = range_end_t'(RANGE_BASE[i]) + RANGE_SIZE[i];
  end

  select_t aw_select, ar_select;

  addr_decode #(
    .NoIndices (NumPorts),
    .NoRules   (NUM_RANGES),
    .addr_t    (addr_t),
    .rule_t    (rule_t),
    .idx_t     (select_t)
  ) u_aw_decode (
    .addr_i           (slv_req_i.aw.addr),
    .addr_map_i       (addr_map),
    .idx_o            (aw_select),
    .dec_valid_o      (),
    .dec_error_o      (),
    .en_default_idx_i (1'b1),
    .default_idx_i    (select_t'(ErrPort))
  );

  addr_decode #(
    .NoIndices (NumPorts),
    .NoRules   (NUM_RANGES),
    .addr_t    (addr_t),
    .rule_t    (rule_t),
    .idx_t     (select_t)
  ) u_ar_decode (
    .addr_i           (slv_req_i.ar.addr),
    .addr_map_i       (addr_map),
    .idx_o            (ar_select),
    .dec_valid_o      (),
    .dec_error_o      (),
    .en_default_idx_i (1'b1),
    .default_idx_i    (select_t'(ErrPort))
  );

  ///////////
  // Demux //
  ///////////

  axil_req_t  [NumPorts-1:0] demux_reqs;
  axil_resp_t [NumPorts-1:0] demux_resps;

  axi_lite_demux #(
    .aw_chan_t   (aw_chan_t),
    .w_chan_t    (w_chan_t),
    .b_chan_t    (b_chan_t),
    .ar_chan_t   (ar_chan_t),
    .r_chan_t    (r_chan_t),
    .axi_req_t   (axil_req_t),
    .axi_resp_t  (axil_resp_t),
    .NoMstPorts  (NumPorts),
    .MaxTrans    (MAX_TRANS),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_demux (
    .clk_i,
    .rst_ni,
    .test_i          (test_en_i),
    .slv_req_i,
    .slv_aw_select_i (aw_select),
    .slv_ar_select_i (ar_select),
    .slv_resp_o,
    .mst_reqs_o      (demux_reqs),
    .mst_resps_i     (demux_resps)
  );

  assign mst_reqs_o                 = demux_reqs[NUM_RANGES-1:0];
  assign demux_resps[NUM_RANGES-1:0] = mst_resps_i;

  ////////////////////////
  // Spare-space answer //
  ////////////////////////

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH (AXI_DATA_WIDTH),
    .axil_req_t     (axil_req_t),
    .axil_resp_t    (axil_resp_t),
    .RESP           (axi_pkg::RESP_SLVERR),
    .RESP_WIDTH     (AXI_DATA_WIDTH),
    .RESP_DATA      ('0),
    .MAX_TRANS      (MAX_TRANS)
  ) u_err_slv (
    .clk_i,
    .rst_ni,
    .test_en_i,
    .axil_req_i  (demux_reqs[ErrPort]),
    .axil_resp_o (demux_resps[ErrPort])
  );

endmodule

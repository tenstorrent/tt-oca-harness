// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route an AXI-Lite port to NUM_RANGES address windows and answer every other address with
// DECERR and read data 0xBADCAB1E, as a crossbar answers an address no rule holds.
//
// Window i holds the RANGE_SIZE[i] bytes from RANGE_BASE[i]. Each RANGE_SIZE[i] is a power of
// two and each RANGE_BASE[i] a multiple of it, so a window is matched on the address bits above
// its low $clog2(RANGE_SIZE[i]) bits, which are the offset into the window. An access to window
// i leaves on mst_reqs_o[i] with its address unchanged. Windows must not overlap.
module prim_axil_addr_demux #(
  parameter int unsigned AXI_ADDR_WIDTH = 32,  // AXI-Lite address width.
  parameter int unsigned AXI_DATA_WIDTH = 32,  // AXI-Lite data width; a power of two of at
                                               // least 8.
  parameter int unsigned NUM_RANGES     = 1,   // Number of windows; at least 1.
  parameter logic [AXI_ADDR_WIDTH-1:0] RANGE_BASE [NUM_RANGES] = '{default: '0},  // First address
                                                                                  // of each window;
                                                                                  // a multiple of
                                                                                  // its size.
  parameter logic [AXI_ADDR_WIDTH-1:0] RANGE_SIZE [NUM_RANGES] = '{default: '0},  // Window sizes in
                                                                                  // bytes; each a
                                                                                  // power of two.
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
  output axil_req_t  [NUM_RANGES-1:0] mst_reqs_o,   // Request to each window.
  input  axil_resp_t [NUM_RANGES-1:0] mst_resps_i   // Response from each window.
);

  `include "ocah_assert.svh"

  localparam int unsigned NumPorts = NUM_RANGES + 1;
  localparam int unsigned ErrPort = NUM_RANGES;

  typedef logic [AXI_ADDR_WIDTH-1:0] addr_t;
  typedef logic [$clog2(NumPorts)-1:0] select_t;
  typedef struct packed {
    int unsigned idx;
    addr_t       base;
    addr_t       mask;
  } rule_t;

  ////////////////
  // Assertions //
  ////////////////

  `OCAH_ASSERT_STATIC(NumRangesValid_A, NUM_RANGES >= 1)

  for (genvar i = 0; i < NUM_RANGES; i++) begin : gen_range_checks
    `OCAH_ASSERT_STATIC(RangeSizePow2_A,
                        RANGE_SIZE[i] != '0 && (RANGE_SIZE[i] & (RANGE_SIZE[i] - 1)) == '0)
    `OCAH_ASSERT_STATIC(RangeBaseAligned_A, (RANGE_BASE[i] & (RANGE_SIZE[i] - 1)) == '0)
    for (genvar j = i + 1; j < NUM_RANGES; j++) begin : gen_disjoint
      `OCAH_ASSERT_STATIC(RangesDisjoint_A,
                          (RANGE_BASE[j] & ~(RANGE_SIZE[i] - 1)) != RANGE_BASE[i] &&
                          (RANGE_BASE[i] & ~(RANGE_SIZE[j] - 1)) != RANGE_BASE[j])
    end
  end

  ////////////////////
  // Address Decode //
  ////////////////////

  rule_t [NUM_RANGES-1:0] addr_map;

  for (genvar i = 0; i < NUM_RANGES; i++) begin : gen_rules
    assign addr_map[i].idx  = i;
    assign addr_map[i].base = RANGE_BASE[i];
    assign addr_map[i].mask = ~(RANGE_SIZE[i] - 1);
  end

  select_t aw_select, ar_select;

  addr_decode_napot #(
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

  addr_decode_napot #(
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

  ///////////////////
  // Miss response //
  ///////////////////

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH (AXI_DATA_WIDTH),
    .axil_req_t     (axil_req_t),
    .axil_resp_t    (axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .MAX_TRANS      (MAX_TRANS)
  ) u_err_slv (
    .clk_i,
    .rst_ni,
    .test_en_i,
    .axil_req_i  (demux_reqs[ErrPort]),
    .axil_resp_o (demux_resps[ErrPort])
  );

endmodule

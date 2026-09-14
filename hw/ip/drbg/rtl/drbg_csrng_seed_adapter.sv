// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// drbg_csrng_seed_adapter
//
// 32-bit entropy-word to CSRNG seed adapter for the DRBG wrapper.
//----------------------------------------------------------

/**
 * @file drbg_csrng_seed_adapter.sv
 * @brief Packs 32-bit entropy words into queued 384-bit CSRNG seeds.
 *
 * @details Uses `prim_packer_fifo` to accumulate twelve 32-bit words into one
 *          384-bit seed with the required lane mapping, then stores complete
 *          `{es_fips, es_bits}` entries in a small same-clock FIFO. The wrapped
 *          CSRNG consumes queued entries through the native
 *          `entropy_src_hw_if_req_t` / `entropy_src_hw_if_rsp_t` interface.
 *
 * @param SEED_FIFO_DEPTH Number of complete seeds that can be queued.
 */
module drbg_csrng_seed_adapter
  import drbg_pkg::*;
#(
  parameter int unsigned SEED_FIFO_DEPTH = DRBG_DEFAULT_SEED_FIFO_DEPTH
) (
  input  wire logic                               clk_i,
  input  wire logic                               rst_ni,

  input  wire logic                               csrng_word_valid_i,
  input  wire logic [31:0]                        csrng_word_data_i,
  output logic                                    csrng_word_ready_o,

  input  wire entropy_src_pkg::entropy_src_hw_if_req_t entropy_src_hw_if_req_i,
  output entropy_src_pkg::entropy_src_hw_if_rsp_t entropy_src_hw_if_rsp_o,

  output logic                                    seed_queue_valid_o,
  output logic [383:0]                            seed_queue_bits_o,
  output logic                                    seed_queue_fips_o,
  output logic                                    seed_push_o,
  output logic [4:0]                              packer_word_count_o,
  output logic [$clog2(SEED_FIFO_DEPTH + 1)-1:0]  seed_queue_depth_o
);

  `include "prim_assert.sv"

  localparam int unsigned WORD_WIDTH = 32;
  localparam int unsigned SEED_WIDTH = entropy_src_pkg::CSRNG_BUS_WIDTH;
  localparam int unsigned FIPS_WIDTH = entropy_src_pkg::FIPS_BUS_WIDTH;
  localparam int unsigned SEED_FIFO_WIDTH = SEED_WIDTH + FIPS_WIDTH;

  logic                  packer_rvalid;
  logic [SEED_WIDTH-1:0] packer_rdata;

  logic                  seed_fifo_wready;
  logic [SEED_FIFO_WIDTH-1:0] seed_fifo_rdata;
  logic                  seed_fifo_full;
  logic                  seed_fifo_err;

  prim_packer_fifo #(
    .InW        (WORD_WIDTH),
    .OutW       (SEED_WIDTH),
    .ClearOnRead(1'b1)
  ) u_seed_packer (
    .clk_i    (clk_i),
    .rst_ni   (rst_ni),
    .clr_i    (1'b0),
    .wvalid_i (csrng_word_valid_i),
    .wdata_i  (csrng_word_data_i),
    .wready_o (csrng_word_ready_o),
    .rvalid_o (packer_rvalid),
    .rdata_o  (packer_rdata),
    .rready_i (seed_fifo_wready),
    .depth_o  (packer_word_count_o)
  );

  assign seed_push_o = packer_rvalid && seed_fifo_wready;

  prim_fifo_sync #(
    .Width            (SEED_FIFO_WIDTH),
    .Pass             (1'b0),
    .Depth            (SEED_FIFO_DEPTH),
    .OutputZeroIfEmpty(1'b1)
  ) u_seed_fifo (
    .clk_i    (clk_i),
    .rst_ni   (rst_ni),
    .clr_i    (1'b0),
    .wvalid_i (packer_rvalid),
    .wready_o (seed_fifo_wready),
    .wdata_i  ({DRBG_CSRNG_SEED_FIPS_PROVISIONAL, packer_rdata}),
    .rvalid_o (seed_queue_valid_o),
    .rready_i (entropy_src_hw_if_req_i.es_req && seed_queue_valid_o),
    .rdata_o  (seed_fifo_rdata),
    .full_o   (seed_fifo_full),
    .depth_o  (seed_queue_depth_o),
    .err_o    (seed_fifo_err)
  );

  assign seed_queue_fips_o = seed_fifo_rdata[SEED_FIFO_WIDTH-1];
  assign seed_queue_bits_o = seed_fifo_rdata[SEED_WIDTH-1:0];

  assign entropy_src_hw_if_rsp_o.es_ack = seed_queue_valid_o && entropy_src_hw_if_req_i.es_req;
  assign entropy_src_hw_if_rsp_o.es_bits = seed_queue_bits_o;
  assign entropy_src_hw_if_rsp_o.es_fips = seed_queue_fips_o;

  // =========================================================================
  // Assertions
  // =========================================================================

  `OCAH_OT_ASSERT_INIT(SeedFifoDepthValid_A, SEED_FIFO_DEPTH > 0)
  `OCAH_OT_ASSERT(EsAckRequiresSeed_A, entropy_src_hw_if_rsp_o.es_ack |-> seed_queue_valid_o)
  `OCAH_OT_ASSERT(
      SeedFipsPolicy_A,
      seed_queue_valid_o |-> entropy_src_hw_if_rsp_o.es_fips == DRBG_CSRNG_SEED_FIPS_PROVISIONAL)
  `OCAH_OT_ASSERT(SeedPushRequiresPackedSeed_A, seed_push_o |-> packer_rvalid)
  `OCAH_OT_ASSERT(SeedAckRequiresRequest_A,
                  entropy_src_hw_if_rsp_o.es_ack |-> entropy_src_hw_if_req_i.es_req)
  `OCAH_OT_ASSERT(SeedQueueStableWhenWaiting_A,
                  seed_queue_valid_o && !entropy_src_hw_if_req_i.es_req |=> $stable
                  (seed_queue_bits_o))

  `OCAH_OT_ASSERT_KNOWN(CsrngWordReadyKnown_A, csrng_word_ready_o)
  `OCAH_OT_ASSERT_KNOWN(EsAckKnown_A, entropy_src_hw_if_rsp_o.es_ack)
  `OCAH_OT_ASSERT_KNOWN_IF(EsBitsKnown_A, entropy_src_hw_if_rsp_o.es_bits, seed_queue_valid_o)
  `OCAH_OT_ASSERT_KNOWN_IF(EsFipsKnown_A, entropy_src_hw_if_rsp_o.es_fips, seed_queue_valid_o)
  `OCAH_OT_ASSERT_KNOWN(SeedQueueValidKnown_A, seed_queue_valid_o)
  `OCAH_OT_ASSERT_KNOWN_IF(SeedQueueBitsKnown_A, seed_queue_bits_o, seed_queue_valid_o)
  `OCAH_OT_ASSERT_KNOWN_IF(SeedQueueFipsKnown_A, seed_queue_fips_o, seed_queue_valid_o)
  `OCAH_OT_ASSERT_KNOWN(PackerWordCountKnown_A, packer_word_count_o)
  `OCAH_OT_ASSERT_KNOWN(SeedQueueDepthKnown_A, seed_queue_depth_o)
  `OCAH_OT_ASSERT(SeedFifoHealthy_A, !seed_fifo_err)
  `OCAH_OT_ASSERT(SeedFifoNotWrittenWhenFull_A, packer_rvalid && seed_fifo_full |-> !seed_push_o)

endmodule : drbg_csrng_seed_adapter

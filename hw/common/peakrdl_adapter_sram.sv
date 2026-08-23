// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// PeakRDL External RAM adapter for prim_ram_1p-like devices
//
// This module bridges between a prim_ram_1p interface and PeakRDL-generated
// external RAM interfaces. It provides key features from tlul_adapter_sram:
//
// - Error detection and reporting
// - Optional ECC encoding/decoding with pipeline support for timing
// - Optional partial write rejection (maintains protocol compliance)
//
// Assumes:
// - PeakRDL interface uses byte addresses, SRAM interface expects word addresses
// - Transactions are constrained to SRAM word size (can be equal or smaller)
// - No overlapping transactions (each transaction completes before the next starts)
// - 1 bus transaction is always word-aligned
// - No transaction splitting across multiple SRAM accesses
// - ram_gnt_i is hardwired from ram_req_o (valid for OTBN instance but may not be valid for other instances)
//
// TODO:
// - woffset FIFO integrity

`include "prim_assert.sv"
module peakrdl_adapter_sram
  import prim_mubi_pkg::mubi4_t;
  import prim_ram_1p_pkg::*;
  import prim_util_pkg::*;
#(
  parameter int SramAw            = 12,  // SRAM address width
  parameter int SramDw            = 32,  // SRAM data width (must be multiple of 8)
  parameter int PeakRdlAw         = 12,  // PeakRDL interface address width
  parameter int PeakRdlDw         = 32,  // PeakRDL interface data width

  parameter bit EnableECC         = 0,   // Enable ECC protection (16→22, 32→39 bit conversion)
  parameter bit HammingECC        = 0,   // 0: Use Hsiao ECC (default), 1: Use Hamming ECC
  parameter bit EnableEccPipeline = 0,   // 1: Pipeline ECC encoding (write) and decoding (read) for timing
  parameter bit RejectPartialWrites = 0,  // 1: Reject partial writes (wr_biten != all ones), 0: Allow all writes
  parameter bit SecFifoPtr        = 0,  // 1: Duplicated fifo pointers

      // Width adaptation calculations
  // ECC adds bits: 16→22 (adds 6), 32→39 (adds 7)
  localparam int PeakRdlEccDw     = EnableECC ? (PeakRdlDw == 16 ? 22 :
                                                 PeakRdlDw == 32 ? 39 : PeakRdlDw) : PeakRdlDw,
  // Width multiplier: number of PeakRDL words that fit in SRAM word
  localparam int WidthMult        = SramDw / PeakRdlDw,
  // Calculate total SRAM ECC width
  localparam int SramEccDw        = EnableECC ? (WidthMult * PeakRdlEccDw) : SramDw,

  // Address offset calculation (broken down for clarity)
  localparam int BytesPerSramWord = SramDw / 8,                    // Bytes in one SRAM word
  localparam int ByteOffsetWidth  = $clog2(BytesPerSramWord),      // Bits for byte offset within SRAM word
  localparam int WordOffsetWidth  = (WidthMult > 1) ? $clog2(WidthMult) : 0,  // Bits for PeakRDL word offset
  localparam int AddrOffsetWidth  = ByteOffsetWidth + WordOffsetWidth          // Total offset bits to strip
) (
  input   clk_i,
  input   rst_ni,

  // prim_ram_1p interface (drives memory)
  output logic                    ram_req_o,
  output logic                    ram_write_o,
  output logic [SramAw-1:0]       ram_addr_o,
  output logic [SramEccDw-1:0]    ram_wdata_o,
  output logic [SramEccDw-1:0]    ram_wmask_o,
  input  logic [SramEccDw-1:0]    ram_rdata_i,
  input  logic                    ram_rvalid_i,
  input  logic                    ram_gnt_i,

  // PeakRDL external RAM interface (master side - receives requests)
  input  logic                        peakrdl_req_i,
  input  logic [PeakRdlAw-1:0]        peakrdl_addr_i,
  input  logic                        peakrdl_req_is_wr_i,
  input  logic [PeakRdlDw-1:0]        peakrdl_wr_data_i,
  input  logic [PeakRdlDw-1:0]        peakrdl_wr_biten_i,
  output logic                        peakrdl_rd_ack_o,
  output logic [PeakRdlDw-1:0]        peakrdl_rd_data_o,
  output logic                        peakrdl_rd_err_o,
  output logic                        peakrdl_wr_ack_o,
  output logic                        peakrdl_wr_err_o,

  // Control and status
  output logic                     intg_error_o,
  input  logic                     wr_collision_i,
  input  logic                     write_pending_i
);

  // Parameter validation
  `OCAH_OT_ASSERT_INIT(SramDwByteGranularity_A, SramDw % 8 == 0)
  `OCAH_OT_ASSERT_INIT(PeakRdlDwByteGranularity_A, PeakRdlDw % 8 == 0)
  `OCAH_OT_ASSERT_INIT(SramAwWidth_A, SramAw <= PeakRdlAw)

  // Internal signals
  logic [1:0] ecc_read_error;
  logic read_req_fifo_error;

  // Permanently latch ECC errors until reset
  logic intg_error_q, intg_error_d;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      intg_error_q <= '0;
    end else if (intg_error_d) begin
      intg_error_q <= 1'b1;
    end
  end

  // Integrity error output is permanent and should be used for alert generation
  // or other downstream effects
  assign intg_error_d = ecc_read_error[1] || read_req_fifo_error;
  assign intg_error_o = intg_error_d || intg_error_q;

  // =========================================================================
  // Width calculations and offset parameters
  // =========================================================================

  // Word offset within SRAM word (for width adaptation only)
  // Extract only the width adaptation bits, skipping byte offset bits
  localparam int WoffsetDeclWidth = (WidthMult > 1) ? WordOffsetWidth : 1;  // Avoid [-1:0] when WordOffsetWidth=0

  // =========================================================================
  // FIFO Structure (following OpenTitan tlul_adapter_sram pattern)
  // =========================================================================

  // Simple FIFO to track woffset for read operations
  typedef struct packed {
    logic [WoffsetDeclWidth-1:0] woffset; // Offset of the PeakRDL word within the SRAM word
  } read_req_t;

  localparam int ReadReqFifoWidth = $bits(read_req_t);

  // Read request FIFO signals
  logic read_req_fifo_wvalid, read_req_fifo_wready;
  logic read_req_fifo_rvalid, read_req_fifo_rready;
  logic read_req_fifo_full;
  read_req_t read_req_fifo_wdata, read_req_fifo_rdata;

  // Current request woffset calculation
  logic [WoffsetDeclWidth-1:0] woffset;
  if (WidthMult > 1) begin : gen_wordwidthadapt
    // Extract word offset: which PeakRDL word within the SRAM word
    // PeakRDL provides byte addresses, so convert to word address first, then extract word offset
    localparam int PeakRdlByteOffsetWidth = $clog2(PeakRdlDw/8);
    // Convert byte address to PeakRDL word address, then take lower WordOffsetWidth bits
    assign woffset = peakrdl_addr_i[PeakRdlByteOffsetWidth +: WordOffsetWidth];
  end else begin : gen_no_wordwidthadapt
    // When WidthMult=1, no width adaptation needed - always select element 0
    assign woffset = 1'b0;
  end

  // Partial write rejection logic (needed for FIFO population)
  logic partial_write;
  assign partial_write = RejectPartialWrites & peakrdl_req_i & peakrdl_req_is_wr_i &
                        (peakrdl_wr_biten_i != {PeakRdlDw{1'b1}});

  // =========================================================================
  // Simple Read Request Tracking
  // =========================================================================

  // Read request FIFO: Store woffset for read operations only
  // logic read_req_ack;
  // assign read_req_ack = peakrdl_req_i & ~peakrdl_req_is_wr_i & read_req_fifo_wready;
  // assign read_req_fifo_wvalid = read_req_ack;  // Push only for valid reads that can be accepted
  assign read_req_fifo_wvalid = peakrdl_req_i & ram_gnt_i & ~peakrdl_req_is_wr_i & read_req_fifo_wready;  // Push only for valid reads that can be accepted
  assign read_req_fifo_wdata = '{
    woffset: woffset
  };
  assign read_req_fifo_rready = ram_rvalid_i;  // Pop when SRAM read data returns

  // =========================================================================
  // SRAM Interface Generation
  // =========================================================================

  // SRAM request generation with ECC pipeline consideration
  logic read_req_ok;
  assign read_req_ok = peakrdl_req_is_wr_i | read_req_fifo_wready;  // Write OK always, Read OK when FIFO ready

  // Combinatorial request signals
  logic ram_req_comb, ram_write_comb;
  logic [SramAw-1:0] ram_addr_comb;
  assign ram_req_comb   = peakrdl_req_i & ~partial_write & read_req_ok;
  assign ram_write_comb = peakrdl_req_i & peakrdl_req_is_wr_i & ~partial_write;
  assign ram_addr_comb  = peakrdl_addr_i[PeakRdlAw-1:ByteOffsetWidth];

  // Pipeline SRAM request signals when ECC pipeline is enabled for writes
  if (EnableEccPipeline && EnableECC) begin : gen_sram_req_pipeline
    logic ram_req_q, ram_write_q;
    logic [SramAw-1:0] ram_addr_q;

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        ram_req_q <= 1'b0;
        ram_write_q <= 1'b0;
        ram_addr_q <= '0;
      end else begin
        // Pipeline write requests to align with ECC-encoded data
        ram_req_q <= ram_req_comb & ram_write_comb;  // Only pipeline write requests
        ram_write_q <= ram_write_comb;
        ram_addr_q <= ram_addr_comb;
      end
    end

    // Output mux: pipelined for writes, immediate for reads
    assign ram_req_o   = ram_write_q ? ram_req_q : (ram_req_comb & ~ram_write_comb);  // Pipelined writes OR immediate reads
    assign ram_write_o = ram_write_q;  // Always use pipelined write signal
    assign ram_addr_o  = ram_write_q ? ram_addr_q : ram_addr_comb;  // Pipelined addr for writes, immediate for reads

  end else begin : gen_no_sram_req_pipeline
    // No ECC pipeline: direct connection
    assign ram_req_o   = ram_req_comb;
    assign ram_write_o = ram_write_comb;
    assign ram_addr_o  = ram_addr_comb;
  end

  // Combined wmask / wdata arrays for width adaptation
  logic [WidthMult-1:0][PeakRdlEccDw-1:0] wmask_combined;
  logic [WidthMult-1:0][PeakRdlEccDw-1:0] wdata_combined;

  // ECC-protected data (after encoding)
  logic [PeakRdlEccDw-1:0] peakrdl_wdata_ecc_comb;
  logic [PeakRdlEccDw-1:0] peakrdl_wmask_ecc_comb;

  // Pipeline registers for write-side ECC encoding (when EnableEccPipeline=1)
  logic [PeakRdlEccDw-1:0] peakrdl_wdata_ecc_q;
  logic [PeakRdlEccDw-1:0] peakrdl_wmask_ecc_q;
  logic [PeakRdlEccDw-1:0] peakrdl_wdata_ecc;
  logic [PeakRdlEccDw-1:0] peakrdl_wmask_ecc;

  // ECC encoder for write data
  if (EnableECC) begin : gen_ecc_enc

    // Check supported widths (same as prim_ram_1p_adv)
    `OCAH_OT_ASSERT_INIT(SecDecWidth_A, PeakRdlDw inside {16, 32})

    if (PeakRdlDw == 16) begin : gen_secded_22_16
      if (HammingECC) begin : gen_hamming
        prim_secded_inv_hamming_22_16_enc u_enc (
          .data_i(peakrdl_wr_data_i),
          .data_o(peakrdl_wdata_ecc_comb)
        );
      end else begin : gen_hsiao
        prim_secded_inv_22_16_enc u_enc (
          .data_i(peakrdl_wr_data_i),
          .data_o(peakrdl_wdata_ecc_comb)
        );
      end
    end else if (PeakRdlDw == 32) begin : gen_secded_39_32
      if (HammingECC) begin : gen_hamming
        prim_secded_inv_hamming_39_32_enc u_enc (
          .data_i(peakrdl_wr_data_i),
          .data_o(peakrdl_wdata_ecc_comb)
        );
      end else begin : gen_hsiao
        prim_secded_inv_39_32_enc u_enc (
          .data_i(peakrdl_wr_data_i),
          .data_o(peakrdl_wdata_ecc_comb)
        );
      end
    end

    // ECC mask is all 1s only when ALL byte enables are set (ECC requires full word writes)
    logic full_word_write;
    assign full_word_write = (peakrdl_wr_biten_i == {PeakRdlDw{1'b1}});
    assign peakrdl_wmask_ecc_comb = {PeakRdlEccDw{full_word_write}};
  end else begin : gen_no_ecc_enc
    // No ECC: pass through data and bit mask directly
    assign peakrdl_wdata_ecc_comb = peakrdl_wr_data_i;
    assign peakrdl_wmask_ecc_comb = peakrdl_wr_biten_i;
  end

  // Pipeline stage for ECC encoder (write path)
  if (EnableEccPipeline && EnableECC) begin : gen_ecc_write_pipeline
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        peakrdl_wdata_ecc_q <= '0;
        peakrdl_wmask_ecc_q <= '0;
      end else begin
        peakrdl_wdata_ecc_q <= peakrdl_wdata_ecc_comb;
        peakrdl_wmask_ecc_q <= peakrdl_wmask_ecc_comb;
      end
    end
    assign peakrdl_wdata_ecc = peakrdl_wdata_ecc_q;
    assign peakrdl_wmask_ecc = peakrdl_wmask_ecc_q;
  end else begin : gen_no_ecc_write_pipeline
    assign peakrdl_wdata_ecc = peakrdl_wdata_ecc_comb;
    assign peakrdl_wmask_ecc = peakrdl_wmask_ecc_comb;
  end

  // PeakRDL data/mask arrays (now using ECC-protected widths)
  logic [WidthMult-1:0][PeakRdlEccDw-1:0] wmask_peakrdl;
  logic [WidthMult-1:0][PeakRdlEccDw-1:0] wdata_peakrdl;

  always_comb begin
    wmask_peakrdl = '0;
    wdata_peakrdl = '0;

    if (peakrdl_req_i && peakrdl_req_is_wr_i) begin
      // Use current woffset for write operations (using pipelined ECC signals)
      wmask_peakrdl[woffset] = peakrdl_wmask_ecc;
      wdata_peakrdl[woffset] = peakrdl_wdata_ecc;
    end
  end

  for (genvar i = 0; i < WidthMult; i++) begin : gen_write_output
    assign wmask_combined[i] = wmask_peakrdl[i];
    assign wdata_combined[i] = wdata_peakrdl[i];
  end

  assign ram_wmask_o = wmask_combined;
  assign ram_wdata_o = wdata_combined;

  // =========================================================================
  // Read Data Handling with FIFO-stored woffset
  // =========================================================================

  // Read data handling with word selection for wider SRAM
  // Use the woffset stored in sramreqfifo (not current woffset!)
  logic [WidthMult-1:0][PeakRdlEccDw-1:0] rdata_reshaped;
  logic [PeakRdlEccDw-1:0] rdata_peakrdlword_ecc;

  // This just changes the array format so that the correct word can be selected by indexing.
  assign rdata_reshaped = ram_rdata_i;

  // CRITICAL FIX: Use stored woffset from read request FIFO, not current woffset
  assign rdata_peakrdlword_ecc = rdata_reshaped[read_req_fifo_rdata.woffset];

  // ECC decoder for read data with optional pipeline
  logic [PeakRdlEccDw-1:0] rdata_peakrdlword_ecc_q;
  logic [PeakRdlDw-1:0] rdata_peakrdlword_comb, rdata_peakrdlword;
  logic [1:0] ecc_read_error_comb;

  // Pipeline stage for ECC decoder (read path)
  if (EnableEccPipeline && EnableECC) begin : gen_ecc_read_pipeline
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        rdata_peakrdlword_ecc_q <= '0;
        rdata_peakrdlword <= '0;
        ecc_read_error <= '0;
      end else begin
        rdata_peakrdlword_ecc_q <= rdata_peakrdlword_ecc;
        rdata_peakrdlword <= rdata_peakrdlword_comb;
        ecc_read_error <= ecc_read_error_comb;
      end
    end
  end else begin : gen_no_ecc_read_pipeline
    assign rdata_peakrdlword_ecc_q = rdata_peakrdlword_ecc;
    assign rdata_peakrdlword = rdata_peakrdlword_comb;
    assign ecc_read_error = ecc_read_error_comb;
  end

  if (EnableECC) begin : gen_ecc_dec
    if (PeakRdlDw == 16) begin : gen_secded_22_16
      if (HammingECC) begin : gen_hamming
        prim_secded_inv_hamming_22_16_dec u_dec (
          .data_i     (rdata_peakrdlword_ecc_q),
          .data_o     (rdata_peakrdlword_comb),
          .syndrome_o ( ),  // Not used
          .err_o      (ecc_read_error_comb)
        );
      end else begin : gen_hsiao
        prim_secded_inv_22_16_dec u_dec (
          .data_i     (rdata_peakrdlword_ecc_q),
          .data_o     (rdata_peakrdlword_comb),
          .syndrome_o ( ),  // Not used
          .err_o      (ecc_read_error_comb)
        );
      end
    end else if (PeakRdlDw == 32) begin : gen_secded_39_32
      if (HammingECC) begin : gen_hamming
        prim_secded_inv_hamming_39_32_dec u_dec (
          .data_i     (rdata_peakrdlword_ecc_q),
          .data_o     (rdata_peakrdlword_comb),
          .syndrome_o ( ),  // Not used
          .err_o      (ecc_read_error_comb)
        );
      end else begin : gen_hsiao
        prim_secded_inv_39_32_dec u_dec (
          .data_i     (rdata_peakrdlword_ecc_q),
          .data_o     (rdata_peakrdlword_comb),
          .syndrome_o ( ),  // Not used
          .err_o      (ecc_read_error_comb)
        );
      end
    end
  end else begin : gen_no_ecc_dec
    assign rdata_peakrdlword_comb = rdata_peakrdlword_ecc_q[PeakRdlDw-1:0];
    assign ecc_read_error_comb = 2'b00;
  end

  // Note: rdata_peakrdlword is used directly in peakrdl_rd_data_o output

  // =========================================================================
  // Read Request FIFO Instantiation
  // =========================================================================

  // Simple FIFO to track woffset for read operations
  prim_fifo_sync #(
    .Width(ReadReqFifoWidth),
    .Pass(1'b0),
    // .Depth(2),  // Small depth for outstanding reads
    .Depth(1),  // We only need to store 1 woffset value, PeakRDL will not issue pipelined transactions
    .NeverClears(1'b1),
    .Secure(SecFifoPtr)
  ) u_read_req_fifo (
    .clk_i,
    .rst_ni,
    .clr_i(1'b0),
    .wvalid_i(read_req_fifo_wvalid),
    .wready_o(read_req_fifo_wready),
    .wdata_i(read_req_fifo_wdata),
    .rvalid_o(read_req_fifo_rvalid),
    .rready_i(read_req_fifo_rready),
    .rdata_o(read_req_fifo_rdata),
    .full_o(read_req_fifo_full),
    .depth_o(),
    .err_o(read_req_fifo_error)
  );

  // =========================================================================
  // PeakRDL Interface Outputs (Direct/Immediate)
  // =========================================================================

  // Write acknowledgment and error: timing depends on ECC pipeline
  // Always acknowledge write requests for protocol compliance, even if rejected due to partial writes
  assign peakrdl_wr_ack_o = peakrdl_req_i & peakrdl_req_is_wr_i;  // Acknowledge all write requests immediately

  // Write error signal - pipeline when ECC pipeline is enabled
  if (EnableEccPipeline && EnableECC) begin : gen_wr_err_pipeline
    logic peakrdl_wr_err_q;
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        peakrdl_wr_err_q <= 1'b0;
      end else begin
        peakrdl_wr_err_q <= RejectPartialWrites & partial_write & peakrdl_req_i & peakrdl_req_is_wr_i;
      end
    end
    assign peakrdl_wr_err_o = peakrdl_wr_err_q;
  end else begin : gen_no_wr_err_pipeline
    assign peakrdl_wr_err_o = RejectPartialWrites & partial_write & peakrdl_req_i & peakrdl_req_is_wr_i;
  end

  // Read acknowledgment and data: immediate when SRAM returns read data
  assign peakrdl_rd_ack_o = ram_rvalid_i;
  assign peakrdl_rd_err_o = 1'b0;  // ECC errors handled via intg_error_o, not bus errors
  assign peakrdl_rd_data_o = ram_rvalid_i ? rdata_peakrdlword : '0;

  // Unused signals
  logic unused_collision;
  assign unused_collision = wr_collision_i | write_pending_i;

  // This module only cares about uncorrectable errors.
  logic unused_rerror;
  assign unused_rerror = ecc_read_error[0];  // Correctable ECC errors not used

  // Simple FIFO-based design: 1 FIFO to track woffset for reads
  // FIXME: These assertions were autogen'd, they might be wrong

  // Basic parameter validation
  `OCAH_OT_ASSERT_INIT(SramDwHasByteGranularity_A, SramDw % 8 == 0)
  `OCAH_OT_ASSERT_INIT(SramDwIsMultipleOfPeakRdlWidth_A, SramDw % PeakRdlDw == 0)
  `OCAH_OT_ASSERT_INIT(PeakRdlDwHasByteGranularity_A, PeakRdlDw % 8 == 0)

  // Ensure PeakRDL address width can provide SRAM address + all offset bits
  `OCAH_OT_ASSERT_INIT(AddressWidthSufficient_A, PeakRdlAw >= ByteOffsetWidth + SramAw)

  // ECC parameter validation
  `OCAH_OT_ASSERT_INIT(EccSupportedWidth_A, !EnableECC || PeakRdlDw inside {16, 32})
  `OCAH_OT_ASSERT_INIT(EccSramWidthMultiple_A, !EnableECC || SramEccDw % PeakRdlEccDw == 0)

  // Pipeline parameter validation
  `OCAH_OT_ASSERT_INIT(EccPipelineRequiresEcc_A, !EnableEccPipeline || EnableECC)

  // Partial write rejection parameter validation
  `OCAH_OT_ASSERT_INIT(PartialWriteRejectWithEccIsConsistent_A, !(EnableECC && !RejectPartialWrites))

  // ECC requires full word writes only for actual SRAM access (partial writes may be filtered out)
  `OCAH_OT_ASSERT(OnlyWordWritePossibleWithEcc_A, !(EnableECC && ram_req_o && ram_write_o) ||
          peakrdl_wr_biten_i == {PeakRdlDw{1'b1}})

  // Simple response assertions
  // Write acknowledgment should be asserted for all write requests (not tied to SRAM grant)
  // if (EnableEccPipeline && EnableECC) begin : gen_wr_ack_assert_pipeline
  //   `OCAH_OT_ASSERT(WrAckPipelined_A, peakrdl_wr_ack_o == gen_wr_ack_pipeline.peakrdl_wr_ack_q)
  // end else begin : gen_wr_ack_assert_immediate
  //   `OCAH_OT_ASSERT(WrAckImmediate_A, peakrdl_wr_ack_o == (peakrdl_req_i & peakrdl_req_is_wr_i))
  // end
  `OCAH_OT_ASSERT(RdAckWithSramValid_A, peakrdl_rd_ack_o -> ram_rvalid_i)

  // The read request FIFO must always be ready to accept writes, since the PeakRDL interface has no backpressure
  // NOTE: PeakRDL will not issue pipelined transactions, so we don't need to worry about FIFO overflow
  // (https://peakrdl-regblock.readthedocs.io/en/latest/rdl_features/external.html)
  // `OCAH_OT_ASSERT(ReadReqFifoWreadyAlwaysHigh_A, read_req_fifo_wready)
  // `OCAH_OT_ASSERT(NoReadFifoOverflow_A, !(read_req_fifo_full & peakrdl_req_i & ~peakrdl_req_is_wr_i),
  //         "Read request FIFO is full but new PeakRDL read request received - potential overflow!")

  // Make sure outputs are defined
  `OCAH_OT_ASSERT_KNOWN(RamReqKnown_A, ram_req_o)
  `OCAH_OT_ASSERT_KNOWN(RamAddrKnown_A, ram_addr_o)
  `OCAH_OT_ASSERT_KNOWN(RamWriteKnown_A, ram_write_o)
  `OCAH_OT_ASSERT_KNOWN(RamWdataKnown_A, ram_wdata_o)
  `OCAH_OT_ASSERT_KNOWN(RamWmaskKnown_A, ram_wmask_o)
  `OCAH_OT_ASSERT_KNOWN(PeakRdlRdAckKnown_A, peakrdl_rd_ack_o)
  `OCAH_OT_ASSERT_KNOWN(PeakRdlWrAckKnown_A, peakrdl_wr_ack_o)
  `OCAH_OT_ASSERT_KNOWN(PeakRdlRdDataKnown_A, peakrdl_rd_data_o)
  `OCAH_OT_ASSERT_KNOWN(PeakRdlRdErrKnown_A, peakrdl_rd_err_o)
  `OCAH_OT_ASSERT_KNOWN(PeakRdlWrErrKnown_A, peakrdl_wr_err_o)

endmodule

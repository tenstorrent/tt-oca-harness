// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Adapt the PicoRV32 native memory interface to the SRAM with scrambling, parity and
// write-lock support.
//
// Bridges the PicoRV32 native memory interface to the standard SRAM memory interface
// (km_sram_mem_req_t / km_sram_mem_rsp_t).
//
// Features:
//
// - Optional address/data scrambling via scrambler_8192x32, controlled by
//   scrambler_key_i / scrambler_en_i from KMCSR.
// - Odd-parity generation on the write path and checking on the read path; parity is
//   computed before scrambling.
// - Per-region write-lock (SramLockRegionBytes per region, so SRAM_NUM_LOCK_REGIONS is
//   SramSizeBytes / SramLockRegionBytes): writes to a locked region are silently
//   dropped but still acknowledged, and write_lock_violation_region_o reports to KMCSR
//   which region had an attempted write while locked.
// - Requests are held off for two cycles after reset release.
// - PicoRV32 look-ahead prefetch support for pipelined SRAM.
//
// The SRAM must return rvalid at least one cycle after accepting a read: the response is
// descrambled and parity-checked with the address and strobes captured at the accept.

module km_sram_interface
  import km_intf_pkg::KM_SRAM_MEM_ADDR_WIDTH;
  import km_intf_pkg::km_sram_mem_req_t;
  import km_intf_pkg::km_sram_mem_rsp_t;
  import km_intf_pkg::KM_MEM_DATA_WIDTH;
#(
  parameter int unsigned SRAM_ADDR_WIDTH = KM_SRAM_MEM_ADDR_WIDTH,                   // SRAM word-address width;
                                                                                     // must be 13 to match
                                                                                     // scrambler_8192x32.
  parameter int unsigned SRAM_NUM_LOCK_REGIONS = km_intf_pkg::SramNumLockRegions     // Number of write-lock regions,
                                                                                     // each SramLockRegionBytes
                                                                                     // long.
) (
  input  logic clk_i,   // System clock.
  input  logic rst_ni,  // Active-low asynchronous reset.

  input  logic        mem_valid_i,  // PicoRV32 native memory request valid (from CPU).
  output logic        mem_ready_o,  // Memory ready: read data valid, write granted, or write to a
                                    // locked region dropped.
  input  logic [31:0] mem_addr_i,   // Byte address.
  input  logic [31:0] mem_wdata_i,  // Write data.
  input  logic [3:0]  mem_wstrb_i,  // Write strobe (non-zero = write).
  input  logic [3:0]  mem_rstrb_i,  // Read strobe: byte lanes consumed by the CPU, which select the
                                    // parity-checked lanes.
  output logic [31:0] mem_rdata_o,  // Read data.

  input  logic        mem_la_read_i,   // Look-ahead read signal (1 cycle before mem_valid).
  input  logic [31:0] mem_la_addr_i,   // Look-ahead address.
  input  logic [3:0]  mem_la_rstrb_i,  // Look-ahead read strobe; selects the parity-checked lanes
                                       // of a look-ahead fetch.

  output km_sram_mem_req_t sram_mem_req_o,  // SRAM memory request, exposed at the subsystem
                                            // boundary.
  input  km_sram_mem_rsp_t sram_mem_rsp_i,  // SRAM memory response.

  input  logic [31:0] scrambler_key_i,  // Scrambler key from KMCSR.
  input  logic   scrambler_en_i,        // Scrambler enable from KMCSR; high scrambles the address
                                        // and write data and descrambles read data.

  input  logic [SRAM_NUM_LOCK_REGIONS-1:0] sram_lock_bits_i,  // SRAM write-lock from KMCSR:
                                                              // bit[i]=1 locks region i.

  output logic        parity_error_o,  // Combinational; high while a valid read response fails
                                       // parity on a strobed lane after descrambling.

  output logic [SRAM_NUM_LOCK_REGIONS-1:0] write_lock_violation_region_o  // One-hot region of a write
                                                                          // presented to a locked region;
                                                                          // combinational.
);

  `include "prim_assert.sv"

  ////////////////////////////////////////////////////////////////////////////
  // Address Decoding
  ////////////////////////////////////////////////////////////////////////////

  // Extract word address from byte address
  // Address width is properly sized to match SRAM interface
  logic [SRAM_ADDR_WIDTH-1:0] word_addr;
  logic [SRAM_ADDR_WIDTH-1:0] la_word_addr;
  assign word_addr    = mem_addr_i[SRAM_ADDR_WIDTH+1:2];
  assign la_word_addr = mem_la_addr_i[SRAM_ADDR_WIDTH+1:2];

  // Determine if this is a write operation
  logic is_write_request;
  logic is_read_request;
  assign is_write_request = mem_valid_i && |mem_wstrb_i;
  assign is_read_request  = mem_valid_i && !(|mem_wstrb_i);

  ////////////////////////////////////////////////////////////////////////////
  // Write-Lock Check
  ////////////////////////////////////////////////////////////////////////////
  // Region index: region r covers
  // [SRAM_BASE + r*SramLockRegionBytes, SRAM_BASE + (r+1)*SramLockRegionBytes).
  // The SRAM base is naturally aligned to its own size, so word_addr is already
  // 0-based within the window and the region index is just its high bits.
  // Bits needed to index a write-lock region.
  localparam int unsigned SramLockRegionAddrW = $clog2(SRAM_NUM_LOCK_REGIONS);
  // Word-address bits consumed by one write-lock region.
  localparam int unsigned SramLockRegionWordW = $clog2(
      km_intf_pkg::SramLockRegionBytes / (KM_MEM_DATA_WIDTH / 8)
  );
  logic [SramLockRegionAddrW-1:0] write_region;
  assign write_region = (word_addr >> SramLockRegionWordW);

  logic write_to_locked_region;
  assign write_to_locked_region = is_write_request && sram_lock_bits_i[write_region];

  // Violation one-hot: assert for the region that had the attempted write (single-cycle pulse)
  assign write_lock_violation_region_o = write_to_locked_region ?
        (SRAM_NUM_LOCK_REGIONS'(1) << write_region) : SRAM_NUM_LOCK_REGIONS'(0);

  ////////////////////////////////////////////////////////////////////////////
  // Scrambler Read Data
  ////////////////////////////////////////////////////////////////////////////

  logic [31:0] descrambled_read_data;

  ////////////////////////////////////////////////////////////////////////////
  // Look-Ahead Request Tracking
  ////////////////////////////////////////////////////////////////////////////

  // Track outstanding read requests to ensure we complete them
  // This is critical for pipelined memory when the CPU may de-assert mem_valid
  // before all responses arrive (e.g., second word of unaligned instruction)
  // Support pipelined sequential reads: can accept new request in same cycle as response
  logic read_pending_q;
  logic [1:0] req_squelch_q;
  logic       req_enable;

  // Determine if we should issue a new read request
  // - On look-ahead read (prefetch for next cycle)
  // - On regular read (when mem_valid is asserted)
  // Don't issue new request if one is already pending
  // EXCEPT: allow new request in same cycle as response (pipelined operation)
  logic issue_la_read;
  assign issue_la_read = mem_la_read_i && (!read_pending_q || sram_mem_rsp_i.rvalid);
  assign req_enable = req_squelch_q[1];

  // Track SRAM read handshakes/responses in shared pending bookkeeping.
  logic read_accept;
  logic read_complete;
  logic [SRAM_ADDR_WIDTH-1:0] req_addr_for_scrambler;
  logic [SRAM_ADDR_WIDTH-1:0] read_pending_addr_q;
  logic [3:0]                 req_rstrb_for_scrambler;
  logic [3:0]                 read_pending_rstrb_q;
  assign read_accept = sram_mem_req_o.req && !sram_mem_req_o.we && sram_mem_rsp_i.gnt;
  assign read_complete = sram_mem_rsp_i.rvalid;
  // Writes must always use the current data-access address. Look-ahead is only
  // for read prefetching and must not redirect a concurrent write.
  assign req_addr_for_scrambler = is_write_request ? word_addr :
                                    (issue_la_read ? la_word_addr : word_addr);
  assign req_rstrb_for_scrambler = issue_la_read ? mem_la_rstrb_i : mem_rstrb_i;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_pending_q <= 1'b0;
      req_squelch_q <= '0;
    end else begin
      if (read_accept) begin
        read_pending_q <= 1'b1;
      end else if (read_complete) begin
        read_pending_q <= 1'b0;
      end

      // Hold req low for two cycles after reset release to avoid propagating
      // PicoRV32 startup X values into memory request assertions.
      req_squelch_q <= {req_squelch_q[0], 1'b1};
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_pending_addr_q  <= '0;
      read_pending_rstrb_q <= '0;
    end else begin
      if (read_accept) begin
        read_pending_addr_q  <= req_addr_for_scrambler;
        read_pending_rstrb_q <= req_rstrb_for_scrambler;
      end
    end
  end

  ////////////////////////////////////////////////////////////////////////////
  // Scrambler Instantiation
  ////////////////////////////////////////////////////////////////////////////

  // Separate request/response scramblers keep read descrambling aligned with the returned word.
  logic [SRAM_ADDR_WIDTH-1:0] scrambled_addr;
  logic [31:0] scrambled_write_data;

  scrambler_8192x32 #(
    .ADDR_WIDTH(SRAM_ADDR_WIDTH),
    .DATA_WIDTH(32),
    .BYTE_WISE(1)
  ) u_req_scrambler (
    .addr_i                (req_addr_for_scrambler),
    .byte_mask_i           ('0),
    .scrambler_key_i       (scrambler_key_i),
    .scrambled_addr_o      (scrambled_addr),
    .write_data_i          (mem_wdata_i),
    .scrambled_write_data_o(scrambled_write_data),
    .scrambled_read_data_i ('0),
    .read_data_o           ()
  );

  scrambler_8192x32 #(
    .ADDR_WIDTH(SRAM_ADDR_WIDTH),
    .DATA_WIDTH(32),
    .BYTE_WISE(1)
  ) u_rsp_descrambler (
    .addr_i                (read_pending_addr_q),
    .byte_mask_i           ('0),
    .scrambler_key_i       (scrambler_key_i),
    .scrambled_addr_o      (),
    .write_data_i          ('0),
    .scrambled_write_data_o(),
    .scrambled_read_data_i (sram_mem_rsp_i.rdata),
    .read_data_o           (descrambled_read_data)
  );

  ////////////////////////////////////////////////////////////////////////////
  // Scrambler Bypass Mux
  ////////////////////////////////////////////////////////////////////////////

  // Read data: descrambled if enabled, otherwise pass-through
  logic [31:0] cpu_rdata_final;
  assign cpu_rdata_final = scrambler_en_i ? descrambled_read_data : sram_mem_rsp_i.rdata;

  ////////////////////////////////////////////////////////////////////////////
  // Parity Generation (Write Path)
  ////////////////////////////////////////////////////////////////////////////

  // Generate odd parity per byte for a 32-bit write data word. Returns 4-bit parity (one
  // bit per byte, odd parity).
  function automatic logic [3:0] gen_parity(logic [31:0] data);
    logic [3:0] parity;
    for (int i = 0; i < 4; i++) begin
      // Odd parity: XOR all bits in byte, then invert
      parity[i] = ~(^data[i*8+:8]);
    end
    return parity;
  endfunction

  ////////////////////////////////////////////////////////////////////////////
  // Parity Checking (Read Path)
  ////////////////////////////////////////////////////////////////////////////

  // Check odd parity per byte of a 32-bit read data word. data is the word after
  // descrambling and parity the 4-bit stored parity (one bit per byte, odd parity).
  // Returns 1 if a parity mismatch is detected, 0 otherwise.
  function automatic logic check_parity(logic [31:0] data, logic [3:0] parity,
                                        logic [3:0] byte_mask);
    logic [3:0] computed_parity;
    logic       mismatch;
    mismatch = 1'b0;
    for (int i = 0; i < 4; i++) begin
      // Compute expected parity (odd parity)
      computed_parity[i] = ~(^data[i*8+:8]);
      if (byte_mask[i]) begin
        mismatch |= (computed_parity[i] != parity[i]);
      end
    end
    return mismatch;
  endfunction

  ////////////////////////////////////////////////////////////////////////////
  // SRAM Request Generation with Look-Ahead Support
  ////////////////////////////////////////////////////////////////////////////

  // Issue SRAM request:
  // - Write: complete directly with the CPU-provided byte enables.
  // - Read: issue either a look-ahead prefetch or a regular read when no prior
  //   read is pending, unless a read response is returning in the same cycle.
  logic issue_request;
  assign issue_request = (is_write_request && !write_to_locked_region) ||
                          issue_la_read ||
                          (is_read_request && (!read_pending_q || sram_mem_rsp_i.rvalid));

  assign sram_mem_req_o.req     = req_enable && issue_request;
  assign sram_mem_req_o.we      = is_write_request && !write_to_locked_region;
  assign sram_mem_req_o.be      = mem_wstrb_i;
  // Address: use scrambled if enabled, select between look-ahead and regular access.
  assign sram_mem_req_o.addr   = scrambler_en_i ? scrambled_addr : req_addr_for_scrambler;
  assign sram_mem_req_o.wdata  = scrambler_en_i ? scrambled_write_data : mem_wdata_i;
  assign sram_mem_req_o.wparity = gen_parity(mem_wdata_i);

  ////////////////////////////////////////////////////////////////////////////
  // Ready Signal Generation
  ////////////////////////////////////////////////////////////////////////////

  // Ready when:
  // - Write: grant received, or write to locked region (drop write, still ack to CPU).
  // - Read: data valid received AND mem_valid is asserted.
  //
  // For write to locked region: we drop the write but still assert mem_ready so the CPU
  // does not hang (write has no effect, interface still completes).
  assign mem_ready_o = ((is_write_request && (sram_mem_rsp_i.gnt || write_to_locked_region)) ||
                          (mem_valid_i && sram_mem_rsp_i.rvalid));

  ////////////////////////////////////////////////////////////////////////////
  // Read Data Output
  ////////////////////////////////////////////////////////////////////////////

  // Pass SRAM data through directly so the latched-data property is defined by the SRAM macro.
  assign mem_rdata_o = cpu_rdata_final;

  ////////////////////////////////////////////////////////////////////////////
  // Parity Error Output
  ////////////////////////////////////////////////////////////////////////////

  // Check parity on the byte lanes actually consumed by the CPU on this read response.
  assign parity_error_o = read_complete ?
                            check_parity(cpu_rdata_final, sram_mem_rsp_i.rparity,
                                         read_pending_rstrb_q) : 1'b0;

  ////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////

  // SRAM request only asserted for look-ahead reads, regular reads, or writes
  `OCAH_OT_ASSERT(SramReqOnlyForValidOps_A, sram_mem_req_o.req |-> (mem_la_read_i || mem_valid_i),
                  clk_i, !rst_ni)

  // mem_ready only asserts when mem_valid is also asserted
  `OCAH_OT_ASSERT(MemReadyOnlyWhenValid_A, mem_ready_o |-> mem_valid_i, clk_i, !rst_ni)

  // SRAM reads only complete after a matching read request has been accepted.
  `OCAH_OT_ASSERT(ReadCompletesAfterAccept_A, sram_mem_rsp_i.rvalid |-> read_pending_q, clk_i,
                  !rst_ni)

endmodule : km_sram_interface


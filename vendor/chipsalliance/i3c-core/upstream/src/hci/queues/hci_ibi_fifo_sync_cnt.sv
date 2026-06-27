// SPDX-License-Identifier: Apache-2.0
//
// Dual write pointer logic for IBI queue synchronous FIFOs
// Forked from caliptra_prim_fifo_sync_cnt.sv
//
// Key differences from original:
// - Two write pointers: wptr_status (for IBI status descriptors) and wptr_data (for IBI data)
// - ibi_status_desc_valid_i input selects which pointer to use/update
// - wptr_data resets to 1 (not 0) to reserve position 0 for first status descriptor
// - Full uses wptr_data, Empty uses wptr_status

module hci_ibi_fifo_sync_cnt #(
  // Depth of the FIFO, i.e., maximum number of entries the FIFO can contain
  parameter int unsigned Depth = 4,
  // Whether to instantiate hardened counters (not supported in this fork)
  parameter bit Secure = 1'b0,
  // Width of the read and write pointers for the FIFO
  localparam int unsigned PtrW = caliptra_prim_util_pkg::vbits(Depth),
  // Width of the 'current depth' output
  localparam int unsigned DepthW = caliptra_prim_util_pkg::vbits(Depth+1)
) (
  input clk_i,
  input rst_ni,
  input clr_i,

  // Write control - with dual pointer support
  input incr_wptr_i,
  input ibi_status_desc_valid_i,  // Selects which write pointer to use

  // Read control
  input incr_rptr_i,

  // Write pointers output (two write pointers for IBI queue)
  output logic [PtrW-1:0] wptr_status_o,  // For status descriptor writes
  output logic [PtrW-1:0] wptr_data_o,    // For data writes

  // Read pointer output
  output logic [PtrW-1:0] rptr_o,

  // Status
  output logic full_o,
  output logic empty_o,
  output logic [DepthW-1:0] depth_o,
  output logic err_o
);

  // Internal 'wrap' pointers that have an extra leading bit to account for wraparounds.
  localparam int unsigned WrapPtrW = PtrW + 1;

  // Dual write pointers and read pointer with wrap-around MSB
  logic [WrapPtrW-1:0] wptr_status_wrap_q, wptr_data_wrap_q, rptr_wrap_q;

  // Derive real pointers by truncating the internal 'wrap' pointers.
  assign wptr_status_o = wptr_status_wrap_q[PtrW-1:0];
  assign wptr_data_o = wptr_data_wrap_q[PtrW-1:0];
  assign rptr_o = rptr_wrap_q[PtrW-1:0];

  // Extract the MSB of the 'wrap' pointers for full/empty/depth calculations.
  logic wptr_data_wrap_msb, wptr_status_wrap_msb, rptr_wrap_msb;
  assign wptr_data_wrap_msb = wptr_data_wrap_q[WrapPtrW-1];
  assign wptr_status_wrap_msb = wptr_status_wrap_q[WrapPtrW-1];
  assign rptr_wrap_msb = rptr_wrap_q[WrapPtrW-1];

  // Wrap detection for pointers (when pointer reaches Depth-1 and about to increment)
  logic wptr_data_at_max, rptr_at_max;
  assign wptr_data_at_max = (wptr_data_o == PtrW'(Depth-1));
  assign rptr_at_max = (rptr_o == PtrW'(Depth-1));

  // Wrap set values: invert MSB and reset lower bits to zero
  logic [WrapPtrW-1:0] wptr_data_wrap_set_cnt, rptr_wrap_set_cnt;
  assign wptr_data_wrap_set_cnt = {~wptr_data_wrap_msb, {(WrapPtrW-1){1'b0}}};
  assign rptr_wrap_set_cnt = {~rptr_wrap_msb, {(WrapPtrW-1){1'b0}}};

  // Full: data write pointer has wrapped and caught up to or passed read pointer
  // (different MSB, and wptr_lower >= rptr_lower)
  assign full_o = (wptr_data_wrap_msb != rptr_wrap_msb) && (wptr_data_o >= rptr_o);

  // Empty: read pointer has caught up to status write pointer
  // (all bits equal including MSB)
  assign empty_o = rptr_wrap_q == wptr_status_wrap_q;

  // Depth calculation using wptr_status (marks "complete" IBIs)
  // - Only count entries up to wptr_status, since data beyond that isn't readable yet
  // - At reset: wptr_status=0, rptr=0 → depth=0 (correct, nothing to read)
  // - After data but before status: depth still 0 (IBI not complete)
  // - After status written: depth includes status + its data
  assign depth_o = full_o                                ? DepthW'(Depth) :
                   wptr_status_wrap_msb == rptr_wrap_msb ? DepthW'(wptr_status_o) - DepthW'(rptr_o) :
                   DepthW'(Depth) - DepthW'(rptr_o) + DepthW'(wptr_status_o);

  // Secure mode not supported in this fork
  if (Secure) begin : gen_secure_ptrs
    // Secure counters not implemented for dual-pointer IBI queue
    // If needed, would require custom implementation with three prim_count instances
    initial begin
      $fatal(1, "Secure mode not supported in hci_ibi_fifo_sync_cnt");
    end
    assign err_o = 1'b0;

  end else begin : gen_normal_ptrs

    // Status write pointer logic
    // Reset to 0, updates to current wptr_data when status descriptor is written
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        wptr_status_wrap_q <= {WrapPtrW{1'b0}};
      end else if (clr_i) begin
        wptr_status_wrap_q <= {WrapPtrW{1'b0}};
      end else if (incr_wptr_i && ibi_status_desc_valid_i) begin
        // Status descriptor write: status pointer takes current data pointer position
        wptr_status_wrap_q <= wptr_data_wrap_q;
      end
    end

    // Data write pointer logic
    // Reset to 1 (not 0!) to reserve position 0 for first status descriptor
    // Increments on any write (both data and status descriptor)
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        wptr_data_wrap_q <= {{(WrapPtrW-1){1'b0}}, 1'b1};  // Reset to 1
      end else if (clr_i) begin
        wptr_data_wrap_q <= {{(WrapPtrW-1){1'b0}}, 1'b1};  // Reset to 1
      end else if (incr_wptr_i) begin
        // Data pointer always increments on write (for both data and status writes)
        if (wptr_data_at_max) begin
          wptr_data_wrap_q <= wptr_data_wrap_set_cnt;
        end else begin
          wptr_data_wrap_q <= wptr_data_wrap_q + {{(WrapPtrW-1){1'b0}}, 1'b1};
        end
      end
    end

    // Read pointer logic (same as original)
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        rptr_wrap_q <= {WrapPtrW{1'b0}};
      end else if (clr_i) begin
        rptr_wrap_q <= {WrapPtrW{1'b0}};
      end else if (incr_rptr_i) begin
        if (rptr_at_max) begin
          rptr_wrap_q <= rptr_wrap_set_cnt;
        end else begin
          rptr_wrap_q <= rptr_wrap_q + {{(WrapPtrW-1){1'b0}}, 1'b1};
        end
      end
    end

    assign err_o = 1'b0;
  end

endmodule

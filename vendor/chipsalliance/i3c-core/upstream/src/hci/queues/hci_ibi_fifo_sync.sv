// SPDX-License-Identifier: Apache-2.0
//
// IBI queue synchronous FIFO with dual write pointers and DWORD counter
// Forked from caliptra_prim_fifo_sync.sv
//
// Key differences from original:
// - Dual write pointers (status and data) from hci_ibi_fifo_sync_cnt
// - ibi_status_desc_valid_i input to select which pointer for memory write
// - DWORD counter to track when we're reading a status descriptor
// - ibi_status_desc_entries output for threshold triggering in queue wrapper

module hci_ibi_fifo_sync #(
  parameter int unsigned Width            = 16,
  parameter bit Pass                      = 1'b0, // IBI queue doesn't use passthrough
  parameter int unsigned Depth            = 4,
  parameter bit OutputZeroIfEmpty         = 1'b1,
  parameter bit Secure                    = 1'b0,
  // derived parameter
  localparam int          DepthW          = caliptra_prim_util_pkg::vbits(Depth+1)
) (
  input                   clk_i,
  input                   rst_ni,
  // synchronous clear / flush port
  input                   clr_i,
  // write port with status descriptor indicator
  input                   wvalid_i,
  output                  wready_data_o,    // Ready for data writes (not full)
  input   [Width-1:0]     wdata_i,
  input                   ibi_status_desc_valid_i,  // NEW: distinguishes status from data
  // read port
  output                  rvalid_o,
  input                   rready_i,
  output  [Width-1:0]     rdata_o,
  // occupancy
  output                  full_o,
  output  [DepthW-1:0]    depth_o,
  output                  err_o,
  // NEW: Status descriptor tracking for threshold
  output  [DepthW-1:0]    ibi_status_desc_entries_o
);

  // FIFO is in complete passthrough mode (not used for IBI queue)
  if (Depth == 0) begin : gen_passthru_fifo
    // Passthrough not supported for IBI queue
    initial begin
      $fatal(1, "Depth=0 (passthrough) not supported in hci_ibi_fifo_sync");
    end
    assign depth_o = 1'b0;
    assign rvalid_o = wvalid_i;
    assign rdata_o = wdata_i;
    assign wready_data_o = rready_i;
    assign full_o = rready_i;
    assign err_o = 1'b0;
    assign ibi_status_desc_entries_o = '0;

  // Normal FIFO construction
  end else begin : gen_normal_fifo

    localparam int unsigned PtrW = caliptra_prim_util_pkg::vbits(Depth);

    // Dual write pointers and read pointer
    logic [PtrW-1:0] fifo_wptr_status, fifo_wptr_data, fifo_rptr;
    logic            fifo_incr_wptr, fifo_incr_rptr, fifo_empty;

    // Module under reset flag
    logic under_rst;
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        under_rst <= 1'b1;
      end else if (under_rst) begin
        under_rst <= ~under_rst;
      end
    end

    logic empty;

    // Full and not ready for write are two different concepts.
    // The latter can be '0' when under reset, while the former is an indication that no more
    // entries can be written.
    assign wready_data_o = ~full_o & ~under_rst;
    assign rvalid_o = ~empty & ~under_rst;

    // Instantiate dual-pointer counter module
    hci_ibi_fifo_sync_cnt #(
      .Depth(Depth),
      .Secure(Secure)
    ) u_fifo_cnt (
      .clk_i,
      .rst_ni,
      .clr_i,
      .incr_wptr_i(fifo_incr_wptr),
      .ibi_status_desc_valid_i,
      .incr_rptr_i(fifo_incr_rptr),
      .wptr_status_o(fifo_wptr_status),
      .wptr_data_o(fifo_wptr_data),
      .rptr_o(fifo_rptr),
      .full_o,
      .empty_o(fifo_empty),
      .depth_o,
      .err_o
    );
    // Write occurs when valid and ready
    // Allow status descriptor writes even when full (they have reserved slots)
    assign fifo_incr_wptr = wvalid_i & (wready_data_o | ibi_status_desc_valid_i) & ~under_rst;
    assign fifo_incr_rptr = rvalid_o & rready_i & ~under_rst;

    // Memory storage
    logic [Depth-1:0][Width-1:0] storage;
    logic [Width-1:0] storage_rdata;

    // DWORD counter - tracks data DWORDs remaining after current status descriptor
    // When counter=0, next read is a status descriptor
    logic [7:0] data_dwords_remaining;
    logic reading_status_desc;

    assign reading_status_desc = (data_dwords_remaining == '0);

    // Status descriptor entry counter (for threshold triggering)
    logic [DepthW-1:0] ibi_status_desc_entries;
    assign ibi_status_desc_entries_o = ibi_status_desc_entries;

    // Detect status descriptor read/write
    logic read_status_desc, write_status_desc;
    assign read_status_desc = fifo_incr_rptr && reading_status_desc;
    assign write_status_desc = fifo_incr_wptr && ibi_status_desc_valid_i;

    // DWORD counter logic
    // Uses data_length field from status descriptor (bits [7:0]) to know how many data DWORDs follow
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        data_dwords_remaining <= '0;
      end else if (clr_i) begin
        data_dwords_remaining <= '0;
      end else if (fifo_incr_rptr) begin
        if (reading_status_desc) begin
          // Just read a status descriptor - load DWORD count from data_length field
          // storage[fifo_rptr][7:0] = data_length in bytes
          // DWORD count = ceil(data_length / 4) = (data_length + 3) >> 2
          data_dwords_remaining <= (storage[fifo_rptr][7:0] + 8'd3) >> 2;
        end else begin
          // Reading data - decrement counter
          data_dwords_remaining <= data_dwords_remaining - 8'd1;
        end
      end
    end

    // Status descriptor entry counter (increment on write, decrement on read)
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        ibi_status_desc_entries <= '0;
      end else if (clr_i) begin
        ibi_status_desc_entries <= '0;
      end else begin
        case ({write_status_desc, read_status_desc})
          2'b10:   ibi_status_desc_entries <= ibi_status_desc_entries + DepthW'(1);
          2'b01:   ibi_status_desc_entries <= ibi_status_desc_entries - DepthW'(1);
          default: ; // 2'b00 or 2'b11: no change
        endcase
      end
    end

    // Memory write logic - select pointer based on descriptor type
    if (Depth == 1) begin : gen_depth_eq1
      assign storage_rdata = storage[0];

      always_ff @(posedge clk_i) begin
        if (fifo_incr_wptr) begin
          storage[0] <= wdata_i;
        end
      end

      logic unused_ptrs;
      assign unused_ptrs = ^{fifo_wptr_status, fifo_wptr_data, fifo_rptr};

    // FIFO with more than one storage element
    end else begin : gen_depth_gt1
      assign storage_rdata = storage[fifo_rptr];

      always_ff @(posedge clk_i) begin
        if (fifo_incr_wptr) begin
          if (ibi_status_desc_valid_i) begin
            // Status descriptor write - use status pointer
            storage[fifo_wptr_status] <= wdata_i;
          end else begin
            // Data write - use data pointer
            storage[fifo_wptr_data] <= wdata_i;
          end
        end
      end
    end

    // Read data logic
    logic [Width-1:0] rdata_int;
    if (Pass == 1'b1) begin : gen_pass
      assign rdata_int = (fifo_empty && wvalid_i) ? wdata_i : storage_rdata;
      assign empty = fifo_empty & ~wvalid_i;
    end else begin : gen_nopass
      assign rdata_int = storage_rdata;
      assign empty = fifo_empty;
    end

    if (OutputZeroIfEmpty == 1'b1) begin : gen_output_zero
      assign rdata_o = empty ? Width'(0) : rdata_int;
    end else begin : gen_no_output_zero
      assign rdata_o = rdata_int;
    end

  end // block: gen_normal_fifo

endmodule

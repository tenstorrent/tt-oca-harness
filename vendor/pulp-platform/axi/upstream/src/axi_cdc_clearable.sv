// Copyright (c) 2026 Tenstorrent Inc.
//
// Licensed under the Solderpad Hardware License, Version 0.51 (the "License");
// you may not use this file except in compliance with the License. You may
// obtain a copy of the License at http://solderpad.org/licenses/SHL-0.51.
// Unless required by applicable law or agreed to in writing, software, hardware
// and materials distributed under this License is distributed on an "AS IS"
// BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
// implied. See the License for the specific language governing permissions and
// limitations under the License.

`include "axi/assign.svh"

/// A clock-domain-crossing for an AXI interface that tolerates one-sided warm
/// resets and supports explicit flush via `src_clear_i` / `dst_clear_i`.
///
/// This is a clearable counterpart to `axi_cdc`: each of the five AXI channels
/// is crossed through a `cdc_fifo_gray_clearable` instance, and each FIFO
/// embeds its own `cdc_reset_ctrlr` so that an asynchronous reset on one side
/// (or a synchronous clear pulse) atomically isolates and flushes the opposite
/// side without leaving the gray pointers out of step.
///
/// The default `ClearOnAsyncReset = 1` makes `src_rst_ni` and `dst_rst_ni`
/// independent: either may assert asynchronously without corrupting the CDC.
/// This requires `SyncStages >= 3` per the `cdc_fifo_gray_clearable` contract.
///
/// `src_clear_pending_o` / `dst_clear_pending_o` are high whenever any channel
/// is still executing an isolate-and-clear sequence on the respective side.
///
/// For SDC constraints on the internal async pointer paths, follow the rules
/// documented in the header of `cdc_fifo_gray_clearable`.
module axi_cdc_clearable #(
  parameter type aw_chan_t  = logic, // AW channel type
  parameter type w_chan_t   = logic, //  W channel type
  parameter type b_chan_t   = logic, //  B channel type
  parameter type ar_chan_t  = logic, // AR channel type
  parameter type r_chan_t   = logic, //  R channel type
  parameter type axi_req_t  = logic, // encapsulates AW, W, AR request channels + B, R ready
  parameter type axi_resp_t = logic, // encapsulates B, R response channels + AW, W, AR ready
  /// Depth of each per-channel FIFO, given as 2**LogDepth.
  parameter int unsigned LogDepth          = 1,
  /// Number of synchronization registers to insert on the async pointers.
  /// Must be >=3 when ClearOnAsyncReset is enabled.
  parameter int unsigned SyncStages        = 3,
  /// When 1, an asynchronous reset on either side triggers a coordinated
  /// isolate+clear on the other side via the embedded cdc_reset_ctrlr.
  parameter bit          ClearOnAsyncReset = 1'b1
) (
  // Source side (AXI master) - clocked by `src_clk_i`
  input  logic      src_clk_i,
  input  logic      src_rst_ni,
  input  logic      src_clear_i,
  output logic      src_clear_pending_o,
  input  axi_req_t  src_req_i,
  output axi_resp_t src_resp_o,
  // Destination side (AXI slave) - clocked by `dst_clk_i`
  input  logic      dst_clk_i,
  input  logic      dst_rst_ni,
  input  logic      dst_clear_i,
  output logic      dst_clear_pending_o,
  output axi_req_t  dst_req_o,
  input  axi_resp_t dst_resp_i
);

  // Pending aggregation. Index mapping follows channel order {AW,W,AR,B,R}.
  // For each FIFO we expose two pending flags (one per domain); we route them
  // to whichever module-side domain that FIFO half lives in.
  logic [4:0] src_pending;
  logic [4:0] dst_pending;

  assign src_clear_pending_o = |src_pending;
  assign dst_clear_pending_o = |dst_pending;

  //////////////////////////////////////////////////////////////////////////////
  // src -> dst channels: AW, W, AR
  //   fifo.src_* = module.src_* ; fifo.dst_* = module.dst_*
  //////////////////////////////////////////////////////////////////////////////

  cdc_fifo_gray_clearable #(
`ifdef QUESTA
    // Workaround for a bug in Questa: pass a flat logic vector to the type
    // parameter rather than the struct typedef.
    .T                    ( logic [$bits(aw_chan_t)-1:0] ),
`else
    .T                    ( aw_chan_t                    ),
`endif
    .LOG_DEPTH            ( LogDepth                     ),
    .SYNC_STAGES          ( SyncStages                   ),
    .CLEAR_ON_ASYNC_RESET ( ClearOnAsyncReset            )
  ) i_cdc_fifo_gray_clearable_aw (
    .src_clk_i           ( src_clk_i           ),
    .src_rst_ni          ( src_rst_ni          ),
    .src_clear_i         ( src_clear_i         ),
    .src_clear_pending_o ( src_pending[0]      ),
    .src_data_i          ( src_req_i.aw        ),
    .src_valid_i         ( src_req_i.aw_valid  ),
    .src_ready_o         ( src_resp_o.aw_ready ),
    .dst_clk_i           ( dst_clk_i           ),
    .dst_rst_ni          ( dst_rst_ni          ),
    .dst_clear_i         ( dst_clear_i         ),
    .dst_clear_pending_o ( dst_pending[0]      ),
    .dst_data_o          ( dst_req_o.aw        ),
    .dst_valid_o         ( dst_req_o.aw_valid  ),
    .dst_ready_i         ( dst_resp_i.aw_ready )
  );

  cdc_fifo_gray_clearable #(
`ifdef QUESTA
    .T                    ( logic [$bits(w_chan_t)-1:0] ),
`else
    .T                    ( w_chan_t                    ),
`endif
    .LOG_DEPTH            ( LogDepth                    ),
    .SYNC_STAGES          ( SyncStages                  ),
    .CLEAR_ON_ASYNC_RESET ( ClearOnAsyncReset           )
  ) i_cdc_fifo_gray_clearable_w (
    .src_clk_i           ( src_clk_i          ),
    .src_rst_ni          ( src_rst_ni         ),
    .src_clear_i         ( src_clear_i        ),
    .src_clear_pending_o ( src_pending[1]     ),
    .src_data_i          ( src_req_i.w        ),
    .src_valid_i         ( src_req_i.w_valid  ),
    .src_ready_o         ( src_resp_o.w_ready ),
    .dst_clk_i           ( dst_clk_i          ),
    .dst_rst_ni          ( dst_rst_ni         ),
    .dst_clear_i         ( dst_clear_i        ),
    .dst_clear_pending_o ( dst_pending[1]     ),
    .dst_data_o          ( dst_req_o.w        ),
    .dst_valid_o         ( dst_req_o.w_valid  ),
    .dst_ready_i         ( dst_resp_i.w_ready )
  );

  cdc_fifo_gray_clearable #(
`ifdef QUESTA
    .T                    ( logic [$bits(ar_chan_t)-1:0] ),
`else
    .T                    ( ar_chan_t                    ),
`endif
    .LOG_DEPTH            ( LogDepth                     ),
    .SYNC_STAGES          ( SyncStages                   ),
    .CLEAR_ON_ASYNC_RESET ( ClearOnAsyncReset            )
  ) i_cdc_fifo_gray_clearable_ar (
    .src_clk_i           ( src_clk_i           ),
    .src_rst_ni          ( src_rst_ni          ),
    .src_clear_i         ( src_clear_i         ),
    .src_clear_pending_o ( src_pending[2]      ),
    .src_data_i          ( src_req_i.ar        ),
    .src_valid_i         ( src_req_i.ar_valid  ),
    .src_ready_o         ( src_resp_o.ar_ready ),
    .dst_clk_i           ( dst_clk_i           ),
    .dst_rst_ni          ( dst_rst_ni          ),
    .dst_clear_i         ( dst_clear_i         ),
    .dst_clear_pending_o ( dst_pending[2]      ),
    .dst_data_o          ( dst_req_o.ar        ),
    .dst_valid_o         ( dst_req_o.ar_valid  ),
    .dst_ready_i         ( dst_resp_i.ar_ready )
  );

  //////////////////////////////////////////////////////////////////////////////
  // dst -> src channels: B, R
  //   fifo.src_* = module.dst_* (producer lives in dst domain)
  //   fifo.dst_* = module.src_*
  //////////////////////////////////////////////////////////////////////////////

  cdc_fifo_gray_clearable #(
`ifdef QUESTA
    .T                    ( logic [$bits(b_chan_t)-1:0] ),
`else
    .T                    ( b_chan_t                    ),
`endif
    .LOG_DEPTH            ( LogDepth                    ),
    .SYNC_STAGES          ( SyncStages                  ),
    .CLEAR_ON_ASYNC_RESET ( ClearOnAsyncReset           )
  ) i_cdc_fifo_gray_clearable_b (
    .src_clk_i           ( dst_clk_i          ),
    .src_rst_ni          ( dst_rst_ni         ),
    .src_clear_i         ( dst_clear_i        ),
    .src_clear_pending_o ( dst_pending[3]     ),
    .src_data_i          ( dst_resp_i.b       ),
    .src_valid_i         ( dst_resp_i.b_valid ),
    .src_ready_o         ( dst_req_o.b_ready  ),
    .dst_clk_i           ( src_clk_i          ),
    .dst_rst_ni          ( src_rst_ni         ),
    .dst_clear_i         ( src_clear_i        ),
    .dst_clear_pending_o ( src_pending[3]     ),
    .dst_data_o          ( src_resp_o.b       ),
    .dst_valid_o         ( src_resp_o.b_valid ),
    .dst_ready_i         ( src_req_i.b_ready  )
  );

  cdc_fifo_gray_clearable #(
`ifdef QUESTA
    .T                    ( logic [$bits(r_chan_t)-1:0] ),
`else
    .T                    ( r_chan_t                    ),
`endif
    .LOG_DEPTH            ( LogDepth                    ),
    .SYNC_STAGES          ( SyncStages                  ),
    .CLEAR_ON_ASYNC_RESET ( ClearOnAsyncReset           )
  ) i_cdc_fifo_gray_clearable_r (
    .src_clk_i           ( dst_clk_i          ),
    .src_rst_ni          ( dst_rst_ni         ),
    .src_clear_i         ( dst_clear_i        ),
    .src_clear_pending_o ( dst_pending[4]     ),
    .src_data_i          ( dst_resp_i.r       ),
    .src_valid_i         ( dst_resp_i.r_valid ),
    .src_ready_o         ( dst_req_o.r_ready  ),
    .dst_clk_i           ( src_clk_i          ),
    .dst_rst_ni          ( src_rst_ni         ),
    .dst_clear_i         ( src_clear_i        ),
    .dst_clear_pending_o ( src_pending[4]     ),
    .dst_data_o          ( src_resp_o.r       ),
    .dst_valid_o         ( src_resp_o.r_valid ),
    .dst_ready_i         ( src_req_i.r_ready  )
  );

  // Compile-time sanity: when async-reset coupling is active the embedded
  // reset controller requires at least three synchronizer stages.
`ifndef SYNTHESIS
  initial begin : p_param_check
    if (ClearOnAsyncReset && (SyncStages < 3)) begin
      $error("axi_cdc_clearable: ClearOnAsyncReset=1 requires SyncStages >= 3 ",
             "(got %0d).", SyncStages);
    end
    if (!ClearOnAsyncReset && (SyncStages < 2)) begin
      $error("axi_cdc_clearable: SyncStages must be >= 2 (got %0d).", SyncStages);
    end
  end
`endif

endmodule

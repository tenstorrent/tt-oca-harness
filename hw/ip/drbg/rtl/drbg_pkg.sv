// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Hold shared DRBG wrapper parameters, enums, and interface typedefs.
//
// Defines the wrapper-local defaults, 64-bit and 32-bit AXI-Lite typedefs used by the CSR
// bridge chain, AXI-Stream typedefs used by the entropy and EDN output paths, and the
// provisional CSRNG seed FIPS policy.

package drbg_pkg;

  `include "axi/typedef.svh"

  // =========================================================================
  // Wrapper Parameter Defaults
  // =========================================================================

  // Default complete-seed queue depth feeding wrapped CSRNG.
  localparam int unsigned DrbgDefaultSeedFifoDepth = 1;
  // Default number of exposed EDN endpoint AXI-Stream outputs.
  localparam int unsigned DrbgDefaultEdnEndpointCount = 1;
  // Default number of native EDN req/rsp endpoints (bypass AXI-Stream).
  localparam int unsigned DrbgDefaultEdnNativeEndpointCount = 0;
  // Default depth of each EDN endpoint output FIFO.
  localparam int unsigned DrbgDefaultEndpointFifoDepth = 8;

  // =========================================================================
  // Provisional FIPS Policy
  // =========================================================================

  // Current feature-release CSRNG seed FIPS policy.
  localparam logic DrbgCsrngSeedFipsProvisional = 1'b1;

  // =========================================================================
  // AXI-Lite Type Definitions
  // =========================================================================

  // 64-bit external AXI-Lite address width for CSRNG and EDN CSRs.
  localparam int unsigned DrbgAxil64AddrWidth = 32;
  // 64-bit external AXI-Lite data width for CSRNG and EDN CSRs.
  localparam int unsigned DrbgAxil64DataWidth = 64;
  // 64-bit external AXI-Lite strobe width for CSRNG and EDN CSRs.
  localparam int unsigned DrbgAxil64StrbWidth = DrbgAxil64DataWidth / 8;

  // 32-bit internal AXI-Lite address width used before TL-UL bridging.
  localparam int unsigned DrbgAxil32AddrWidth = 32;
  // 32-bit internal AXI-Lite data width used before TL-UL bridging.
  localparam int unsigned DrbgAxil32DataWidth = 32;
  // 32-bit internal AXI-Lite strobe width used before TL-UL bridging.
  localparam int unsigned DrbgAxil32StrbWidth = DrbgAxil32DataWidth / 8;

  // 64-bit external AXI-Lite address type.
  typedef logic [DrbgAxil64AddrWidth-1:0] drbg_axil64_addr_t;
  // 64-bit external AXI-Lite data type.
  typedef logic [DrbgAxil64DataWidth-1:0] drbg_axil64_data_t;
  // 64-bit external AXI-Lite strobe type.
  typedef logic [DrbgAxil64StrbWidth-1:0] drbg_axil64_strb_t;

  // 32-bit internal AXI-Lite address type.
  typedef logic [DrbgAxil32AddrWidth-1:0] drbg_axil32_addr_t;
  // 32-bit internal AXI-Lite data type.
  typedef logic [DrbgAxil32DataWidth-1:0] drbg_axil32_data_t;
  // 32-bit internal AXI-Lite strobe type.
  typedef logic [DrbgAxil32StrbWidth-1:0] drbg_axil32_strb_t;

  // 64-bit AXI-Lite channel, request, and response types.
  // Expands to drbg_axil64_aw_chan_t, drbg_axil64_w_chan_t,
  // drbg_axil64_b_chan_t, drbg_axil64_ar_chan_t, drbg_axil64_r_chan_t,
  // drbg_axil64_req_t, and drbg_axil64_resp_t.
  `AXI_LITE_TYPEDEF_ALL(drbg_axil64, drbg_axil64_addr_t, drbg_axil64_data_t, drbg_axil64_strb_t)

  // 32-bit AXI-Lite channel, request, and response types.
  // Expands to drbg_axil32_aw_chan_t, drbg_axil32_w_chan_t,
  // drbg_axil32_b_chan_t, drbg_axil32_ar_chan_t, drbg_axil32_r_chan_t,
  // drbg_axil32_req_t, and drbg_axil32_resp_t.
  `AXI_LITE_TYPEDEF_ALL(drbg_axil32, drbg_axil32_addr_t, drbg_axil32_data_t, drbg_axil32_strb_t)

  // =========================================================================
  // AXI-Stream Type Definitions
  // =========================================================================

  // DRBG wrapper AXI-Stream data width.
  localparam int unsigned DrbgAxisDataWidth = 32;
  // DRBG wrapper AXI-Stream strobe width.
  localparam int unsigned DrbgAxisStrbWidth = DrbgAxisDataWidth / 8;

  // DRBG wrapper AXI-Stream data type.
  typedef logic [DrbgAxisDataWidth-1:0] drbg_axis_data_t;
  // DRBG wrapper AXI-Stream strobe type.
  typedef logic [DrbgAxisStrbWidth-1:0] drbg_axis_strb_t;

  // AXI-Stream request bundle driven by the DRBG wrapper.
  // tuser is a generic per-beat AXI-Stream sideband. The bit currently forwards
  // the FIPS provenance of the current word from the source: post-CSRNG DRBG
  // endpoints drive it from the native EDN edn_fips bit, while externally
  // provided entropy-source streams should drive it according to the producer's
  // own FIPS policy (commonly tied low when the source is not NIST-approved).
  // Downstream consumers that care about FIPS status (e.g. OTBN RND, which
  // raises rnd_fips_chk_fail when an ack arrives with edn_fips = 0) sample this
  // bit on each beat. Future producers may repurpose tuser for other per-beat
  // metadata as long as all consumers agree.
  typedef struct packed {
    logic            tvalid;
    drbg_axis_data_t tdata;
    drbg_axis_strb_t tstrb;
    logic            tuser;
  } drbg_axis_req_t;

  // AXI-Stream response bundle driven by a downstream consumer.
  typedef struct packed {logic tready;} drbg_axis_rsp_t;

endpackage : drbg_pkg

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Encoding-stable AXI types for the ocah_axi_vip SV-UVM layer. Response codes
// match the cocotb layer's ocah_axi_types.py (OKAY=0/EXOKAY=1/SLVERR=2/DECERR=3)
// so evidence values are directly comparable across frameworks.

typedef enum logic [1:0] {
  OCAH_AXI_RESP_OKAY   = 2'd0,
  OCAH_AXI_RESP_EXOKAY = 2'd1,
  OCAH_AXI_RESP_SLVERR = 2'd2,
  OCAH_AXI_RESP_DECERR = 2'd3
} ocah_axi_resp_e;

typedef enum {
  OCAH_AXI_PROTO_AXI4,
  OCAH_AXI_PROTO_AXI4_LITE
} ocah_axi_protocol_e;

typedef enum {
  OCAH_AXI_DIR_READ,
  OCAH_AXI_DIR_WRITE
} ocah_axi_dir_e;

typedef enum logic [1:0] {
  OCAH_AXI_BURST_FIXED = 2'd0,
  OCAH_AXI_BURST_INCR  = 2'd1,
  OCAH_AXI_BURST_WRAP  = 2'd2
} ocah_axi_burst_e;

// Worst (highest-severity) response across a burst; empty list reads OKAY.
function automatic ocah_axi_resp_e ocah_axi_worst_resp(ocah_axi_resp_e resps[$]);
  ocah_axi_resp_e worst = OCAH_AXI_RESP_OKAY;
  foreach (resps[i]) begin
    if (resps[i] > worst) worst = resps[i];
  end
  return worst;
endfunction

// True when every beat response is OKAY or EXOKAY.
function automatic bit ocah_axi_resp_ok(ocah_axi_resp_e resps[$]);
  if (resps.size() == 0) return 1'b0;
  foreach (resps[i]) begin
    if (!(resps[i] inside {OCAH_AXI_RESP_OKAY, OCAH_AXI_RESP_EXOKAY})) return 1'b0;
  end
  return 1'b1;
endfunction

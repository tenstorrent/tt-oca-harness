// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Graded-window owner codes of the Phase 2 FCOV sampler (docs/SEP_FCOV.adoc,
// graded window). One table for the sampler and the cocotb leaves:
// cov/sv/sep_fcov.sv includes it, and cocotb/env/sep_fcov_gate.py reads it.
//
// A code names one Phase 3 VPLAN entry: area * 100 + entry number, so 2.25 is
// 225. 0 means "no window open". Each line is
//   localparam int unsigned FCOV_OWN_<TEST NAME IN UPPER CASE> = <code>;
// and the test name is the testcase module name of the entry. Add a line for a
// new owner; never reuse a code.

localparam int unsigned FCOV_OWN_NONE = 0;

// Fabric and remap (VPLAN 2.25 to 2.33).
localparam int unsigned FCOV_OWN_SEP_FABRIC_INBOUND_REBASE_TEST = 225;
localparam int unsigned FCOV_OWN_SEP_FABRIC_FILTER_MATCH_PRIORITY_RAND_TEST = 226;
localparam int unsigned FCOV_OWN_SEP_FABRIC_OUTBOUND_ROUTE_ATTR_TEST = 227;
localparam int unsigned FCOV_OWN_SEP_FABRIC_ALIAS_REMAP_ATTR_RAND_TEST = 228;
localparam int unsigned FCOV_OWN_SEP_FABRIC_SMC_ROUTE_TEST = 229;
localparam int unsigned FCOV_OWN_SEP_FABRIC_EXTENSION_PORT_WINDOW_TEST = 230;
localparam int unsigned FCOV_OWN_SEP_FABRIC_ROW_RESPONSE_MATRIX_TEST = 231;
localparam int unsigned FCOV_OWN_SEP_CPU_LSU_ALIAS_WINDOW_TWIN_TEST = 232;
localparam int unsigned FCOV_OWN_SEP_FABRIC_DMA_ENDPOINT_MATRIX_TEST = 233;

// Memory, boot, reset (VPLAN 5.25): owner of
// sep_fabric_dedicated_port_cg.cp_tcm_dma_dir_range.
localparam int unsigned FCOV_OWN_SEP_TCM_DMA_APERTURE_ECC_TEST = 525;

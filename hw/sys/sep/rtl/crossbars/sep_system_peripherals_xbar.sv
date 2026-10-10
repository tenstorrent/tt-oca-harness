// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route system-peripherals AXI traffic to mailbox, system CSR, and SMN paths.
//
// Address rules are explicit integration apertures in AddrMap below:
// 0x10A0_0000-0x10A0_FFFF to the mailbox, and each system-CSR register block's extent from
// sep_top_addrmap_pkg to the system CSRs. Every other address in 0x10A1_0000-0x10A4_FFFF and
// 0x1080_2000-0x1080_20FF, and anything at or above 0x4000_0000, gets the axi_xbar DECERR
// responder; the rest of the space below 0x4000_0000 goes to smn_inbound_from_xbar. The
// system_csr AXI-Lite converter answers every write error with SLVERR, so a refusal in those
// windows has to come from this decode to read and write as DECERR. Both initiators reach
// every target.
// Initiators are full AXI4 64-bit. mailbox and system_csr targets are AXI4-Lite 64-bit;
// smn_inbound_from_xbar stays full AXI4, with one more ID bit than the initiators.

`include "axi/typedef.svh"
`include "axi/assign.svh"

module sep_system_peripherals_xbar
  import sep_system_peripherals_xbar_pkg::axi64_req_t;
  import sep_system_peripherals_xbar_pkg::axi64_resp_t;
  import sep_system_peripherals_xbar_pkg::axi_out_req_t;
  import sep_system_peripherals_xbar_pkg::axi_out_resp_t;
  import sep_system_peripherals_xbar_pkg::axi_lite64_req_t;
  import sep_system_peripherals_xbar_pkg::axi_lite64_resp_t;
  import sep_system_peripherals_xbar_pkg::addr_rule_t;
  import sep_system_peripherals_xbar_pkg::NumAddrRules;
  import sep_system_peripherals_xbar_pkg::xbar_slv_req_t;
  import sep_system_peripherals_xbar_pkg::xbar_slv_resp_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_req_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_resp_t;
  import sep_system_peripherals_xbar_pkg::XbarCfg;
  import sep_system_peripherals_xbar_pkg::Connectivity;
  import sep_system_peripherals_xbar_pkg::xbar_slv_aw_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_aw_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_slv_w_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_slv_b_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_b_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_slv_ar_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_ar_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_slv_r_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_mst_r_chan_t;
  import sep_system_peripherals_xbar_pkg::xbar_out_mailbox_req_t;
  import sep_system_peripherals_xbar_pkg::mailbox_req_t;
  import sep_system_peripherals_xbar_pkg::xbar_out_mailbox_resp_t;
  import sep_system_peripherals_xbar_pkg::mailbox_resp_t;
  import sep_system_peripherals_xbar_pkg::xbar_out_system_csr_req_t;
  import sep_system_peripherals_xbar_pkg::system_csr_req_t;
  import sep_system_peripherals_xbar_pkg::xbar_out_system_csr_resp_t;
  import sep_system_peripherals_xbar_pkg::system_csr_resp_t;
(
  input  logic clk_i,                         // System clock.
  input  logic rst_ni,                        // Active-low reset.
  input  logic test_i,                        // DFT test mode to axi_xbar.

  input  axi64_req_t  sep_local_from_remap_req_i,  // Local-master request after the alias remap and
                                                   // SEP_LOCAL decode in sep_system_peripherals.
  output axi64_resp_t sep_local_from_remap_resp_o,  // Response to the local-master request.

  input  axi64_req_t  smn_inbound_req_i,      // SMN inbound request after the inbound filter and
                                              // global-to-local rebase.
  output axi64_resp_t smn_inbound_resp_o,     // Response to the SMN inbound request.

  output axi_out_req_t  smn_inbound_from_xbar_req_o,  // Request for any address below 0x4000_0000
                                                      // outside the mailbox and system CSR windows,
                                                      // forwarded to the SEP local xbar in
                                                      // sep_system_peripherals.
  input  axi_out_resp_t smn_inbound_from_xbar_resp_i,  // Response to smn_inbound_from_xbar_req_o.

  output axi_lite64_req_t  mailbox_req_o,     // Request for 0x10A0_0000-0x10A0_FFFF, converted to
                                              // AXI-Lite.
  input  axi_lite64_resp_t mailbox_resp_i,    // Mailbox AXI-Lite response.

  output axi_lite64_req_t  system_csr_req_o,  // Request for a system-CSR register block extent
                                              // in 0x10A1_0000-0x10A4_FFFF or
                                              // 0x1080_2000-0x1080_20FF, converted to AXI-Lite.
  input  axi_lite64_resp_t system_csr_resp_i  // System CSR AXI-Lite response.
);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  // AddrMap rules honour optional per-range parameterisation fields:
  //   - base_expr     : verbatim SV expression for start_addr
  //   - end_expr      : verbatim SV expression for end_addr
  //   - tile_relative : when true (and no *_expr), shift base/end by base_addr_param
  //   - target_slave  : verbatim SV expression for the idx field (may use
  //                     parameters like HAS_* and slave-name tokens in quotes)
  localparam addr_rule_t [NumAddrRules-1:0] AddrMap = '{
    // smn_inbound_from_xbar.region_0: 0x00000000 - 0x10802000
    '{idx: 0, start_addr: 56'h0, end_addr: 57'h10802000},
    // smn_inbound_from_xbar.region_1: 0x10802100 - 0x10a00000
    '{idx: 0, start_addr: 56'h10802100, end_addr: 57'h10a00000},
    // smn_inbound_from_xbar.region_2: 0x10a50000 - 0x40000000
    '{idx: 0, start_addr: 56'h10a50000, end_addr: 57'h40000000},
    // mailbox.main: 0x10a00000 - 0x10a10000
    '{idx: 1, start_addr: 56'h10a00000, end_addr: 57'h10a10000},
    // system_csr.local_master_alias_remap_ctrl: 0x10a10000 - 0x10a10200
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_BASE_ADDR(0)),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_BASE_ADDR(0) +
                    sep_top_addrmap_pkg::SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_TOTAL_SIZE)
    },
    // system_csr.ap_output_remap_ctrl: 0x10a10200 - 0x10a10280
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(0)),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_BASE_ADDR(0) +
                    sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_TOTAL_SIZE)
    },
    // system_csr.stee_output_remap_ctrl: 0x10a10300 - 0x10a10380
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(0)),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_BASE_ADDR(0) +
                    sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_TOTAL_SIZE)
    },
    // system_csr.outbound_filter_ctrl: 0x10a20000 - 0x10a20400
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(0) +
                    sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_TOTAL_SIZE)
    },
    // system_csr.inbound_filter_ctrl: 0x10a21000 - 0x10a21200
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0)),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0) +
                    sep_top_addrmap_pkg::SEP_TOP_INBOUND_FILTER_CTRL_TOTAL_SIZE)
    },
    // system_csr.sep_cpu_ctrl: 0x10a30000 - 0x10a31008
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_SEP_CPU_CTRL_BASE_ADDR),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_SEP_CPU_CTRL_BASE_ADDR +
                    sep_top_addrmap_pkg::SEP_TOP_SEP_CPU_CTRL_SIZE)
    },
    // system_csr.sep_scratch_cold: 0x10802000 - 0x10802040
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR +
                    sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_COLD_SIZE)
    },
    // system_csr.sep_scratch_warm: 0x10802080 - 0x108020c0
    '{
      idx: 2,
      start_addr: 56'(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR),
      end_addr: 57'(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR +
                    sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_WARM_SIZE)
    }
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  xbar_slv_req_t  [1:0] xbar_slv_req;
  xbar_slv_resp_t [1:0] xbar_slv_resp;

  // Input sep_local_from_remap: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[0] = sep_local_from_remap_req_i;
  assign sep_local_from_remap_resp_o = xbar_slv_resp[0];

  // Input smn_inbound: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[1] = smn_inbound_req_i;
  assign smn_inbound_resp_o = xbar_slv_resp[1];

  // ===========================================================================
  // Crossbar
  // ===========================================================================
  xbar_mst_req_t  [2:0] xbar_mst_req;
  xbar_mst_resp_t [2:0] xbar_mst_resp;

  axi_xbar #(
    .Cfg          (XbarCfg),
    .ATOPs        (1'b0),
    .Connectivity (Connectivity),
    .slv_aw_chan_t(xbar_slv_aw_chan_t),
    .mst_aw_chan_t(xbar_mst_aw_chan_t),
    .w_chan_t     (xbar_slv_w_chan_t),
    .slv_b_chan_t (xbar_slv_b_chan_t),
    .mst_b_chan_t (xbar_mst_b_chan_t),
    .slv_ar_chan_t(xbar_slv_ar_chan_t),
    .mst_ar_chan_t(xbar_mst_ar_chan_t),
    .slv_r_chan_t (xbar_slv_r_chan_t),
    .mst_r_chan_t (xbar_mst_r_chan_t),
    .slv_req_t    (xbar_slv_req_t),
    .slv_resp_t   (xbar_slv_resp_t),
    .mst_req_t    (xbar_mst_req_t),
    .mst_resp_t   (xbar_mst_resp_t),
    .rule_t       (addr_rule_t)
  ) u_axi_xbar (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .test_i                (test_i),
    .sel_hash_i            (2'b0),
    .slv_ports_req_i       (xbar_slv_req),
    .slv_ports_resp_o      (xbar_slv_resp),
    .mst_ports_req_o       (xbar_mst_req),
    .mst_ports_resp_i      (xbar_mst_resp),
    .addr_map_i            (AddrMap),
    .en_default_mst_port_i ('0),
    .default_mst_port_i    ('0)
  );

  // ===========================================================================
  // Output Protocol/Width Conversion
  // ===========================================================================
  // ---------------------------------------------------------------------------
  // Output: smn_inbound_from_xbar (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign smn_inbound_from_xbar_req_o = xbar_mst_req[0];
  assign xbar_mst_resp[0] = smn_inbound_from_xbar_resp_i;

  // ---------------------------------------------------------------------------
  // Output: mailbox (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  // Conversion chain: axi_to_axi_lite
  // Signal declarations
  xbar_out_mailbox_req_t  xbar_out_mailbox_req;
  xbar_out_mailbox_resp_t xbar_out_mailbox_resp;
  mailbox_req_t  mailbox_req;
  mailbox_resp_t mailbox_resp;

  // Xbar to chain connection
  assign xbar_out_mailbox_req = xbar_mst_req[1];
  assign xbar_mst_resp[1] = xbar_out_mailbox_resp;

  // Conversion instances
  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    (56),
    .AxiDataWidth    (64),
    .AxiIdWidth      (7),
    .AxiUserWidth    (12),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .FallThrough     (1'b0),
    .full_req_t      (xbar_out_mailbox_req_t),
    .full_resp_t     (xbar_out_mailbox_resp_t),
    .lite_req_t      (mailbox_req_t),
    .lite_resp_t     (mailbox_resp_t)
  ) u_mailbox_a2l_1 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (xbar_out_mailbox_req),
    .slv_resp_o (xbar_out_mailbox_resp),
    .mst_req_o  (mailbox_req),
    .mst_resp_i (mailbox_resp)
  );

  // Chain to output port connection
  assign mailbox_req_o = mailbox_req;
  assign mailbox_resp = mailbox_resp_i;

  // ---------------------------------------------------------------------------
  // Output: system_csr (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  // Conversion chain: axi_to_axi_lite
  // Signal declarations
  xbar_out_system_csr_req_t  xbar_out_system_csr_req;
  xbar_out_system_csr_resp_t xbar_out_system_csr_resp;
  system_csr_req_t  system_csr_req;
  system_csr_resp_t system_csr_resp;

  // Xbar to chain connection
  assign xbar_out_system_csr_req = xbar_mst_req[2];
  assign xbar_mst_resp[2] = xbar_out_system_csr_resp;

  // Conversion instances
  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    (56),
    .AxiDataWidth    (64),
    .AxiIdWidth      (7),
    .AxiUserWidth    (12),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .FallThrough     (1'b0),
    .full_req_t      (xbar_out_system_csr_req_t),
    .full_resp_t     (xbar_out_system_csr_resp_t),
    .lite_req_t      (system_csr_req_t),
    .lite_resp_t     (system_csr_resp_t)
  ) u_system_csr_a2l_1 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (xbar_out_system_csr_req),
    .slv_resp_o (xbar_out_system_csr_resp),
    .mst_req_o  (system_csr_req),
    .mst_resp_i (system_csr_resp)
  );

  // Chain to output port connection
  assign system_csr_req_o = system_csr_req;
  assign system_csr_resp = system_csr_resp_i;

endmodule : sep_system_peripherals_xbar

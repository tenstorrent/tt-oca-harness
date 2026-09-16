// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

/**
 * @file km_axi_lite_xbar.sv
 * @brief AXI4-Lite crossbar for the Key Manager subsystem.
 *
 * @details Routes transactions from a single KM CPU master port to ten
 *          slave ports:
 *          - Internal: KPV, KMCSR, DRBG Sampler, Mailbox
 *          - External crypto engines: OTBN, AES, KMAC, HMAC, Adams Bridge
 *          - OTP/eFuse (index 8): KM-local window OTP_BASE_ADDR-OTP_END_ADDR,
 *            forwarded to otp_req_o; key_manager.sv remaps addr[31:12] to
 *            OTP_EFUSE_REMAP_BASE[31:12] before driving efuse_req_o.
 *
 *          Uses the PULP axi_lite_xbar IP with address-based routing.
 *          Zero-latency mode is configured (no pipeline stages).
 *
 * @param axil_req_t       AXI-Lite request struct type.
 * @param axil_resp_t      AXI-Lite response struct type.
 * @param axil_aw_chan_t   Write address channel type.
 * @param axil_w_chan_t    Write data channel type.
 * @param axil_b_chan_t    Write response channel type.
 * @param axil_ar_chan_t   Read address channel type.
 * @param axil_r_chan_t    Read data channel type.
 */

module km_axi_lite_xbar
  import km_intf_pkg::*;
  import axi_pkg::*;
#(
  // AXI-Lite interface types
  parameter type axil_req_t  = km_axil_req_t,
  parameter type axil_resp_t = km_axil_resp_t,
  // Channel types (must match the req/resp types)
  parameter type axil_aw_chan_t = km_axil_aw_chan_t,
  parameter type axil_w_chan_t  = km_axil_w_chan_t,
  parameter type axil_b_chan_t  = km_axil_b_chan_t,
  parameter type axil_ar_chan_t = km_axil_ar_chan_t,
  parameter type axil_r_chan_t  = km_axil_r_chan_t
) (
  // Clock and Reset
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_i,

  // Slave Port (from KM CPU)
  input  axil_req_t slv_req_i,
  output axil_resp_t slv_resp_o,

  // Master Ports (to peripherals)
  // Internal peripherals
  output axil_req_t  kpv_req_o,
  input  axil_resp_t kpv_resp_i,

  output axil_req_t  kmcsr_req_o,
  input  axil_resp_t kmcsr_resp_i,

  output axil_req_t  drbg_req_o,
  input  axil_resp_t drbg_resp_i,

  output axil_req_t  mbox_req_o,
  input  axil_resp_t mbox_resp_i,

  // External crypto engine ports
  output axil_req_t  otbn_req_o,
  input  axil_resp_t otbn_resp_i,

  output axil_req_t  aes_req_o,
  input  axil_resp_t aes_resp_i,

  output axil_req_t  kmac_req_o,
  input  axil_resp_t kmac_resp_i,

  output axil_req_t  hmac_req_o,
  input  axil_resp_t hmac_resp_i,

  output axil_req_t  abr_req_o,
  input  axil_resp_t abr_resp_i,

  // OTP/eFuse pass-through port (index 8, OTP_BASE_ADDR-OTP_END_ADDR).
  // Addresses are forwarded unchanged; key_manager.sv applies the
  // OTP_EFUSE_REMAP_BASE remap before driving efuse_req_o.
  output axil_req_t  otp_req_o,
  input  axil_resp_t otp_resp_i
);

  `include "prim_assert.sv"

  //=========================================================================
  // Type Definitions for Crossbar
  //=========================================================================

  /** @brief Address-map rule for axi_lite_xbar (end_addr is 33 bits to handle overflow). */
  typedef struct packed {
    int unsigned idx;
    logic [KM_AXI_ADDR_WIDTH-1:0] start_addr;
    logic [KM_AXI_ADDR_WIDTH:0]   end_addr;  // 33 bits for overflow
  } xbar_rule_t;

  // =========================================================================
  // Crossbar Configuration
  // =========================================================================

  /** @brief PULP axi_lite_xbar configuration: 1 slave, 10 masters, zero-latency. */
  localparam xbar_cfg_t XbarCfg = '{
      NoSlvPorts: 1,  // KM CPU only
      NoMstPorts: 10,  // KPV, KMCSR, DRBG, Mailbox + 5 external (OTBN, AES, KMAC, HMAC, ABR) + OTP
      MaxMstTrans: 2,  // Allow 2 outstanding transactions per master
      MaxSlvTrans: 2,  // Allow 2 outstanding transactions from slave
      FallThrough: 1'b0,  // No fall-through mode
      LatencyMode: NO_LATENCY,  // Zero latency mode
      PipelineStages: 0,  // No pipeline stages
      AxiIdWidthSlvPorts: 1,  // Not used for AXI-Lite, but required
      AxiIdUsedSlvPorts: 1,  // Not used for AXI-Lite, but required
      UniqueIds: 1'b0,  // Not used for AXI-Lite
      SelHashIds: 1'b0,  // Not used for AXI-Lite
      AxiAddrWidth: KM_AXI_ADDR_WIDTH,
      AxiDataWidth: KM_AXI_DATA_WIDTH,
      NoAddrRules:
      10,  // 10 address ranges (KPV, KMCSR, DRBG, MBOX, OTBN, AES, KMAC, HMAC, OTP, ABR)
      default: '0
  };

  // =========================================================================
  // Address Map
  // =========================================================================

  /** @brief Address decode rules mapping master indices to peripheral regions. */
  localparam xbar_rule_t [9:0] AddrMap = '{
      // Index 0: KPV
      '{
          idx: 0,
          start_addr: KPV_BASE_ADDR,
          end_addr: 33'(KPV_END_ADDR + 1'b1)
      },
      // Index 1: KMCSR
      '{
          idx: 1,
          start_addr: KMCSR_BASE_ADDR,
          end_addr: 33'(KMCSR_END_ADDR + 1'b1)
      },
      // Index 2: DRBG Sampler
      '{
          idx: 2,
          start_addr: DRBG_SAMPLER_BASE_ADDR,
          end_addr: 33'(DRBG_SAMPLER_END_ADDR + 1'b1)
      },
      // Index 3: Mailbox
      '{
          idx: 3,
          start_addr: MBOX_BASE_ADDR,
          end_addr: 33'(MBOX_END_ADDR + 1'b1)
      },
      // Index 4: OTBN
      '{
          idx: 4,
          start_addr: OTBN_BASE_ADDR,
          end_addr: 33'(OTBN_END_ADDR + 1'b1)
      },
      // Index 5: AES
      '{
          idx: 5,
          start_addr: AES_BASE_ADDR,
          end_addr: 33'(AES_END_ADDR + 1'b1)
      },
      // Index 6: KMAC
      '{
          idx: 6,
          start_addr: KMAC_BASE_ADDR,
          end_addr: 33'(KMAC_END_ADDR + 1'b1)
      },
      // Index 7: HMAC
      '{
          idx: 7,
          start_addr: HMAC_BASE_ADDR,
          end_addr: 33'(HMAC_END_ADDR + 1'b1)
      },
      // Index 8: OTP/eFuse
      '{
          idx: 8,
          start_addr: OTP_BASE_ADDR,
          end_addr: 33'(OTP_END_ADDR + 1'b1)
      },
      // Index 9: Adams Bridge
      '{
          idx: 9,
          start_addr: ABR_BASE_ADDR,
          end_addr: 33'(ABR_END_ADDR + 1'b1)
      }
  };

  //=========================================================================
  // Address Map Validation
  //=========================================================================
  // A slave keeps only the low address bits of its own decode window, so a
  // rule has to be a power of two and aligned to its base, or the slave's
  // registers repeat under a second set of addresses inside the same rule.
  // The window sizes come from the generated register packages, but a moved
  // base or an added rule can still break either property.

  /** @brief Every rule is a power of two in size and aligned to that size. */
  function automatic bit km_addr_map_aligned();
    logic [KM_AXI_ADDR_WIDTH:0] base;
    logic [KM_AXI_ADDR_WIDTH:0] size;
    for (int unsigned i = 0; i < XbarCfg.NoAddrRules; i++) begin
      base = {1'b0, AddrMap[i].start_addr};
      size = AddrMap[i].end_addr - base;
      if (size == '0) return 1'b0;
      if ((size & (size - 1)) != '0) return 1'b0;
      if ((base & (size - 1)) != '0) return 1'b0;
    end
    return 1'b1;
  endfunction

  /** @brief No two rules cover a common address. */
  function automatic bit km_addr_map_disjoint();
    for (int unsigned i = 0; i < XbarCfg.NoAddrRules; i++) begin
      for (int unsigned j = i + 1; j < XbarCfg.NoAddrRules; j++) begin
        if (({1'b0, AddrMap[i].start_addr} < AddrMap[j].end_addr) &&
                    ({1'b0, AddrMap[j].start_addr} < AddrMap[i].end_addr)) begin
          return 1'b0;
        end
      end
    end
    return 1'b1;
  endfunction

  `OCAH_OT_ASSERT_INIT(AddrMapAligned_A, km_addr_map_aligned())
  `OCAH_OT_ASSERT_INIT(AddrMapDisjoint_A, km_addr_map_disjoint())

  //=========================================================================
  // Internal Crossbar Signals
  //=========================================================================

  // Slave port (from CPU)
  axil_req_t  [0:0] xbar_slv_req;
  axil_resp_t [0:0] xbar_slv_resp;

  // Master ports (to peripherals)
  axil_req_t  [9:0] xbar_mst_req;
  axil_resp_t [9:0] xbar_mst_resp;

  // Connect slave port to crossbar array
  assign xbar_slv_req[0] = slv_req_i;
  assign slv_resp_o = xbar_slv_resp[0];

  //=========================================================================
  // AXI-Lite Crossbar Instantiation
  //=========================================================================

  axi_lite_xbar #(
    .Cfg        (XbarCfg),
    .aw_chan_t  (axil_aw_chan_t),
    .w_chan_t   (axil_w_chan_t),
    .b_chan_t   (axil_b_chan_t),
    .ar_chan_t  (axil_ar_chan_t),
    .r_chan_t   (axil_r_chan_t),
    .axi_req_t  (axil_req_t),
    .axi_resp_t (axil_resp_t),
    .rule_t     (xbar_rule_t)
  ) u_axi_lite_xbar (
    .clk_i                  (clk_i),
    .rst_ni                 (rst_ni),
    .test_i                 (test_i),
    .slv_ports_req_i        (xbar_slv_req),
    .slv_ports_resp_o       (xbar_slv_resp),
    .mst_ports_req_o        (xbar_mst_req),
    .mst_ports_resp_i       (xbar_mst_resp),
    .addr_map_i             (AddrMap),
    .en_default_mst_port_i  ('0),
    .default_mst_port_i     ('0)
  );

  //=========================================================================
  // Master Port Output Conversion: xbar internal -> parameterized axil_*
  //=========================================================================

  // KPV (index 0)
  assign kpv_req_o.aw.addr   = xbar_mst_req[0].aw.addr;
  assign kpv_req_o.aw.prot   = xbar_mst_req[0].aw.prot;
  assign kpv_req_o.aw_valid  = xbar_mst_req[0].aw_valid;
  assign kpv_req_o.w.data    = xbar_mst_req[0].w.data;
  assign kpv_req_o.w.strb    = xbar_mst_req[0].w.strb;
  assign kpv_req_o.w_valid   = xbar_mst_req[0].w_valid;
  assign kpv_req_o.b_ready   = xbar_mst_req[0].b_ready;
  assign kpv_req_o.ar.addr   = xbar_mst_req[0].ar.addr;
  assign kpv_req_o.ar.prot   = xbar_mst_req[0].ar.prot;
  assign kpv_req_o.ar_valid  = xbar_mst_req[0].ar_valid;
  assign kpv_req_o.r_ready   = xbar_mst_req[0].r_ready;
  assign xbar_mst_resp[0].aw_ready = kpv_resp_i.aw_ready;
  assign xbar_mst_resp[0].w_ready   = kpv_resp_i.w_ready;
  assign xbar_mst_resp[0].b.resp    = kpv_resp_i.b.resp;
  assign xbar_mst_resp[0].b_valid   = kpv_resp_i.b_valid;
  assign xbar_mst_resp[0].ar_ready  = kpv_resp_i.ar_ready;
  assign xbar_mst_resp[0].r.data    = kpv_resp_i.r.data;
  assign xbar_mst_resp[0].r.resp    = kpv_resp_i.r.resp;
  assign xbar_mst_resp[0].r_valid   = kpv_resp_i.r_valid;

  // KMCSR (index 1)
  assign kmcsr_req_o.aw.addr  = xbar_mst_req[1].aw.addr;
  assign kmcsr_req_o.aw.prot  = xbar_mst_req[1].aw.prot;
  assign kmcsr_req_o.aw_valid = xbar_mst_req[1].aw_valid;
  assign kmcsr_req_o.w.data   = xbar_mst_req[1].w.data;
  assign kmcsr_req_o.w.strb   = xbar_mst_req[1].w.strb;
  assign kmcsr_req_o.w_valid  = xbar_mst_req[1].w_valid;
  assign kmcsr_req_o.b_ready  = xbar_mst_req[1].b_ready;
  assign kmcsr_req_o.ar.addr  = xbar_mst_req[1].ar.addr;
  assign kmcsr_req_o.ar.prot  = xbar_mst_req[1].ar.prot;
  assign kmcsr_req_o.ar_valid = xbar_mst_req[1].ar_valid;
  assign kmcsr_req_o.r_ready  = xbar_mst_req[1].r_ready;
  assign xbar_mst_resp[1].aw_ready = kmcsr_resp_i.aw_ready;
  assign xbar_mst_resp[1].w_ready   = kmcsr_resp_i.w_ready;
  assign xbar_mst_resp[1].b.resp     = kmcsr_resp_i.b.resp;
  assign xbar_mst_resp[1].b_valid    = kmcsr_resp_i.b_valid;
  assign xbar_mst_resp[1].ar_ready   = kmcsr_resp_i.ar_ready;
  assign xbar_mst_resp[1].r.data     = kmcsr_resp_i.r.data;
  assign xbar_mst_resp[1].r.resp     = kmcsr_resp_i.r.resp;
  assign xbar_mst_resp[1].r_valid    = kmcsr_resp_i.r_valid;

  // DRBG Sampler (index 2)
  assign drbg_req_o.aw.addr   = xbar_mst_req[2].aw.addr;
  assign drbg_req_o.aw.prot   = xbar_mst_req[2].aw.prot;
  assign drbg_req_o.aw_valid  = xbar_mst_req[2].aw_valid;
  assign drbg_req_o.w.data    = xbar_mst_req[2].w.data;
  assign drbg_req_o.w.strb    = xbar_mst_req[2].w.strb;
  assign drbg_req_o.w_valid   = xbar_mst_req[2].w_valid;
  assign drbg_req_o.b_ready   = xbar_mst_req[2].b_ready;
  assign drbg_req_o.ar.addr   = xbar_mst_req[2].ar.addr;
  assign drbg_req_o.ar.prot   = xbar_mst_req[2].ar.prot;
  assign drbg_req_o.ar_valid  = xbar_mst_req[2].ar_valid;
  assign drbg_req_o.r_ready   = xbar_mst_req[2].r_ready;
  assign xbar_mst_resp[2].aw_ready = drbg_resp_i.aw_ready;
  assign xbar_mst_resp[2].w_ready   = drbg_resp_i.w_ready;
  assign xbar_mst_resp[2].b.resp    = drbg_resp_i.b.resp;
  assign xbar_mst_resp[2].b_valid   = drbg_resp_i.b_valid;
  assign xbar_mst_resp[2].ar_ready   = drbg_resp_i.ar_ready;
  assign xbar_mst_resp[2].r.data    = drbg_resp_i.r.data;
  assign xbar_mst_resp[2].r.resp    = drbg_resp_i.r.resp;
  assign xbar_mst_resp[2].r_valid   = drbg_resp_i.r_valid;

  // Mailbox (index 3)
  assign mbox_req_o.aw.addr   = xbar_mst_req[3].aw.addr;
  assign mbox_req_o.aw.prot   = xbar_mst_req[3].aw.prot;
  assign mbox_req_o.aw_valid  = xbar_mst_req[3].aw_valid;
  assign mbox_req_o.w.data    = xbar_mst_req[3].w.data;
  assign mbox_req_o.w.strb    = xbar_mst_req[3].w.strb;
  assign mbox_req_o.w_valid   = xbar_mst_req[3].w_valid;
  assign mbox_req_o.b_ready   = xbar_mst_req[3].b_ready;
  assign mbox_req_o.ar.addr   = xbar_mst_req[3].ar.addr;
  assign mbox_req_o.ar.prot   = xbar_mst_req[3].ar.prot;
  assign mbox_req_o.ar_valid  = xbar_mst_req[3].ar_valid;
  assign mbox_req_o.r_ready   = xbar_mst_req[3].r_ready;
  assign xbar_mst_resp[3].aw_ready = mbox_resp_i.aw_ready;
  assign xbar_mst_resp[3].w_ready   = mbox_resp_i.w_ready;
  assign xbar_mst_resp[3].b.resp    = mbox_resp_i.b.resp;
  assign xbar_mst_resp[3].b_valid   = mbox_resp_i.b_valid;
  assign xbar_mst_resp[3].ar_ready  = mbox_resp_i.ar_ready;
  assign xbar_mst_resp[3].r.data    = mbox_resp_i.r.data;
  assign xbar_mst_resp[3].r.resp    = mbox_resp_i.r.resp;
  assign xbar_mst_resp[3].r_valid   = mbox_resp_i.r_valid;

  // OTBN (index 4)
  assign otbn_req_o.aw.addr   = xbar_mst_req[4].aw.addr;
  assign otbn_req_o.aw.prot   = xbar_mst_req[4].aw.prot;
  assign otbn_req_o.aw_valid  = xbar_mst_req[4].aw_valid;
  assign otbn_req_o.w.data    = xbar_mst_req[4].w.data;
  assign otbn_req_o.w.strb    = xbar_mst_req[4].w.strb;
  assign otbn_req_o.w_valid   = xbar_mst_req[4].w_valid;
  assign otbn_req_o.b_ready   = xbar_mst_req[4].b_ready;
  assign otbn_req_o.ar.addr   = xbar_mst_req[4].ar.addr;
  assign otbn_req_o.ar.prot   = xbar_mst_req[4].ar.prot;
  assign otbn_req_o.ar_valid  = xbar_mst_req[4].ar_valid;
  assign otbn_req_o.r_ready   = xbar_mst_req[4].r_ready;
  assign xbar_mst_resp[4].aw_ready = otbn_resp_i.aw_ready;
  assign xbar_mst_resp[4].w_ready   = otbn_resp_i.w_ready;
  assign xbar_mst_resp[4].b.resp    = otbn_resp_i.b.resp;
  assign xbar_mst_resp[4].b_valid   = otbn_resp_i.b_valid;
  assign xbar_mst_resp[4].ar_ready   = otbn_resp_i.ar_ready;
  assign xbar_mst_resp[4].r.data    = otbn_resp_i.r.data;
  assign xbar_mst_resp[4].r.resp    = otbn_resp_i.r.resp;
  assign xbar_mst_resp[4].r_valid   = otbn_resp_i.r_valid;

  // AES (index 5)
  assign aes_req_o.aw.addr    = xbar_mst_req[5].aw.addr;
  assign aes_req_o.aw.prot    = xbar_mst_req[5].aw.prot;
  assign aes_req_o.aw_valid   = xbar_mst_req[5].aw_valid;
  assign aes_req_o.w.data     = xbar_mst_req[5].w.data;
  assign aes_req_o.w.strb     = xbar_mst_req[5].w.strb;
  assign aes_req_o.w_valid    = xbar_mst_req[5].w_valid;
  assign aes_req_o.b_ready    = xbar_mst_req[5].b_ready;
  assign aes_req_o.ar.addr    = xbar_mst_req[5].ar.addr;
  assign aes_req_o.ar.prot    = xbar_mst_req[5].ar.prot;
  assign aes_req_o.ar_valid   = xbar_mst_req[5].ar_valid;
  assign aes_req_o.r_ready    = xbar_mst_req[5].r_ready;
  assign xbar_mst_resp[5].aw_ready = aes_resp_i.aw_ready;
  assign xbar_mst_resp[5].w_ready   = aes_resp_i.w_ready;
  assign xbar_mst_resp[5].b.resp    = aes_resp_i.b.resp;
  assign xbar_mst_resp[5].b_valid   = aes_resp_i.b_valid;
  assign xbar_mst_resp[5].ar_ready  = aes_resp_i.ar_ready;
  assign xbar_mst_resp[5].r.data    = aes_resp_i.r.data;
  assign xbar_mst_resp[5].r.resp    = aes_resp_i.r.resp;
  assign xbar_mst_resp[5].r_valid   = aes_resp_i.r_valid;

  // KMAC (index 6)
  assign kmac_req_o.aw.addr   = xbar_mst_req[6].aw.addr;
  assign kmac_req_o.aw.prot   = xbar_mst_req[6].aw.prot;
  assign kmac_req_o.aw_valid  = xbar_mst_req[6].aw_valid;
  assign kmac_req_o.w.data    = xbar_mst_req[6].w.data;
  assign kmac_req_o.w.strb    = xbar_mst_req[6].w.strb;
  assign kmac_req_o.w_valid   = xbar_mst_req[6].w_valid;
  assign kmac_req_o.b_ready   = xbar_mst_req[6].b_ready;
  assign kmac_req_o.ar.addr   = xbar_mst_req[6].ar.addr;
  assign kmac_req_o.ar.prot   = xbar_mst_req[6].ar.prot;
  assign kmac_req_o.ar_valid  = xbar_mst_req[6].ar_valid;
  assign kmac_req_o.r_ready   = xbar_mst_req[6].r_ready;
  assign xbar_mst_resp[6].aw_ready = kmac_resp_i.aw_ready;
  assign xbar_mst_resp[6].w_ready   = kmac_resp_i.w_ready;
  assign xbar_mst_resp[6].b.resp    = kmac_resp_i.b.resp;
  assign xbar_mst_resp[6].b_valid   = kmac_resp_i.b_valid;
  assign xbar_mst_resp[6].ar_ready  = kmac_resp_i.ar_ready;
  assign xbar_mst_resp[6].r.data    = kmac_resp_i.r.data;
  assign xbar_mst_resp[6].r.resp    = kmac_resp_i.r.resp;
  assign xbar_mst_resp[6].r_valid   = kmac_resp_i.r_valid;

  // HMAC (index 7)
  assign hmac_req_o.aw.addr   = xbar_mst_req[7].aw.addr;
  assign hmac_req_o.aw.prot   = xbar_mst_req[7].aw.prot;
  assign hmac_req_o.aw_valid  = xbar_mst_req[7].aw_valid;
  assign hmac_req_o.w.data    = xbar_mst_req[7].w.data;
  assign hmac_req_o.w.strb    = xbar_mst_req[7].w.strb;
  assign hmac_req_o.w_valid   = xbar_mst_req[7].w_valid;
  assign hmac_req_o.b_ready   = xbar_mst_req[7].b_ready;
  assign hmac_req_o.ar.addr   = xbar_mst_req[7].ar.addr;
  assign hmac_req_o.ar.prot   = xbar_mst_req[7].ar.prot;
  assign hmac_req_o.ar_valid  = xbar_mst_req[7].ar_valid;
  assign hmac_req_o.r_ready   = xbar_mst_req[7].r_ready;
  assign xbar_mst_resp[7].aw_ready = hmac_resp_i.aw_ready;
  assign xbar_mst_resp[7].w_ready   = hmac_resp_i.w_ready;
  assign xbar_mst_resp[7].b.resp    = hmac_resp_i.b.resp;
  assign xbar_mst_resp[7].b_valid   = hmac_resp_i.b_valid;
  assign xbar_mst_resp[7].ar_ready  = hmac_resp_i.ar_ready;
  assign xbar_mst_resp[7].r.data    = hmac_resp_i.r.data;
  assign xbar_mst_resp[7].r.resp    = hmac_resp_i.r.resp;
  assign xbar_mst_resp[7].r_valid   = hmac_resp_i.r_valid;

  // Adams Bridge (index 9)
  assign abr_req_o.aw.addr    = xbar_mst_req[9].aw.addr;
  assign abr_req_o.aw.prot    = xbar_mst_req[9].aw.prot;
  assign abr_req_o.aw_valid   = xbar_mst_req[9].aw_valid;
  assign abr_req_o.w.data     = xbar_mst_req[9].w.data;
  assign abr_req_o.w.strb     = xbar_mst_req[9].w.strb;
  assign abr_req_o.w_valid    = xbar_mst_req[9].w_valid;
  assign abr_req_o.b_ready    = xbar_mst_req[9].b_ready;
  assign abr_req_o.ar.addr    = xbar_mst_req[9].ar.addr;
  assign abr_req_o.ar.prot    = xbar_mst_req[9].ar.prot;
  assign abr_req_o.ar_valid   = xbar_mst_req[9].ar_valid;
  assign abr_req_o.r_ready    = xbar_mst_req[9].r_ready;
  assign xbar_mst_resp[9].aw_ready = abr_resp_i.aw_ready;
  assign xbar_mst_resp[9].w_ready  = abr_resp_i.w_ready;
  assign xbar_mst_resp[9].b.resp   = abr_resp_i.b.resp;
  assign xbar_mst_resp[9].b_valid  = abr_resp_i.b_valid;
  assign xbar_mst_resp[9].ar_ready = abr_resp_i.ar_ready;
  assign xbar_mst_resp[9].r.data   = abr_resp_i.r.data;
  assign xbar_mst_resp[9].r.resp   = abr_resp_i.r.resp;
  assign xbar_mst_resp[9].r_valid  = abr_resp_i.r_valid;

  // OTP/eFuse (index 8)
  assign otp_req_o.aw.addr    = xbar_mst_req[8].aw.addr;
  assign otp_req_o.aw.prot    = xbar_mst_req[8].aw.prot;
  assign otp_req_o.aw_valid   = xbar_mst_req[8].aw_valid;
  assign otp_req_o.w.data     = xbar_mst_req[8].w.data;
  assign otp_req_o.w.strb     = xbar_mst_req[8].w.strb;
  assign otp_req_o.w_valid    = xbar_mst_req[8].w_valid;
  assign otp_req_o.b_ready    = xbar_mst_req[8].b_ready;
  assign otp_req_o.ar.addr    = xbar_mst_req[8].ar.addr;
  assign otp_req_o.ar.prot    = xbar_mst_req[8].ar.prot;
  assign otp_req_o.ar_valid   = xbar_mst_req[8].ar_valid;
  assign otp_req_o.r_ready    = xbar_mst_req[8].r_ready;
  assign xbar_mst_resp[8].aw_ready = otp_resp_i.aw_ready;
  assign xbar_mst_resp[8].w_ready  = otp_resp_i.w_ready;
  assign xbar_mst_resp[8].b.resp   = otp_resp_i.b.resp;
  assign xbar_mst_resp[8].b_valid  = otp_resp_i.b_valid;
  assign xbar_mst_resp[8].ar_ready = otp_resp_i.ar_ready;
  assign xbar_mst_resp[8].r.data   = otp_resp_i.r.data;
  assign xbar_mst_resp[8].r.resp   = otp_resp_i.r.resp;
  assign xbar_mst_resp[8].r_valid  = otp_resp_i.r_valid;

endmodule : km_axi_lite_xbar


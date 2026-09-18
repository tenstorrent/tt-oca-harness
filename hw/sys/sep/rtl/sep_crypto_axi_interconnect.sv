// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP crypto AXI fabric: 13-port host decode, bus-width conversion, and
// transaction-draining isolation for internal TRNG, accelerator, and Key
// Manager paths.

`include "axi/typedef.svh"

module sep_crypto_axi_interconnect (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,

  // Full AXI4 slave from local crossbar
  input  sep_pkg::sep_32_64_6_12_axi_req_t   sep_crypto_axi_req_i,
  output sep_pkg::sep_32_64_6_12_axi_resp_t  sep_crypto_axi_resp_o,

  // Isolation handshake with sep_reset_ctrl
  input  sep_pkg::sep_crypto_isolate_t       isolate_req_i,
  output sep_pkg::sep_crypto_isolate_t       isolated_o,

  // Isolated host CSR buses to the accelerator wrappers (32-bit AXI-Lite)
  output sep_pkg::sep_32_32_axil_req_t       otbn_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      otbn_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       hmac_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      hmac_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       aes_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      aes_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       kmac_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      kmac_axil_isolated_resp_i,

  // Isolated full-AXI host bus to Adams Bridge
  output sep_pkg::sep_32_64_6_12_axi_req_t   abr_axi_isolated_req_o,
  input  sep_pkg::sep_32_64_6_12_axi_resp_t  abr_axi_isolated_resp_i,

  // KM key-bus slave ports (from key_manager master ports)
  input  sep_pkg::sep_32_32_axil_req_t       otbn_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t      otbn_key_axil_resp_o,
  input  sep_pkg::sep_32_32_axil_req_t       aes_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t      aes_key_axil_resp_o,
  input  sep_pkg::sep_32_32_axil_req_t       hmac_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t      hmac_key_axil_resp_o,
  input  sep_pkg::sep_32_32_axil_req_t       kmac_key_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t      kmac_key_axil_resp_o,
  input  km_intf_pkg::km_axil_req_t          abr_key_axil_req_i,
  output km_intf_pkg::km_axil_resp_t         abr_key_axil_resp_o,
  input  km_intf_pkg::km_axil_req_t          km_efuse_axil_req_i,
  output km_intf_pkg::km_axil_resp_t         km_efuse_axil_resp_o,

  // Isolated KM key buses (to the wrapper key CSRs / ABR key CSR / efuse)
  output sep_pkg::sep_32_32_axil_req_t       otbn_key_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      otbn_key_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       aes_key_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      aes_key_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       hmac_key_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      hmac_key_axil_isolated_resp_i,
  output sep_pkg::sep_32_32_axil_req_t       kmac_key_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      kmac_key_axil_isolated_resp_i,
  output km_intf_pkg::km_axil_req_t          abr_key_axil_isolated_req_o,
  input  km_intf_pkg::km_axil_resp_t         abr_key_axil_isolated_resp_i,
  output km_intf_pkg::km_axil_req_t          km_efuse_axil_isolated_req_o,
  input  km_intf_pkg::km_axil_resp_t         km_efuse_axil_isolated_resp_i,

  // KM mailbox AXI-Lite master (converted host path, not isolated)
  output km_intf_pkg::km_axil_req_t          km_mbox_axil_req_o,
  input  km_intf_pkg::km_axil_resp_t         km_mbox_axil_resp_i,

  // Converted and isolated AXI-Lite CSR buses to the internal TRNG complex
  output sep_pkg::sep_32_32_axil_req_t       esrc_axil_isolated_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      esrc_axil_isolated_resp_i,
  output drbg_pkg::drbg_axil64_req_t         csrng_axil_isolated_req_o,
  input  drbg_pkg::drbg_axil64_resp_t        csrng_axil_isolated_resp_i,
  output drbg_pkg::drbg_axil64_req_t         edn_axil_isolated_req_o,
  input  drbg_pkg::drbg_axil64_resp_t        edn_axil_isolated_resp_i,

  // External TRNG AXI-Lite passthrough
  output sep_pkg::sep_32_32_axil_req_t       ext_trng_axil_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      ext_trng_axil_resp_i,

  // Full AXI4 passthrough masters
  output sep_pkg::sep_32_64_6_12_axi_req_t   fuse_axi_req_o,
  input  sep_pkg::sep_32_64_6_12_axi_resp_t  fuse_axi_resp_i,
  output sep_pkg::sep_32_64_6_12_axi_req_t   lifecycle_axi_req_o,
  input  sep_pkg::sep_32_64_6_12_axi_resp_t  lifecycle_axi_resp_i
);

  // Drain depth of every isolate matches the crypto demux transaction limit.
  // Host-path axi_to_axi_lite instances use the same limit.
  localparam int unsigned ISOLATE_NUM_PENDING = 4;

  sep_pkg::sep_32_64_6_12_axi_req_t  [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST-1:0] sep_crypto_axi_reqs;
  sep_pkg::sep_32_64_6_12_axi_resp_t [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST-1:0] sep_crypto_axi_resps;
  sep_pkg::sep_32_64_6_12_axi_req_t  abr_axi_isolated_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t abr_axi_isolated_resp;

  ////////////////
  // AXI4 Demux //
  ////////////////

  logic otbn_write, otbn_read, hmac_write, hmac_read;
  logic aes_write, aes_read, kmac_write, kmac_read;
  logic fuse_write, fuse_read, lifecycle_write, lifecycle_read;
  logic km_write, km_read;
  logic csrng_write, csrng_read, edn_write, edn_read;
  logic entropy_src_write, entropy_src_read, trng_write, trng_read;
  logic abr_write, abr_read;  // Adams Bridge PQC
  logic aw_is_burst, ar_is_burst;
  logic [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL-1:0] aw_select, ar_select;

  assign aw_is_burst = (|sep_crypto_axi_req_i.aw.len);
  assign ar_is_burst = (|sep_crypto_axi_req_i.ar.len);

  always_comb begin
    otbn_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::otbn_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::otbn_rule.end_addr);
    otbn_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::otbn_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::otbn_rule.end_addr);

    hmac_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::hmac_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::hmac_rule.end_addr);
    hmac_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::hmac_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::hmac_rule.end_addr);

    aes_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::aes_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::aes_rule.end_addr);
    aes_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::aes_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::aes_rule.end_addr);

    kmac_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::kmac_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::kmac_rule.end_addr);
    kmac_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::kmac_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::kmac_rule.end_addr);

    fuse_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::fuse_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::fuse_rule.end_addr);
    fuse_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::fuse_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::fuse_rule.end_addr);

    lifecycle_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::lifecycle_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::lifecycle_rule.end_addr);
    lifecycle_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::lifecycle_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::lifecycle_rule.end_addr);

    km_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::km_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::km_rule.end_addr);
    km_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::km_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::km_rule.end_addr);

    csrng_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::csrng_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::csrng_rule.end_addr);
    csrng_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::csrng_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::csrng_rule.end_addr);

    edn_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::edn_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::edn_rule.end_addr);
    edn_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::edn_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::edn_rule.end_addr);

    entropy_src_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::entropy_source_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::entropy_source_rule.end_addr);
    entropy_src_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::entropy_source_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::entropy_source_rule.end_addr);

    trng_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::trng_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::trng_rule.end_addr);
    trng_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::trng_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::trng_rule.end_addr);

    abr_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::abr_rule.start_addr) &&
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::abr_rule.end_addr);
    abr_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::abr_rule.start_addr) &&
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::abr_rule.end_addr);

    if (aw_is_burst) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiErrSlv);
    end else if (abr_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiAbr);
    end else if (trng_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiTrng);
    end else if (entropy_src_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiEntropySrc);
    end else if (edn_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiEdn);
    end else if (csrng_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiCsrng);
    end else if (km_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiKm);
    end else if (lifecycle_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiLifecycle);
    end else if (fuse_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiFuse);
    end else if (kmac_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiKmac);
    end else if (aes_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiAes);
    end else if (hmac_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiHmac);
    end else if (otbn_write) begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiOtbn);
    end else begin
      aw_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiErrSlv);
    end

    if (ar_is_burst) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiErrSlv);
    end else if (abr_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiAbr);
    end else if (trng_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiTrng);
    end else if (entropy_src_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiEntropySrc);
    end else if (edn_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiEdn);
    end else if (csrng_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiCsrng);
    end else if (km_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiKm);
    end else if (lifecycle_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiLifecycle);
    end else if (fuse_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiFuse);
    end else if (kmac_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiKmac);
    end else if (aes_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiAes);
    end else if (hmac_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiHmac);
    end else if (otbn_read) begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiOtbn);
    end else begin
      ar_select = sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL'(sep_crypto_pkg::SepCryptoAxiErrSlv);
    end
  end

  axi_demux #(
    .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AtopSupport     (1'b0),
    .aw_chan_t       (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t        (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t       (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .NoMstPorts      (sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST),
    .MaxTrans        (4),
    .AxiLookBits     (2),
    .UniqueIds       (1'b0),
    .SelHashIds      (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b1),
    .SpillB          (1'b1),
    .SpillAr         (1'b1),
    .SpillR          (1'b1)
  ) axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .sel_hash_i      (2'h0),

    .slv_req_i       (sep_crypto_axi_req_i),
    .slv_aw_select_i (aw_select),
    .slv_ar_select_i (ar_select),
    .slv_resp_o      (sep_crypto_axi_resp_o),
    .mst_reqs_o      (sep_crypto_axi_reqs),
    .mst_resps_i     (sep_crypto_axi_resps)
  );

  axi_err_slv #(
    .AxiIdWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .ATOPs      (1'b0),
    .MaxTrans   (1)
  ) axi_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiErrSlv]),
    .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiErrSlv])
  );

  /////////////////////////////////////////
  // Host paths to accelerator wrappers  //
  // 64b AXI -> 32b AXI-Lite -> isolate  //
  /////////////////////////////////////////

  sep_pkg::sep_32_32_axil_req_t
      otbn_conv_axil_req, hmac_conv_axil_req, aes_conv_axil_req, kmac_conv_axil_req;
  sep_pkg::sep_32_32_axil_resp_t
      otbn_conv_axil_resp, hmac_conv_axil_resp, aes_conv_axil_resp, kmac_conv_axil_resp;

  // ---- OTBN ----

  // Force the AXCACHE modifiable bit on the OTBN path: VeeR EL2 may issue
  // cache=0 for MMIO, and the downstream axi_to_axi_lite burst splitter
  // requires cache[1]=1 to accept the len=1 bursts the dw converter makes
  // from 64-bit beats.
  sep_pkg::sep_32_64_6_12_axi_req_t otbn_axi_req_cache_forced;

  always_comb begin
    otbn_axi_req_cache_forced = sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiOtbn];
    otbn_axi_req_cache_forced.aw.cache =
            sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiOtbn].aw.cache | axi_pkg::CACHE_MODIFIABLE;
    otbn_axi_req_cache_forced.ar.cache =
            sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiOtbn].ar.cache | axi_pkg::CACHE_MODIFIABLE;
  end

  sep_pkg::sep_32_32_6_12_axi_req_t  otbn_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t otbn_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_otbn_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (otbn_axi_req_cache_forced),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiOtbn]),
    .mst_req_o (otbn_axi32_req),
    .mst_resp_i(otbn_axi32_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_otbn_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (otbn_axi32_req),
    .slv_resp_o  (otbn_axi32_resp),
    .mst_req_o   (otbn_conv_axil_req),
    .mst_resp_i  (otbn_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_otbn_host_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (otbn_conv_axil_req),
    .slv_resp_o (otbn_conv_axil_resp),
    .mst_req_o  (otbn_axil_isolated_req_o),
    .mst_resp_i (otbn_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.host_otbn),
    .isolated_o (isolated_o.host_otbn)
  );

  // ---- HMAC ----

  sep_pkg::sep_32_32_6_12_axi_req_t  hmac_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t hmac_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_hmac_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiHmac]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiHmac]),
    .mst_req_o (hmac_axi32_req),
    .mst_resp_i(hmac_axi32_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_hmac_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (hmac_axi32_req),
    .slv_resp_o  (hmac_axi32_resp),
    .mst_req_o   (hmac_conv_axil_req),
    .mst_resp_i  (hmac_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_hmac_host_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (hmac_conv_axil_req),
    .slv_resp_o (hmac_conv_axil_resp),
    .mst_req_o  (hmac_axil_isolated_req_o),
    .mst_resp_i (hmac_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.host_hmac),
    .isolated_o (isolated_o.host_hmac)
  );

  // ---- AES ----

  sep_pkg::sep_32_32_6_12_axi_req_t  aes_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t aes_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_aes_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiAes]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiAes]),
    .mst_req_o (aes_axi32_req),
    .mst_resp_i(aes_axi32_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_aes_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (aes_axi32_req),
    .slv_resp_o  (aes_axi32_resp),
    .mst_req_o   (aes_conv_axil_req),
    .mst_resp_i  (aes_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_aes_host_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (aes_conv_axil_req),
    .slv_resp_o (aes_conv_axil_resp),
    .mst_req_o  (aes_axil_isolated_req_o),
    .mst_resp_i (aes_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.host_aes),
    .isolated_o (isolated_o.host_aes)
  );

  // ---- KMAC ----

  sep_pkg::sep_32_32_6_12_axi_req_t  kmac_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t kmac_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_kmac_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiKmac]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiKmac]),
    .mst_req_o (kmac_axi32_req),
    .mst_resp_i(kmac_axi32_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_kmac_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (kmac_axi32_req),
    .slv_resp_o  (kmac_axi32_resp),
    .mst_req_o   (kmac_conv_axil_req),
    .mst_resp_i  (kmac_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_kmac_host_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (kmac_conv_axil_req),
    .slv_resp_o (kmac_conv_axil_resp),
    .mst_req_o  (kmac_axil_isolated_req_o),
    .mst_resp_i (kmac_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.host_kmac),
    .isolated_o (isolated_o.host_kmac)
  );

  //////////////////////////////////
  // KM master path isolates      //
  //////////////////////////////////
  // The KM key buses pass through unmodified in normal operation; the
  // isolates drain them before either endpoint's reset may assert.

  // KM -> sep_crypto_otbn_wrapper key CSRs
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_otbn_key_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (otbn_key_axil_req_i),
    .slv_resp_o (otbn_key_axil_resp_o),
    .mst_req_o  (otbn_key_axil_isolated_req_o),
    .mst_resp_i (otbn_key_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_otbn),
    .isolated_o (isolated_o.km_otbn)
  );

  // KM -> aes_wrapper key CSRs
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_aes_key_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (aes_key_axil_req_i),
    .slv_resp_o (aes_key_axil_resp_o),
    .mst_req_o  (aes_key_axil_isolated_req_o),
    .mst_resp_i (aes_key_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_aes),
    .isolated_o (isolated_o.km_aes)
  );

  // KM -> hmac_wrapper key CSRs
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_hmac_key_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (hmac_key_axil_req_i),
    .slv_resp_o (hmac_key_axil_resp_o),
    .mst_req_o  (hmac_key_axil_isolated_req_o),
    .mst_resp_i (hmac_key_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_hmac),
    .isolated_o (isolated_o.km_hmac)
  );

  // KM -> kmac_wrapper key CSRs
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_kmac_key_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (kmac_key_axil_req_i),
    .slv_resp_o (kmac_key_axil_resp_o),
    .mst_req_o  (kmac_key_axil_isolated_req_o),
    .mst_resp_i (kmac_key_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_kmac),
    .isolated_o (isolated_o.km_kmac)
  );

  // KM -> ABR sideload key CSRs
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (km_intf_pkg::KM_AXI_ADDR_WIDTH),
    .AxiDataWidth         (km_intf_pkg::KM_AXI_DATA_WIDTH),
    .axi_lite_req_t       (km_intf_pkg::km_axil_req_t),
    .axi_lite_resp_t      (km_intf_pkg::km_axil_resp_t)
  ) u_abr_key_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (abr_key_axil_req_i),
    .slv_resp_o (abr_key_axil_resp_o),
    .mst_req_o  (abr_key_axil_isolated_req_o),
    .mst_resp_i (abr_key_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_abr),
    .isolated_o (isolated_o.km_abr)
  );

  // KM -> sep_efuse_wrapper
  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (km_intf_pkg::KM_AXI_ADDR_WIDTH),
    .AxiDataWidth         (km_intf_pkg::KM_AXI_DATA_WIDTH),
    .axi_lite_req_t       (km_intf_pkg::km_axil_req_t),
    .axi_lite_resp_t      (km_intf_pkg::km_axil_resp_t)
  ) u_km_efuse_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (km_efuse_axil_req_i),
    .slv_resp_o (km_efuse_axil_resp_o),
    .mst_req_o  (km_efuse_axil_isolated_req_o),
    .mst_resp_i (km_efuse_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.km_efuse),
    .isolated_o (isolated_o.km_efuse)
  );

  ///////////////////////////////////////
  // Converted, non-isolated paths     //
  ///////////////////////////////////////

  //=========================================================================
  // Key Manager AXI4-64 to AXI-Lite-32 Conversion (demux port [7])
  //=========================================================================
  // Two-stage conversion:
  //   Stage 1: axi_dw_converter  (64-bit AXI4 -> 32-bit AXI4)
  //   Stage 2: axi_to_axi_lite   (32-bit AXI4 -> 32-bit AXI-Lite)

  sep_pkg::sep_32_32_6_12_axi_req_t  km_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t km_axi32_resp;

  // Stage 1: AXI Data Width Converter (64-bit -> 32-bit)
  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),  // 64-bit input
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),  // 32-bit output
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_km_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiKm]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiKm]),
    .mst_req_o (km_axi32_req),
    .mst_resp_i(km_axi32_resp)
  );

  // Stage 2: AXI to AXI-Lite Conversion (32-bit AXI4 -> 32-bit AXI-Lite)
  // Note: axi_to_axi_lite outputs km_axil_req_t directly so that the KM
  //       mailbox port connection requires no type cast.
  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (km_intf_pkg::km_axil_req_t),
    .lite_resp_t     (km_intf_pkg::km_axil_resp_t)
  ) u_km_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (km_axi32_req),
    .slv_resp_o  (km_axi32_resp),
    .mst_req_o   (km_mbox_axil_req_o),
    .mst_resp_i  (km_mbox_axil_resp_i)
  );

  //////////////////////////////////////////////
  // Internal TRNG converted AXI-Lite paths   //
  //////////////////////////////////////////////

  // ---- Entropy source: 64b AXI -> 32b AXI -> 32b AXI-Lite -> isolate ----

  sep_pkg::sep_32_32_6_12_axi_req_t  esrc_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t esrc_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_esrc_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiEntropySrc]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiEntropySrc]),
    .mst_req_o (esrc_axi32_req),
    .mst_resp_i(esrc_axi32_resp)
  );

  sep_pkg::sep_32_32_axil_req_t  esrc_conv_axil_req;
  sep_pkg::sep_32_32_axil_resp_t esrc_conv_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_esrc_axi_to_axi_lite (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (esrc_axi32_req),
    .slv_resp_o (esrc_axi32_resp),
    .mst_req_o  (esrc_conv_axil_req),
    .mst_resp_i (esrc_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .axi_lite_req_t       (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_resp_t      (sep_pkg::sep_32_32_axil_resp_t)
  ) u_esrc_host_isolate (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (esrc_conv_axil_req),
    .slv_resp_o (esrc_conv_axil_resp),
    .mst_req_o  (esrc_axil_isolated_req_o),
    .mst_resp_i (esrc_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.trng_entropy_source),
    .isolated_o (isolated_o.trng_entropy_source)
  );

  // ---- CSRNG: 64b AXI -> 64b AXI-Lite -> isolate ----

  drbg_pkg::drbg_axil64_req_t  csrng_conv_axil_req;
  drbg_pkg::drbg_axil64_resp_t csrng_conv_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .lite_req_t      (drbg_pkg::drbg_axil64_req_t),
    .lite_resp_t     (drbg_pkg::drbg_axil64_resp_t)
  ) u_csrng_axi_to_axi_lite (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiCsrng]),
    .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiCsrng]),
    .mst_req_o  (csrng_conv_axil_req),
    .mst_resp_i (csrng_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .axi_lite_req_t       (drbg_pkg::drbg_axil64_req_t),
    .axi_lite_resp_t      (drbg_pkg::drbg_axil64_resp_t)
  ) u_csrng_host_isolate (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (csrng_conv_axil_req),
    .slv_resp_o (csrng_conv_axil_resp),
    .mst_req_o  (csrng_axil_isolated_req_o),
    .mst_resp_i (csrng_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.trng_csrng),
    .isolated_o (isolated_o.trng_csrng)
  );

  // ---- EDN: 64b AXI -> 64b AXI-Lite -> isolate ----

  drbg_pkg::drbg_axil64_req_t  edn_conv_axil_req;
  drbg_pkg::drbg_axil64_resp_t edn_conv_axil_resp;

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (ISOLATE_NUM_PENDING),
    .AxiMaxReadTxns  (ISOLATE_NUM_PENDING),
    .full_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .lite_req_t      (drbg_pkg::drbg_axil64_req_t),
    .lite_resp_t     (drbg_pkg::drbg_axil64_resp_t)
  ) u_edn_axi_to_axi_lite (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiEdn]),
    .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiEdn]),
    .mst_req_o  (edn_conv_axil_req),
    .mst_resp_i (edn_conv_axil_resp)
  );

  axi_lite_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AxiAddrWidth         (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .axi_lite_req_t       (drbg_pkg::drbg_axil64_req_t),
    .axi_lite_resp_t      (drbg_pkg::drbg_axil64_resp_t)
  ) u_edn_host_isolate (
    .clk_i,
    .rst_ni,
    .test_i     (test_en_i),
    .slv_req_i  (edn_conv_axil_req),
    .slv_resp_o (edn_conv_axil_resp),
    .mst_req_o  (edn_axil_isolated_req_o),
    .mst_resp_i (edn_axil_isolated_resp_i),
    .isolate_i  (isolate_req_i.trng_edn),
    .isolated_o (isolated_o.trng_edn)
  );

  //=========================================================================
  // TRNG AXI-Lite passthrough — demux port [sep_crypto_pkg::SepCryptoAxiTrng]
  //=========================================================================
  // 64b AXI → 32b AXI → 32b AXI-Lite → ext_trng_axil_*

  sep_pkg::sep_32_32_6_12_axi_req_t  trng_axi32_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t trng_axi32_resp;

  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_trng_axi_dw_converter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .slv_req_i (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiTrng]),
    .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiTrng]),
    .mst_req_o (trng_axi32_req),
    .mst_resp_i(trng_axi32_resp)
  );

  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_trng_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (trng_axi32_req),
    .slv_resp_o  (trng_axi32_resp),
    .mst_req_o   (ext_trng_axil_req_o),
    .mst_resp_i  (ext_trng_axil_resp_i)
  );

  //////////////////////////
  // Full AXI4 paths      //
  //////////////////////////

  assign fuse_axi_req_o = sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiFuse];
  assign sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiFuse] = fuse_axi_resp_i;

  assign lifecycle_axi_req_o = sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiLifecycle];
  assign sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiLifecycle] = lifecycle_axi_resp_i;

  axi_isolate #(
    .NumPending           (ISOLATE_NUM_PENDING),
    .TerminateTransaction (1'b1),
    .AtopSupport          (1'b0),
    .AxiAddrWidth         (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiDataWidth         (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiIdWidth           (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AxiUserWidth         (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
    .axi_req_t            (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t           (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_abr_host_isolate (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiAbr]),
    .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiAbr]),
    .mst_req_o  (abr_axi_isolated_req),
    .mst_resp_i (abr_axi_isolated_resp),
    .isolate_i  (isolate_req_i.host_abr),
    .isolated_o (isolated_o.host_abr)
  );

`ifdef SEP_ABR_EN
  // Break the B-channel combinational loop between the sep_crypto demux's
  // round-robin B arbiter and the VeeR axi4_to_ahb bridge inside the ABR wrapper.
  axi_cut #(
    .Bypass     (1'b1),   // AW/W/AR/R: combinational passthrough
    .BypassB    (1'b0),   // B: registered - this is what cuts the loop
    .aw_chan_t  (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .w_chan_t   (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t   (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t  (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .r_chan_t   (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_abr_b_cut (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (abr_axi_isolated_req),
    .slv_resp_o (abr_axi_isolated_resp),
    .mst_req_o  (abr_axi_isolated_req_o),
    .mst_resp_i (abr_axi_isolated_resp_i)
  );
`else
  assign abr_axi_isolated_req_o = abr_axi_isolated_req;
  assign abr_axi_isolated_resp  = abr_axi_isolated_resp_i;
`endif

endmodule

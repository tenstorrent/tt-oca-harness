// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP Cryptographic Subsystem

`include "axi/assign.svh"
`include "axi/typedef.svh"

module sep_crypto #(
    parameter bit LATCHED_MEM_RDATA = 1'b1,
    parameter int unsigned EXT_TRNG_NUM_AXIS = 3,
    // During synthesis, to be replaced with the actual token digest embedded in the netlist
    parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0
) (
    input logic                           clk_i,
    input logic                           rst_ni,

    // Ring-oscillator sample clock for entropy_source
    input logic                           entropy_rosc_sample_clk_i,

    // OTP debug AXI-Lite manager interface
    input  sep_efuse_pkg::efuse_axil_req_t  axil_sep_otp_jtag_req_i,
    output sep_efuse_pkg::efuse_axil_resp_t axil_sep_otp_jtag_resp_o,

    // Full AXI4 slave from local crossbar
    input  sep_pkg::sep_32_64_6_12_axi_req_t        sep_crypto_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t       sep_crypto_axi_resp_o,

    // eFuse shim CSR leg, split out of the sep_external crossbar window
    input  sep_pkg::sep_32_64_6_12_axi_req_t        efuse_shim_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t       efuse_shim_axi_resp_o,

    // Entropy source interrupt
    output logic                               entropy_source_irq_o,

    // External TRNG AXI-Lite passthrough (to sep_ip_integration)
    output sep_pkg::sep_32_32_axil_req_t       ext_trng_axil_req_o,
    input  sep_pkg::sep_32_32_axil_resp_t      ext_trng_axil_resp_i,

    // External TRNG AXI-Stream inputs (from sep_ip_integration)
    input  sep_crypto_pkg::ext_trng_axis_req_t  ext_trng_axis_req_i [EXT_TRNG_NUM_AXIS-1:0],
    output sep_crypto_pkg::ext_trng_axis_rsp_t ext_trng_axis_rsp_o [EXT_TRNG_NUM_AXIS-1:0],

    // Native EDN client of the SEP entropy-pool FIFO (sep_entropy_fifo) that
    // refills the pool. Served by u_axis_edn_pool_s3c_scan from the muxed pool AXI-Stream
    // leg, so the pool draws from either the internal DRBG or the external TRNG.
    input  edn_pkg::edn_req_t                  entropy_pool_edn_req_i,
    output edn_pkg::edn_rsp_t                  entropy_pool_edn_rsp_o,

    // Efuse Interface to SHIM CSR
	output sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_o,
	input  sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_i,
	// Efuse Command Interface - custom interface for SHIM
	output sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_o,
    input  sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_i,

    // DFT
    input logic                                test_en_i,
    input logic                                scan_rst_ni,

    // Efuse release reset
    input logic                                sep_reset_ni,
    // Efuse intermediate reset
	output logic 							   sep_intermediate_reset_no,
    // Efuse signals
    input  sep_pkg::sep_straps_t  	           sep_straps_i,
    input  logic                               ext_boot_seq_done_i,
    output logic                               security_disable_o,    // To SMC
    output logic [2*sep_pkg::LC_STATE_BIT_WIDTH-1:0] lc_state_o,      // To SMC
    output sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl_o, // To SMC / DTP
    output logic                               lc_sigint_err_o,
    output sep_efuse_pkg::efuse_map_t 		   shadow_regs_o,
    output logic                               fuse_sense_done_o,
    output logic                               secure_tm_o,

    //=========================================================================
    // Key Manager Interfaces (exposed from sep_crypto)
    //=========================================================================

    // KM ROM memory interface (hard macro at integration level)
    output km_intf_pkg::km_rom_mem_req_t       km_rom_mem_req_o,
    input  km_intf_pkg::km_rom_mem_rsp_t       km_rom_mem_rsp_i,

    // KM SRAM memory interface (hard macro at integration level)
    output km_intf_pkg::km_sram_mem_req_t      km_sram_mem_req_o,
    input  km_intf_pkg::km_sram_mem_rsp_t      km_sram_mem_rsp_i,

    // KM Mailbox interrupt to SEP host
    output logic                               km_mbox_irq_to_sep_o,

    // KM error signals
    output logic                               km_unrecoverable_err_o,
    output logic                               km_recoverable_err_o,

    // Software resets from SEP host (active-low, synchronized)
    input  logic                               km_sw_rst_ni,
    input  logic                               otbn_sw_rst_ni,
    input  logic                               aes_sw_rst_ni,
    input  logic                               hmac_sw_rst_ni,
    input  logic                               kmac_sw_rst_ni,

    output logic [1:0]                         lcc_demote_state_1_o, // To SMC

    output logic [1:0]                         lcc_demote_state_2_o, // To SMC

    // External TRNG source selection (from sep_cpu_ctrl via sep_system_csr)
    input  logic [EXT_TRNG_NUM_AXIS-1:0]       ext_trng_src_sel_i,
    // Key Manager emergency wipe control (from sep_cpu_ctrl via sep_system_csr)
    input  logic                               km_wipe_state_i,
    //=========================================================================
    // Crypto Subsystem Interrupts (exposed to SEP PIC)
    //=========================================================================

    // HMAC interrupts
    output logic                               intr_hmac_done_o,
    output logic                               intr_hmac_fifo_empty_o,
    output logic                               intr_hmac_err_o,

    // KMAC interrupts
    output logic                               intr_kmac_done_o,
    output logic                               intr_kmac_fifo_empty_o,
    output logic                               intr_kmac_err_o,

    // CSRNG interrupts
    output logic                               intr_cs_cmd_req_done_o,
    output logic                               intr_cs_entropy_req_o,
    output logic                               intr_cs_hw_inst_exc_o,
    output logic                               intr_cs_fatal_err_o,

    // EDN interrupts
    output logic                               intr_edn_cmd_req_done_o,
    output logic                               intr_edn_fatal_err_o,

    // OTBN interrupt
    output logic                               intr_otbn_done_o,

    // Adams Bridge (PQC) interrupts. Held low when the engine is compiled out.
    output logic                               intr_abr_error_o,
    output logic                               intr_abr_notif_o,

    // OTBN external SRAM interfaces
    output sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t      sep_crypto_pka_imem_sram_req_o,
    input  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t      sep_crypto_pka_imem_sram_rsp_i,
    output sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t      sep_crypto_pka_dmem_sram_req_o,
    input  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t      sep_crypto_pka_dmem_sram_rsp_i,

    // Adams Bridge (PQC) external SRAM interface -- behavioral/tech macros live in
    // sep_ip_integration (tech-macro home). Packed struct req/rsp (OTBN pattern).
    output sep_crypto_pkg::abr_mem_req_t                       abr_mem_req_o,
    input  sep_crypto_pkg::abr_mem_rsp_t                       abr_mem_rsp_i,

    // Aggregated crypto alert (OR of all OpenTitan alert channels)
    output logic                               crypto_alert_o,

    // Debug signals
    output logic [9:0]                         sep_efuse_debug_o,
    output logic [5:0]                         sep_efuse_token_match_sip_debug_o,
    output logic [5:0]                         sep_efuse_token_match_chiplet_debug_o,

    // Locked Field Access Interrupt
    output logic                               locked_field_access_interrupt_o
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    //=========================================================================
    // Alert Receiver Infrastructure
    //=========================================================================
    // Flat array of all 11 OpenTitan alert channels across crypto sub-IPs:
    //   [0]     HMAC   (1 alert)
    //   [2:1]   OTBN   (2 alerts)
    //   [4:3]   AES    (2 alerts)
    //   [6:5]   KMAC   (2 alerts)
    //   [8:7]   CSRNG  (2 alerts)
    //   [10:9]  EDN    (2 alerts)

    localparam int unsigned NUM_CRYPTO_ALERTS = 11;

    prim_alert_pkg::alert_tx_t [NUM_CRYPTO_ALERTS-1:0] crypto_alert_tx;
    prim_alert_pkg::alert_rx_t [NUM_CRYPTO_ALERTS-1:0] crypto_alert_rx;
    logic [NUM_CRYPTO_ALERTS-1:0] crypto_alert_pulse;
    logic [NUM_CRYPTO_ALERTS-1:0] crypto_alert_integ_fail;

    for (genvar i = 0; i < NUM_CRYPTO_ALERTS; i++) begin : gen_alert_receivers
        prim_alert_receiver #(
            .AsyncOn   (1'b0),
            .SkewCycles(1)
        ) u_alert_receiver (
            .clk_i,
            .rst_ni,
            .init_trig_i  (prim_mubi_pkg::MuBi4False),
            .ping_req_i   (1'b0),
            .ping_ok_o    (),
            .integ_fail_o (crypto_alert_integ_fail[i]),
            .alert_o      (crypto_alert_pulse[i]),
            .alert_rx_o   (crypto_alert_rx[i]),
            .alert_tx_i   (crypto_alert_tx[i])
        );
    end

    assign crypto_alert_o = (|crypto_alert_pulse) | (|crypto_alert_integ_fail);

    // Native EDN wires: [0]=AES, [1]=KMAC, [2]=OTBN RND, [3]=OTBN URND — fed from mux1 via drbg_axis_edn_adapter
    edn_pkg::edn_req_t [sep_crypto_pkg::SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT-1:0] crypto_edn_req;
    edn_pkg::edn_rsp_t [sep_crypto_pkg::SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT-1:0] crypto_edn_rsp;

    // Native EDN wires for the entropy pool — fed from mux2 via drbg_axis_edn_adapter (N=1).
    // Packed [0:0] arrays so the adapter's NUM_ENDPOINTS-wide ports bind cleanly; index [0]
    // connects to the scalar entropy_pool_edn_req_i/rsp_o pool interface.
    edn_pkg::edn_req_t [sep_crypto_pkg::SEP_CRYPTO_POOL_EDN_CLIENT_COUNT-1:0] pool_edn_req;
    edn_pkg::edn_rsp_t [sep_crypto_pkg::SEP_CRYPTO_POOL_EDN_CLIENT_COUNT-1:0] pool_edn_rsp;

    sep_pkg::sep_32_64_6_12_axi_req_t  [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST-1:0] sep_crypto_axi_reqs;
    sep_pkg::sep_32_64_6_12_axi_resp_t [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST-1:0] sep_crypto_axi_resps;

    //=========================================================================
    // External TRNG / DRBG Entropy Source Muxing
    //=========================================================================
    //
    // Three 2:1 muxes controlled by ext_trng_src_sel_i (from sep_cpu_ctrl):
    //   sel=1 (default): external TRNG stream selected
    //   sel=0:           internal DRBG output selected (post-CSRNG on every leg)
    //
    // Mux 0: ext_trng[0] vs DRBG edn_axis_o[0]  -> Key Manager
    // Mux 1: ext_trng[1] vs DRBG edn_axis_o[1]  -> drbg_axis_edn_adapter -> AES/KMAC/OTBN
    // Mux 2: ext_trng[2] vs DRBG edn_axis_o[2]  -> drbg_axis_edn_adapter -> entropy pool

    // Internal DRBG-side AXI-Stream (one per mux)
    drbg_pkg::drbg_axis_req_t [EXT_TRNG_NUM_AXIS-1:0] drbg_int_axis_req;
    drbg_pkg::drbg_axis_rsp_t [EXT_TRNG_NUM_AXIS-1:0] drbg_int_axis_rsp;

    // Muxed AXI-Stream outputs (one per mux)
    drbg_pkg::drbg_axis_req_t [EXT_TRNG_NUM_AXIS-1:0] entropy_muxed_req;
    drbg_pkg::drbg_axis_rsp_t [EXT_TRNG_NUM_AXIS-1:0] entropy_muxed_rsp;

    ////////////////
    // AXI4 Demux //
    ////////////////

    logic otbn_write, otbn_read, hmac_write, hmac_read, aes_write, aes_read, kmac_write, kmac_read, fuse_write, fuse_read, lifecycle_write, lifecycle_read, km_write, km_read;
    logic csrng_write, csrng_read, edn_write, edn_read;
    logic entropy_src_write, entropy_src_read, trng_write, trng_read;
    logic abr_write, abr_read;  // Adams Bridge PQC
    logic [sep_crypto_pkg::SEP_CRYPTO_NUM_AXI_MST_SEL-1:0] aw_select, ar_select;

    always_comb begin
        otbn_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::otbn_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::otbn_rule.end_addr);
        otbn_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::otbn_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::otbn_rule.end_addr);

        hmac_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::hmac_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::hmac_rule.end_addr);
        hmac_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::hmac_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::hmac_rule.end_addr);

        aes_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::aes_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::aes_rule.end_addr);
        aes_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::aes_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::aes_rule.end_addr);

        kmac_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::kmac_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::kmac_rule.end_addr);
        kmac_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::kmac_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::kmac_rule.end_addr);

        fuse_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::fuse_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::fuse_rule.end_addr);
        fuse_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::fuse_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::fuse_rule.end_addr);

        lifecycle_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::lifecycle_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::lifecycle_rule.end_addr);
        lifecycle_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::lifecycle_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::lifecycle_rule.end_addr);

        km_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::km_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::km_rule.end_addr);
        km_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::km_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::km_rule.end_addr);

        csrng_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::csrng_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::csrng_rule.end_addr);
        csrng_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::csrng_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::csrng_rule.end_addr);

        edn_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::edn_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::edn_rule.end_addr);
        edn_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::edn_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::edn_rule.end_addr);

        entropy_src_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::entropy_source_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::entropy_source_rule.end_addr);
        entropy_src_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::entropy_source_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::entropy_source_rule.end_addr);

        trng_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::trng_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::trng_rule.end_addr);
        trng_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::trng_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::trng_rule.end_addr);

        abr_write = (sep_crypto_axi_req_i.aw.addr >= sep_crypto_pkg::abr_rule.start_addr) &
            (sep_crypto_axi_req_i.aw.addr < sep_crypto_pkg::abr_rule.end_addr);
        abr_read  = (sep_crypto_axi_req_i.ar.addr >= sep_crypto_pkg::abr_rule.start_addr) &
            (sep_crypto_axi_req_i.ar.addr < sep_crypto_pkg::abr_rule.end_addr);

        // Port mapping follows sep_crypto_axi_port_e
        if (abr_write) begin
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

        if (abr_read) begin
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
        .clk_i,
        .rst_ni,
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
        .clk_i,
        .rst_ni,
        .test_i     (test_en_i),
        .slv_req_i  (sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiErrSlv]),
        .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiErrSlv])
    );


    //////////////////////////
    // SW Reset AXI Isolate //
    //////////////////////////

    // Isolated AXI ports and sequenced resets for the accelerator wrappers
    sep_pkg::sep_32_64_6_12_axi_req_t  hmac_axi_isolated_req,  otbn_axi_isolated_req,
                                       aes_axi_isolated_req,   kmac_axi_isolated_req;
    sep_pkg::sep_32_64_6_12_axi_resp_t hmac_axi_isolated_resp, otbn_axi_isolated_resp,
                                       aes_axi_isolated_resp,  kmac_axi_isolated_resp;
    logic hmac_gated_rst_n, otbn_gated_rst_n, aes_gated_rst_n, kmac_gated_rst_n;

    sep_crypto_axi_isolate #(
        .ADDR_WIDTH  (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .DATA_WIDTH  (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .ID_WIDTH    (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .USER_WIDTH  (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .NUM_PENDING (4),
        .axi_req_t   (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_resp_t  (sep_pkg::sep_32_64_6_12_axi_resp_t)
    ) u_sep_crypto_axi_isolate (
        .clk_i              (clk_i),
        .rst_ni             (rst_ni),

        .hmac_sw_rst_req_ni (hmac_sw_rst_ni),
        .hmac_slv_req_i     (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiHmac]),
        .hmac_slv_resp_o    (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiHmac]),
        .hmac_mst_req_o     (hmac_axi_isolated_req),
        .hmac_mst_resp_i    (hmac_axi_isolated_resp),
        .hmac_gated_rst_no  (hmac_gated_rst_n),

        .otbn_sw_rst_req_ni (otbn_sw_rst_ni),
        .otbn_slv_req_i     (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiOtbn]),
        .otbn_slv_resp_o    (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiOtbn]),
        .otbn_mst_req_o     (otbn_axi_isolated_req),
        .otbn_mst_resp_i    (otbn_axi_isolated_resp),
        .otbn_gated_rst_no  (otbn_gated_rst_n),

        .aes_sw_rst_req_ni  (aes_sw_rst_ni),
        .aes_slv_req_i      (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiAes]),
        .aes_slv_resp_o     (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiAes]),
        .aes_mst_req_o      (aes_axi_isolated_req),
        .aes_mst_resp_i     (aes_axi_isolated_resp),
        .aes_gated_rst_no   (aes_gated_rst_n),

        .kmac_sw_rst_req_ni (kmac_sw_rst_ni),
        .kmac_slv_req_i     (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiKmac]),
        .kmac_slv_resp_o    (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiKmac]),
        .kmac_mst_req_o     (kmac_axi_isolated_req),
        .kmac_mst_resp_i    (kmac_axi_isolated_resp),
        .kmac_gated_rst_no  (kmac_gated_rst_n)
    );


    //////////////////
    // HMAC Wrapper //
    //////////////////

    // HMAC key bus AXI-Lite signals — driven by Key Manager hmac_req_o
    sep_pkg::sep_32_32_axil_req_t  hmac_key_axil_req;
    sep_pkg::sep_32_32_axil_resp_t hmac_key_axil_resp;

    hmac_wrapper hmac_wrapper_s3c_scan (
        .clk_i,
        .rst_ni                  (hmac_gated_rst_n),
        .hmac_axi_req_i          (hmac_axi_isolated_req),
        .hmac_axi_resp_o         (hmac_axi_isolated_resp),
        .hmac_key_axil_req_i     (hmac_key_axil_req),
        .hmac_key_axil_resp_o    (hmac_key_axil_resp),
        .intr_hmac_done_o        (intr_hmac_done_o),
        .intr_fifo_empty_o       (intr_hmac_fifo_empty_o),
        .intr_hmac_err_o         (intr_hmac_err_o),
        .alert_rx_i              (crypto_alert_rx[0:0]),
        .alert_tx_o              (crypto_alert_tx[0:0]),
        .idle_o                  (/* UNUSED */)
    );


    //////////////////
    // OTBN Wrapper //
    //////////////////

    // OTBN key bus AXI-Lite signals — driven by Key Manager otbn_req_o
    sep_pkg::sep_32_32_axil_req_t  otbn_key_axil_req;
    sep_pkg::sep_32_32_axil_resp_t otbn_key_axil_resp;

    sep_crypto_otbn_wrapper sep_crypto_otbn_wrapper_s3c_scan (
        .clk_i,
        .rst_ni                       (otbn_gated_rst_n),
        .otbn_axi_req_i               (otbn_axi_isolated_req),
        .otbn_axi_resp_o              (otbn_axi_isolated_resp),
        .otbn_key_axil_req_i          (otbn_key_axil_req),
        .otbn_key_axil_resp_o         (otbn_key_axil_resp),
        .edn_rnd_req_o                (crypto_edn_req[2]),
        .edn_rnd_rsp_i                (crypto_edn_rsp[2]),
        .edn_urnd_req_o               (crypto_edn_req[3]),
        .edn_urnd_rsp_i               (crypto_edn_rsp[3]),
        .intr_done_o                  (intr_otbn_done_o),
        .alert_rx_i                   (crypto_alert_rx[2:1]),
        .alert_tx_o                   (crypto_alert_tx[2:1]),
        .imem_sram_req_o              (sep_crypto_pka_imem_sram_req_o),
        .imem_sram_rsp_i              (sep_crypto_pka_imem_sram_rsp_i),
        .dmem_sram_req_o              (sep_crypto_pka_dmem_sram_req_o),
        .dmem_sram_rsp_i              (sep_crypto_pka_dmem_sram_rsp_i)
    );


    /////////////////
    // AES Wrapper //
    /////////////////

    // AES key bus AXI-Lite signals — driven by Key Manager aes_req_o
    sep_pkg::sep_32_32_axil_req_t  aes_key_axil_req;
    sep_pkg::sep_32_32_axil_resp_t aes_key_axil_resp;

    aes_wrapper aes_wrapper_s3c_scan (
        .clk_i,
        .rst_ni              (aes_gated_rst_n),
        .aes_axi_req_i       (aes_axi_isolated_req),
        .aes_axi_resp_o      (aes_axi_isolated_resp),
        .aes_key_axil_req_i  (aes_key_axil_req),
        .aes_key_axil_resp_o (aes_key_axil_resp),
        .edn_req_o           (crypto_edn_req[0]),
        .edn_rsp_i           (crypto_edn_rsp[0]),
        .alert_rx_i          (crypto_alert_rx[4:3]),
        .alert_tx_o          (crypto_alert_tx[4:3]),
        .idle_o              (/* UNUSED */)
    );


    //////////////////
    // KMAC Wrapper //
    //////////////////

    // KMAC key bus AXI-Lite signals — driven by Key Manager kmac_req_o
    sep_pkg::sep_32_32_axil_req_t  kmac_key_axil_req;
    sep_pkg::sep_32_32_axil_resp_t kmac_key_axil_resp;

    kmac_wrapper kmac_wrapper_s3c_scan (
        .clk_i,
        .rst_ni                  (kmac_gated_rst_n),
        .kmac_axi_req_i          (kmac_axi_isolated_req),
        .kmac_axi_resp_o         (kmac_axi_isolated_resp),
        .kmac_key_axil_req_i     (kmac_key_axil_req),
        .kmac_key_axil_resp_o    (kmac_key_axil_resp),
        .edn_req_o               (crypto_edn_req[1]),
        .edn_rsp_i               (crypto_edn_rsp[1]),
        .intr_kmac_done_o        (intr_kmac_done_o),
        .intr_fifo_empty_o       (intr_kmac_fifo_empty_o),
        .intr_kmac_err_o         (intr_kmac_err_o),
        .alert_rx_i              (crypto_alert_rx[6:5]),
        .alert_tx_o              (crypto_alert_tx[6:5]),
        .idle_o                  (/* UNUSED */)
    );


    //////////////////////////
    // Adams Bridge Wrapper //
    //////////////////////////

    // ABR key bus AXI-Lite signals — driven by Key Manager abr_req_o
    km_intf_pkg::km_axil_req_t  abr_key_axil_req;
    km_intf_pkg::km_axil_resp_t abr_key_axil_resp;

    // ML-KEM shared-key IRQ (driven by the wrapper; consumed by the Key Manager).
    logic abr_mlkem_sharedkey_irq;

    // ABR error/notif drive SEP PIC slots 34/35 (see the aggregation in sep.sv). busy_o
    // has no consumer at this level -- abr_top's BUSY is also readable over the ABR CSR
    // aperture -- so it is sunk rather than exported. Declared outside the SEP_ABR_EN
    // guard so both branches can drive them.
    logic abr_error_intr, abr_notif_intr, abr_busy;
    logic unused_abr_busy;

    // The Adams Bridge crypto engine wrapper now owns the abr_wrapper_key_reg CSR
    // block, the KV shim, the ABR memory adapter, and the shared-key IRQ (matching
    // the aes/otbn wrapper convention). Presence is gated by SEP_ABR_EN -- OCAH's own
    // switch -- rather than by CALIPTRA, which is the VENDOR's define for exposing
    // abr_top's Caliptra Key-Vault ports. Bender defines the two together (see the
    // Adams Bridge source group in Bender.yml); the check below rejects a build that
    // enables ABR without the vendor define. When compiled out, the KM's ABR key bus
    // and the ABR control/status aperture are both terminated with DECERR
    // err-slaves, the ABR memory request struct is tied off, and the shared-key
    // IRQ and error/notif interrupts are held low.
`ifdef SEP_ABR_EN
`ifndef CALIPTRA
    if (1) begin : g_sep_abr_en_requires_caliptra
        $error({"SEP_ABR_EN is set but CALIPTRA is not: the vendored abr_top would be ",
                "compiled without its Key-Vault ports and sep_abr_kv_shim cannot bind. ",
                "Define both (see the Adams Bridge source group in Bender.yml)."});
    end
`endif

    // Break the B-channel combinational loop between the sep_crypto demux's
    // round-robin B arbiter and the VeeR axi4_to_ahb bridge inside the ABR wrapper.
    
    sep_pkg::sep_32_64_6_12_axi_req_t  abr_axi_req_cut;
    sep_pkg::sep_32_64_6_12_axi_resp_t abr_axi_resp_cut;

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
        .clk_i,
        .rst_ni     (sep_reset_ni),
        .slv_req_i  (sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiAbr]),
        .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiAbr]),
        .mst_req_o  (abr_axi_req_cut),
        .mst_resp_i (abr_axi_resp_cut)
    );

    // Same package parameters feed the ABR SRAM instances in sep_ip_integration;
    // abr_top and its memories must be configured identically.
    sep_crypto_abr_wrapper #(
        .MASKING_EN   (sep_crypto_pkg::SEP_CRYPTO_ABR_MASKING_EN),
        .SRAM_LATENCY (sep_crypto_pkg::SEP_CRYPTO_ABR_SRAM_LATENCY)
    ) u_sep_crypto_abr_wrapper_s3c_scan (
        .clk_i,
        .rst_ni                (sep_reset_ni),
        // Control/status path: ABR AXI aperture off the sep_crypto demux, via the
        // B-channel cut above.
        .abr_axi_req_i         (abr_axi_req_cut),
        .abr_axi_resp_o        (abr_axi_resp_cut),
        // Key path: KM private AXI4-Lite key bus (CSR block lives in the wrapper)
        .abr_key_axil_req_i    (abr_key_axil_req),
        .abr_key_axil_resp_o   (abr_key_axil_resp),
        // AB internal SRAMs (tech macros in sep_ip_integration; threaded up)
        .abr_mem_req_o         (abr_mem_req_o),
        .abr_mem_rsp_i         (abr_mem_rsp_i),
        .scan_mode_i           (test_en_i),     // DFT scan/test-enable (matches sep_cpu)
        .mlkem_sharedkey_irq_o (abr_mlkem_sharedkey_irq),
        .error_intr_o          (abr_error_intr),
        .notif_intr_o          (abr_notif_intr),
        .busy_o                (abr_busy)
    );

    assign intr_abr_error_o = abr_error_intr;
    assign intr_abr_notif_o = abr_notif_intr;
    assign unused_abr_busy  = abr_busy;
`else
    // Adams Bridge engine compiled out.
    // (1) Terminate the ABR control/status AXI aperture with DECERR.
    axi_err_slv #(
        .AxiIdWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .Resp       (axi_pkg::RESP_DECERR),
        .ATOPs      (1'b0),
        .MaxTrans   (1)
    ) u_abr_axi_err_slv (
        .clk_i,
        .rst_ni,
        .test_i     (test_en_i),
        .slv_req_i  (sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiAbr]),
        .slv_resp_o (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiAbr])
    );

    // (2) Terminate the KM's private ABR key bus with DECERR. The key CSR block
    //     now lives inside the CALIPTRA-only wrapper, so there is no OKAY
    //     responder here; use an AXI4-Lite err-slave (mirrors u_abr_axi_err_slv).
    prim_axil_err_slv #(
        .AXI_DATA_WIDTH (km_intf_pkg::KM_AXI_DATA_WIDTH),
        .AXI_ADDR_WIDTH (km_intf_pkg::KM_AXI_ADDR_WIDTH),
        .axil_req_t     (km_intf_pkg::km_axil_req_t),
        .axil_resp_t    (km_intf_pkg::km_axil_resp_t)
    ) u_abr_key_err_slv (
        .clk_i,
        .rst_ni      (sep_reset_ni),
        .axil_req_i  (abr_key_axil_req),
        .axil_resp_o (abr_key_axil_resp)
    );

    // (3) No ABR memory requester; hold the request struct quiescent.
    assign abr_mem_req_o = '0;

    // (4) No shared-key IRQ source.
    assign abr_mlkem_sharedkey_irq = 1'b0;

    // (5) No engine, so no error/notif interrupts and no busy status.
    assign intr_abr_error_o = 1'b0;
    assign intr_abr_notif_o = 1'b0;
    assign abr_error_intr   = 1'b0;
    assign abr_notif_intr   = 1'b0;
    assign abr_busy         = 1'b0;
    assign unused_abr_busy  = abr_busy;
`endif  // SEP_ABR_EN


    ////////////////////
    // Fuse Wrapper   //
    ////////////////////

    logic prod_dbg_active;

    // Key Manager eFuse AXI-Lite master bus — driven by key_manager efuse_req_o,
    // consumed by sep_efuse_wrapper's km_efuse_axil_req_i port.
    km_intf_pkg::km_axil_req_t  km_efuse_axil_req;
    km_intf_pkg::km_axil_resp_t km_efuse_axil_resp;

    ///////////////////////////////
    // eFuse leg / SHIM merge    //
    ///////////////////////////////

    // eFuse decode leg (crypto address space) and the eFuse shim CSR leg that is
    // split out of the sep_external window (on xbar) are merged here (not in above decode).
    // Shim addresses never enter the crypto address map.

    // axi_mux widens the ID by one bit (6 -> 7), converter squashes it back so sep_efuse_wrapper keeps its 6-bit port.
    sep_pkg::sep_32_64_7_12_axi_req_t  efuse_mux_axi_req;
    sep_pkg::sep_32_64_7_12_axi_resp_t efuse_mux_axi_resp;
    sep_pkg::sep_32_64_6_12_axi_req_t  efuse_merged_axi_req;
    sep_pkg::sep_32_64_6_12_axi_resp_t efuse_merged_axi_resp;

    axi_mux #(
        .SlvAxiIDWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .slv_aw_chan_t (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
        .mst_aw_chan_t (sep_pkg::sep_32_64_7_12_axi_aw_chan_t),
        .w_chan_t      (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
        .slv_b_chan_t  (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
        .mst_b_chan_t  (sep_pkg::sep_32_64_7_12_axi_b_chan_t),
        .slv_ar_chan_t (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
        .mst_ar_chan_t (sep_pkg::sep_32_64_7_12_axi_ar_chan_t),
        .slv_r_chan_t  (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
        .mst_r_chan_t  (sep_pkg::sep_32_64_7_12_axi_r_chan_t),
        .slv_req_t     (sep_pkg::sep_32_64_6_12_axi_req_t),
        .slv_resp_t    (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .mst_req_t     (sep_pkg::sep_32_64_7_12_axi_req_t),
        .mst_resp_t    (sep_pkg::sep_32_64_7_12_axi_resp_t),
        .NoSlvPorts    (2),
        .MaxWTrans     (4),
        .FallThrough   (1'b0),
        .SpillAw       (1'b1),
        .SpillW        (1'b0),
        .SpillB        (1'b0),
        .SpillAr       (1'b1),
        .SpillR        (1'b0)
    ) u_efuse_shim_axi_mux (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .test_i      (test_en_i),
        .slv_reqs_i  ({efuse_shim_axi_req_i,
                       sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiFuse]}),
        .slv_resps_o ({efuse_shim_axi_resp_o,
                       sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiFuse]}),
        .mst_req_o   (efuse_mux_axi_req),
        .mst_resp_i  (efuse_mux_axi_resp)
    );

    // The axi mux upstream forces the axi to be 7 bits. Use this converter to turn it back to 6 bits to fit with efuse controller
    prim_axi_id_converter #(
        .AXI_ADDR_WIDTH    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AXI_DATA_WIDTH    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AXI_USER_WIDTH    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AXI_ID_WIDTH_IN   (sep_pkg::SEP_32_64_7_12_ID_WIDTH),
        .AXI_ID_WIDTH_OUT  (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .input_axi_req_t   (sep_pkg::sep_32_64_7_12_axi_req_t),
        .input_axi_resp_t  (sep_pkg::sep_32_64_7_12_axi_resp_t),
        .output_axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
        .output_axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .MAX_INFLIGHT_IDS  (16),
        .MAX_TXNS_PER_ID   (4)
    ) u_efuse_shim_id_conv (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .test_en_i     (test_en_i),
        .axi_in_req_i  (efuse_mux_axi_req),
        .axi_in_resp_o (efuse_mux_axi_resp),
        .axi_out_req_o (efuse_merged_axi_req),
        .axi_out_resp_i(efuse_merged_axi_resp)
    );

    sep_efuse_wrapper #(
        .SEP_SEC_DISABLE_TOKEN (SEP_SEC_DISABLE_TOKEN)
    ) u_sep_efuse_wrapper (
        .clk_i (clk_i),
        .rst_ni (rst_ni),
        .test_en_i    (test_en_i),
        .scan_rst_ni  (scan_rst_ni),

        .sep_straps_i                          (sep_straps_i),
        .ext_boot_seq_done_i                   (ext_boot_seq_done_i),

        .security_disable_o                    (security_disable_o),
        .lc_state_o                            (lc_state_o),
        .shadow_regs_o                         (shadow_regs_o),
        .fuse_sense_done_o                     (fuse_sense_done_o),

        .secure_tm_o                           (secure_tm_o),
        .prod_dbg_active_i                     (prod_dbg_active),

        // DTP JTAG to AXI-Lite bus
        .axil_sep_otp_jtag_req_i               (axil_sep_otp_jtag_req_i),
        .axil_sep_otp_jtag_resp_o              (axil_sep_otp_jtag_resp_o),

        // Key Manager AXI-Lite manager interface
        .km_efuse_axil_req_i                   (km_efuse_axil_req),
        .km_efuse_axil_resp_o                  (km_efuse_axil_resp),

        .sep_efuse_axi_req_i                   (efuse_merged_axi_req),
        .sep_efuse_axi_resp_o                  (efuse_merged_axi_resp),
        .efuse_bank_ctrl_req_o                 (efuse_bank_ctrl_req_o),
        .efuse_bank_ctrl_resp_i                (efuse_bank_ctrl_resp_i),
        .efuse_shim_command_req_o              (efuse_shim_command_req_o),
        .efuse_shim_command_resp_i             (efuse_shim_command_resp_i),

        .sep_intermediate_reset_no(sep_intermediate_reset_no),

        .sep_efuse_debug_o(sep_efuse_debug_o),
        .sep_efuse_token_match_sip_debug_o(sep_efuse_token_match_sip_debug_o),
        .sep_efuse_token_match_chiplet_debug_o(sep_efuse_token_match_chiplet_debug_o),

        .locked_field_access_interrupt_o       (locked_field_access_interrupt_o)
    );

    sep_lifecycle_ctrl #(
        .LC_STATE_WIDTH(sep_pkg::LC_STATE_BIT_WIDTH)
    ) u_sep_lifecycle_ctrl (
        .clk_i(clk_i),
        .reset_n_i(rst_ni),
        .test_en_i(test_en_i),

        .security_disable_i(security_disable_o), // From efuse wrapper
        .secure_tm_i(secure_tm_o), // From efuse wrapper
        .shadow_regs_i(shadow_regs_o), // From efuse wrapper
        .feat_ctrl_o(feat_ctrl_o),
        .lcc_demote_state_1_o(lcc_demote_state_1_o),
        .lcc_demote_state_2_o(lcc_demote_state_2_o),
        .lc_sigint_err_o(lc_sigint_err_o),
        .prod_dbg_active_o(prod_dbg_active),

        .lifecycle_axi_req_i(sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiLifecycle]),
        .lifecycle_axi_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiLifecycle])
    );

    //=========================================================================
    // OTP Data Assembly for Key Manager
    //=========================================================================
    // Assemble km_otp_data_t from efuse shadow registers and lifecycle ctrl.
    // LC state and demotion state arrive already differentially encoded from
    // their respective sources (shadow register and LCC output).
    // The four 256-bit secret fields (chiplet_uid, class_key, sip_uid, sys_uid)
    // are dual-rail encoded here at the source (Sep->KM boundary) using
    // prim_diff_encode_multi so that any fault on the wire is detectable.
    // Encoded format: data_o = {~value[255:0], value[255:0]} (512 bits total).

    km_intf_pkg::km_otp_data_t km_otp_data;

    // LC state and demotion state arrive already differentially encoded from
    // their respective sources (shadow register and LCC output).
    assign km_otp_data.life_cycle       = shadow_regs_o.f.lc_state.lc_state;
    assign km_otp_data.demotion_state_1 = lcc_demote_state_1_o;
    assign km_otp_data.demotion_state_2 = lcc_demote_state_2_o;

    // Dual-rail encode all four 256-bit KM-routed OTP fields.
    // OutputFlop=0: purely combinational encode (no pipeline latency).
    prim_diff_encode_multi #(
        .Width      (256),
        .OutputFlop (1'b0)
    ) u_chiplet_uid_enc (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .data_i (shadow_regs_o.f.chiplet_uid.uid),
        .data_o (km_otp_data.chiplet_uid)
    );

    prim_diff_encode_multi #(
        .Width      (256),
        .OutputFlop (1'b0)
    ) u_class_key_enc (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .data_i (shadow_regs_o.f.class_key.key),
        .data_o (km_otp_data.class_key)
    );

    prim_diff_encode_multi #(
        .Width      (256),
        .OutputFlop (1'b0)
    ) u_sip_uid_enc (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .data_i (shadow_regs_o.f.sip_uid.uid),
        .data_o (km_otp_data.sip_uid)
    );

    prim_diff_encode_multi #(
        .Width      (256),
        .OutputFlop (1'b0)
    ) u_sys_uid_enc (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),
        .data_i (shadow_regs_o.f.sys_uid.uid),
        .data_o (km_otp_data.sys_uid)
    );


    //=========================================================================
    // Key Manager AXI4-64 to AXI-Lite-32 Conversion (demux port [7])
    //=========================================================================
    // Two-stage conversion following the AES/KMAC wrapper pattern:
    //   Stage 1: axi_dw_converter  (64-bit AXI4 -> 32-bit AXI4)
    //   Stage 2: axi_to_axi_lite   (32-bit AXI4 -> 32-bit AXI-Lite)

    // 32-bit AXI4 intermediate types for KM data width conversion
    localparam int unsigned KM_AXI32_DATA_WIDTH = 32;
    localparam int unsigned KM_AXI32_STRB_WIDTH = KM_AXI32_DATA_WIDTH / 8;

    typedef logic [KM_AXI32_DATA_WIDTH-1:0] km_axi32_data_t;
    typedef logic [KM_AXI32_STRB_WIDTH-1:0] km_axi32_strb_t;

    `AXI_TYPEDEF_ALL(km_axi32,
                     sep_pkg::sep_32_64_6_12_axi_addr_t,
                     sep_pkg::sep_32_64_6_12_axi_id_t,
                     km_axi32_data_t,
                     km_axi32_strb_t,
                     sep_pkg::sep_32_64_6_12_axi_user_t)

    km_axi32_req_t  km_axi32_req;
    km_axi32_resp_t km_axi32_resp;

    // Stage 1: AXI Data Width Converter (64-bit -> 32-bit)
    axi_dw_converter #(
        .AxiMaxReads         (8),
        .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),  // 64-bit input
        .AxiMstPortDataWidth (KM_AXI32_DATA_WIDTH),                // 32-bit output
        .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
        .mst_w_chan_t        (km_axi32_w_chan_t),
        .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
        .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
        .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
        .mst_r_chan_t        (km_axi32_r_chan_t),
        .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
        .axi_mst_req_t       (km_axi32_req_t),
        .axi_mst_resp_t      (km_axi32_resp_t),
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
    km_intf_pkg::km_axil_req_t  km_mbox_axil_req;
    km_intf_pkg::km_axil_resp_t km_mbox_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
        .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
        .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
        .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
        .AxiMaxWriteTxns (4),
        .AxiMaxReadTxns  (4),
        .full_req_t      (km_axi32_req_t),
        .full_resp_t     (km_axi32_resp_t),
        .lite_req_t      (km_intf_pkg::km_axil_req_t),
        .lite_resp_t     (km_intf_pkg::km_axil_resp_t)
    ) u_km_axi_to_axi_lite (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .test_i      (test_en_i),
        .slv_req_i   (km_axi32_req),
        .slv_resp_o  (km_axi32_resp),
        .mst_req_o   (km_mbox_axil_req),
        .mst_resp_i  (km_mbox_axil_resp)
    );


    //=========================================================================
    // DRBG AXI4-64 to AXI-Lite-64 Conversion (demux ports [8] and [9])
    //=========================================================================
    // Single-stage conversion: bus is already 64-bit data, matching DRBG's
    // AXI-Lite-64 interface. No data-width converter needed.

    drbg_pkg::drbg_axil64_req_t  csrng_axil_req;
    drbg_pkg::drbg_axil64_resp_t csrng_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AxiMaxWriteTxns (4),
        .AxiMaxReadTxns  (4),
        .full_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
        .full_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .lite_req_t      (drbg_pkg::drbg_axil64_req_t),
        .lite_resp_t     (drbg_pkg::drbg_axil64_resp_t)
    ) u_csrng_axi_to_axi_lite (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .test_i      (test_en_i),
        .slv_req_i   (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiCsrng]),
        .slv_resp_o  (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiCsrng]),
        .mst_req_o   (csrng_axil_req),
        .mst_resp_i  (csrng_axil_resp)
    );

    drbg_pkg::drbg_axil64_req_t  edn_axil_req;
    drbg_pkg::drbg_axil64_resp_t edn_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth    (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiDataWidth    (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiIdWidth      (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .AxiUserWidth    (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AxiMaxWriteTxns (4),
        .AxiMaxReadTxns  (4),
        .full_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
        .full_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .lite_req_t      (drbg_pkg::drbg_axil64_req_t),
        .lite_resp_t     (drbg_pkg::drbg_axil64_resp_t)
    ) u_edn_axi_to_axi_lite (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .test_i      (test_en_i),
        .slv_req_i   (sep_crypto_axi_reqs[sep_crypto_pkg::SepCryptoAxiEdn]),
        .slv_resp_o  (sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiEdn]),
        .mst_req_o   (edn_axil_req),
        .mst_resp_i  (edn_axil_resp)
    );

    //=========================================================================
    // Entropy Source (ESRC) — demux port [sep_crypto_pkg::SepCryptoAxiEntropySrc]
    //=========================================================================
    // Two-stage conversion: 64b AXI → 32b AXI → 32b AXI-Lite flat ports.

    km_axi32_req_t  esrc_axi32_req;
    km_axi32_resp_t esrc_axi32_resp;

    axi_dw_converter #(
        .AxiMaxReads         (8),
        .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiMstPortDataWidth (KM_AXI32_DATA_WIDTH),
        .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
        .mst_w_chan_t        (km_axi32_w_chan_t),
        .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
        .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
        .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
        .mst_r_chan_t        (km_axi32_r_chan_t),
        .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
        .axi_mst_req_t       (km_axi32_req_t),
        .axi_mst_resp_t      (km_axi32_resp_t),
        .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
    ) u_esrc_axi_dw_converter (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .slv_req_i (sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiEntropySrc]),
        .slv_resp_o(sep_crypto_axi_resps[sep_crypto_pkg::SepCryptoAxiEntropySrc]),
        .mst_req_o (esrc_axi32_req),
        .mst_resp_i(esrc_axi32_resp)
    );

    sep_pkg::sep_32_32_axil_req_t  esrc_axil_req;
    sep_pkg::sep_32_32_axil_resp_t esrc_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
        .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
        .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
        .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
        .AxiMaxWriteTxns (4),
        .AxiMaxReadTxns  (4),
        .full_req_t      (km_axi32_req_t),
        .full_resp_t     (km_axi32_resp_t),
        .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
        .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
    ) u_esrc_axi_to_axi_lite (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .test_i      (test_en_i),
        .slv_req_i   (esrc_axi32_req),
        .slv_resp_o  (esrc_axi32_resp),
        .mst_req_o   (esrc_axil_req),
        .mst_resp_i  (esrc_axil_resp)
    );

    logic [31:0] entropy_stream_data;
    logic        entropy_stream_vld;

    entropy_source u_entropy_source_s3c_scan (
        .clk_i,
        .rst_ni              (sep_reset_ni),

        .s_axil_awvalid_i    (esrc_axil_req.aw_valid),
        .s_axil_awready_o    (esrc_axil_resp.aw_ready),
        .s_axil_awaddr_i     (esrc_axil_req.aw.addr[8:0]),
        .s_axil_awprot_i     (esrc_axil_req.aw.prot),

        .s_axil_wvalid_i     (esrc_axil_req.w_valid),
        .s_axil_wready_o     (esrc_axil_resp.w_ready),
        .s_axil_wdata_i      (esrc_axil_req.w.data),
        .s_axil_wstrb_i      (esrc_axil_req.w.strb),

        .s_axil_bvalid_o     (esrc_axil_resp.b_valid),
        .s_axil_bready_i     (esrc_axil_req.b_ready),
        .s_axil_bresp_o      (esrc_axil_resp.b.resp),

        .s_axil_arvalid_i    (esrc_axil_req.ar_valid),
        .s_axil_arready_o    (esrc_axil_resp.ar_ready),
        .s_axil_araddr_i     (esrc_axil_req.ar.addr[8:0]),
        .s_axil_arprot_i     (esrc_axil_req.ar.prot),

        .s_axil_rvalid_o     (esrc_axil_resp.r_valid),
        .s_axil_rready_i     (esrc_axil_req.r_ready),
        .s_axil_rdata_o      (esrc_axil_resp.r.data),
        .s_axil_rresp_o      (esrc_axil_resp.r.resp),

        .signal_monitor_o    (/* unconnected */),
        .rosc_sample_clk_i   (entropy_rosc_sample_clk_i),

        .entropy_stream_data_o (entropy_stream_data),
        .entropy_stream_vld_o  (entropy_stream_vld),
        .irq_o                 (entropy_source_irq_o)
    );


    //=========================================================================
    // TRNG AXI-Lite passthrough — demux port [sep_crypto_pkg::SepCryptoAxiTrng]
    //=========================================================================
    // 64b AXI → 32b AXI → 32b AXI-Lite → ext_trng_axil_* (to sep_ip_integration)

    km_axi32_req_t  trng_axi32_req;
    km_axi32_resp_t trng_axi32_resp;

    axi_dw_converter #(
        .AxiMaxReads         (8),
        .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiMstPortDataWidth (KM_AXI32_DATA_WIDTH),
        .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
        .mst_w_chan_t        (km_axi32_w_chan_t),
        .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
        .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
        .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
        .mst_r_chan_t        (km_axi32_r_chan_t),
        .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
        .axi_mst_req_t       (km_axi32_req_t),
        .axi_mst_resp_t      (km_axi32_resp_t),
        .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
    ) u_trng_axi_dw_converter (
        .clk_i     (clk_i),
        .rst_ni    (rst_ni),
        .slv_req_i (sep_crypto_axi_reqs [sep_crypto_pkg::SepCryptoAxiTrng]),
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
        .full_req_t      (km_axi32_req_t),
        .full_resp_t     (km_axi32_resp_t),
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


    //=========================================================================
    // DRBG Instance
    //=========================================================================

    // drbg_int_axis_req/rsp are packed arrays, matching u_drbg_s3c_scan.edn_axis_o/i
    // shape, so we bind them directly below (mux leg [i] = DRBG EDN endpoint [i]).
    drbg #(
        .EDN_ENDPOINT_COUNT        (sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT),
        .EDN_NATIVE_ENDPOINT_COUNT (0)
    ) u_drbg_s3c_scan (
        .clk_i,
        .rst_ni              (sep_reset_ni),

        .entropy_stream_data_i (entropy_stream_data),
        .entropy_stream_vld_i  (entropy_stream_vld),

        // EDN AXI-Stream endpoints, one per ext-TRNG mux leg:
        //   [0]=Key Manager (mux0), [1]=crypto adapter (mux1), [2]=entropy pool (mux2)
        .edn_axis_o            (drbg_int_axis_req),
        .edn_axis_i            (drbg_int_axis_rsp),

        // No native EDN endpoints: every DRBG output is an AXI-Stream leg so it can
        // be muxed against the external TRNG. Tie off the width-1 port proxy.
        .edn_native_req_i      (edn_pkg::EDN_REQ_DEFAULT),
        .edn_native_rsp_o      (/* unconnected */),

        // AXI-Lite CSR buses
        .csrng_axil_req_i      (csrng_axil_req),
        .csrng_axil_rsp_o      (csrng_axil_resp),
        .edn_axil_req_i        (edn_axil_req),
        .edn_axil_rsp_o        (edn_axil_resp),

        // Sideband — safe defaults
        .otp_en_csrng_sw_app_read_i (prim_mubi_pkg::MuBi8True),
        .lc_hw_debug_en_i           (lc_ctrl_pkg::Off),

        // Alerts
        .csrng_alert_rx_i (crypto_alert_rx[8:7]),
        .csrng_alert_tx_o (crypto_alert_tx[8:7]),
        .edn_alert_rx_i   (crypto_alert_rx[10:9]),
        .edn_alert_tx_o   (crypto_alert_tx[10:9]),

        // Interrupts
        .intr_cs_cmd_req_done_o (intr_cs_cmd_req_done_o),
        .intr_cs_entropy_req_o  (intr_cs_entropy_req_o),
        .intr_cs_hw_inst_exc_o  (intr_cs_hw_inst_exc_o),
        .intr_cs_fatal_err_o    (intr_cs_fatal_err_o),
        .intr_edn_cmd_req_done_o(intr_edn_cmd_req_done_o),
        .intr_edn_fatal_err_o   (intr_edn_fatal_err_o)
    );

    // One DRBG EDN endpoint per mux leg. Direct packed-array bind of
    // u_drbg_s3c_scan.edn_axis_o/i to drbg_int_axis_req/rsp assumes this
    // invariant.
    // Elaboration-time check (evaluated by synth and simulators).
    if (EXT_TRNG_NUM_AXIS != sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT) begin : g_drbg_endpoint_mux_width_check
        $error("sep_crypto: EXT_TRNG_NUM_AXIS must equal SEP_CRYPTO_EDN_ENDPOINT_COUNT; one DRBG EDN endpoint per mux leg.");
    end

    //=========================================================================
    // Entropy Source Mux Logic
    //=========================================================================
    //
    // Mux 0: feeds Key Manager       — selects between DRBG edn_axis_o[0] and ext_trng[0]
    // Mux 1: feeds crypto blocks     — selects between DRBG edn_axis_o[1] and ext_trng[1]
    // Mux 2: feeds entropy pool      — selects between DRBG edn_axis_o[2] and ext_trng[2]
    //
    // Back-pressure policy for non-selected source:
    //   - DRBG side: tready=0 (hold in FIFO, don't drop)
    //   - ext_trng side: tready=1 (drain to avoid backpressure on external TRNG)

    for (genvar i = 0; i < EXT_TRNG_NUM_AXIS; i++) begin : gen_entropy_mux
        always_comb begin
            if (ext_trng_src_sel_i[i]) begin
                entropy_muxed_req[i].tvalid     = ext_trng_axis_req_i[i].tvalid;
                entropy_muxed_req[i].tdata      = ext_trng_axis_req_i[i].tdata;
                entropy_muxed_req[i].tstrb      = ext_trng_axis_req_i[i].tstrb;
                // External TRNG stream is FIPS-compliant; mark muxed beats so
                // FIPS-aware consumers such as OTBN RND see edn_fips=1.
                entropy_muxed_req[i].tuser      = 1'b1;
                ext_trng_axis_rsp_o[i]          = '{tready: entropy_muxed_rsp[i].tready};
                drbg_int_axis_rsp[i]            = drbg_pkg::drbg_axis_rsp_t'{tready: 1'b0};
            end else begin
                entropy_muxed_req[i].tvalid     = drbg_int_axis_req[i].tvalid;
                entropy_muxed_req[i].tdata      = drbg_int_axis_req[i].tdata;
                entropy_muxed_req[i].tstrb      = drbg_int_axis_req[i].tstrb;
                // DRBG leg: forward the per-beat FIPS bit sourced from u_edn
                // through drbg_edn_axis_adapter so OTBN RND sees edn_fips=1.
                entropy_muxed_req[i].tuser      = drbg_int_axis_req[i].tuser;
                drbg_int_axis_rsp[i]            = entropy_muxed_rsp[i];
                ext_trng_axis_rsp_o[i]          = '{tready: 1'b1};
            end
        end
    end

    //=========================================================================
    // Mux 1 -> native EDN for crypto (32b FIFO + arbiter + edn_ack_sm)
    //=========================================================================

    drbg_axis_edn_adapter #(
        .NUM_ENDPOINTS (sep_crypto_pkg::SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT)
    ) u_axis_edn_crypto_s3c_scan (
        .clk_i      (clk_i),
        .rst_ni     (sep_reset_ni),
        .axis_req_i (entropy_muxed_req[1]),
        .axis_rsp_o (entropy_muxed_rsp[1]),
        .edn_req_i  (crypto_edn_req),
        .edn_rsp_o  (crypto_edn_rsp)
    );

    //=========================================================================
    // Mux 2 -> native EDN for the entropy pool (32b FIFO + edn_ack_sm)
    //=========================================================================
    //
    // Reuses drbg_axis_edn_adapter with NUM_ENDPOINTS=1: converts the muxed
    // AXI-Stream (internal DRBG edn_axis_o[2] or external TRNG[2]) back into a
    // single native EDN req/rsp, presented to sep_entropy_fifo unchanged. The
    // adapter forwards tuser -> edn_fips, so the pool boundary sees the FIPS bit.
    assign pool_edn_req[0]         = entropy_pool_edn_req_i;
    assign entropy_pool_edn_rsp_o  = pool_edn_rsp[0];

    drbg_axis_edn_adapter #(
        .NUM_ENDPOINTS (sep_crypto_pkg::SEP_CRYPTO_POOL_EDN_CLIENT_COUNT)
    ) u_axis_edn_pool_s3c_scan (
        .clk_i      (clk_i),
        .rst_ni     (sep_reset_ni),
        .axis_req_i (entropy_muxed_req[2]),
        .axis_rsp_o (entropy_muxed_rsp[2]),
        .edn_req_i  (pool_edn_req),
        .edn_rsp_o  (pool_edn_rsp)
    );

    //=========================================================================
    // Key Manager Instance
    //=========================================================================
    //
    // Connections:
    //   - Mailbox slave port    <- demux port [7] via AXI4-64 to AXI-Lite-32 conversion
    //   - Crypto key bus master <- OTBN/AES/KMAC wrapper key ports
    //   - ROM/SRAM interfaces   <- exposed at sep_crypto top level (hard macros)
    //   - DRBG AXI-Stream       <- muxed from u_drbg_s3c_scan edn_axis_o[0] or ext_trng[0]

    key_manager #(
        .ROM_SIZE_BYTES       (16384),
        .SRAM_SIZE_BYTES      (16384),
        .MAILBOX_DEPTH        (16),
        .LATCHED_MEM_RDATA    (LATCHED_MEM_RDATA),
        .OTP_EFUSE_REMAP_BASE (32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR))
    ) u_key_manager_s3c_scan (
        .clk_i              (clk_i),
        // Cold reset: SEP system cold reset (AASD) resets the entire KM.
        .cold_rst_ni         (sep_reset_ni),
        // Warm reset: SEP KM sub-component software reset CSR bit triggers a
        // partial synchronous reset of the KM CPU and volatile state only.
        .warm_rst_ni         (km_sw_rst_ni),

        // Mailbox AXI-Lite slave (from demux port [7] via conversion)
        .mbox_sep_req_i      (km_mbox_axil_req),
        .mbox_sep_resp_o     (km_mbox_axil_resp),

        // Mailbox interrupt to SEP host
        .mbox_irq_to_sep_o   (km_mbox_irq_to_sep_o),

        // Error signals
        .unrecoverable_err_o (km_unrecoverable_err_o),
        .recoverable_err_o   (km_recoverable_err_o),

        // Crypto engine AXI-Lite master ports (private key bus)
        .otbn_req_o          (otbn_key_axil_req),
        .otbn_resp_i         (otbn_key_axil_resp),
        .aes_req_o           (aes_key_axil_req),
        .aes_resp_i          (aes_key_axil_resp),
        .kmac_req_o          (kmac_key_axil_req),
        .kmac_resp_i         (kmac_key_axil_resp),
        .hmac_req_o          (hmac_key_axil_req),
        .hmac_resp_i         (hmac_key_axil_resp),
        .abr_req_o           (abr_key_axil_req),
        .abr_resp_i          (abr_key_axil_resp),
        .abr_mlkem_sharedkey_irq_i  (abr_mlkem_sharedkey_irq),

        // Efuse AXI-Lite master bus -> sep_efuse_wrapper mux
        .efuse_req_o         (km_efuse_axil_req),
        .efuse_resp_i        (km_efuse_axil_resp),

        // ROM/SRAM memory interfaces (exposed at sep_crypto top)
        .rom_mem_req_o       (km_rom_mem_req_o),
        .rom_mem_rsp_i       (km_rom_mem_rsp_i),
        .sram_mem_req_o      (km_sram_mem_req_o),
        .sram_mem_rsp_i      (km_sram_mem_rsp_i),

        // DRBG AXI-Stream — muxed from DRBG EDN[0] or ext_trng[0]
        .drbg_axis_req_i     (entropy_muxed_req[0]),
        .drbg_axis_resp_o    (entropy_muxed_rsp[0]),

        // OTP data — assembled from efuse shadow registers and lifecycle ctrl
        .otp_data_i          (km_otp_data),

        // Wipe state — rising edge zeroes the KPV and sets the KM WIPE_STATE IRQ
        .wipe_state_i        (km_wipe_state_i),

        // Test/DFT
        .test_en_i           (test_en_i),
        .scan_rst_ni         (scan_rst_ni)
    );

    // =========================================================================
    // Key Manager AXI-Lite Type Width Assertions
    // The Key Manager drives this bus as km_intf_pkg::km_axil_* but it connects
    // to sep_efuse_wrapper's sep_efuse_pkg::efuse_axil_* port. The two are
    // distinct named structs (generated by AXI_LITE_TYPEDEF_ALL); this
    // elaboration-time check guarantees they stay bit-compatible so the port
    // bind is not silently truncated or bit-shifted. Because address/data/strb
    // all live inside these structs, any width change shows up in the total
    // $bits of the req/resp.
    // =========================================================================
`ifndef SYNTHESIS  // elaboration-time width checks; excluded from synthesis
    initial begin : g_km_efuse_axil_type_assertions
        assert ($bits(km_intf_pkg::km_axil_req_t)  == $bits(sep_efuse_pkg::efuse_axil_req_t))
            else $fatal(1, "KM_EFUSE_AXIL req width mismatch: km_axil_req_t != efuse_axil_req_t");
        assert ($bits(km_intf_pkg::km_axil_resp_t) == $bits(sep_efuse_pkg::efuse_axil_resp_t))
            else $fatal(1, "KM_EFUSE_AXIL resp width mismatch: km_axil_resp_t != efuse_axil_resp_t");
    end
`endif  // SYNTHESIS

endmodule

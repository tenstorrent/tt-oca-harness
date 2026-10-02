// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate SEP cryptographic accelerators, Key Manager, eFuse, lifecycle, and entropy
// paths.
//
// Hosts OTBN, AES, HMAC, KMAC, Adams Bridge (only when SEP_ABR_EN is defined; otherwise its
// apertures answer DECERR), Key Manager, eFuse, lifecycle, and the internal TRNG behind the
// local-crossbar slave and isolation handshake with sep_reset_ctrl.
// Three 2:1 muxes, one per ext_trng_src_sel_i bit, choose between external TRNG stream i and
// internal DRBG stream i: leg 0 feeds the Key Manager, leg 1 the AES, KMAC and OTBN EDN
// clients, and leg 2 the entropy pool. The unselected DRBG stream is held (tready low) and
// the unselected external stream is drained (tready high).
// The native EDN client for sep_entropy_fifo is served by u_axis_edn_pool_s3c_scan from
// the muxed pool AXI-Stream leg so the pool draws from either the internal DRBG or the
// external TRNG. trng_entropy_clear_o clears the fabric entropy pool while the internal
// TRNG reset is active.
// Each *_bus_err_o is set by a TL-UL error response on that block's register bridge; in sep
// they are ORed onto one PIC source (see sep_pkg::periph_bus_err_e).
// SEP_SEC_DISABLE_TOKEN is replaced at synthesis with the netlist-embedded token digest.
// External TRNG AXI-Lite/Stream and eFuse shim interfaces leave for sep_ip_integration.

`include "axi/assign.svh"
`include "axi/typedef.svh"
`include "ocah_assert.svh"

module sep_crypto #(
  parameter bit LATCHED_MEM_RDATA = 1'b1,     // 1 if the Key Manager ROM and SRAM macros latch read
                                              // data for look-ahead.
  parameter bit MASKING_EN = 1'b1,            // Enables 2-share DOM masking in the Adams Bridge
                                              // engine.
  parameter int unsigned SRAM_LATENCY = 1,    // Adams Bridge SRAM read latency in cycles.
  parameter int unsigned EXT_TRNG_NUM_AXIS = 3,  // Number of external TRNG AXI-Stream ports and
                                                 // entropy muxes; must equal
                                                 // SEP_CRYPTO_EDN_ENDPOINT_COUNT (3).
  parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0  // Netlist-embedded secure-disable token
                                                        // digest; replace at synthesis.
) (
  input logic                           clk_i,  // System clock.
  input logic                           rst_ni,  // Active-low power-on reset for the interconnect,
                                                 // eFuse, lifecycle, alert receivers and post-mux
                                                 // EDN adapters.

  input logic                           entropy_rosc_sample_clk_i,  // Ring-oscillator sample clock for entropy_source; asynchronous to clk_i.

  input  sep_efuse_pkg::efuse_axil_req_t  axil_sep_otp_jtag_req_i,  // OTP debug AXI-Lite manager interface.
  output sep_efuse_pkg::efuse_axil_resp_t axil_sep_otp_jtag_resp_o,  // Response from the eFuse wrapper to the OTP debug manager.

  input  sep_pkg::sep_32_64_6_12_axi_req_t        sep_crypto_axi_req_i,  // Full AXI4 slave from local crossbar.
  output sep_pkg::sep_32_64_6_12_axi_resp_t       sep_crypto_axi_resp_o,  // Response from the crypto interconnect to the local crossbar.

  input  sep_pkg::sep_32_64_6_12_axi_req_t        efuse_shim_axi_req_i,  // eFuse shim CSR leg, split out of the sep_external crossbar window.
  output sep_pkg::sep_32_64_6_12_axi_resp_t       efuse_shim_axi_resp_o,  // Response to the eFuse shim CSR leg, from the eFuse wrapper through the shim
                                                                          // merge mux.

  output logic                               entropy_source_irq_o,  // Entropy source interrupt.

  output sep_pkg::sep_32_32_axil_req_t       ext_trng_axil_req_o,  // External TRNG AXI-Lite
                                                                   // passthrough (to
                                                                   // sep_ip_integration).
  input  sep_pkg::sep_32_32_axil_resp_t      ext_trng_axil_resp_i,  // Response from the external TRNG register interface.

  input  sep_crypto_pkg::ext_trng_axis_req_t  ext_trng_axis_req_i [EXT_TRNG_NUM_AXIS-1:0],  // External TRNG AXI-Stream inputs (from sep_ip_integration).
  output sep_crypto_pkg::ext_trng_axis_rsp_t ext_trng_axis_rsp_o [EXT_TRNG_NUM_AXIS-1:0],  // tready to each external TRNG stream: the consumer's tready when selected,
                                                                                           // held high to drain the stream when not.

  input  edn_pkg::edn_req_t                  entropy_pool_edn_req_i,  // Native EDN client of the SEP entropy-pool FIFO (sep_entropy_fifo) that
                                                                      // refills the pool. Served by u_axis_edn_pool_s3c_scan from the muxed pool AXI-Stream
                                                                      // leg, so the pool draws from either the internal DRBG or the external TRNG.
  output edn_pkg::edn_rsp_t                  entropy_pool_edn_rsp_o,  // Entropy response to the pool's native EDN client, carrying the FIPS bit from
                                                                      // the selected leg-2 stream.
  output logic                               trng_entropy_clear_o,  // Clears the fabric entropy pool while the internal TRNG reset is active;
                                                                    // synchronized to clk_i and high during power-on reset.

  output sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_o,  // eFuse wrapper AXI-Lite requests to the eFuse shim CSRs.
  input  sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_i,  // Response from the eFuse shim CSRs.
  output sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_o,  // eFuse read and program commands on the custom shim command interface.
  input  sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_i,  // Shim response to the eFuse commands.

  input logic                                test_en_i,  // DFT test-enable (scan-enable).
  input logic                                scan_rst_ni,  // DFT scan reset, active-low; bypasses
                                                           // the reset synchronizer.

  input logic                                sep_reset_ni,  // Active-low SEP reset after the JTAG
                                                            // override, from sep_reset_ctrl; cold
                                                            // reset for the Key Manager.
  output logic           sep_intermediate_reset_no,  // Active-low SEP reset, synchronized to clk_i
                                                     // and released once fuse sense and the
                                                     // external boot sequence are done; to
                                                     // sep_reset_ctrl before the JTAG override.
  input  logic                              secure_tm_req_i,  // Secure test mode request strap,
                                                              // latched into secure_tm_o.
  input  logic                               ext_boot_seq_done_i,  // Integration boot-sequence
                                                                   // completion (memory repair and
                                                                   // SMC straps); gates release of
                                                                   // sep_intermediate_reset_no.
  output logic                               security_disable_o,  // Security-disable status from
                                                                  // eFuse token processing,
                                                                  // active-high; exported to the
                                                                  // SMC.
  output logic [2*sep_pkg::LC_STATE_BIT_WIDTH-1:0]     lc_state_o,  // Differentially encoded lifecycle state from the eFuse shadow registers; exported
                                                                    // to the SMC.
  output sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl_o,  // Per-feature enable vector (1 = enabled) derived from the LC state, the SiP and
                                                                     // system disable fuses, and the DEMOTE registers; all ones while security is
                                                                     // disabled, otherwise all zeros on an LC-state integrity error.
  output sep_lifecycle_ctrl_pkg::dbg_disable_t         dbg_disable_o,  // Per-interface debug disables for the DTP, active-high (1 = disabled).
  output logic                               sep_fuse_dft_disable_o,  // Disables the SEP fuse DFT access path, active-high; no functional consumer,
                                                                      // provided for DFT insertion.
  output logic                               smc_fuse_dft_disable_o,  // Disables the SMC fuse DFT access path, active-high; no functional consumer,
                                                                      // provided for DFT insertion.
  output logic                               lc_sigint_err_o,  // Integrity error on the
                                                               // differentially encoded LC state;
                                                               // forces every feature enable off
                                                               // unless security is disabled.
  output sep_efuse_pkg::efuse_map_t      shadow_regs_o,  // eFuse shadow register contents; secret
                                                         // fields read as zero in secure test mode.
  output logic                               fuse_sense_done_o,  // High once the shadow registers
                                                                 // have been loaded from the fuses.
  output logic                               secure_tm_o,  // Latched secure test mode, active-high;
                                                           // captured on the second clock edge
                                                           // after rst_ni release when security is
                                                           // disabled, otherwise on the rising edge
                                                           // of fuse sense done.

  output km_intf_pkg::km_rom_mem_req_t       km_rom_mem_req_o,  // Key Manager request to its 16 KiB
                                                                // ROM hard macro, instantiated at
                                                                // integration level.
  input  km_intf_pkg::km_rom_mem_rsp_t       km_rom_mem_rsp_i,  // Read data from the Key Manager
                                                                // ROM hard macro to the Key
                                                                // Manager.

  output km_intf_pkg::km_sram_mem_req_t      km_sram_mem_req_o,  // Key Manager request to its 32
                                                                 // KiB SRAM hard macro,
                                                                 // instantiated at integration
                                                                 // level.
  input  km_intf_pkg::km_sram_mem_rsp_t      km_sram_mem_rsp_i,  // Read data from the Key Manager
                                                                 // SRAM hard macro to the Key
                                                                 // Manager.

  output logic                               km_mbox_irq_to_sep_o,  // Key Manager mailbox interrupt to the SEP host.

  output logic                               km_unrecoverable_err_o,  // Key Manager unrecoverable fault, active-high: its CPU is in the trap state and no
                                                                      // longer executing.
  output logic                               km_recoverable_err_o,  // Key Manager recoverable-fault indication, from its KMCSR register bit.

  input  sep_pkg::sep_crypto_isolate_t       isolate_req_i,  // Per-path isolation requests from
                                                             // sep_reset_ctrl, active-high.
  output sep_pkg::sep_crypto_isolate_t       isolated_o,  // Per-path isolation acknowledge to
                                                          // sep_reset_ctrl, same layout as
                                                          // isolate_req_i; a bit is high once that
                                                          // path is isolated and its outstanding
                                                          // transactions have drained.
  input  sep_pkg::sep_sw_rst_t               gated_rst_ni,  // Isolation-sequenced software resets
                                                            // from sep_reset_ctrl (active-low).

  output logic [1:0]                         lcc_demote_state_1_o,  // Differentially encoded DEMOTE_1.demote register bit, which re-opens debug
                                                                    // feature bits [23:0] in TEST_DEV and PROD.
                                                                    // Exported to the SMC.

  output logic [1:0]                         lcc_demote_state_2_o,  // Differentially encoded DEMOTE_2.demote register bit, which re-opens debug
                                                                    // feature bits [47:24] in TEST_DEV and PROD.
                                                                    // Exported to the SMC.

  input  logic [EXT_TRNG_NUM_AXIS-1:0]       ext_trng_src_sel_i,  // Per-leg entropy source select:
                                                                  // 1 selects external TRNG stream
                                                                  // i, 0 the internal DRBG stream i
                                                                  // (from sep_cpu_ctrl via
                                                                  // sep_system_csr).
  input  logic                               km_wipe_state_i,  // Key Manager emergency wipe
                                                               // control; a rising edge zeroes the
                                                               // Key Manager key state (from
                                                               // sep_cpu_ctrl via sep_system_csr).

  output logic                               intr_hmac_done_o,  // HMAC done interrupt, to the SEP
                                                                // PIC.
  output logic                               intr_hmac_fifo_empty_o,  // HMAC message FIFO empty interrupt.
  output logic                               intr_hmac_err_o,  // HMAC error interrupt.

  output logic                               intr_kmac_done_o,  // KMAC done interrupt, to the SEP
                                                                // PIC.
  output logic                               intr_kmac_fifo_empty_o,  // KMAC message FIFO empty interrupt.
  output logic                               intr_kmac_err_o,  // KMAC error interrupt.

  output logic                               intr_cs_cmd_req_done_o,  // CSRNG command-request-done interrupt.
  output logic                               intr_cs_entropy_req_o,  // CSRNG entropy-request interrupt.
  output logic                               intr_cs_hw_inst_exc_o,  // CSRNG hardware-instance exception interrupt.
  output logic                               intr_cs_fatal_err_o,  // CSRNG fatal-error interrupt.

  output logic                               intr_edn_cmd_req_done_o,  // EDN command-request-done interrupt.
  output logic                               intr_edn_fatal_err_o,  // EDN fatal-error interrupt.

  output logic                               intr_otbn_done_o,  // OTBN done interrupt.

  output logic                               intr_abr_error_o,  // Adams Bridge (PQC) error
                                                                // interrupt; held low when the
                                                                // engine is compiled out.
  output logic                               intr_abr_notif_o,  // Adams Bridge notification
                                                                // interrupt, set on command
                                                                // completion; held low when the
                                                                // engine is compiled out.

  output sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t      sep_crypto_pka_imem_sram_req_o,  // OTBN instruction-memory request to the external IMEM SRAM.
  input  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t      sep_crypto_pka_imem_sram_rsp_i,  // Read data from the external OTBN IMEM SRAM.
  output sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t      sep_crypto_pka_dmem_sram_req_o,  // OTBN data-memory request to the external DMEM SRAM.
  input  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t      sep_crypto_pka_dmem_sram_rsp_i,  // Read data from the external OTBN DMEM SRAM.

  output sep_crypto_pkg::abr_mem_req_t                       abr_mem_req_o,  // Adams Bridge (PQC) requests to its external SRAMs, whose macros live in
                                                                             // sep_ip_integration; tied to zero when the engine is compiled out.
  input  sep_crypto_pkg::abr_mem_rsp_t                       abr_mem_rsp_i,  // Read data from the Adams Bridge external SRAMs.

  output logic                               crypto_alert_o,  // Aggregated crypto alert: OR of the
                                                              // alert pulses and integrity failures
                                                              // of the 11 OpenTitan alert receivers
                                                              // (HMAC, OTBN, AES, KMAC, CSRNG,
                                                              // EDN).

  output logic [9:0]                         sep_efuse_debug_o,  // eFuse controller debug flags:
                                                                 // [0] shadow write locked, [1]
                                                                 // shadow read locked, [2] program
                                                                 // locked, [3] read locked, [4]
                                                                 // write set-only, [5] LC-state
                                                                 // access, [6] read timeout, [7]
                                                                 // program timeout, [8] request
                                                                 // error, [9] secure TM blocked.
  output logic [5:0]                         sep_efuse_token_match_sip_debug_o,  // RMA SiP token match status code; 6'b010101 indicates a match.
  output logic [5:0]                         sep_efuse_token_match_chiplet_debug_o,  // RMA chiplet token match status code; 6'b010101 indicates a match.

  output logic                               locked_field_access_interrupt_o,  // Interrupt raised when an access targets a locked eFuse field.

  output logic                               token_match_fault_o,  // Token Comparator Redundancy
                                                                   // Fault Interrupt.

  output logic                               aes_bus_err_o,  // Sticky AES register-bridge fault;
                                                             // held until aes_bus_err_clr_i.
  output logic                               hmac_bus_err_o,  // Sticky HMAC register-bridge fault;
                                                              // held until hmac_bus_err_clr_i.
  output logic                               kmac_bus_err_o,  // Sticky KMAC register-bridge fault;
                                                              // held until kmac_bus_err_clr_i.
  output logic                               otbn_bus_err_o,  // Sticky OTBN register-bridge fault;
                                                              // held until otbn_bus_err_clr_i.
  output logic                               csrng_bus_err_o,  // Sticky CSRNG register-bridge
                                                               // fault; held until
                                                               // csrng_bus_err_clr_i.
  output logic                               edn_bus_err_o,  // Sticky EDN register-bridge fault;
                                                             // held until edn_bus_err_clr_i.
  input  logic                               aes_bus_err_clr_i,  // Single-cycle clear for
                                                                 // aes_bus_err_o, pulsed by
                                                                 // PERIPH_BUS_ERR_CLEAR.aes.
  input  logic                               hmac_bus_err_clr_i,  // Single-cycle clear for
                                                                  // hmac_bus_err_o, pulsed by
                                                                  // PERIPH_BUS_ERR_CLEAR.hmac.
  input  logic                               kmac_bus_err_clr_i,  // Single-cycle clear for
                                                                  // kmac_bus_err_o, pulsed by
                                                                  // PERIPH_BUS_ERR_CLEAR.kmac.
  input  logic                               otbn_bus_err_clr_i,  // Single-cycle clear for
                                                                  // otbn_bus_err_o, pulsed by
                                                                  // PERIPH_BUS_ERR_CLEAR.otbn.
  input  logic                               csrng_bus_err_clr_i,  // Single-cycle clear for
                                                                   // csrng_bus_err_o, pulsed by
                                                                   // PERIPH_BUS_ERR_CLEAR.csrng.
  input  logic                               edn_bus_err_clr_i  // Single-cycle clear for
                                                                // edn_bus_err_o, pulsed by
                                                                // PERIPH_BUS_ERR_CLEAR.edn.
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
  logic trng_reset_active;
  logic [sep_crypto_pkg::SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT-1:0] crypto_edn_endpoint_cancel;

  // Muxed AXI-Stream outputs (one per mux)
  drbg_pkg::drbg_axis_req_t [EXT_TRNG_NUM_AXIS-1:0] entropy_muxed_req;
  drbg_pkg::drbg_axis_rsp_t [EXT_TRNG_NUM_AXIS-1:0] entropy_muxed_rsp;

  /////////////////////////////
  // Crypto AXI Interconnect //
  /////////////////////////////

  sep_pkg::sep_32_32_axil_req_t
      otbn_axil_isolated_req, hmac_axil_isolated_req, aes_axil_isolated_req, kmac_axil_isolated_req;
  sep_pkg::sep_32_32_axil_resp_t
      otbn_axil_isolated_resp,
      hmac_axil_isolated_resp,
      aes_axil_isolated_resp,
      kmac_axil_isolated_resp;
  sep_pkg::sep_32_32_axil_req_t
      otbn_key_axil_req, aes_key_axil_req, hmac_key_axil_req, kmac_key_axil_req;
  sep_pkg::sep_32_32_axil_resp_t
      otbn_key_axil_resp, aes_key_axil_resp, hmac_key_axil_resp, kmac_key_axil_resp;
  sep_pkg::sep_32_32_axil_req_t
      otbn_key_axil_isolated_req,
      aes_key_axil_isolated_req,
      hmac_key_axil_isolated_req,
      kmac_key_axil_isolated_req;
  sep_pkg::sep_32_32_axil_resp_t
      otbn_key_axil_isolated_resp,
      aes_key_axil_isolated_resp,
      hmac_key_axil_isolated_resp,
      kmac_key_axil_isolated_resp;

  km_intf_pkg::km_axil_req_t abr_key_axil_req, km_efuse_axil_req;
  km_intf_pkg::km_axil_resp_t abr_key_axil_resp, km_efuse_axil_resp;
  km_intf_pkg::km_axil_req_t abr_key_axil_isolated_req, km_efuse_axil_isolated_req;
  km_intf_pkg::km_axil_resp_t abr_key_axil_isolated_resp, km_efuse_axil_isolated_resp;
  km_intf_pkg::km_axil_req_t     km_mbox_axil_req;
  km_intf_pkg::km_axil_resp_t    km_mbox_axil_resp;
  sep_pkg::sep_32_32_axil_req_t  esrc_axil_isolated_req;
  sep_pkg::sep_32_32_axil_resp_t esrc_axil_isolated_resp;
  drbg_pkg::drbg_axil64_req_t csrng_axil_isolated_req, edn_axil_isolated_req;
  drbg_pkg::drbg_axil64_resp_t csrng_axil_isolated_resp, edn_axil_isolated_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t fuse_axi_req, lifecycle_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t fuse_axi_resp, lifecycle_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  abr_axi_isolated_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t abr_axi_isolated_resp;

  sep_crypto_axi_interconnect u_sep_crypto_axi_interconnect (
    .clk_i                        (clk_i),
    .rst_ni                       (rst_ni),
    .test_en_i                    (test_en_i),
    .sep_crypto_axi_req_i         (sep_crypto_axi_req_i),
    .sep_crypto_axi_resp_o        (sep_crypto_axi_resp_o),
    .isolate_req_i                (isolate_req_i),
    .isolated_o                   (isolated_o),
    .otbn_axil_isolated_req_o     (otbn_axil_isolated_req),
    .otbn_axil_isolated_resp_i    (otbn_axil_isolated_resp),
    .hmac_axil_isolated_req_o     (hmac_axil_isolated_req),
    .hmac_axil_isolated_resp_i    (hmac_axil_isolated_resp),
    .aes_axil_isolated_req_o      (aes_axil_isolated_req),
    .aes_axil_isolated_resp_i     (aes_axil_isolated_resp),
    .kmac_axil_isolated_req_o     (kmac_axil_isolated_req),
    .kmac_axil_isolated_resp_i    (kmac_axil_isolated_resp),
    .otbn_key_axil_req_i          (otbn_key_axil_req),
    .otbn_key_axil_resp_o         (otbn_key_axil_resp),
    .aes_key_axil_req_i           (aes_key_axil_req),
    .aes_key_axil_resp_o          (aes_key_axil_resp),
    .hmac_key_axil_req_i          (hmac_key_axil_req),
    .hmac_key_axil_resp_o         (hmac_key_axil_resp),
    .kmac_key_axil_req_i          (kmac_key_axil_req),
    .kmac_key_axil_resp_o         (kmac_key_axil_resp),
    .abr_key_axil_req_i           (abr_key_axil_req),
    .abr_key_axil_resp_o          (abr_key_axil_resp),
    .km_efuse_axil_req_i          (km_efuse_axil_req),
    .km_efuse_axil_resp_o         (km_efuse_axil_resp),
    .otbn_key_axil_isolated_req_o (otbn_key_axil_isolated_req),
    .otbn_key_axil_isolated_resp_i(otbn_key_axil_isolated_resp),
    .aes_key_axil_isolated_req_o  (aes_key_axil_isolated_req),
    .aes_key_axil_isolated_resp_i (aes_key_axil_isolated_resp),
    .hmac_key_axil_isolated_req_o (hmac_key_axil_isolated_req),
    .hmac_key_axil_isolated_resp_i(hmac_key_axil_isolated_resp),
    .kmac_key_axil_isolated_req_o (kmac_key_axil_isolated_req),
    .kmac_key_axil_isolated_resp_i(kmac_key_axil_isolated_resp),
    .abr_key_axil_isolated_req_o  (abr_key_axil_isolated_req),
    .abr_key_axil_isolated_resp_i (abr_key_axil_isolated_resp),
    .km_efuse_axil_isolated_req_o (km_efuse_axil_isolated_req),
    .km_efuse_axil_isolated_resp_i(km_efuse_axil_isolated_resp),
    .km_mbox_axil_req_o           (km_mbox_axil_req),
    .km_mbox_axil_resp_i          (km_mbox_axil_resp),
    .esrc_axil_isolated_req_o     (esrc_axil_isolated_req),
    .esrc_axil_isolated_resp_i    (esrc_axil_isolated_resp),
    .csrng_axil_isolated_req_o    (csrng_axil_isolated_req),
    .csrng_axil_isolated_resp_i   (csrng_axil_isolated_resp),
    .edn_axil_isolated_req_o      (edn_axil_isolated_req),
    .edn_axil_isolated_resp_i     (edn_axil_isolated_resp),
    .ext_trng_axil_req_o          (ext_trng_axil_req_o),
    .ext_trng_axil_resp_i         (ext_trng_axil_resp_i),
    .fuse_axi_req_o               (fuse_axi_req),
    .fuse_axi_resp_i              (fuse_axi_resp),
    .lifecycle_axi_req_o          (lifecycle_axi_req),
    .lifecycle_axi_resp_i         (lifecycle_axi_resp),
    .abr_axi_isolated_req_o       (abr_axi_isolated_req),
    .abr_axi_isolated_resp_i      (abr_axi_isolated_resp)
  );

  // Internal entropy complex: coordinated reset/isolation, ESRC, and DRBG.
  // Source muxes and post-mux adapters remain below.
  sep_trng #(
    .NUM_AXIS(EXT_TRNG_NUM_AXIS)
  ) u_sep_trng (
    .clk_i                     (clk_i),
    .por_rst_ni                (rst_ni),
    .rst_ni                    (gated_rst_ni.trng),
    .entropy_rosc_sample_clk_i (entropy_rosc_sample_clk_i),
    .esrc_axil_req_i           (esrc_axil_isolated_req),
    .esrc_axil_resp_o          (esrc_axil_isolated_resp),
    .csrng_axil_req_i          (csrng_axil_isolated_req),
    .csrng_axil_resp_o         (csrng_axil_isolated_resp),
    .edn_axil_req_i            (edn_axil_isolated_req),
    .edn_axil_resp_o           (edn_axil_isolated_resp),
    .drbg_axis_req_o           (drbg_int_axis_req),
    .drbg_axis_rsp_i           (drbg_int_axis_rsp),
    .csrng_alert_rx_i          (crypto_alert_rx[8:7]),
    .csrng_alert_tx_o          (crypto_alert_tx[8:7]),
    .edn_alert_rx_i            (crypto_alert_rx[10:9]),
    .edn_alert_tx_o            (crypto_alert_tx[10:9]),
    .entropy_source_irq_o      (entropy_source_irq_o),
    .intr_cs_cmd_req_done_o    (intr_cs_cmd_req_done_o),
    .intr_cs_entropy_req_o     (intr_cs_entropy_req_o),
    .intr_cs_hw_inst_exc_o     (intr_cs_hw_inst_exc_o),
    .intr_cs_fatal_err_o       (intr_cs_fatal_err_o),
    .intr_edn_cmd_req_done_o   (intr_edn_cmd_req_done_o),
    .intr_edn_fatal_err_o      (intr_edn_fatal_err_o),
    .trng_reset_active_o       (trng_reset_active),
    .csrng_bus_err_o           (csrng_bus_err_o),
    .csrng_bus_err_clr_i       (csrng_bus_err_clr_i),
    .edn_bus_err_o             (edn_bus_err_o),
    .edn_bus_err_clr_i         (edn_bus_err_clr_i)
  );

  assign trng_entropy_clear_o = trng_reset_active;


  //////////////////
  // HMAC Wrapper //
  //////////////////

  hmac_wrapper u_hmac_wrapper_s3c_scan (
    .clk_i                   (clk_i),
    .rst_ni                  (gated_rst_ni.hmac),
    .hmac_axil_req_i         (hmac_axil_isolated_req),
    .hmac_axil_resp_o        (hmac_axil_isolated_resp),
    .hmac_key_axil_req_i     (hmac_key_axil_isolated_req),
    .hmac_key_axil_resp_o    (hmac_key_axil_isolated_resp),
    .intr_hmac_done_o        (intr_hmac_done_o),
    .intr_fifo_empty_o       (intr_hmac_fifo_empty_o),
    .intr_hmac_err_o         (intr_hmac_err_o),
    .alert_rx_i              (crypto_alert_rx[0:0]),
    .alert_tx_o              (crypto_alert_tx[0:0]),
    .idle_o                  (/* UNUSED */),
    .bus_err_o               (hmac_bus_err_o),
    .bus_err_clr_i           (hmac_bus_err_clr_i)
  );


  //////////////////
  // OTBN Wrapper //
  //////////////////

  sep_crypto_otbn_wrapper u_sep_crypto_otbn_wrapper_s3c_scan (
    .clk_i,
    .rst_ni                       (gated_rst_ni.otbn),
    .otbn_axil_req_i              (otbn_axil_isolated_req),
    .otbn_axil_resp_o             (otbn_axil_isolated_resp),
    .otbn_key_axil_req_i          (otbn_key_axil_isolated_req),
    .otbn_key_axil_resp_o         (otbn_key_axil_isolated_resp),
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
    .dmem_sram_rsp_i              (sep_crypto_pka_dmem_sram_rsp_i),
    .bus_err_o                    (otbn_bus_err_o),
    .bus_err_clr_i                (otbn_bus_err_clr_i)
  );


  /////////////////
  // AES Wrapper //
  /////////////////

  aes_wrapper u_aes_wrapper_s3c_scan (
    .clk_i               (clk_i),
    .rst_ni              (gated_rst_ni.aes),
    .aes_axil_req_i      (aes_axil_isolated_req),
    .aes_axil_resp_o     (aes_axil_isolated_resp),
    .aes_key_axil_req_i  (aes_key_axil_isolated_req),
    .aes_key_axil_resp_o (aes_key_axil_isolated_resp),
    .edn_req_o           (crypto_edn_req[0]),
    .edn_rsp_i           (crypto_edn_rsp[0]),
    .alert_rx_i          (crypto_alert_rx[4:3]),
    .alert_tx_o          (crypto_alert_tx[4:3]),
    .idle_o              (/* UNUSED */),
    .bus_err_o           (aes_bus_err_o),
    .bus_err_clr_i       (aes_bus_err_clr_i)
  );


  //////////////////
  // KMAC Wrapper //
  //////////////////

  kmac_wrapper u_kmac_wrapper_s3c_scan (
    .clk_i                   (clk_i),
    .rst_ni                  (gated_rst_ni.kmac),
    .kmac_axil_req_i         (kmac_axil_isolated_req),
    .kmac_axil_resp_o        (kmac_axil_isolated_resp),
    .kmac_key_axil_req_i     (kmac_key_axil_isolated_req),
    .kmac_key_axil_resp_o    (kmac_key_axil_isolated_resp),
    .edn_req_o               (crypto_edn_req[1]),
    .edn_rsp_i               (crypto_edn_rsp[1]),
    .intr_kmac_done_o        (intr_kmac_done_o),
    .intr_fifo_empty_o       (intr_kmac_fifo_empty_o),
    .intr_kmac_err_o         (intr_kmac_err_o),
    .alert_rx_i              (crypto_alert_rx[6:5]),
    .alert_tx_o              (crypto_alert_tx[6:5]),
    .idle_o                  (/* UNUSED */),
    .bus_err_o               (kmac_bus_err_o),
    .bus_err_clr_i           (kmac_bus_err_clr_i)
  );


  //////////////////////////
  // Adams Bridge Wrapper //
  //////////////////////////

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
  if (1) begin : gen_sep_abr_en_requires_caliptra
    $error(
        {
          "SEP_ABR_EN is set but CALIPTRA is not: the vendored abr_top would be ",
          "compiled without its Key-Vault ports and sep_abr_kv_shim cannot bind. ",
          "Define both (see the Adams Bridge source group in Bender.yml)."
        }
    );
  end
`endif

  sep_crypto_abr_wrapper #(
    .MASKING_EN   (MASKING_EN),
    .SRAM_LATENCY (SRAM_LATENCY)
  ) u_sep_crypto_abr_wrapper_s3c_scan (
    .clk_i                 (clk_i),
    .rst_ni                (gated_rst_ni.abr),
    // Control/status path: ABR AXI aperture off the crypto interconnect
    .abr_axi_req_i         (abr_axi_isolated_req),
    .abr_axi_resp_o        (abr_axi_isolated_resp),
    // Key path: KM private AXI4-Lite key bus (CSR block lives in the wrapper)
    .abr_key_axil_req_i    (abr_key_axil_isolated_req),
    .abr_key_axil_resp_o   (abr_key_axil_isolated_resp),
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
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (abr_axi_isolated_req),
    .slv_resp_o (abr_axi_isolated_resp)
  );

  // (2) Terminate the KM's private ABR key bus with DECERR. The key CSR block
  //     now lives inside the CALIPTRA-only wrapper, so there is no OKAY
  //     responder here; use an AXI4-Lite err-slave (mirrors u_abr_axi_err_slv).
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (km_intf_pkg::KM_AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH (km_intf_pkg::KM_AXI_DATA_WIDTH),
    .axil_req_t     (km_intf_pkg::km_axil_req_t),
    .axil_resp_t    (km_intf_pkg::km_axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (km_intf_pkg::KM_AXI_DATA_WIDTH),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) u_abr_key_err_slv (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .axil_req_i  (abr_key_axil_isolated_req),
    .axil_resp_o (abr_key_axil_isolated_resp)
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
    .slv_reqs_i  ({efuse_shim_axi_req_i, fuse_axi_req}),
    .slv_resps_o ({efuse_shim_axi_resp_o, fuse_axi_resp}),
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
    .SEP_SEC_DISABLE_TOKEN(SEP_SEC_DISABLE_TOKEN)
  ) u_sep_efuse_wrapper (
    .clk_i (clk_i),
    .rst_ni (rst_ni),
    .test_en_i    (test_en_i),
    .scan_rst_ni  (scan_rst_ni),

    .secure_tm_req_i                       (secure_tm_req_i),
    .ext_boot_seq_done_i                   (ext_boot_seq_done_i),

    .security_disable_o                    (security_disable_o),
    .lc_state_o                            (lc_state_o),
    .shadow_regs_o                         (shadow_regs_o),
    .fuse_sense_done_o                     (fuse_sense_done_o),

    .secure_tm_o                           (secure_tm_o),

    // DTP JTAG to AXI-Lite bus
    .axil_sep_otp_jtag_req_i               (axil_sep_otp_jtag_req_i),
    .axil_sep_otp_jtag_resp_o              (axil_sep_otp_jtag_resp_o),

    // Key Manager AXI-Lite manager interface
    .km_efuse_axil_req_i                   (km_efuse_axil_isolated_req),
    .km_efuse_axil_resp_o                  (km_efuse_axil_isolated_resp),

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

    .locked_field_access_interrupt_o       (locked_field_access_interrupt_o),

    .token_match_fault_o                   (token_match_fault_o)
  );

  sep_lifecycle_ctrl #(
    .LC_STATE_WIDTH(sep_pkg::LC_STATE_BIT_WIDTH)
  ) u_sep_lifecycle_ctrl (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .test_en_i            (test_en_i),

    .security_disable_i   (security_disable_o),
    .shadow_regs_i        (shadow_regs_o),
    .feat_ctrl_o          (feat_ctrl_o),
    .dbg_disable_o        (dbg_disable_o),
    .sep_fuse_dft_disable_o (sep_fuse_dft_disable_o),
    .smc_fuse_dft_disable_o (smc_fuse_dft_disable_o),
    .lcc_demote_state_1_o (lcc_demote_state_1_o),
    .lcc_demote_state_2_o (lcc_demote_state_2_o),
    .lc_sigint_err_o      (lc_sigint_err_o),

    .lifecycle_axi_req_i  (lifecycle_axi_req),
    .lifecycle_axi_resp_o (lifecycle_axi_resp)
  );

  //=========================================================================
  // OTP Data Assembly for Key Manager
  //=========================================================================
  // Assemble km_otp_data_t from efuse shadow registers and lifecycle ctrl.
  // LC state and demotion state arrive already differentially encoded from
  // their respective sources (shadow register and LCC output).
  // Seven 256-bit fields are dual-rail encoded here at the Sep->KM boundary
  // using prim_diff_encode_multi so that any fault on the wire is detectable.
  // Encoded format: data_o = {~value[255:0], value[255:0]} (512 bits total).
  //
  // The four secrets (chiplet_uid, sip_uid, sys_uid, class_key) sit in
  // sep_efuse_pkg::SecretShadowRanges. Under secure_tm the eFuse shadow
  // hardware output zeros those words, so the encoder dual-rail-encodes
  // zero. The three public identity fields (sep_chiplet_id, sep_sip_id,
  // sep_sys_id) are outside SecretShadowRanges and remain on the shadow
  // output in secure test mode.

  km_intf_pkg::km_otp_data_t km_otp_data;

  // LC state and demotion state arrive already differentially encoded from
  // their respective sources (shadow register and LCC output).
  assign km_otp_data.life_cycle       = shadow_regs_o.fields.lc_state.lc_state;
  assign km_otp_data.demotion_state_1 = lcc_demote_state_1_o;
  assign km_otp_data.demotion_state_2 = lcc_demote_state_2_o;

  // Dual-rail encode every 256-bit KM-routed OTP field.
  // OUTPUT_FLOP=0: purely combinational encode (no pipeline latency).
  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_chiplet_uid_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.chiplet_uid.uid),
    .data_o (km_otp_data.chiplet_uid)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_class_key_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.class_key.key),
    .data_o (km_otp_data.class_key)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_sip_uid_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.sip_uid.uid),
    .data_o (km_otp_data.sip_uid)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_sys_uid_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.sys_uid.uid),
    .data_o (km_otp_data.sys_uid)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_sep_chiplet_id_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.sep_chiplet_id.id),
    .data_o (km_otp_data.sep_chiplet_id)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_sep_sip_id_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.sep_sip_id.id),
    .data_o (km_otp_data.sep_sip_id)
  );

  prim_diff_encode_multi #(
    .WIDTH       (256),
    .OUTPUT_FLOP (1'b0)
  ) u_sep_sys_id_enc (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .data_i (shadow_regs_o.fields.sep_sys_id.id),
    .data_o (km_otp_data.sep_sys_id)
  );

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
  //
  // These post-mux adapters also serve the external source, so they remain in
  // the POR reset domain. An internal-TRNG reset synchronously clears buffered
  // entropy and handshake state without exporting a generated reset domain.
  // An engine reset cancels only that engine's endpoints. The engine reset
  // asserts the cycle after its isolation completes and releases with the
  // isolation request, so isolated-and-requested cancels the endpoint a cycle
  // ahead of the reset and holds it throughout, while EDN keeps serving the
  // engine during the drain. OTBN owns both RND and URND.
  assign crypto_edn_endpoint_cancel = {
    isolate_req_i.host_otbn & isolated_o.host_otbn & isolated_o.km_otbn,
    isolate_req_i.host_otbn & isolated_o.host_otbn & isolated_o.km_otbn,
    isolate_req_i.host_kmac & isolated_o.host_kmac & isolated_o.km_kmac,
    isolate_req_i.host_aes & isolated_o.host_aes & isolated_o.km_aes
  };

  drbg_axis_edn_adapter #(
    .NUM_ENDPOINTS(sep_crypto_pkg::SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT)
  ) u_axis_edn_crypto_s3c_scan (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .endpoint_cancel_i  (crypto_edn_endpoint_cancel),
    .clear_i            (trng_reset_active),
    .axis_req_i         (entropy_muxed_req[1]),
    .axis_rsp_o         (entropy_muxed_rsp[1]),
    .edn_req_i          (crypto_edn_req),
    .edn_rsp_o          (crypto_edn_rsp)
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
    .NUM_ENDPOINTS(sep_crypto_pkg::SEP_CRYPTO_POOL_EDN_CLIENT_COUNT)
  ) u_axis_edn_pool_s3c_scan (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .endpoint_cancel_i  ('0),
    .clear_i            (trng_reset_active),
    .axis_req_i         (entropy_muxed_req[2]),
    .axis_rsp_o         (entropy_muxed_rsp[2]),
    .edn_req_i          (pool_edn_req),
    .edn_rsp_o          (pool_edn_rsp)
  );

  //=========================================================================
  // Key Manager Instance
  //=========================================================================
  //
  // Connections:
  //   - Mailbox slave port    <- crypto interconnect via AXI4-64 to AXI-Lite-32 conversion
  //   - Crypto key bus master <- OTBN/AES/KMAC wrapper key ports
  //   - ROM/SRAM interfaces   <- exposed at sep_crypto top level (hard macros)
  //   - DRBG AXI-Stream       <- muxed from u_drbg_s3c_scan edn_axis_o[0] or ext_trng[0]

  key_manager #(
    .ROM_SIZE_BYTES       (16384),
    .SRAM_SIZE_BYTES      (32768),
    .MAILBOX_DEPTH        (16),
    .LATCHED_MEM_RDATA    (LATCHED_MEM_RDATA),
    .OTP_EFUSE_REMAP_BASE (32'(sep_top_addrmap_pkg::SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR))
  ) u_key_manager_s3c_scan (
    .clk_i              (clk_i),
    // Cold reset: SEP system cold reset (AASD) resets the entire KM.
    .cold_rst_ni         (sep_reset_ni),
    // Warm reset: SEP KM sub-component software reset CSR bit triggers a
    // partial synchronous reset of the KM CPU and volatile state only.
    .warm_rst_ni         (gated_rst_ni.km),

    // Mailbox AXI-Lite slave (from the crypto interconnect, via conversion)
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
`ifdef OCAH_DEBUG_LIVE  // elaboration-time width checks; excluded from synthesis
  initial begin : gen_km_efuse_axil_type_assertions
    assert ($bits(km_intf_pkg::km_axil_req_t) == $bits(sep_efuse_pkg::efuse_axil_req_t))
    else $fatal(1, "KM_EFUSE_AXIL req width mismatch: km_axil_req_t != efuse_axil_req_t");
    assert ($bits(km_intf_pkg::km_axil_resp_t) == $bits(sep_efuse_pkg::efuse_axil_resp_t))
    else $fatal(1, "KM_EFUSE_AXIL resp width mismatch: km_axil_resp_t != efuse_axil_resp_t");
  end
`endif  // OCAH_DEBUG_LIVE

endmodule

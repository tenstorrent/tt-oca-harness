// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// Key Manager Testbench
//
// Description:
// Top-level testbench for Key Manager verification
// Instantiates key_manager top-level module with ROM/SRAM memory models
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

`include "axi/assign.svh"
`include "axi/typedef.svh"
import km_intf_pkg::*;
import axi_pkg::*;
import hmac_wrapper_key_reg_pkg::*;
import aes_wrapper_key_reg_pkg::*;
import kmac_wrapper_key_reg_pkg::*;
import otbn_wrapper_key_reg_pkg::*;
import abr_wrapper_key_reg_pkg::*;

module tb_key_manager;

  //=========================================================================
  // SEP AXI4-Lite Type Definitions (32-bit)
  //=========================================================================
  // SEP AXI types are defined here for testbench use.

  localparam int unsigned SEP_AXI_ADDR_WIDTH = 32;
  localparam int unsigned SEP_AXI_DATA_WIDTH = 32;
  localparam int unsigned SEP_AXI_STRB_WIDTH = SEP_AXI_DATA_WIDTH / 8;

  typedef logic [SEP_AXI_ADDR_WIDTH-1:0] sep_addr_t;
  typedef logic [SEP_AXI_DATA_WIDTH-1:0] sep_data_t;
  typedef logic [SEP_AXI_STRB_WIDTH-1:0] sep_strb_t;

  // Generate all SEP AXI-Lite types using macro
  // Creates: sep_axil_aw_chan_t, sep_axil_w_chan_t, sep_axil_b_chan_t,
  //          sep_axil_ar_chan_t, sep_axil_r_chan_t, sep_axil_req_t, sep_axil_resp_t
  `AXI_LITE_TYPEDEF_ALL(sep_axil, sep_addr_t, sep_data_t, sep_strb_t)

  // Clock and reset
  logic clk;
  logic cold_rst_n = 1'b0;  // Cold (AASD) reset — resets entire KM
  logic warm_rst_n = 1'b1;  // Warm (synchronous) reset — resets CPU + volatile state only
  logic test_en = 1'b0;

  // Parity error injection signals (for testing)
  logic        rom_parity_err_inject = 1'b0;
  logic        sram_parity_err_inject = 1'b0;

  // ROM memory array (size from interface package)
  localparam int unsigned ROM_SIZE_WORDS = km_intf_pkg::ROM_SIZE_BYTES / 4;
  logic [31:0] rom_mem[0:ROM_SIZE_WORDS-1];

  // Virtual ROM memory array (size from interface package)
  localparam int unsigned VROM_SIZE_WORDS = km_intf_pkg::VROM_SIZE_BYTES / 4;
  logic [31:0] vrom_mem[0:VROM_SIZE_WORDS-1];

  //=========================================================================
  // Clock Generation
  //=========================================================================

  initial begin
    clk = 0;
    forever #5ns clk = ~clk;  // 10ns period = 100MHz
  end

  //=========================================================================
  // Reset Generation
  //=========================================================================
  // Reset is controlled entirely by cocotb test - initialize to reset state (active low)
  // DO NOT de-assert reset here - cocotb will control reset timing via reset_dut()
  initial begin
    // Start in cold reset (active low) - cocotb will control de-assertion.
    // Defaults are also applied at declaration time to avoid time-zero X races.
    cold_rst_n = 1'b0;
    warm_rst_n = 1'b1;  // Warm reset deasserted by default (active-low: 1 = not resetting)
    test_en = 1'b0;
    // Initialize parity injection to disabled (prevents X values causing spurious errors)
    rom_parity_err_inject = 1'b0;
    sram_parity_err_inject = 1'b0;
  end

  //=========================================================================
  // DUT: Top-Level Key Manager Module
  //=========================================================================

  // ROM/SRAM memory interfaces (from top-level module)
  km_rom_mem_req_t  km_rom_mem_req;
  km_rom_mem_rsp_t  km_rom_mem_rsp;
  km_sram_mem_req_t km_sram_mem_req;
  km_sram_mem_rsp_t km_sram_mem_rsp;

  // External crypto engine ports (stubs)
  km_axil_req_t  otbn_req;
  km_axil_resp_t otbn_resp;
  km_axil_req_t  aes_req;
  km_axil_resp_t aes_resp;
  km_axil_req_t  kmac_req;
  km_axil_resp_t kmac_resp;
  km_axil_req_t  hmac_req;
  km_axil_resp_t hmac_resp;

  // OTP/eFuse AXI-Lite port (crossbar master 8, driven via efuse_req_o/resp_i).
  // key_manager.sv remaps KM-local 0x0001_1xxx -> 0x1093_0xxx before driving
  // this bus, so the responder decodes 0x1093_0xxx.
  km_axil_req_t  efuse_req;
  km_axil_resp_t efuse_resp;

  // Adams Bridge sideload window (crossbar master 9, ABR_BASE_ADDR 0x0001_Cxxx).
  // Connected to the abr_wrapper_key reg block instantiated below.
  km_axil_req_t  abr_req;
  km_axil_resp_t abr_resp;

  // ML-KEM shared-key IRQ: sustained level (KEY_VALID & IRQ_ENABLE).
  logic abr_mlkem_sharedkey_irq;

  // TB-side signals for modeling Adams Bridge writing a shared key into the reg block.
  // cocotb drives tb_abr_sk_load_data[i] and tb_abr_sk_load_valid to inject a key.
  logic [31:0] tb_abr_sk_load_data [8];  // Shared key words from TB model
  logic        tb_abr_sk_load_valid;      // Pulse: set KEY_CTRL.KEY_VALID via hwset

  // SEP mailbox interface (for cocotb access)
  km_axil_req_t  mbox_sep_req;
  km_axil_resp_t mbox_sep_resp;

  // Mailbox IRQ to SEP (exposed for cocotb)
  logic mbox_irq_to_sep;

  // Error condition outputs (exposed for cocotb / waveform)
  logic unrecoverable_err;
  logic recoverable_err;

  // DRBG AXI-Stream (flattened for cocotb; tie off when not driven)
  logic        drbg_tvalid = 1'b0;
  logic [31:0] drbg_tdata = 32'h0;
  logic [3:0]  drbg_tstrb = 4'h0;
  logic        drbg_tready;
  km_drbg_axis_req_t  drbg_axis_req;
  km_drbg_axis_resp_t drbg_axis_resp;
  assign drbg_axis_req.tvalid = drbg_tvalid;
  assign drbg_axis_req.tdata  = drbg_tdata;
  assign drbg_axis_req.tstrb  = drbg_tstrb;
  assign drbg_tready = drbg_axis_resp.tready;
  // OTP data interface (for test_otp_data; cocotb can drive)
  km_otp_data_t otp_data = '0;

  // Wipe state (for test_wipe_state; cocotb pulses to trigger KPV zero and WIPE_STATE IRQ)
  logic          wipe_state = 1'b0;

  key_manager #(
    .ROM_SIZE_BYTES(km_intf_pkg::ROM_SIZE_BYTES),
    .SRAM_SIZE_BYTES(km_intf_pkg::SRAM_SIZE_BYTES),
    .MAILBOX_DEPTH(16),
    .LATCHED_MEM_RDATA(1'b1)  // Testbench ROM/SRAM models hold rdata after read completion
  ) u_key_manager (
    .clk_i              (clk),
    .cold_rst_ni         (cold_rst_n),  // Cold reset: deasserted by cocotb reset_dut()
    .warm_rst_ni         (warm_rst_n),  // Warm reset: pulsed by cocotb TB_CMD_KM_WARM_RESET
    // Mailbox SEP interface (for cocotb testing)
    .mbox_sep_req_i     (mbox_sep_req),
    .mbox_sep_resp_o    (mbox_sep_resp),
    .mbox_irq_to_sep_o  (mbox_irq_to_sep),
    // Error condition outputs (for monitoring; cocotb can probe)
    .unrecoverable_err_o (unrecoverable_err),
    .recoverable_err_o  (recoverable_err),
    // External crypto engine ports (stubs)
    .otbn_req_o         (otbn_req),
    .otbn_resp_i        (otbn_resp),
    .aes_req_o          (aes_req),
    .aes_resp_i         (aes_resp),
    .kmac_req_o         (kmac_req),
    .kmac_resp_i        (kmac_resp),
    .hmac_req_o         (hmac_req),
    .hmac_resp_i        (hmac_resp),
    // OTP/eFuse AXI-Lite port (wired to behavioral responder below)
    .efuse_req_o        (efuse_req),
    .efuse_resp_i       (efuse_resp),
    // Adams Bridge sideload window (wired to abr_wrapper_key reg block below)
    .abr_req_o              (abr_req),
    .abr_resp_i             (abr_resp),
    .abr_mlkem_sharedkey_irq_i(abr_mlkem_sharedkey_irq),
    // ROM/SRAM memory interfaces (to memory models)
    .rom_mem_req_o      (km_rom_mem_req),
    .rom_mem_rsp_i      (km_rom_mem_rsp),
    .sram_mem_req_o     (km_sram_mem_req),
    .sram_mem_rsp_i     (km_sram_mem_rsp),
    // DRBG AXI-Stream (tie-off; cocotb can drive for DRBG tests)
    .drbg_axis_req_i    (drbg_axis_req),
    .drbg_axis_resp_o   (drbg_axis_resp),
    // OTP data (read-through; cocotb drives for test_otp_data)
    .otp_data_i        (otp_data),
    // Wipe state (cocotb pulses for test_wipe_state)
    .wipe_state_i      (wipe_state),
    // Test mode (DFT enable)
    .test_en_i           (test_en),
    // Scan chain (tied off - not controlled by testbench)
    .scan_rst_ni         (1'b1)             // Scan reset disabled (active-low: 1 = normal operation)
  );

  //=========================================================================
  // Crypto Engine Key Register Blocks (HMAC, AES, KMAC, OTBN)
  //=========================================================================
  // PeakRDL-generated AXI-Lite key sideload register blocks connected
  // directly to the Key Manager's private bus. No full crypto engines
  // needed -- firmware only writes keys and controls key_valid via these
  // registers.
  //
  // hwif_out structs are connected and flattened into arrays so cocotb
  // can read back the write-only key shares via TB_CMD_KEY_SHARE_READ.

  hmac_wrapper_key_reg_pkg::hmac_wrapper_key__out_t hmac_hwif_out;
  aes_wrapper_key_reg_pkg::aes_wrapper_key__out_t   aes_hwif_out;
  kmac_wrapper_key_reg_pkg::kmac_wrapper_key__out_t kmac_hwif_out;
  otbn_wrapper_key_reg_pkg::otbn_wrapper_key__out_t otbn_hwif_out;

  // Flat arrays for cocotb readback (engine order: 0=HMAC, 1=KMAC, 2=AES, 3=OTBN)
  wire [31:0] hmac_share0 [8];
  wire [31:0] hmac_share1 [8];
  wire [31:0] aes_share0  [8];
  wire [31:0] aes_share1  [8];
  wire [31:0] kmac_share0 [8];
  wire [31:0] kmac_share1 [8];
  wire [31:0] otbn_share0 [12];
  wire [31:0] otbn_share1 [12];

  for (genvar gi = 0; gi < 8; gi++) begin : gen_key_shares_8
    assign hmac_share0[gi] = hmac_hwif_out.KEY_SHARE0[gi].data.value;
    assign hmac_share1[gi] = hmac_hwif_out.KEY_SHARE1[gi].data.value;
    assign aes_share0[gi]  = aes_hwif_out.KEY_SHARE0[gi].data.value;
    assign aes_share1[gi]  = aes_hwif_out.KEY_SHARE1[gi].data.value;
    assign kmac_share0[gi] = kmac_hwif_out.KEY_SHARE0[gi].data.value;
    assign kmac_share1[gi] = kmac_hwif_out.KEY_SHARE1[gi].data.value;
  end
  for (genvar gi = 0; gi < 12; gi++) begin : gen_key_shares_12
    assign otbn_share0[gi] = otbn_hwif_out.KEY_SHARE0[gi].data.value;
    assign otbn_share1[gi] = otbn_hwif_out.KEY_SHARE1[gi].data.value;
  end

  hmac_wrapper_key_reg u_hmac_key_reg (
    .clk            (clk),
    .arst_n         (cold_rst_n),
    .s_axil_awvalid (hmac_req.aw_valid),
    .s_axil_awready (hmac_resp.aw_ready),
    .s_axil_awaddr  (hmac_req.aw.addr[HMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (hmac_req.aw.prot),
    .s_axil_wvalid  (hmac_req.w_valid),
    .s_axil_wready  (hmac_resp.w_ready),
    .s_axil_wdata   (hmac_req.w.data),
    .s_axil_wstrb   (hmac_req.w.strb),
    .s_axil_bvalid  (hmac_resp.b_valid),
    .s_axil_bready  (hmac_req.b_ready),
    .s_axil_bresp   (hmac_resp.b.resp),
    .s_axil_arvalid (hmac_req.ar_valid),
    .s_axil_arready (hmac_resp.ar_ready),
    .s_axil_araddr  (hmac_req.ar.addr[HMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (hmac_req.ar.prot),
    .s_axil_rvalid  (hmac_resp.r_valid),
    .s_axil_rready  (hmac_req.r_ready),
    .s_axil_rdata   (hmac_resp.r.data),
    .s_axil_rresp   (hmac_resp.r.resp),
    .hwif_out       (hmac_hwif_out)
  );

  aes_wrapper_key_reg u_aes_key_reg (
    .clk            (clk),
    .arst_n         (cold_rst_n),
    .s_axil_awvalid (aes_req.aw_valid),
    .s_axil_awready (aes_resp.aw_ready),
    .s_axil_awaddr  (aes_req.aw.addr[AES_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (aes_req.aw.prot),
    .s_axil_wvalid  (aes_req.w_valid),
    .s_axil_wready  (aes_resp.w_ready),
    .s_axil_wdata   (aes_req.w.data),
    .s_axil_wstrb   (aes_req.w.strb),
    .s_axil_bvalid  (aes_resp.b_valid),
    .s_axil_bready  (aes_req.b_ready),
    .s_axil_bresp   (aes_resp.b.resp),
    .s_axil_arvalid (aes_req.ar_valid),
    .s_axil_arready (aes_resp.ar_ready),
    .s_axil_araddr  (aes_req.ar.addr[AES_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (aes_req.ar.prot),
    .s_axil_rvalid  (aes_resp.r_valid),
    .s_axil_rready  (aes_req.r_ready),
    .s_axil_rdata   (aes_resp.r.data),
    .s_axil_rresp   (aes_resp.r.resp),
    .hwif_out       (aes_hwif_out)
  );

  kmac_wrapper_key_reg u_kmac_key_reg (
    .clk            (clk),
    .arst_n         (cold_rst_n),
    .s_axil_awvalid (kmac_req.aw_valid),
    .s_axil_awready (kmac_resp.aw_ready),
    .s_axil_awaddr  (kmac_req.aw.addr[KMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (kmac_req.aw.prot),
    .s_axil_wvalid  (kmac_req.w_valid),
    .s_axil_wready  (kmac_resp.w_ready),
    .s_axil_wdata   (kmac_req.w.data),
    .s_axil_wstrb   (kmac_req.w.strb),
    .s_axil_bvalid  (kmac_resp.b_valid),
    .s_axil_bready  (kmac_req.b_ready),
    .s_axil_bresp   (kmac_resp.b.resp),
    .s_axil_arvalid (kmac_req.ar_valid),
    .s_axil_arready (kmac_resp.ar_ready),
    .s_axil_araddr  (kmac_req.ar.addr[KMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (kmac_req.ar.prot),
    .s_axil_rvalid  (kmac_resp.r_valid),
    .s_axil_rready  (kmac_req.r_ready),
    .s_axil_rdata   (kmac_resp.r.data),
    .s_axil_rresp   (kmac_resp.r.resp),
    .hwif_out       (kmac_hwif_out)
  );

  otbn_wrapper_key_reg u_otbn_key_reg (
    .clk            (clk),
    .arst_n         (cold_rst_n),
    .s_axil_awvalid (otbn_req.aw_valid),
    .s_axil_awready (otbn_resp.aw_ready),
    .s_axil_awaddr  (otbn_req.aw.addr[OTBN_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (otbn_req.aw.prot),
    .s_axil_wvalid  (otbn_req.w_valid),
    .s_axil_wready  (otbn_resp.w_ready),
    .s_axil_wdata   (otbn_req.w.data),
    .s_axil_wstrb   (otbn_req.w.strb),
    .s_axil_bvalid  (otbn_resp.b_valid),
    .s_axil_bready  (otbn_req.b_ready),
    .s_axil_bresp   (otbn_resp.b.resp),
    .s_axil_arvalid (otbn_req.ar_valid),
    .s_axil_arready (otbn_resp.ar_ready),
    .s_axil_araddr  (otbn_req.ar.addr[OTBN_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (otbn_req.ar.prot),
    .s_axil_rvalid  (otbn_resp.r_valid),
    .s_axil_rready  (otbn_req.r_ready),
    .s_axil_rdata   (otbn_resp.r.data),
    .s_axil_rresp   (otbn_resp.r.resp),
    .hwif_out       (otbn_hwif_out)
  );

  //=========================================================================
  // Adams Bridge Key Sideload Register Block
  //=========================================================================
  // Single abr_wrapper_key_reg instance on crossbar master port 9.
  // Mirrors the existing engine key-reg pattern (u_hmac_key_reg, etc.).
  //
  // - Four seed sub-blocks (MLDSA_SEED, MLKEM_SEED_D, MLKEM_SEED_Z, MLKEM_MSG):
  //   hwif_out provides KEY_SHARE0/1 arrays readable by cocotb via
  //   TB_CMD_KEY_SHARE_READ.
  // - MLKEM_SHARED_KEY sub-block: hwif_in allows the TB model to inject a
  //   shared key (next+we on KEY[*].data) and set KEY_VALID via hwset.
  //   The same load event hwsets the sticky IRQ_STATUS.key_valid bit; the
  //   reg block clears it on a firmware W1C write.

  abr_wrapper_key_reg_pkg::abr_wrapper_key__in_t  abr_hwif_in;
  abr_wrapper_key_reg_pkg::abr_wrapper_key__out_t abr_hwif_out;

  // Flat seed share arrays for cocotb readback (sub-block order:
  //   4=MLDSA_SEED, 5=MLKEM_SEED_D, 6=MLKEM_SEED_Z, 7=MLKEM_MSG)
  wire [31:0] mldsa_seed_share0 [8];
  wire [31:0] mldsa_seed_share1 [8];
  wire [31:0] mlkem_seed_d_share0 [8];
  wire [31:0] mlkem_seed_d_share1 [8];
  wire [31:0] mlkem_seed_z_share0 [8];
  wire [31:0] mlkem_seed_z_share1 [8];
  wire [31:0] mlkem_msg_share0 [8];
  wire [31:0] mlkem_msg_share1 [8];

  for (genvar gi = 0; gi < 8; gi++) begin : gen_abr_seed_shares
    assign mldsa_seed_share0[gi]   = abr_hwif_out.MLDSA_SEED.KEY_SHARE0[gi].data.value;
    assign mldsa_seed_share1[gi]   = abr_hwif_out.MLDSA_SEED.KEY_SHARE1[gi].data.value;
    assign mlkem_seed_d_share0[gi] = abr_hwif_out.MLKEM_SEED_D.KEY_SHARE0[gi].data.value;
    assign mlkem_seed_d_share1[gi] = abr_hwif_out.MLKEM_SEED_D.KEY_SHARE1[gi].data.value;
    assign mlkem_seed_z_share0[gi] = abr_hwif_out.MLKEM_SEED_Z.KEY_SHARE0[gi].data.value;
    assign mlkem_seed_z_share1[gi] = abr_hwif_out.MLKEM_SEED_Z.KEY_SHARE1[gi].data.value;
    assign mlkem_msg_share0[gi]    = abr_hwif_out.MLKEM_MSG.KEY_SHARE0[gi].data.value;
    assign mlkem_msg_share1[gi]    = abr_hwif_out.MLKEM_MSG.KEY_SHARE1[gi].data.value;
  end

  assign abr_mlkem_sharedkey_irq =
        abr_hwif_out.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.value &
        abr_hwif_out.MLKEM_SHARED_KEY.IRQ_ENABLE.key_valid_en.value;

  always_comb begin
    abr_hwif_in = '{default:'0};

    // The sticky IRQ_STATUS bit is set by hardware (hwset) on the same
    // key-ready event that loads the key; the reg block clears it on W1C.
    abr_hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.next  = 1'b0;
    abr_hwif_in.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.hwset = tb_abr_sk_load_valid;

    // TB-modeled AB write: load shared-key words and set KEY_VALID.
    for (int i = 0; i < 8; i++) begin
      abr_hwif_in.MLKEM_SHARED_KEY.KEY[i].data.next = tb_abr_sk_load_data[i];
      abr_hwif_in.MLKEM_SHARED_KEY.KEY[i].data.we   = tb_abr_sk_load_valid;
      // hwclr: hardware clears word to 0 when KEY_VALID drops (KEY_CTRL = 0).
      abr_hwif_in.MLKEM_SHARED_KEY.KEY[i].data.hwclr =
                ~abr_hwif_out.MLKEM_SHARED_KEY.KEY_CTRL.key_valid.value;
    end
    abr_hwif_in.MLKEM_SHARED_KEY.KEY_CTRL.key_valid.hwset = tb_abr_sk_load_valid;
  end

  // Initialize TB shared-key injection signals to quiescent state.
  initial begin
    for (int i = 0; i < 8; i++) tb_abr_sk_load_data[i] = '0;
    tb_abr_sk_load_valid = 1'b0;
  end

  abr_wrapper_key_reg u_abr_key_reg (
    .clk            (clk),
    .arst_n         (cold_rst_n),
    .s_axil_awvalid (abr_req.aw_valid),
    .s_axil_awready (abr_resp.aw_ready),
    .s_axil_awaddr  (abr_req.aw.addr[ABR_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (abr_req.aw.prot),
    .s_axil_wvalid  (abr_req.w_valid),
    .s_axil_wready  (abr_resp.w_ready),
    .s_axil_wdata   (abr_req.w.data),
    .s_axil_wstrb   (abr_req.w.strb),
    .s_axil_bvalid  (abr_resp.b_valid),
    .s_axil_bready  (abr_req.b_ready),
    .s_axil_bresp   (abr_resp.b.resp),
    .s_axil_arvalid (abr_req.ar_valid),
    .s_axil_arready (abr_resp.ar_ready),
    .s_axil_araddr  (abr_req.ar.addr[ABR_WRAPPER_KEY_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (abr_req.ar.prot),
    .s_axil_rvalid  (abr_resp.r_valid),
    .s_axil_rready  (abr_req.r_ready),
    .s_axil_rdata   (abr_resp.r.data),
    .s_axil_rresp   (abr_resp.r.resp),
    .hwif_in        (abr_hwif_in),
    .hwif_out       (abr_hwif_out)
  );

  //=========================================================================
  // OTP/eFuse AXI-Lite Behavioral Responder
  //=========================================================================
  // Responds to transactions on efuse_req/efuse_resp (connected to the DUT's
  // efuse_req_o/efuse_resp_i ports).  key_manager.sv remaps the KM-local
  // OTP window (OTP_BASE_ADDR) to the SEP eFuse absolute base determined by
  // the DUT's OTP_EFUSE_REMAP_BASE parameter before driving this interface.
  // The responder therefore decodes the *remapped* address window.
  //
  // Behavior:
  //  - OKAY  for addresses in [EFUSE_RESP_BASE : EFUSE_RESP_END]; uses addr[11:2]
  //          as a word index into a 4 KB RAM.
  //  - SLVERR for any address outside that window.  A broken remap would
  //          deliver OTP_BASE_ADDR here, which is outside the window and would
  //          fail any firmware test that checks the AXI response.
  // Single-cycle ready; no pipeline stages.

  // Derive the window bounds directly from the DUT parameter so this
  // responder stays correct if OTP_EFUSE_REMAP_BASE is overridden.
  localparam logic [31:0] EFUSE_RESP_BASE = u_key_manager.OTP_EFUSE_REMAP_BASE;
  localparam logic [31:0] EFUSE_RESP_END = u_key_manager.OTP_EFUSE_REMAP_BASE + 32'h0FFF;
  localparam int unsigned EFUSE_MEM_WORDS = 1024;  // 4 KB / 4 B (covers MAP+CTRL+MMR)

  logic [31:0] efuse_mem [EFUSE_MEM_WORDS];

  // AXI-Lite write channel — AW and W may arrive independently (AXI-Lite spec).
  // Track each in separate buffers and produce B only after both are captured.
  logic        efuse_aw_pend;   // AW latched, waiting for matching W
  logic [31:0] efuse_aw_addr;
  logic        efuse_w_pend;    // W latched, waiting for matching AW
  logic [31:0] efuse_w_data;
  logic        efuse_b_pend;    // B response outstanding
  logic [1:0]  efuse_b_resp;

  // Combinatorial signals used inside the always_ff write block
  logic        efuse_aw_fire;   // AW handshake this cycle
  logic        efuse_w_fire;    // W  handshake this cycle
  logic [31:0] efuse_waddr_nxt; // resolved write address
  logic [31:0] efuse_wdata_nxt; // resolved write data

  assign efuse_aw_fire   = efuse_req.aw_valid & !efuse_aw_pend & !efuse_b_pend;
  assign efuse_w_fire    = efuse_req.w_valid  & !efuse_w_pend  & !efuse_b_pend;
  assign efuse_waddr_nxt = efuse_aw_pend ? efuse_aw_addr : efuse_req.aw.addr;
  assign efuse_wdata_nxt = efuse_w_pend  ? efuse_w_data  : efuse_req.w.data;

  always_ff @(posedge clk or negedge cold_rst_n) begin
    if (!cold_rst_n) begin
      efuse_aw_pend <= 1'b0;
      efuse_w_pend  <= 1'b0;
      efuse_b_pend  <= 1'b0;
      efuse_aw_addr <= '0;
      efuse_w_data  <= '0;
      efuse_b_resp  <= 2'b00;
    end else begin
      // Latch AW
      if (efuse_aw_fire) begin
        efuse_aw_pend <= 1'b1;
        efuse_aw_addr <= efuse_req.aw.addr;
      end
      // Latch W
      if (efuse_w_fire) begin
        efuse_w_pend <= 1'b1;
        efuse_w_data <= efuse_req.w.data;
      end
      // When both are available (just latched or already pending): execute write
      if ((efuse_aw_pend | efuse_aw_fire) && (efuse_w_pend | efuse_w_fire)) begin
        if (efuse_waddr_nxt >= EFUSE_RESP_BASE && efuse_waddr_nxt <= EFUSE_RESP_END) begin
          efuse_mem[efuse_waddr_nxt[11:2]] <= efuse_wdata_nxt;
          efuse_b_resp <= 2'b00; // OKAY
        end else begin
          efuse_b_resp <= 2'b10;  // SLVERR
        end
        efuse_aw_pend <= 1'b0;
        efuse_w_pend  <= 1'b0;
        efuse_b_pend  <= 1'b1;
      end
      // Clear B when master accepts response
      if (efuse_b_pend && efuse_req.b_ready) begin
        efuse_b_pend <= 1'b0;
      end
    end
  end

  // Read channel: latch AR address, return data one cycle later
  logic        efuse_r_pend;
  logic [31:0] efuse_r_data;
  logic [1:0]  efuse_r_resp;

  always_ff @(posedge clk or negedge cold_rst_n) begin
    if (!cold_rst_n) begin
      efuse_r_pend <= 1'b0;
      efuse_r_data <= '0;
      efuse_r_resp <= 2'b00;
    end else begin
      if (efuse_req.ar_valid && !efuse_r_pend) begin
        efuse_r_pend <= 1'b1;
        if (efuse_req.ar.addr >= EFUSE_RESP_BASE && efuse_req.ar.addr <= EFUSE_RESP_END) begin
          efuse_r_data <= efuse_mem[efuse_req.ar.addr[11:2]];
          efuse_r_resp <= 2'b00; // OKAY
        end else begin
          efuse_r_data <= 32'hDEAD_C0DE;
          efuse_r_resp <= 2'b10; // SLVERR
        end
      end
      if (efuse_r_pend && efuse_req.r_ready) begin
        efuse_r_pend <= 1'b0;
      end
    end
  end

  // Drive AXI-Lite response channels from registered state
  always_comb begin
    efuse_resp.aw_ready = !efuse_aw_pend && !efuse_b_pend;
    efuse_resp.w_ready  = !efuse_w_pend  && !efuse_b_pend;
    efuse_resp.b_valid  = efuse_b_pend;
    efuse_resp.b.resp   = efuse_b_resp;
    efuse_resp.ar_ready = !efuse_r_pend;
    efuse_resp.r_valid  = efuse_r_pend;
    efuse_resp.r.data   = efuse_r_data;
    efuse_resp.r.resp   = efuse_r_resp;
  end

  //=========================================================================
  // Virtual ROM Connection (testbench only - attaches directly to mem_* bus)
  //=========================================================================
  // Virtual ROM memory bus is exposed directly from CPU wrapper
  // Testbench attaches to mem_* signals and drives responses directly

  // Probe virtual ROM memory bus signals from CPU wrapper
  wire        vrom_mem_valid = u_key_manager.u_cpu.vrom_mem_valid;
  wire        vrom_mem_instr = u_key_manager.u_cpu.vrom_mem_instr;
  wire [31:0] vrom_mem_addr  = u_key_manager.u_cpu.vrom_mem_addr;
  wire [31:0] vrom_mem_wdata = u_key_manager.u_cpu.vrom_mem_wdata;
  wire [3:0]  vrom_mem_wstrb = u_key_manager.u_cpu.vrom_mem_wstrb;
  wire        vrom_mem_la_read = u_key_manager.u_cpu.vrom_mem_la_read;
  wire [31:0] vrom_mem_la_addr = u_key_manager.u_cpu.vrom_mem_la_addr;

  // Drive virtual ROM response signals directly
  wire        vrom_mem_ready;
  wire [31:0] vrom_mem_rdata;

  // Force the response signals to be driven by testbench
  initial begin
    force u_key_manager.u_cpu.vrom_mem_ready = vrom_mem_ready;
    force u_key_manager.u_cpu.vrom_mem_rdata = vrom_mem_rdata;
  end

  //=========================================================================
  // ROM Connection (to top-level key_manager module)
  //=========================================================================

  // ROM memory interface signals (for behavioral model)
  logic        rom_mem_req;
  logic [km_intf_pkg::KM_ROM_MEM_ADDR_WIDTH-1:0] rom_mem_addr;
  logic        rom_mem_gnt;
  logic        rom_mem_rvalid;
  logic [31:0] rom_mem_rdata;
  logic [3:0]  rom_mem_parity_injected;  // Parity with error injection for testing

  // Connect top-level ROM interface struct to individual signals for memory model
  assign rom_mem_req = km_rom_mem_req.req;
  assign rom_mem_addr = km_rom_mem_req.addr;
  assign km_rom_mem_rsp.gnt = rom_mem_gnt;
  assign km_rom_mem_rsp.rvalid = rom_mem_rvalid;
  assign km_rom_mem_rsp.rdata = rom_mem_rdata;
  assign km_rom_mem_rsp.parity = rom_mem_parity_injected;  // Use injected parity for testing

  //=========================================================================
  // SRAM Interface Signals
  //=========================================================================

  // SRAM memory interface signals (for behavioral model)
  logic        sram_mem_req;
  logic        sram_mem_we;
  logic [3:0]  sram_mem_be;
  logic [km_intf_pkg::KM_SRAM_MEM_ADDR_WIDTH-1:0] sram_mem_addr;
  logic [31:0] sram_mem_wdata;
  logic        sram_mem_gnt;
  logic        sram_mem_rvalid;
  logic [31:0] sram_mem_rdata;
  logic [3:0]  sram_mem_wparity;
  logic [3:0]  sram_mem_rparity_injected;  // Parity with error injection for testing

  // SRAM memory array (size from interface package)
  localparam int unsigned SRAM_SIZE_WORDS = km_intf_pkg::SRAM_SIZE_BYTES / 4;
  logic [31:0] sram_mem [0:SRAM_SIZE_WORDS-1];
  logic [3:0]  sram_parity [0:SRAM_SIZE_WORDS-1];  // Parity storage

  //=========================================================================
  // SRAM Connection (to top-level key_manager module)
  //=========================================================================

  // Connect top-level SRAM interface struct to individual signals for memory model
  assign sram_mem_req = km_sram_mem_req.req;
  assign sram_mem_we = km_sram_mem_req.we;
  assign sram_mem_be = km_sram_mem_req.be;
  assign sram_mem_addr = km_sram_mem_req.addr;
  assign sram_mem_wdata = km_sram_mem_req.wdata;
  assign sram_mem_wparity = km_sram_mem_req.wparity;
  assign km_sram_mem_rsp.gnt = sram_mem_gnt;
  assign km_sram_mem_rsp.rvalid = sram_mem_rvalid;
  assign km_sram_mem_rsp.rdata = sram_mem_rdata;
  assign km_sram_mem_rsp.rparity = sram_mem_rparity_injected;  // Use injected parity for testing

  //=========================================================================
  // SEP Mailbox Interface (for cocotb access)
  //=========================================================================
  // Note: The mailbox is inside key_manager, but we expose the SEP side
  // interface for cocotb testing

  // Flattened SEP AXI-Lite signals for cocotb access
  logic        sep_awvalid = 1'b0;
  logic [31:0] sep_awaddr = 32'h0;
  logic [2:0]  sep_awprot = 3'h0;
  logic        sep_awready;
  logic        sep_wvalid = 1'b0;
  logic [31:0] sep_wdata = 32'h0;
  logic [3:0]  sep_wstrb = 4'h0;
  logic        sep_wready;
  logic        sep_bready = 1'b0;
  logic        sep_bvalid;
  logic [1:0]  sep_bresp;
  logic        sep_arvalid = 1'b0;
  logic [31:0] sep_araddr = 32'h0;
  logic [2:0]  sep_arprot = 3'h0;
  logic        sep_arready;
  logic        sep_rready = 1'b0;
  logic        sep_rvalid;
  logic [31:0] sep_rdata;
  logic [1:0]  sep_rresp;

  // Connect flattened signals (driven by cocotb) to structs
  // Note: key_manager uses km_axil types for SEP interface (same as KM interface)
  assign mbox_sep_req.aw_valid = sep_awvalid;
  assign mbox_sep_req.aw.addr  = sep_awaddr;
  assign mbox_sep_req.aw.prot  = sep_awprot;
  assign sep_awready = mbox_sep_resp.aw_ready;
  assign mbox_sep_req.w_valid  = sep_wvalid;
  assign mbox_sep_req.w.data   = sep_wdata;
  assign mbox_sep_req.w.strb   = sep_wstrb;
  assign sep_wready  = mbox_sep_resp.w_ready;
  assign mbox_sep_req.b_ready  = sep_bready;
  assign sep_bvalid  = mbox_sep_resp.b_valid;
  assign sep_bresp   = mbox_sep_resp.b.resp;
  assign mbox_sep_req.ar_valid = sep_arvalid;
  assign mbox_sep_req.ar.addr  = sep_araddr;
  assign mbox_sep_req.ar.prot  = sep_arprot;
  assign sep_arready = mbox_sep_resp.ar_ready;
  assign mbox_sep_req.r_ready  = sep_rready;
  assign sep_rvalid  = mbox_sep_resp.r_valid;
  assign sep_rdata   = mbox_sep_resp.r.data;
  assign sep_rresp   = mbox_sep_resp.r.resp;

  // KM mailbox AR/R inject: cocotb overlaps a READ_DATA AR with SEP CTRL.FLUSH.
  // Force the mailbox request pin only while inject is set; otherwise the xbar
  // port map drives km_axil_req_i.
  logic        tb_km_mbox_inject = 1'b0;
  logic        tb_km_arvalid = 1'b0;
  logic [31:0] tb_km_araddr = 32'h0;
  logic [2:0]  tb_km_arprot = 3'h0;
  logic        tb_km_rready = 1'b0;
  logic        tb_km_arready;
  logic        tb_km_rvalid;
  logic [31:0] tb_km_rdata;
  logic [1:0]  tb_km_rresp;
  km_axil_req_t tb_mbox_km_req;

  always_comb begin
    tb_mbox_km_req = u_key_manager.mbox_req;
    if (tb_km_mbox_inject) begin
      tb_mbox_km_req.ar_valid = tb_km_arvalid;
      tb_mbox_km_req.ar.addr  = tb_km_araddr;
      tb_mbox_km_req.ar.prot  = tb_km_arprot;
      tb_mbox_km_req.r_ready  = tb_km_rready;
    end
  end

  assign tb_km_arready = u_key_manager.u_mailbox.km_axil_resp_o.ar_ready;
  assign tb_km_rvalid  = u_key_manager.u_mailbox.km_axil_resp_o.r_valid;
  assign tb_km_rdata   = u_key_manager.u_mailbox.km_axil_resp_o.r.data;
  assign tb_km_rresp   = u_key_manager.u_mailbox.km_axil_resp_o.r.resp;
  logic tb_km_fifo_clr;
  assign tb_km_fifo_clr = u_key_manager.u_mailbox.fifo_clr;

  always @(*) begin
    if (tb_km_mbox_inject) begin
      force u_key_manager.u_mailbox.km_axil_req_i = tb_mbox_km_req;
    end else begin
      release u_key_manager.u_mailbox.km_axil_req_i;
    end
  end

  //=========================================================================
  // Behavioral ROM Model (connected to ROM interface)
  //=========================================================================

  // ROM memory interface - connect to behavioral model
  // Grant is always ready (combinational memory)
  assign rom_mem_gnt = rom_mem_req;

  // Read data valid after 1 cycle (pipelined)
  // Support pipelined sequential reads: can accept new request in same cycle as returning data
  // Cycle 1: Accept request 1 → set pending, capture addr1
  // Cycle 2: Return data 1 (rvalid=1) AND accept request 2 → set pending for request 2, capture addr2
  //          (pending cleared by new request, so rvalid stays 1 for cycle 3)
  // Cycle 3: Return data 2 (rvalid=1)
  logic rom_read_pending;
  logic [31:0] rom_rsp_data;
  logic [3:0]  rom_rsp_parity;
  always_ff @(posedge clk or negedge cold_rst_n) begin
    if (!cold_rst_n) begin
      rom_read_pending <= 1'b0;
      rom_rsp_data <= '0;
      rom_rsp_parity <= '0;
    end else begin
      // Set pending when request is issued
      // If new request arrives while returning data, accept it immediately (pipelined)
      // This allows accepting new request in same cycle as returning data
      if (rom_mem_req) begin
        rom_read_pending <= 1'b1;
        rom_rsp_data <= rom_mem[rom_mem_addr];
        rom_rsp_parity <= gen_parity(rom_mem[rom_mem_addr]);
`ifdef ROM_DEBUG
        $display("[KM TB ROM] @%0t: READ addr=0x%03X, data=0x%08X", $time, rom_mem_addr,
                 rom_mem[rom_mem_addr]);
`endif
      end else begin
        // Clear pending when no new request and we've returned the data
        // Note: rom_mem_rvalid is combinational from rom_read_pending, so clearing
        // pending will clear rvalid in the next cycle
        rom_read_pending <= 1'b0;
      end
    end
  end

  // Data valid one cycle after request (pipelined)
  // When request is issued in cycle N, rvalid is true in cycle N+1
  // If new request arrives in cycle N+1, rvalid stays true for cycle N+2
  assign rom_mem_rvalid = rom_read_pending;
  assign rom_mem_rdata = rom_rsp_data;

  // Generate parity for ROM data (odd parity per byte)
  function automatic logic [3:0] gen_parity(logic [31:0] data);
    logic [3:0] parity;
    for (int i = 0; i < 4; i++) begin
      parity[i] = ~(^data[i*8+:8]);  // Odd parity: XOR then invert
    end
    return parity;
  endfunction

  logic [3:0] rom_mem_parity_correct;
  assign rom_mem_parity_correct = rom_rsp_parity;

  // Parity error injection for testing
  assign rom_mem_parity_injected = rom_parity_err_inject ? ~rom_mem_parity_correct : rom_mem_parity_correct;

  //=========================================================================
  // Behavioral SRAM Model (connected to SRAM interface)
  //=========================================================================

  // SRAM memory interface - connect to behavioral model
  // Single-stage SRAM model: accept request in cycle N and return read data in N+1.
  assign sram_mem_gnt = sram_mem_req;

  // Write handling
  // Use 4-state equality (===) to prevent X values during early simulation
  // from being interpreted as valid requests and corrupting SRAM/parity
  //
  // Data: store exactly what the DUT sends (scrambled when scrambler is on).
  // Parity: store the DUT's wparity. The DUT computes parity on plaintext before
  // scrambling and, on read, descrambles then checks parity(plaintext) == rparity, so
  // the model returns the parity the DUT wrote, not the parity of the stored data.

  // No explicit initialization of sram_mem/sram_parity: they remain at the simulator default
  // (typically X) until the DUT writes, and are not bulk-cleared on cold_rst_n (warm reset retains
  // content for tests that use SRAM markers across TB-driven reset).
  always_ff @(posedge clk) begin
    if (cold_rst_n) begin
      if (sram_mem_req === 1'b1 && sram_mem_gnt === 1'b1 && sram_mem_we === 1'b1) begin
        // Write operation from DUT - update data and parity per-byte based on byte enables
`ifdef SRAM_DEBUG
        $display("[KM TB SRAM] @%0t: WRITE addr=0x%03X, data=0x%08X, be=0x%01X", $time,
                 sram_mem_addr, sram_mem_wdata, sram_mem_be);
`endif
        for (int i = 0; i < 4; i++) begin
          if (sram_mem_be[i] === 1'b1) begin
            // Update data byte (may be scrambled when scrambler is on)
            sram_mem[sram_mem_addr][i*8+:8] <= sram_mem_wdata[i*8+:8];
            // Store DUT's wparity (plaintext parity); only if known
            if (!$isunknown(sram_mem_wparity[i])) begin
              sram_parity[sram_mem_addr][i] <= sram_mem_wparity[i];
            end
          end
        end
      end
`ifdef SRAM_DEBUG
      if (sram_mem_req === 1'b1 && sram_mem_gnt === 1'b1 && sram_mem_we === 1'b0) begin
        $display("[KM TB SRAM] @%0t: READ addr=0x%03X, data=0x%08X", $time, sram_mem_addr,
                 sram_mem[sram_mem_addr]);
      end
`endif
    end
  end

  // Read handling (single-stage pipelined). Response data/parity are latched at read
  // accept from the request address, so a read accepted in the same cycle as rvalid=1
  // returns the completing read's word and parity, not the new request's.
  logic sram_read_pending;
  logic [31:0] sram_rsp_data;
  logic [3:0]  sram_rsp_parity;
  logic        sram_read_accept;
  assign sram_read_accept = sram_mem_req && sram_mem_gnt && !sram_mem_we;
  always_ff @(posedge clk or negedge cold_rst_n) begin
    if (!cold_rst_n) begin
      sram_read_pending <= 1'b0;
      sram_rsp_data     <= '0;
      sram_rsp_parity   <= '0;
    end else begin
      sram_read_pending <= sram_read_accept;
      if (sram_read_accept) begin
        sram_rsp_data   <= sram_mem[sram_mem_addr];
        sram_rsp_parity <= sram_parity[sram_mem_addr];
      end
    end
  end

  assign sram_mem_rvalid = sram_read_pending;
  assign sram_mem_rdata  = sram_rsp_data;

  logic [3:0] sram_mem_parity_correct;
  assign sram_mem_parity_correct = sram_rsp_parity;

  // Parity error injection for testing
  assign sram_mem_rparity_injected = sram_parity_err_inject ? ~sram_mem_parity_correct : sram_mem_parity_correct;

  //=========================================================================
  // Behavioral Virtual ROM Model (attached directly to mem_* bus)
  //=========================================================================
  // Virtual ROM attaches directly to CPU memory bus signals
  // Handles pipelined memory access with look-ahead support (matches ROM interface behavior)

  // Extract word address from byte address
  // For byte address 0x1000_0000, subtract base and divide by 4 to get word index
  logic [15:0] vrom_word_addr;
  logic [15:0] vrom_la_word_addr;
  localparam logic [31:0] VROM_BASE = km_intf_pkg::VROM_BASE_ADDR;
  assign vrom_word_addr = (vrom_mem_addr >= VROM_BASE) ?
                            ((vrom_mem_addr - VROM_BASE) >> 2) : 16'h0;
  assign vrom_la_word_addr = (vrom_mem_la_addr >= VROM_BASE) ?
                               ((vrom_mem_la_addr - VROM_BASE) >> 2) : 16'h0;

  // Virtual ROM is read-only - ignore writes
  logic vrom_is_read;
  assign vrom_is_read = vrom_mem_valid && !(|vrom_mem_wstrb);

  // Track outstanding read requests for pipelined response
  // Match ROM model behavior: use pending flag that's set in same cycle as request
  // Key: Start pipeline on look-ahead read (mem_la_read) to have data ready
  // when mem_valid arrives, matching ROM interface behavior for zero-cycle latency
  //
  // Timing (matching ROM model):
  // Cycle N:   vrom_mem_la_read asserted → set vrom_read_pending, capture address
  // Cycle N+1: vrom_mem_valid arrives, vrom_rdata_valid = vrom_read_pending (true)
  //            vrom_mem_ready asserts immediately (zero-cycle latency)
  logic vrom_read_pending;
  logic [15:0] vrom_read_addr;
  logic [31:0] vrom_rsp_data;

  // Issue new request: look-ahead read (highest priority) or regular read
  // Look-ahead arrives 1 cycle before mem_valid, allowing prefetch
  logic vrom_issue_request;
  assign vrom_issue_request = vrom_mem_la_read || vrom_is_read;

  always_ff @(posedge clk or negedge cold_rst_n) begin
    if (!cold_rst_n) begin
      vrom_read_pending <= 1'b0;
      vrom_read_addr <= '0;
      vrom_rsp_data <= '0;
    end else begin
      // Set pending flag in same cycle as request (matching ROM model)
      // This allows rdata_valid to be true in the next cycle when mem_valid arrives
      vrom_read_pending <= vrom_issue_request;
      if (vrom_issue_request) begin
        // Use look-ahead address for prefetch (arrives 1 cycle before mem_valid)
        // This allows data to be ready when mem_valid is asserted
        vrom_read_addr <= vrom_mem_la_read ? vrom_la_word_addr : vrom_word_addr;
        vrom_rsp_data <= vrom_mem[vrom_mem_la_read ? vrom_la_word_addr : vrom_word_addr];
`ifdef VROM_DEBUG
        $display("[KM TB VROM] @%0t: REQ addr=0x%08X (word=0x%04X) la=%0d", $time,
                 vrom_mem_la_read ? vrom_mem_la_addr : vrom_mem_addr,
                 vrom_mem_la_read ? vrom_la_word_addr : vrom_word_addr, vrom_mem_la_read);
`endif
      end
    end
  end

  // Data valid one cycle after request (matching ROM model: rvalid = read_pending)
  // For look-ahead: request in cycle N, rdata_valid true in cycle N+1 when mem_valid arrives
  assign vrom_rdata_valid = vrom_read_pending;

  // Ready signal: assert when data is valid and CPU is requesting (mem_valid)
  // For look-ahead reads: data is prefetched and ready when mem_valid arrives
  // This provides zero-cycle latency when look-ahead is used
  // Also respond immediately to writes (which are ignored)
  assign vrom_mem_ready = (vrom_mem_valid && vrom_rdata_valid) ||
                            (vrom_mem_valid && |vrom_mem_wstrb);  // Write: respond immediately

  // Hold the last fetched word so the VROM path matches LATCHED_MEM_RDATA behavior.
  assign vrom_mem_rdata = vrom_rsp_data;

  //=========================================================================
  // Behavioral ROM Model Initialization (for testing)
  //=========================================================================

  initial begin
    string rom_hex_file;
    bit have_rom_file;
    int rom_size;
    byte mem_buffer[km_intf_pkg::ROM_SIZE_BYTES];  // ROM size from interface package
    int i, byte_idx;  // Declare loop variables outside loop

    // Initialize ROM with NOP instructions (0x00000013 = ADDI x0, x0, 0)
    for (i = 0; i < ROM_SIZE_WORDS; i++) begin
      rom_mem[i] = 32'h00000013;
    end

    // Check if ROM hex file is provided via plusarg
    have_rom_file = $value$plusargs("ROM_HEX_FILE=%s", rom_hex_file);

    if (have_rom_file) begin
      $display("[KM TB] Loading ROM from file: %s", rom_hex_file);

      // Verilog hex format: @address followed by space-separated hex bytes
      // $readmemh reads bytes directly into the array
      // Format: @00000000\n 37 61 00 00 ... (bytes in little-endian order per word)
      $readmemh(rom_hex_file, mem_buffer);

      // Load ROM memory (hex file is byte-addressed, convert to word-addressed)
      // Verilog hex format stores bytes, we need to reconstruct 32-bit words
      // Bytes are stored in little-endian order: [byte0, byte1, byte2, byte3] = word
      for (i = 0; i < ROM_SIZE_WORDS; i++) begin
        byte_idx = i * 4;
        if (byte_idx + 3 < km_intf_pkg::ROM_SIZE_BYTES) begin
          // Reconstruct word from little-endian bytes
          // mem_buffer[byte_idx] is LSB, mem_buffer[byte_idx+3] is MSB
          rom_mem[i] = {
            mem_buffer[byte_idx+3],
            mem_buffer[byte_idx+2],
            mem_buffer[byte_idx+1],
            mem_buffer[byte_idx]
          };
        end else begin
          // Pad with NOPs if file is shorter than ROM size
          rom_mem[i] = 32'h00000013;
        end
      end
      $display("[KM TB] ROM loaded successfully (%0d words)", ROM_SIZE_WORDS);
    end else begin
      $display("[KM TB] No ROM_HEX_FILE provided, using default NOP pattern");
    end
  end

  //=========================================================================
  // Behavioral Virtual ROM Model Initialization (for testing)
  //=========================================================================

  initial begin
    string vrom_hex_file;
    bit have_vrom_file;
    byte vrom_mem_buffer[km_intf_pkg::VROM_SIZE_BYTES];  // Virtual ROM size from interface package
    int i, byte_idx;

    // Initialize virtual ROM with zeros
    for (i = 0; i < VROM_SIZE_WORDS; i++) begin
      vrom_mem[i] = 32'h00000000;
    end

    // Check if virtual ROM hex file is provided via plusarg
    have_vrom_file = $value$plusargs("VROM_HEX_FILE=%s", vrom_hex_file);

    if (have_vrom_file) begin
      $display("[KM TB] Loading Virtual ROM from file: %s", vrom_hex_file);

      // Verilog hex format: @address followed by space-separated hex bytes
      $readmemh(vrom_hex_file, vrom_mem_buffer);

      // Load virtual ROM memory (hex file is byte-addressed, convert to word-addressed)
      // Bytes are stored in little-endian order: [byte0, byte1, byte2, byte3] = word
      for (i = 0; i < VROM_SIZE_WORDS; i++) begin
        byte_idx = i * 4;
        if (byte_idx + 3 < km_intf_pkg::VROM_SIZE_BYTES) begin
          // Reconstruct word from little-endian bytes
          vrom_mem[i] = {
            vrom_mem_buffer[byte_idx+3],
            vrom_mem_buffer[byte_idx+2],
            vrom_mem_buffer[byte_idx+1],
            vrom_mem_buffer[byte_idx]
          };
        end else begin
          // Pad with zeros if file is shorter than virtual ROM size
          vrom_mem[i] = 32'h00000000;
        end
      end
      $display("[KM TB] Virtual ROM loaded successfully (%0d words)", VROM_SIZE_WORDS);
    end else begin
      $display("[KM TB] No VROM_HEX_FILE provided, using default zero pattern");
    end
  end

  //=========================================================================
  // Virtual UART TX Capture and Display
  //=========================================================================
  // Captures VUART TX characters by probing internal km_csr signals.
  // This approach keeps the VUART interface internal to the design while
  // allowing testbench to capture firmware printf output.
  //
  // Probed signals (hierarchical path into key_manager):
  // - u_key_manager.u_kmcsr.vuart_tx_valid_o : TX valid strobe
  // - u_key_manager.u_kmcsr.vuart_tx_data_o  : TX byte data

  // Alias signals for easier access (probed from design hierarchy)
  wire       vuart_tx_valid = u_key_manager.u_kmcsr.vuart_tx_valid_o;
  wire [7:0] vuart_tx_data  = u_key_manager.u_kmcsr.vuart_tx_data_o;

  // TX output buffer for cocotb access
  logic [7:0] vuart_tx_buffer [0:4095];  // 4KB circular buffer
  int unsigned vuart_tx_wr_ptr = 0;
  int unsigned vuart_tx_count = 0;

  // String accumulator for line-based output
  logic [7:0] vuart_line_buffer [0:255];  // 256-char line buffer as byte array
  int unsigned vuart_line_pos = 0;

  always @(posedge clk) begin
    if (vuart_tx_valid) begin
      // Store in buffer for cocotb
      vuart_tx_buffer[vuart_tx_wr_ptr] = vuart_tx_data;
      vuart_tx_wr_ptr = (vuart_tx_wr_ptr + 1) % 4096;
      vuart_tx_count = vuart_tx_count + 1;

      // Display character to console
      if (vuart_tx_data == 8'h0A) begin  // Newline
        // Print accumulated line using $write for each character
        $write("[VUART] ");
        for (int i = 0; i < vuart_line_pos; i++) begin
          $write("%c", vuart_line_buffer[i]);
        end
        $display("");  // Newline
        vuart_line_pos = 0;
      end else if (vuart_tx_data >= 8'h20 && vuart_tx_data < 8'h7F) begin
        // Printable character - accumulate in buffer
        vuart_line_buffer[vuart_line_pos] = vuart_tx_data;
        vuart_line_pos = vuart_line_pos + 1;
      end
      // Ignore carriage return (0x0D) and other control characters
    end
  end

  //=========================================================================
  // Waveform Dumping
  //=========================================================================
  // When WAVES=1, VCD is dumped. If both +vcd_start_ns=N and +vcd_end_ns=M
  // are passed, dump only in [N, M) ns using $dumpoff/$dumpon with # delays.

`ifdef VCD_DUMP
  initial begin
    if ($test$plusargs("waves")) begin
      integer vcd_start_ns, vcd_end_ns;
      $dumpfile(`VCD_FILE);
      $dumpvars(0, tb_key_manager);
      if ($value$plusargs(
              "vcd_start_ns=%d", vcd_start_ns
          ) && $value$plusargs(
              "vcd_end_ns=%d", vcd_end_ns
          )) begin
        $dumpoff;
        #(vcd_start_ns) $dumpon;
        #(vcd_end_ns - vcd_start_ns) $dumpoff;
      end
    end
  end
`endif

`ifdef FSDB_DUMP
  initial begin
    if ($test$plusargs("waves")) begin
      // File path is set via +fsdbfile+ compile-time argument in Makefile
      $fsdbDumpfile("sim/logs/test_cpu_boot/tb_key_manager.fsdb");
      $fsdbDumpvars(0, tb_key_manager);
      $fsdbDumpvars("+all");
    end
  end
`endif

endmodule

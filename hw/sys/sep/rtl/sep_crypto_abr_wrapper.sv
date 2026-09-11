// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP <-> Caliptra Adams Bridge (PQC) integration wrapper
// -----------------------------------------------------------------------------
// Brings the Caliptra Adams Bridge engine (ML-DSA-87 / ML-KEM-1024) into the
// SEP crypto subsystem as a dedicated PQC block. Two integration seams:
//
//   1. Control/status path : sep_crypto 64-bit AXI -> reused VeeR axi4_to_ahb
//                            (deps/el2/design/lib/axi4_to_ahb.sv) -> abr_top AHB.
//                            AB's AHB slave is 64b data / 32b addr, which matches
//                            axi4_to_ahb exactly (no data-width conversion).
//   2. Key path            : KM private 32-bit AXI4-Lite key bus terminates on the
//                            abr_wrapper_key_reg CSR block instantiated *here*
//                            (mirroring aes_wrapper/otbn-wrapper), whose decoded
//                            hardware interface feeds sep_abr_kv_shim. The shim
//                            presents AB's Caliptra Key-Vault ports (kv_read /
//                            kv_rd_resp / kv_write / kv_wr_resp).
//
// Technology-dependent SRAM macros are NOT instantiated here. The ABR memory is
// exposed as packed req/rsp structs (abr_mem_req_t / abr_mem_rsp_t) threaded up
// to sep_ip_integration (the home for all macros / 3rd-party IP), mirroring the
// OTBN otbn_imem/dmem_sram pattern. Word-write channels are we/re/addr/data;
// sig_z and pk also carry one-bit-per-byte wstrobe. A local abr_mem_if + comb
// pack/unpack adapter bridges abr_top's interface port to the struct ports.
//
// The shim serves the ML-DSA seed on kv_read[0], the ML-KEM seed (D||Z) on
// kv_read[1] and the ML-KEM msg on kv_read[2], and implements the ML-KEM
// kv_write -> MLKEM_SHARED_KEY writeback (+ key_valid / IRQ_STATUS hwset);
// mlkem_sharedkey_irq_o exposes the resulting gated interrupt for the Key
// Manager. ML-KEM has no engine driver yet, so its lanes are DV-stimulus-only.

module sep_crypto_abr_wrapper
  import sep_pkg::*;
  import sep_crypto_pkg::*;
  import kv_defines_pkg::*;
  import abr_params_pkg::*;
  import abr_wrapper_key_reg_pkg::*;
#(
  parameter bit          MASKING_EN   = 1,  // 2-share DOM masking (ship for SCA)
  parameter int unsigned SRAM_LATENCY = 1
) (
  input  wire logic clk_i,
  input  wire logic rst_ni,

  // ---- Control/status path: 64-bit AXI from the sep_crypto demux ----
  input  wire sep_pkg::sep_32_64_6_12_axi_req_t  abr_axi_req_i,
  output      sep_pkg::sep_32_64_6_12_axi_resp_t abr_axi_resp_o,

  // ---- Key path: KM private 32-bit AXI4-Lite key bus ----
  // Terminates on the internal abr_wrapper_key_reg CSR block (u_abr_key_csr),
  // matching the aes/otbn wrapper convention (raw AXI4-Lite in, not a decoded
  // hwif struct).
  input  wire km_intf_pkg::km_axil_req_t  abr_key_axil_req_i,
  output      km_intf_pkg::km_axil_resp_t abr_key_axil_resp_o,

  // ---- AB internal SRAMs: technology macros live in sep_ip_integration. ----
  // Packed req/rsp structs (OTBN convention). abr_top is the memory requester;
  // a local abr_mem_if + comb adapter packs its requests into abr_mem_req_o and
  // unpacks abr_mem_rsp_i back onto the interface read-data signals.
  output      abr_mem_req_t abr_mem_req_o,
  input       abr_mem_rsp_t abr_mem_rsp_i,

  // ---- DFT ----
  input  wire logic scan_mode_i,

  // ---- Interrupts + status ----
  output      logic mlkem_sharedkey_irq_o,  // ML-KEM shared-key ready (gated)
  output      logic error_intr_o,
  output      logic notif_intr_o,
  output      logic busy_o
);

  `include "prim_assert.sv"

  // =========================================================================
  // AXI4 (64b) -> AHB-lite (64b/32a) : reuse the verified VeeR bridge
  // =========================================================================
  logic [31:0] ab_haddr;
  logic [63:0] ab_hwdata;
  logic [63:0] ab_hrdata;
  logic [2:0]  ab_hsize;
  logic [2:0]  ab_hburst;     // unused by abr_top (AB has no hburst input)
  logic [3:0]  ab_hprot;      // unused by abr_top
  logic        ab_hmastlock;  // unused by abr_top
  logic [1:0]  ab_htrans;
  logic        ab_hwrite;
  logic        ab_hreadyout;  // abr_top.hreadyout_o (single-slave global hready)
  logic        ab_hresp;

  axi4_to_ahb #(
    .TAG(sep_pkg::SEP_32_64_6_12_ID_WIDTH)  // carry the 6-bit SEP AXI ID
  ) u_axi4_to_ahb (
    .clk                (clk_i),
    .free_clk           (clk_i),
    .rst_l              (rst_ni),
    .scan_mode          (scan_mode_i),
    .bus_clk_en         (1'b1),
    .clk_override       (1'b0),
    .dec_tlu_force_halt (1'b0),

    // AXI slave (struct -> flat). Single-beat MMIO from the RV32 CPU, so the
    // bridge's lack of awlen/arlen is fine (len == 0).
    .axi_awvalid (abr_axi_req_i.aw_valid),
    .axi_awready (abr_axi_resp_o.aw_ready),
    .axi_awid    (abr_axi_req_i.aw.id),
    .axi_awaddr  (abr_axi_req_i.aw.addr),
    .axi_awsize  (abr_axi_req_i.aw.size),
    .axi_awprot  (abr_axi_req_i.aw.prot),

    .axi_wvalid  (abr_axi_req_i.w_valid),
    .axi_wready  (abr_axi_resp_o.w_ready),
    .axi_wdata   (abr_axi_req_i.w.data),
    .axi_wstrb   (abr_axi_req_i.w.strb),
    .axi_wlast   (abr_axi_req_i.w.last),

    .axi_bvalid  (abr_axi_resp_o.b_valid),
    .axi_bready  (abr_axi_req_i.b_ready),
    .axi_bresp   (abr_axi_resp_o.b.resp),
    .axi_bid     (abr_axi_resp_o.b.id),

    .axi_arvalid (abr_axi_req_i.ar_valid),
    .axi_arready (abr_axi_resp_o.ar_ready),
    .axi_arid    (abr_axi_req_i.ar.id),
    .axi_araddr  (abr_axi_req_i.ar.addr),
    .axi_arsize  (abr_axi_req_i.ar.size),
    .axi_arprot  (abr_axi_req_i.ar.prot),

    .axi_rvalid  (abr_axi_resp_o.r_valid),
    .axi_rready  (abr_axi_req_i.r_ready),
    .axi_rid     (abr_axi_resp_o.r.id),
    .axi_rdata   (abr_axi_resp_o.r.data),
    .axi_rresp   (abr_axi_resp_o.r.resp),
    .axi_rlast   (abr_axi_resp_o.r.last),

    // AHB master -> abr_top slave
    .ahb_haddr     (ab_haddr),
    .ahb_hburst    (ab_hburst),
    .ahb_hmastlock (ab_hmastlock),
    .ahb_hprot     (ab_hprot),
    .ahb_hsize     (ab_hsize),
    .ahb_htrans    (ab_htrans),
    .ahb_hwrite    (ab_hwrite),
    .ahb_hwdata    (ab_hwdata),
    .ahb_hrdata    (ab_hrdata),
    .ahb_hready    (ab_hreadyout),  // single slave: bus hready == slave hreadyout
    .ahb_hresp     (ab_hresp)
  );

  // axi4_to_ahb has no AXI USER ports
  assign abr_axi_resp_o.b.user = '0;
  assign abr_axi_resp_o.r.user = '0;

  // =========================================================================
  // Key CSR register block : KM AXI4-Lite key bus -> abr_wrapper_key_reg
  // =========================================================================
  // Instantiated here (aes/otbn wrapper convention) so the KM's private key bus
  // terminates inside the wrapper. hwif_out (KM-written dual-share seed +
  // shared-key control) feeds the shim; hwif_in (HW-driven ML-KEM shared-key
  // writeback) is produced by the shim.
  // NOTE: the PeakRDL hwif types are *unpacked* structs (cannot be a net);
  // declare with no explicit `wire` (defaults to var) to match the generated
  // abr_wrapper_key_reg port style and satisfy Xcelium (SVUPSL).
  abr_wrapper_key__in_t  abr_key_hwif_in;
  abr_wrapper_key__out_t abr_key_hwif_out;

  localparam int unsigned ABR_KEY_CSR_ADDR_WIDTH =
        abr_wrapper_key_reg_pkg::ABR_WRAPPER_KEY_REG_MIN_ADDR_WIDTH;

  abr_wrapper_key_reg u_abr_key_csr (
    .clk    (clk_i),
    .arst_n (rst_ni),

    // AW channel
    .s_axil_awvalid (abr_key_axil_req_i.aw_valid),
    .s_axil_awaddr  (abr_key_axil_req_i.aw.addr[ABR_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (abr_key_axil_req_i.aw.prot),
    .s_axil_awready (abr_key_axil_resp_o.aw_ready),

    // W channel
    .s_axil_wvalid  (abr_key_axil_req_i.w_valid),
    .s_axil_wdata   (abr_key_axil_req_i.w.data),
    .s_axil_wstrb   (abr_key_axil_req_i.w.strb),
    .s_axil_wready  (abr_key_axil_resp_o.w_ready),

    // B channel
    .s_axil_bready  (abr_key_axil_req_i.b_ready),
    .s_axil_bvalid  (abr_key_axil_resp_o.b_valid),
    .s_axil_bresp   (abr_key_axil_resp_o.b.resp),

    // AR channel
    .s_axil_arvalid (abr_key_axil_req_i.ar_valid),
    .s_axil_araddr  (abr_key_axil_req_i.ar.addr[ABR_KEY_CSR_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (abr_key_axil_req_i.ar.prot),
    .s_axil_arready (abr_key_axil_resp_o.ar_ready),

    // R channel
    .s_axil_rready  (abr_key_axil_req_i.r_ready),
    .s_axil_rvalid  (abr_key_axil_resp_o.r_valid),
    .s_axil_rdata   (abr_key_axil_resp_o.r.data),
    .s_axil_rresp   (abr_key_axil_resp_o.r.resp),

    // HW interface
    .hwif_in  (abr_key_hwif_in),
    .hwif_out (abr_key_hwif_out)
  );

  // ML-KEM shared-key IRQ: level-sensitive, gated by IRQ_ENABLE. Driven by the
  // shim's writeback (IRQ_STATUS.key_valid hwset on the final shared-key dword).
  assign mlkem_sharedkey_irq_o =
        abr_key_hwif_out.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.value &
        abr_key_hwif_out.MLKEM_SHARED_KEY.IRQ_ENABLE.key_valid_en.value;

  // =========================================================================
  // Key-Vault facade : KM key bus  <->  AB Caliptra KV ports
  // =========================================================================
  kv_read_t    [2:0] ab_kv_read;
  kv_rd_resp_t [2:0] ab_kv_rd_resp;
  kv_write_t         ab_kv_write;    // AB output (ML-DSA never asserts; ML-KEM does)
  kv_wr_resp_t       ab_kv_wr_resp;  // driven by the shim ('{error:0})

  // Recovers the seed/msg blocks from the abr_wrapper_key_reg dual XOR shares:
  // ML-DSA seed on kv_read[0], ML-KEM seed (D||Z) on kv_read[1], ML-KEM msg on
  // kv_read[2] (assert last on each lane's final dword, error until valid).
  // kv_write drives the MLKEM_SHARED_KEY writeback + key_valid / IRQ_STATUS
  // hwset via abr_key_hwif_in.
  sep_abr_kv_shim u_sep_abr_kv_shim (
    .hwif_i       (abr_key_hwif_out),
    .hwif_o       (abr_key_hwif_in),
    .kv_read_i    (ab_kv_read),
    .kv_rd_resp_o (ab_kv_rd_resp),
    .kv_write_i   (ab_kv_write),
    .kv_wr_resp_o (ab_kv_wr_resp)
  );

  // =========================================================================
  // ABR memory adapter : local abr_mem_if  <->  struct ports (up to IP integ.)
  // =========================================================================
  // abr_top drives the request side of u_abr_mem; pack those into the struct
  // output. abr_mem_rsp_i (from the SRAM macros in sep_ip_integration) is
  // unpacked back onto the interface read-data signals abr_top reads.
  abr_mem_if u_abr_mem ();

  always_comb begin
    abr_mem_req_o = '0;

    // Carry abr_top's clock to the SRAM macros in sep_ip_integration.
    abr_mem_req_o.clk = clk_i;

    // w1_mem (4-bit data)
    abr_mem_req_o.w1_we    = u_abr_mem.w1_mem_we_i;
    abr_mem_req_o.w1_waddr = u_abr_mem.w1_mem_waddr_i;
    abr_mem_req_o.w1_wdata = u_abr_mem.w1_mem_wdata_i;
    abr_mem_req_o.w1_re    = u_abr_mem.w1_mem_re_i;
    abr_mem_req_o.w1_raddr = u_abr_mem.w1_mem_raddr_i;

    // 96-bit coefficient memories
    abr_mem_req_o.mem_inst0_bank0.we    = u_abr_mem.mem_inst0_bank0_we_i;
    abr_mem_req_o.mem_inst0_bank0.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank0_waddr_i);
    abr_mem_req_o.mem_inst0_bank0.wdata = u_abr_mem.mem_inst0_bank0_wdata_i;
    abr_mem_req_o.mem_inst0_bank0.re    = u_abr_mem.mem_inst0_bank0_re_i;
    abr_mem_req_o.mem_inst0_bank0.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank0_raddr_i);

    abr_mem_req_o.mem_inst0_bank1.we    = u_abr_mem.mem_inst0_bank1_we_i;
    abr_mem_req_o.mem_inst0_bank1.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank1_waddr_i);
    abr_mem_req_o.mem_inst0_bank1.wdata = u_abr_mem.mem_inst0_bank1_wdata_i;
    abr_mem_req_o.mem_inst0_bank1.re    = u_abr_mem.mem_inst0_bank1_re_i;
    abr_mem_req_o.mem_inst0_bank1.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank1_raddr_i);

    abr_mem_req_o.mem_inst1.we    = u_abr_mem.mem_inst1_we_i;
    abr_mem_req_o.mem_inst1.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst1_waddr_i);
    abr_mem_req_o.mem_inst1.wdata = u_abr_mem.mem_inst1_wdata_i;
    abr_mem_req_o.mem_inst1.re    = u_abr_mem.mem_inst1_re_i;
    abr_mem_req_o.mem_inst1.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst1_raddr_i);

    abr_mem_req_o.mem_inst2.we    = u_abr_mem.mem_inst2_we_i;
    abr_mem_req_o.mem_inst2.waddr = u_abr_mem.mem_inst2_waddr_i;
    abr_mem_req_o.mem_inst2.wdata = u_abr_mem.mem_inst2_wdata_i;
    abr_mem_req_o.mem_inst2.re    = u_abr_mem.mem_inst2_re_i;
    abr_mem_req_o.mem_inst2.raddr = u_abr_mem.mem_inst2_raddr_i;

    // Masked coefficient memories (tied to '0 inside abr_top when MASKING_EN=0)
    abr_mem_req_o.mem_inst0_bank0_masked.we    = u_abr_mem.mem_inst0_bank0_masked_we_i;
    abr_mem_req_o.mem_inst0_bank0_masked.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank0_masked_waddr_i);
    abr_mem_req_o.mem_inst0_bank0_masked.wdata = u_abr_mem.mem_inst0_bank0_masked_wdata_i;
    abr_mem_req_o.mem_inst0_bank0_masked.re    = u_abr_mem.mem_inst0_bank0_masked_re_i;
    abr_mem_req_o.mem_inst0_bank0_masked.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank0_masked_raddr_i);

    abr_mem_req_o.mem_inst0_bank1_masked.we    = u_abr_mem.mem_inst0_bank1_masked_we_i;
    abr_mem_req_o.mem_inst0_bank1_masked.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank1_masked_waddr_i);
    abr_mem_req_o.mem_inst0_bank1_masked.wdata = u_abr_mem.mem_inst0_bank1_masked_wdata_i;
    abr_mem_req_o.mem_inst0_bank1_masked.re    = u_abr_mem.mem_inst0_bank1_masked_re_i;
    abr_mem_req_o.mem_inst0_bank1_masked.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst0_bank1_masked_raddr_i);

    abr_mem_req_o.mem_inst1_masked.we    = u_abr_mem.mem_inst1_masked_we_i;
    abr_mem_req_o.mem_inst1_masked.waddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst1_masked_waddr_i);
    abr_mem_req_o.mem_inst1_masked.wdata = u_abr_mem.mem_inst1_masked_wdata_i;
    abr_mem_req_o.mem_inst1_masked.re    = u_abr_mem.mem_inst1_masked_re_i;
    abr_mem_req_o.mem_inst1_masked.raddr = SEP_CRYPTO_ABR_INST2_ADDR_W'(u_abr_mem.mem_inst1_masked_raddr_i);

    abr_mem_req_o.mem_inst2_masked.we    = u_abr_mem.mem_inst2_masked_we_i;
    abr_mem_req_o.mem_inst2_masked.waddr = u_abr_mem.mem_inst2_masked_waddr_i;
    abr_mem_req_o.mem_inst2_masked.wdata = u_abr_mem.mem_inst2_masked_wdata_i;
    abr_mem_req_o.mem_inst2_masked.re    = u_abr_mem.mem_inst2_masked_re_i;
    abr_mem_req_o.mem_inst2_masked.raddr = u_abr_mem.mem_inst2_masked_raddr_i;

    // sk banks (32-bit data)
    abr_mem_req_o.sk_bank0_we    = u_abr_mem.sk_mem_bank0_we_i;
    abr_mem_req_o.sk_bank0_waddr = u_abr_mem.sk_mem_bank0_waddr_i;
    abr_mem_req_o.sk_bank0_wdata = u_abr_mem.sk_mem_bank0_wdata_i;
    abr_mem_req_o.sk_bank0_re    = u_abr_mem.sk_mem_bank0_re_i;
    abr_mem_req_o.sk_bank0_raddr = u_abr_mem.sk_mem_bank0_raddr_i;

    abr_mem_req_o.sk_bank1_we    = u_abr_mem.sk_mem_bank1_we_i;
    abr_mem_req_o.sk_bank1_waddr = u_abr_mem.sk_mem_bank1_waddr_i;
    abr_mem_req_o.sk_bank1_wdata = u_abr_mem.sk_mem_bank1_wdata_i;
    abr_mem_req_o.sk_bank1_re    = u_abr_mem.sk_mem_bank1_re_i;
    abr_mem_req_o.sk_bank1_raddr = u_abr_mem.sk_mem_bank1_raddr_i;

    // sig_z_mem (byte-enabled, 160-bit data)
    abr_mem_req_o.sig_z_we      = u_abr_mem.sig_z_mem_we_i;
    abr_mem_req_o.sig_z_waddr   = u_abr_mem.sig_z_mem_waddr_i;
    abr_mem_req_o.sig_z_wdata   = u_abr_mem.sig_z_mem_wdata_i;
    abr_mem_req_o.sig_z_wstrobe = u_abr_mem.sig_z_mem_wstrobe_i;
    abr_mem_req_o.sig_z_re      = u_abr_mem.sig_z_mem_re_i;
    abr_mem_req_o.sig_z_raddr   = u_abr_mem.sig_z_mem_raddr_i;

    // pk_mem (byte-enabled, 320-bit data)
    abr_mem_req_o.pk_mem.we      = u_abr_mem.pk_mem_we_i;
    abr_mem_req_o.pk_mem.waddr   = u_abr_mem.pk_mem_waddr_i;
    abr_mem_req_o.pk_mem.wdata   = u_abr_mem.pk_mem_wdata_i;
    abr_mem_req_o.pk_mem.wstrobe = u_abr_mem.pk_mem_wstrobe_i;
    abr_mem_req_o.pk_mem.re      = u_abr_mem.pk_mem_re_i;
    abr_mem_req_o.pk_mem.raddr   = u_abr_mem.pk_mem_raddr_i;
  end

  // Response: struct input -> interface read-data signals (abr_top reads these)
  always_comb begin
    u_abr_mem.w1_mem_rdata_o                 = abr_mem_rsp_i.w1_rdata;
    u_abr_mem.mem_inst0_bank0_rdata_o        = abr_mem_rsp_i.mem_inst0_bank0_rdata;
    u_abr_mem.mem_inst0_bank1_rdata_o        = abr_mem_rsp_i.mem_inst0_bank1_rdata;
    u_abr_mem.mem_inst1_rdata_o              = abr_mem_rsp_i.mem_inst1_rdata;
    u_abr_mem.mem_inst2_rdata_o              = abr_mem_rsp_i.mem_inst2_rdata;
    u_abr_mem.mem_inst0_bank0_masked_rdata_o = abr_mem_rsp_i.mem_inst0_bank0_masked_rdata;
    u_abr_mem.mem_inst0_bank1_masked_rdata_o = abr_mem_rsp_i.mem_inst0_bank1_masked_rdata;
    u_abr_mem.mem_inst1_masked_rdata_o       = abr_mem_rsp_i.mem_inst1_masked_rdata;
    u_abr_mem.mem_inst2_masked_rdata_o       = abr_mem_rsp_i.mem_inst2_masked_rdata;
    u_abr_mem.sk_mem_bank0_rdata_o           = abr_mem_rsp_i.sk_bank0_rdata;
    u_abr_mem.sk_mem_bank1_rdata_o           = abr_mem_rsp_i.sk_bank1_rdata;
    u_abr_mem.sig_z_mem_rdata_o              = abr_mem_rsp_i.sig_z_rdata;
    u_abr_mem.pk_mem_rdata_o                 = abr_mem_rsp_i.pk_rdata;
  end

  // =========================================================================
  // Address-range asserts (non-power-of-two depths)
  // =========================================================================
  // INST0=832, INST2=1536, SK=596, SIG_Z=224. An address can fit in the port
  // width and still miss the array. SK writes are not checked: abr_ctrl's
  // MLDSA_PRIVKEY_IN window underflows dword 31 to bank1 address 1023.

  `OCAH_OT_ASSERT_NEVER(
      Inst0B0Rd_A,
      u_abr_mem.mem_inst0_bank0_re_i && (u_abr_mem.mem_inst0_bank0_raddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B0Wr_A,
      u_abr_mem.mem_inst0_bank0_we_i && (u_abr_mem.mem_inst0_bank0_waddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B1Rd_A,
      u_abr_mem.mem_inst0_bank1_re_i && (u_abr_mem.mem_inst0_bank1_raddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B1Wr_A,
      u_abr_mem.mem_inst0_bank1_we_i && (u_abr_mem.mem_inst0_bank1_waddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B0MskRd_A,
      u_abr_mem.mem_inst0_bank0_masked_re_i && (u_abr_mem.mem_inst0_bank0_masked_raddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B0MskWr_A,
      u_abr_mem.mem_inst0_bank0_masked_we_i && (u_abr_mem.mem_inst0_bank0_masked_waddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B1MskRd_A,
      u_abr_mem.mem_inst0_bank1_masked_re_i && (u_abr_mem.mem_inst0_bank1_masked_raddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst0B1MskWr_A,
      u_abr_mem.mem_inst0_bank1_masked_we_i && (u_abr_mem.mem_inst0_bank1_masked_waddr_i >= abr_params_pkg::ABR_MEM_INST0_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst2Rd_A,
      u_abr_mem.mem_inst2_re_i && (u_abr_mem.mem_inst2_raddr_i >= abr_params_pkg::ABR_MEM_INST2_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst2Wr_A,
      u_abr_mem.mem_inst2_we_i && (u_abr_mem.mem_inst2_waddr_i >= abr_params_pkg::ABR_MEM_INST2_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst2MskRd_A,
      u_abr_mem.mem_inst2_masked_re_i && (u_abr_mem.mem_inst2_masked_raddr_i >= abr_params_pkg::ABR_MEM_INST2_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      Inst2MskWr_A,
      u_abr_mem.mem_inst2_masked_we_i && (u_abr_mem.mem_inst2_masked_waddr_i >= abr_params_pkg::ABR_MEM_INST2_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      SkB0Rd_A,
      u_abr_mem.sk_mem_bank0_re_i && (u_abr_mem.sk_mem_bank0_raddr_i >= abr_ctrl_pkg::SK_MEM_BANK_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      SkB1Rd_A,
      u_abr_mem.sk_mem_bank1_re_i && (u_abr_mem.sk_mem_bank1_raddr_i >= abr_ctrl_pkg::SK_MEM_BANK_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      SigZRd_A,
      u_abr_mem.sig_z_mem_re_i && (u_abr_mem.sig_z_mem_raddr_i >= abr_ctrl_pkg::SIG_Z_MEM_DEPTH),
      clk_i, !rst_ni)
  `OCAH_OT_ASSERT_NEVER(
      SigZWr_A,
      u_abr_mem.sig_z_mem_we_i && (u_abr_mem.sig_z_mem_waddr_i >= abr_ctrl_pkg::SIG_Z_MEM_DEPTH),
      clk_i, !rst_ni)



  // =========================================================================
  // ABR memory contract checks (elaboration-time; evaluated by synth and simulators)
  // =========================================================================
  // sep_crypto_pkg is compiled before abr_params_pkg / abr_ctrl_pkg, so its
  // abr_mem_req_t / abr_mem_rsp_t field widths are a hand-copied mirror of the vendor
  // geometry. This module sees both, so it is where the mirror is pinned: a vendor bump
  // that changes any width fails elaboration here instead of silently truncating an
  // address or read-data field in the comb adapters above. abr_mem_if declares every one
  // of its signals from these same parameters.
  //
  // The four 96-bit coefficient channels are deliberately asymmetric: the packed struct
  // sizes waddr/raddr to the WIDEST channel (INST2) and lets the narrower banks ride in
  // the low bits, so those are bounded rather than required to be equal.
  //
  // --- Data widths: every wdata/rdata field must match its channel EXACTLY. The masked
  // coefficient twins are declared from the same parameters as the unmasked ones, so the
  // INST0/INST1/INST2 rows cover them too. ---
  if (abr_params_pkg::ABR_MEM_W1_DATA_W    != SEP_CRYPTO_ABR_W1_DATA_W   ||
        abr_params_pkg::ABR_MEM_INST0_DATA_W != SEP_CRYPTO_ABR_MEM_DATA_W  ||
        abr_params_pkg::ABR_MEM_INST1_DATA_W != SEP_CRYPTO_ABR_MEM_DATA_W  ||
        abr_params_pkg::ABR_MEM_INST2_DATA_W != SEP_CRYPTO_ABR_MEM_DATA_W  ||
        abr_ctrl_pkg::SK_MEM_BANK_DATA_W     != SEP_CRYPTO_ABR_SK_DATA_W   ||
        abr_ctrl_pkg::SIG_Z_MEM_DATA_W       != SEP_CRYPTO_ABR_SIGZ_DATA_W ||
        abr_ctrl_pkg::PK_MEM_DATA_W          != SEP_CRYPTO_ABR_PK_DATA_W)
    begin : gen_abr_mem_data_width_check
    $error(
        {
          "abr_mem_req_t / abr_mem_rsp_t data widths no longer match the vendor ",
          "memory geometry; writes and read data would be truncated or ",
          "zero-extended. Re-derive the SEP_CRYPTO_ABR_*_DATA_W mirrors in ",
          "sep_crypto_pkg from abr_params_pkg / abr_ctrl_pkg."
        }
    );
  end

  // --- Byte strobes: exact, or a masked write lands on the wrong bytes. ---
  if (abr_ctrl_pkg::SIG_Z_MEM_WSTROBE_W != SEP_CRYPTO_ABR_SIGZ_WSTRB_W ||
        abr_ctrl_pkg::PK_MEM_WSTROBE_W    != SEP_CRYPTO_ABR_PK_WSTRB_W)
    begin : gen_abr_mem_wstrobe_width_check
    $error(
        {
          "abr_mem_req_t wstrobe widths no longer match the vendor memory geometry; ",
          "byte-enabled writes to sig_z_mem / pk_mem would corrupt neighbouring bytes"
        }
    );
  end

  // --- Dedicated (non-shared) address fields: exact. ---
  if (abr_params_pkg::ABR_MEM_W1_ADDR_W != SEP_CRYPTO_ABR_W1_ADDR_W   ||
        abr_ctrl_pkg::SK_MEM_BANK_ADDR_W  != SEP_CRYPTO_ABR_SK_ADDR_W   ||
        abr_ctrl_pkg::SIG_Z_MEM_ADDR_W    != SEP_CRYPTO_ABR_SIGZ_ADDR_W ||
        abr_ctrl_pkg::PK_MEM_ADDR_W       != SEP_CRYPTO_ABR_PK_ADDR_W)
    begin : gen_abr_mem_addr_width_check
    $error(
        {
          "abr_mem_req_t address widths no longer match the vendor memory geometry; ",
          "an address bit would alias. Re-derive the SEP_CRYPTO_ABR_*_ADDR_W ",
          "mirrors in sep_crypto_pkg from abr_params_pkg / abr_ctrl_pkg."
        }
    );
  end

  // --- Shared coefficient address field: must be >= every channel abr_mem_ch_req_t
  // carries, and exactly equal to the widest one. ---
  if (SEP_CRYPTO_ABR_INST2_ADDR_W <  abr_params_pkg::ABR_MEM_INST0_ADDR_W ||
        SEP_CRYPTO_ABR_INST2_ADDR_W <  abr_params_pkg::ABR_MEM_INST1_ADDR_W ||
        SEP_CRYPTO_ABR_INST2_ADDR_W != abr_params_pkg::ABR_MEM_INST2_ADDR_W)
    begin : gen_abr_mem_coeff_addr_check
    $error(
        {
          "abr_mem_ch_req_t addr field (SEP_CRYPTO_ABR_INST2_ADDR_W) must equal the ",
          "widest coefficient-memory address and be >= all of them; a coefficient ",
          "address bit would be dropped where sep_ip_integration slices the field"
        }
    );
  end

  // =========================================================================
  // Adams Bridge engine
  // =========================================================================
  // Built with the Caliptra KV interface enabled (CALIPTRA, see the Adams Bridge
  // source group in Bender.yml) so the seed arrives over kv_read and the SK lock
  // stays engaged.
  abr_top #(
    .MASKING_EN        (MASKING_EN),
    .SRAM_LATENCY      (SRAM_LATENCY),
    .AHB_ADDR_WIDTH    (32),
    .AHB_DATA_WIDTH    (64),
    .CLIENT_DATA_WIDTH (32)
  ) u_abr_top (
    .clk         (clk_i),
    .rst_b       (rst_ni),

    // AHB-lite slave (single slave: hsel tied high, hready == hreadyout)
    .haddr_i     (ab_haddr),
    .hwdata_i    (ab_hwdata),
    .hsel_i      (1'b1),
    .hwrite_i    (ab_hwrite),
    .hready_i    (ab_hreadyout),
    .htrans_i    (ab_htrans),
    .hsize_i     (ab_hsize),
    .hresp_o     (ab_hresp),
    .hreadyout_o (ab_hreadyout),
    .hrdata_o    (ab_hrdata),

    // SRAM macros are in sep_ip_integration; local interface bridged to the
    // struct ports by the adapter above.
    .abr_memory_export (u_abr_mem),

    // Caliptra KV interface -> sep_abr_kv_shim
    .kv_read     (ab_kv_read),
    .kv_rd_resp  (ab_kv_rd_resp),
    .kv_write    (ab_kv_write),
    .kv_wr_resp  (ab_kv_wr_resp),

    // PCR signing / OCP L.O.C.K. unused in SEP for now
    .pcr_signing_data    ('0),
    .ocp_lock_in_progress(1'b0),

    // Tied off deliberately. Caliptra drives this from security-state TRANSITION
    // detectors (caliptra_top.sv `_d ^ _f`), and abr_ctrl consumes it level-
    // sensitively (`zeroize = ...ZEROIZE || debugUnlock_or_scan_mode_switch`), so a
    // static level here would pin zeroize high: seed writes blocked, MLDSA_SEED
    // continuously cleared, privkey/dk locks held, memory sweep never releasing.
    //
    // SEP does not want a scan-entry wipe anyway. Class 2 protection is upstream of
    // the engine (lifecycle_controller.adoc, `secure_tm` and Scan Dump): under
    // secure_tm=1 the UID / CLASS_KEY sources are disconnected so nothing real is
    // shifted, and under secure_tm=0 the Class 2 chain is tied off -- specifically so
    // crypto logic STAYS on the scan chain for DFT coverage. Firmware retains
    // MLDSA_CTRL.ZEROIZE / MLKEM_CTRL.ZEROIZE for explicit wipes.
    .debugUnlock_or_scan_mode_switch (1'b0),

    .busy_o      (busy_o),
    .error_intr  (error_intr_o),
    .notif_intr  (notif_intr_o)
  );

  // =========================================================================
  // Entropy: abr_top has NO entropy port. The 512-bit `entropy` register is
  // written over the AHB register bus. First cut = KM firmware seeds it before
  // each protected op. FUTURE: a small EDN -> entropy-register loader (a second
  // AHB writer or a CSR-mux) for automatic per-op reseed.
  // =========================================================================

  // Assertion to protect against truncation on casts
  `OCAH_OT_ASSERT_INIT(
      AbrChanAddrFits_A,
      (SEP_CRYPTO_ABR_INST0_ADDR_W <= SEP_CRYPTO_ABR_INST2_ADDR_W) && (SEP_CRYPTO_ABR_INST1_ADDR_W <= SEP_CRYPTO_ABR_INST2_ADDR_W))

endmodule

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OSS functional-coverage sampler (docs/SEP_FCOV.adoc). VCS covergroups only.
//
// One passive instance in tb_top (`u_sep_fcov`). It drives nothing.
//
// ATTACH. The CSR side is the post-remap CPU-LSU AXI bus that tb_top already
// mirrors to its flat `s_axi_*` ports and force-splices on the no-CPU builds.
// Sampling that bus (not the flat ports) is what makes a bin reachable in BOTH
// run modes: under `+cpu_boot` the EL2 owns the bus and the flat request ports
// are idle, so a port-side sampler would see no firmware traffic at all. The
// external inbound master is the real `m_axi_*` DUT port. Everything else is an
// named probe port of tb_top. No new hierarchy reach.
//
// WHAT A BIN MEANS. A bin records an interface event: a completed AXI
// handshake, a decoded CTRL/CFG write, a readback that matches what was
// written, or a probe strobe. Golden compares (digest, banner text,
// shadow==image, FEAT_CTRL decode) stay on the VPLAN checkers; a covergroup
// cannot replace one.
//
// TRANSACTION PAIRING. Register data bins need the address that goes with the
// data. AXI allows several outstanding transactions and out-of-order read
// returns, so a deeper model could pair the wrong address with the wrong word
// and score a bin that never happened. Every data-bearing event here is gated
// on exactly ONE outstanding transaction in that direction, which is
// unambiguous by construction. The register drivers are strictly serial, so the
// gate costs no cell; pipelined firmware traffic is sampled only where it
// happens to be serial. A missed sample is a missed hit, never a false one.
//
// Encodings come from the generated register header (`sep_reg.svh`) and the
// memory-window package (`sep_top_addrmap_pkg`). Where a vendored block exports no
// field symbol, the bit position is named in a comment against the driver that
// programs it.

`ifndef VERILATOR

module sep_fcov (
  input wire        clk_i,
  input wire        rst_ni,

  // CPU-LSU AXI (sep_32_64_3_12), flattened by tb_top.
  input wire [31:0] lsu_aw_addr_i,
  input wire        lsu_aw_valid_i,
  input wire        lsu_aw_ready_i,
  input wire [63:0] lsu_w_data_i,
  input wire [7:0]  lsu_w_strb_i,
  input wire        lsu_w_valid_i,
  input wire        lsu_w_ready_i,
  input wire [1:0]  lsu_b_resp_i,
  input wire        lsu_b_valid_i,
  input wire        lsu_b_ready_i,
  input wire [31:0] lsu_ar_addr_i,
  input wire        lsu_ar_valid_i,
  input wire        lsu_ar_ready_i,
  input wire [63:0] lsu_r_data_i,
  input wire [1:0]  lsu_r_resp_i,
  input wire        lsu_r_last_i,
  input wire        lsu_r_valid_i,
  input wire        lsu_r_ready_i,

  // SMN-inbound external AXI (sep_56_64_6_12), the real DUT port.
  input wire [55:0] m_axi_awaddr_i,
  input wire        m_axi_awvalid_i,
  input wire        m_axi_awready_i,
  input wire [1:0]  m_axi_bresp_i,
  input wire        m_axi_bvalid_i,
  input wire        m_axi_bready_i,
  input wire [55:0] m_axi_araddr_i,
  input wire        m_axi_arvalid_i,
  input wire        m_axi_arready_i,
  input wire [1:0]  m_axi_rresp_i,
  input wire        m_axi_rlast_i,
  input wire        m_axi_rvalid_i,
  input wire        m_axi_rready_i,

  // tb_top probe ports.
  input wire        cpu_trace_valid_i,
  input wire [31:0] cpu_trace_addr_i,
  input wire        cpu_trace_interrupt_i,
  input wire        cpu_trace_exc_i,
  input wire        fw_done_i,
  input wire        fw_pass_i,
  input wire        fw_char_valid_i,
  input wire        fuse_sense_done_i,
  input wire        drbg_seed_valid_i,
  input wire        drbg_genbits_vld_i,
  input wire        axis1_tvalid_i,
  input wire        axis1_tready_i,
  // Per-client post-adapter EDN grant (drbg_axis_edn_adapter client order:
  // AES, KMAC, OTBN-RND, OTBN-URND). axis1_* above is the shared stream
  // ahead of the fan-out and cannot say which client took the beat.
  input wire [3:0]  crypto_edn_ack_i,
  input wire        km_entropy_tvalid_i,
  input wire        km_entropy_tready_i,
  input wire [7:0]  irq_mailbox_i,
  input wire        irq_km_mbox_i,
  input wire        irq_dma_done_i,
  input wire [3:0]  efuse_lc_raw_i,      // sensed LC nibble of the shadow probe
  input wire [1:0]  efuse_read_state_i,     // efuse_read_interface FSM
  input wire [1:0]  efuse_program_state_i,  // efuse_program_interface FSM
  input wire        secure_tm_i,
  input wire        sec_dis_i,
  input wire [1:0]  demote_1_i,          // {~demote, demote}: 2'b10 clear, 2'b01 set
  input wire [1:0]  demote_2_i,
  input wire        cpu_reset_n_i,
  input wire        spi_cs_n_i,
  input wire        spi_sck_i,
  // IC_RESET sep_reset_n override as SEP receives it, after the TB mux.
  // ovrd selects val in place of the sense-gated reset.
  input wire        jtag_sep_reset_n_ovrd_i,
  input wire        jtag_sep_reset_n_val_i,

  // Crypto isolate / per-IP reset sequencing for the HMAC domain. An
  // accelerator reset waits on BOTH the SEP host path and the Key Manager
  // path, so the two isolate-completion bits are separate inputs.
  input wire        hmac_gated_rst_n_i,
  input wire        hmac_host_isolated_i,
  input wire        hmac_km_isolated_i,
  // The same three for the Adams Bridge domain. Its host path is a full-AXI
  // isolate and its Key Manager path is shared with the KM domain.
  input wire        abr_gated_rst_n_i,
  input wire        abr_host_isolated_i,
  input wire        abr_km_isolated_i
);

  import sep_top_addrmap_pkg::*;
  `include "sep_reg.svh"

  // ------------------------------------------------------------------
  // Apertures. Memory windows come from sep_top_addrmap_pkg; every CSR address
  // and field mask below is a sep_reg.svh symbol.
  // ------------------------------------------------------------------
  localparam logic [31:0] SramBase = 32'(SEP_TOP_SEP_SRAM_BASE_ADDR);
  localparam logic [31:0] SramEnd = SramBase + 32'(SEP_TOP_SEP_SRAM_SIZE);
  localparam logic [31:0] BootRomBase = 32'(SEP_TOP_SEP_BOOT_ROM_BASE_ADDR);
  localparam logic [31:0] BootRomEnd = BootRomBase + 32'(SEP_TOP_SEP_BOOT_ROM_SIZE);
  localparam logic [31:0] SpiBase = SPI_CONTROLLER_REG_MAP_BASE_ADDR;
  localparam logic [31:0] SpiEnd = SpiBase + SPI_CONTROLLER_REG_MAP_SIZE;
  localparam logic [31:0] ColdBase = SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR;
  localparam logic [31:0] ColdEnd = ColdBase + SEP_SCRATCH_COLD_REG_MAP_SIZE;
  localparam logic [31:0] WarmBase = SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR;
  localparam logic [31:0] WarmEnd = WarmBase + SEP_SCRATCH_WARM_REG_MAP_SIZE;

  // Inbound filter entry bank: 16 RDL array entries at a fixed stride.
  localparam logic [31:0] FiltBase = INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] FiltStride   = INBOUND_FILTER_CTRL_1__REG_MAP_BASE_ADDR -
                                         INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam int unsigned FiltEntries = sep_pkg::INBOUND_FILTER_NUM_FILTERS;
  localparam logic [31:0] FiltEnd = FiltBase + FiltStride * FiltEntries;
  localparam logic [31:0] FiltCfgOff = INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_OFFSET;
  localparam logic [31:0] FiltStartOff = INBOUND_FILTER_CTRL_0__START_ADDR_REG_OFFSET;
  localparam logic [31:0] FiltEndOff = INBOUND_FILTER_CTRL_0__END_ADDR_REG_OFFSET;
  localparam logic [31:0] FiltEnMask = 32'(FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_MASK);

  // Adams Bridge MLDSA_CTRL / MLDSA_STATUS addresses and field masks come from
  // the generated sep_reg.svh. The command encodings are in the abr_reg.rdl
  // CTRL field description, which the export does not carry.
  localparam logic [31:0] AbrBase = ABR_REG_MAP_BASE_ADDR;
  localparam logic [31:0] AbrCtrl = ABR_MLDSA_CTRL_REG_ADDR;
  localparam logic [31:0] AbrStatus = ABR_MLDSA_STATUS_REG_ADDR;
  // MLDSA_CTRL.CTRL is [2:0]; bit 3 is ZEROIZE, so a command is compared on
  // the CTRL field only and a command written with ZEROIZE still scores.
  localparam logic [31:0] AbrCtrlCmdMask = ABR_REG_MLDSA_CTRL_CTRL_MASK;
  localparam logic [31:0] AbrCmdKeygen = 32'h1;  // MLDSA_CTRL.CTRL = KEYGEN
  localparam logic [31:0] AbrCmdSign = 32'h2;  // MLDSA_CTRL.CTRL = SIGNING
  localparam logic [31:0] AbrCmdVerify = 32'h3;  // MLDSA_CTRL.CTRL = VERIFYING
  localparam logic [31:0] AbrStValid = ABR_REG_MLDSA_STATUS_VALID_MASK;

  // ML-KEM is a separate register block in the same aperture: its own CTRL and
  // STATUS, so a ML-DSA command can never score an ML-KEM cell. Offsets from
  // the Caliptra abr_reg.rdl MLKEM block.
  localparam logic [31:0] KemCtrl = AbrBase + 32'h9010;
  localparam logic [31:0] KemStatus = AbrBase + 32'h9014;
  localparam logic [31:0] KemCmdKeygen = 32'h1;  // MLKEM_CTRL.CTRL = KEYGEN
  localparam logic [31:0] KemCmdEncaps = 32'h2;  // MLKEM_CTRL.CTRL = ENCAPS
  localparam logic [31:0] KemCmdDecaps = 32'h3;  // MLKEM_CTRL.CTRL = DECAPS
  localparam logic [31:0] KemStValid = 32'h2;  // MLKEM_STATUS.VALID

  // AES CTRL_SHADOWED / STATUS (OpenTitan aes_reg_pkg via sep_reg.svh).
  localparam logic [1:0] AesOpEnc = 2'b01;
  localparam logic [1:0] AesOpDec = 2'b10;
  localparam logic [5:0] AesModeEcb = 6'b00_0001;
  localparam logic [5:0] AesModeCbc = 6'b00_0010;
  localparam logic [5:0] AesModeCtr = 6'b01_0000;
  localparam logic [2:0] AesKey128 = 3'b001;
  localparam logic [2:0] AesKey192 = 3'b010;
  localparam logic [2:0] AesKey256 = 3'b100;

  // HMAC CFG one-hot fields (prim_sha2_pkg digest_mode_e / key_length_e).
  localparam logic [3:0] HmacSha256 = 4'h1;
  localparam logic [3:0] HmacSha384 = 4'h2;
  localparam logic [3:0] HmacSha512 = 4'h4;
  localparam logic [5:0] HmacKey128 = 6'h01;
  localparam logic [5:0] HmacKey256 = 6'h02;
  localparam logic [5:0] HmacKey384 = 6'h04;
  localparam logic [5:0] HmacKey512 = 6'h08;
  localparam logic [5:0] HmacKey1024 = 6'h10;

  // KMAC CFG_SHADOWED mode / strength (sha3_pkg sha3_mode_e, keccak_strength_e)
  // and the KEY_LEN register (kmac_pkg key_len_e).
  localparam logic [1:0] KmacSha3 = 2'd0;
  localparam logic [1:0] KmacShake = 2'd2;
  localparam logic [1:0] KmacCshake = 2'd3;
  localparam logic [2:0] KmacL128 = 3'd0;
  localparam logic [2:0] KmacL224 = 3'd1;
  localparam logic [2:0] KmacL256 = 3'd2;
  localparam logic [2:0] KmacL384 = 3'd3;
  localparam logic [2:0] KmacL512 = 3'd4;
  localparam logic [2:0] KmacKey128 = 3'd0;
  localparam logic [2:0] KmacKey192 = 3'd1;
  localparam logic [2:0] KmacKey256 = 3'd2;
  localparam logic [2:0] KmacKey384 = 3'd3;
  localparam logic [2:0] KmacKey512 = 3'd4;
  // kmac_pkg kmac_cmd_e is a sparse encoding; CmdProcess is the absorb trigger.
  localparam logic [31:0] KmacCmdProcess = 32'h2E;
  localparam logic [31:0] KmacDoneMask = KMAC_INTR_STATE_KMAC_DONE_MASK;

  localparam logic [31:0] HmacCmdProcess = HMAC_CMD_HASH_PROCESS_MASK;
  localparam logic [31:0] HmacDoneMask = HMAC_INTR_STATE_HMAC_DONE_MASK;

  // CMD.cmd EXECUTE and STATUS IDLE from
  // vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/otbn.hjson.
  localparam logic [7:0] OtbnExecute = 8'hD8;
  localparam logic [7:0] OtbnIdle = 8'h00;

  localparam logic [3:0] DmaOpCopy = 4'h0;  // fw/drivers/sep_dma.h
  localparam logic [3:0] DmaOpSha256 = 4'h1;
  localparam logic [3:0] DmaOpSha384 = 4'h2;

  // aon_timer INTR_STATE: wkup_timer_expired[0], wdog_timer_bark[1]. The
  // vendored block exports no field symbol into sep_reg.svh; the position is
  // the one seq_lib/sep_wdt_aon_seq.py resolves from the register metadata.
  localparam logic [31:0] WdtBarkMask = 32'h2;

  // LC_STATE shadow word: bits[7:0] hold the differential {~raw, raw}
  // (env/sep_efuse_image.py lc_encode). Legal raw codes are
  // efuse_pkg::lc_state_raw_e.
  localparam logic [3:0] LcTestDev = 4'h0;
  localparam logic [3:0] LcProd = 4'h1;
  localparam logic [3:0] LcRmaSip0 = 4'h2;
  localparam logic [3:0] LcRmaSip1 = 4'h3;
  localparam logic [3:0] LcRmaChip0 = 4'h6;
  localparam logic [3:0] LcRmaChip1 = 4'h7;
  localparam logic [3:0] LcProdEnd = 4'h8;

  // KM mailbox frame (seq_lib/sep_km_mailbox_seq.py):
  //   header = {crc8[31:24], payload_len[23:16], cmd_id[15:8], seq_num[7:0]}
  //   RESP_CMD payload = [cmd_seq, cmd_id, rc, arg]
  localparam logic [7:0] KmRespCmd = 8'h00;
  localparam logic [7:0] KmCmdHwVer = 8'h00;
  localparam logic [7:0] KmCmdRomVer = 8'h01;
  localparam logic [7:0] KmCmdSramVer = 8'h02;
  localparam logic [7:0] KmCmdRecovAck = 8'h04;
  localparam logic [7:0] KmCmdExecRom = 8'h10;
  localparam logic [7:0] KmCmdSramLoadExec = 8'h11;
  localparam logic [7:0] KmCmdSramExec = 8'h12;
  localparam logic [7:0] KmCmdGenerate = 8'h22;
  localparam logic [7:0] KmCmdTransfer = 8'h24;
  localparam logic [7:0] KmCmdOtpLock = 8'h28;
  localparam logic [7:0] KmDestHmac = 8'h01;
  localparam logic [7:0] KmDestKmac = 8'h02;
  localparam logic [7:0] KmDestAes = 8'h04;
  localparam logic [7:0] KmDestOtbn = 8'h08;
  localparam logic [7:0] KmDestAbrMldsaSeed = 8'h10;
  localparam logic [7:0] KmDestAbrMlkemSeedD = 8'h20;
  localparam logic [7:0] KmDestAbrMlkemSeedZ = 8'h40;
  localparam logic [7:0] KmDestAbrMlkemMsg = 8'h80;

  localparam logic [1:0] AxiOkay = 2'b00;
  localparam int unsigned PageShift = 12;  // traffic_filter.sv compares [.:12]

  // ------------------------------------------------------------------
  // AXI transaction model. Reset is treated as "not a known 1" so the
  // bring-up window before cocotb drives rst_ni scores nothing.
  // ------------------------------------------------------------------
  wire in_reset = (rst_ni !== 1'b1);

  // `+skip_fuse_sense` makes efuse_shadow_regs.sv force fuse_sense_done to 1 one
  // cycle after reset, with no sense FSM and no macro read (that file's
  // sim_skip_fuse_sense arm). A bin that scored on it would record the
  // simulation bypass, so the sense bin is dead on those runs by construction.
  logic skip_fuse_sense_q;
  initial skip_fuse_sense_q = ($test$plusargs("skip_fuse_sense") != 0);

  wire aw_hs = (lsu_aw_valid_i === 1'b1) && (lsu_aw_ready_i === 1'b1);
  wire w_hs  = (lsu_w_valid_i  === 1'b1) && (lsu_w_ready_i  === 1'b1);
  wire b_hs  = (lsu_b_valid_i  === 1'b1) && (lsu_b_ready_i  === 1'b1);
  wire ar_hs = (lsu_ar_valid_i === 1'b1) && (lsu_ar_ready_i === 1'b1);
  wire r_hs  = (lsu_r_valid_i  === 1'b1) && (lsu_r_ready_i  === 1'b1) &&
               (lsu_r_last_i   === 1'b1);

  logic [3:0] aw_out_q, ar_out_q;
  logic [31:0] aw_addr_q, ar_addr_q;
  logic [63:0] w_data_q;
  logic [7:0]  w_strb_q;

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      aw_out_q <= '0;
      ar_out_q <= '0;
    end else begin
      aw_out_q <= aw_out_q + (aw_hs ? 4'd1 : 4'd0) - (b_hs ? 4'd1 : 4'd0);
      ar_out_q <= ar_out_q + (ar_hs ? 4'd1 : 4'd0) - (r_hs ? 4'd1 : 4'd0);
      if (aw_hs) aw_addr_q <= lsu_aw_addr_i;
      if (ar_hs) ar_addr_q <= lsu_ar_addr_i;
      if (w_hs) begin
        w_data_q <= lsu_w_data_i;
        w_strb_q <= lsu_w_strb_i;
      end
    end
  end

  // Exactly one outstanding transaction, so the latched address belongs to this
  // response. See TRANSACTION PAIRING at the head of the file.
  wire wr_okay = !in_reset && b_hs && (aw_out_q == 4'd1) && (lsu_b_resp_i == AxiOkay);
  wire rd_okay = !in_reset && r_hs && (ar_out_q == 4'd1) && (lsu_r_resp_i == AxiOkay);

  // A 4-byte beat on a 64-bit bus sits in the address-selected lane. Reading
  // bits [31:0] unconditionally would miss every odd-word register (AES
  // CTRL_SHADOWED, OTBN CMD, the ABR STATUS at +0x14, ...).
  wire [31:0] wr_data = aw_addr_q[2] ? w_data_q[63:32]  : w_data_q[31:0];
  wire [3:0]  wr_strb = aw_addr_q[2] ? w_strb_q[7:4]    : w_strb_q[3:0];
  wire [31:0] rd_data = ar_addr_q[2] ? lsu_r_data_i[63:32] : lsu_r_data_i[31:0];

  function automatic logic in_win(logic [31:0] a, logic [31:0] lo, logic [31:0] hi);
    return (a >= lo) && (a < hi);
  endfunction



  // ------------------------------------------------------------------
  // Decoded events
  // ------------------------------------------------------------------
  wire wr_ev = wr_okay;
  wire rd_ev = rd_okay;

  // --- AXI fabric decode -------------------------------------------------
  // SEP_LOCAL_BASE_ADDR reads its specified reset value. A dead read path
  // returning zeros cannot hit this bin.
  wire decode_reset_value = rd_ev &&
      (ar_addr_q == SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_ADDR) &&
      (rd_data == 32'(SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_DEFAULT));

  // Write / readback: latch one CSR write, then require a later OKAY read of
  // THAT address to return the bytes the write strobed. A write alone, or an
  // OKAY with any data, does not hit it.
  logic [31:0] csr_addr_q, csr_data_q;
  logic        csr_valid_q;
  // Non-zero data is required: sep_reg_bit_bash_seq walks read-only and RAZ
  // registers, so a 0x0 write followed by a 0x0 read would fill this bin with
  // nothing retained. Same guard the reset-value bin already carries.
  wire         csr_write = wr_ev && !in_win(aw_addr_q, SramBase, SramEnd) &&
      (wr_strb == 4'hF) && (wr_data != 32'h0);
  wire         csr_readback = rd_ev && csr_valid_q && (ar_addr_q == csr_addr_q) &&
      (rd_data == csr_data_q);

  // --- SRAM --------------------------------------------------------------
  logic [31:0] sram_addr_q;
  logic [63:0] sram_data_q;
  logic        sram_valid_q;
  wire         sram_write = wr_ev && in_win(aw_addr_q, SramBase, SramEnd);
  wire         sram_readback = rd_ev && sram_valid_q && (ar_addr_q == sram_addr_q) &&
      (lsu_r_data_i == sram_data_q);

  // --- Boot ROM ----------------------------------------------------------
  wire rom_ifu = !in_reset && (cpu_trace_valid_i === 1'b1) &&
      in_win(cpu_trace_addr_i, BootRomBase, BootRomEnd);
  wire rom_lsu = rd_ev && in_win(ar_addr_q, BootRomBase, BootRomEnd);

  // --- CPU boot ----------------------------------------------------------
  logic fw_pass_q;
  wire cpu_console = !in_reset && (fw_char_valid_i === 1'b1);
  wire cpu_pass    = !in_reset && (fw_done_i === 1'b1) && (fw_pass_i === 1'b1) && !fw_pass_q;
  wire cpu_pc      = !in_reset && (cpu_trace_valid_i === 1'b1) && (cpu_trace_addr_i != 32'h0);

  // --- AES ---------------------------------------------------------------
  wire       aes_ctrl_wr  = wr_ev && (aw_addr_q == AES_CTRL_SHADOWED_REG_ADDR);
  wire [1:0] aes_op_w      = (wr_data & AES_CTRL_SHADOWED_OPERATION_MASK) >>
      AES_CTRL_SHADOWED_OPERATION_SHIFT;
  wire       aes_sideload_w = (wr_data & AES_CTRL_SHADOWED_SIDELOAD_MASK) != 32'h0;
  wire [5:0] aes_mode_w = (wr_data & AES_CTRL_SHADOWED_MODE_MASK) >>
      AES_CTRL_SHADOWED_MODE_SHIFT;
  wire [2:0] aes_key_w  = (wr_data & AES_CTRL_SHADOWED_KEY_LEN_MASK) >>
      AES_CTRL_SHADOWED_KEY_LEN_SHIFT;
  wire       aes_out_valid = rd_ev && (ar_addr_q == AES_STATUS_REG_ADDR) &&
      ((rd_data & AES_STATUS_OUTPUT_VALID_MASK) != 32'h0);
  wire       aes_ct_read   = rd_ev && (ar_addr_q == AES_DATA_OUT_0__REG_ADDR);

  logic [5:0] aes_mode_q;
  logic [2:0] aes_key_q;
  logic [1:0] aes_op_q;
  logic       aes_sideload_q;
  logic aes_cfg_valid_q, aes_out_valid_q;
  // One AES cell completes when the configured mode/key size reached
  // OUTPUT_VALID and the ciphertext word was read back.
  wire        aes_cell_done = aes_ct_read && aes_cfg_valid_q && aes_out_valid_q;

  // --- HMAC --------------------------------------------------------------
  wire       hmac_cfg_wr = wr_ev && (aw_addr_q == HMAC_CFG_REG_ADDR);
  wire [3:0] hmac_digest_w = (wr_data & HMAC_CFG_DIGEST_SIZE_MASK) >>
      HMAC_CFG_DIGEST_SIZE_SHIFT;
  wire [5:0] hmac_keylen_w = (wr_data & HMAC_CFG_KEY_LENGTH_MASK) >>
      HMAC_CFG_KEY_LENGTH_SHIFT;
  wire       hmac_en_w = (wr_data & HMAC_CFG_HMAC_EN_MASK) != 32'h0;
  wire       hmac_process = wr_ev && (aw_addr_q == HMAC_CMD_REG_ADDR) &&
      ((wr_data & HmacCmdProcess) != 32'h0);
  // Done is the INTR_STATE status bit the driver polls, not the CMD write.
  wire       hmac_done = rd_ev && (ar_addr_q == HMAC_INTR_STATE_REG_ADDR) &&
      ((rd_data & HmacDoneMask) != 32'h0);

  logic [3:0] hmac_digest_q;
  logic [5:0] hmac_keylen_q;
  logic hmac_en_q, hmac_cfg_valid_q, hmac_process_q;
  wire        hmac_cell_done = hmac_done && hmac_cfg_valid_q && hmac_process_q;

  // --- KMAC --------------------------------------------------------------
  wire       kmac_cfg_wr = wr_ev && (aw_addr_q == KMAC_CFG_SHADOWED_REG_ADDR);
  wire       kmac_en_w   = (wr_data & KMAC_CFG_SHADOWED_KMAC_EN_MASK) != 32'h0;
  wire [1:0] kmac_mode_w = (wr_data & KMAC_CFG_SHADOWED_MODE_MASK) >>
      KMAC_CFG_SHADOWED_MODE_SHIFT;
  wire [2:0] kmac_str_w  = (wr_data & KMAC_CFG_SHADOWED_KSTRENGTH_MASK) >>
      KMAC_CFG_SHADOWED_KSTRENGTH_SHIFT;
  wire       kmac_sideload_w = (wr_data & KMAC_CFG_SHADOWED_SIDELOAD_MASK) != 32'h0;
  wire       kmac_keylen_wr = wr_ev && (aw_addr_q == KMAC_KEY_LEN_REG_ADDR);
  wire       kmac_process = wr_ev && (aw_addr_q == KMAC_CMD_REG_ADDR) &&
      (wr_data == KmacCmdProcess);
  wire       kmac_done = rd_ev && (ar_addr_q == KMAC_INTR_STATE_REG_ADDR) &&
      ((rd_data & KmacDoneMask) != 32'h0);
  // Reading a STATE share back is the completion event BOTH drivers produce.
  // `keyed_mac` -- the only path the KM sideload KAT takes -- polls STATUS and
  // reads the shares, and never touches INTR_STATE, so an INTR_STATE-only
  // anchor could not sample a sideloaded operation at all: the leaf's single
  // INTR_STATE read lands at EOT, after the last SW-key leg.
  wire       kmac_digest_rd = rd_ev && in_win(ar_addr_q, KMAC_STATE_MEM_BASE_ADDR,
      KMAC_STATE_MEM_BASE_ADDR + KMAC_STATE_MEM_SIZE);

  logic kmac_en_q, kmac_cfg_valid_q, kmac_process_q, kmac_keylen_valid_q;
  logic [1:0] kmac_mode_q;
  logic [2:0] kmac_str_q, kmac_keylen_q;
  logic       kmac_sideload_q;
  wire        kmac_cell_done = (kmac_done || kmac_digest_rd) && kmac_cfg_valid_q &&
      kmac_process_q;

  // --- OTBN --------------------------------------------------------------
  wire otbn_execute = wr_ev && (aw_addr_q == OTBN_CMD_REG_ADDR) &&
      (wr_data[7:0] == OtbnExecute);
  wire otbn_status_idle = rd_ev && (ar_addr_q == OTBN_STATUS_REG_ADDR) &&
      (((rd_data & OTBN_STATUS_STATUS_MASK) >> OTBN_STATUS_STATUS_SHIFT) == 32'(OtbnIdle));
  wire otbn_err_zero = rd_ev && (ar_addr_q == OTBN_ERR_BITS_REG_ADDR) && (rd_data == 32'h0);

  // otbn.hjson STATUS: IDLE 0x00, BUSY_EXECUTE 0x01, BUSY_SEC_WIPE_* 0x02-0x04.
  // Without an observed busy status the poll can win a race against OTBN
  // leaving IDLE and score a program that never started.
  wire otbn_status_busy = rd_ev && (ar_addr_q == OTBN_STATUS_REG_ADDR) &&
      (rd_data[7:0] inside {8'h01, 8'h02, 8'h03, 8'h04});
  logic otbn_exec_q, otbn_busy_q, otbn_idle_q;
  // One Done bin: the SAME post-EXECUTE window saw STATUS back at IDLE and
  // then ERR_BITS == 0. Two independent strobes would score a program that
  // never ran alongside a stale zero.
  wire  otbn_done = otbn_err_zero && otbn_exec_q && otbn_idle_q;

  // --- Adams Bridge ------------------------------------------------------
  wire abr_keygen = wr_ev && (aw_addr_q == AbrCtrl) &&
      ((wr_data & AbrCtrlCmdMask) == AbrCmdKeygen);
  wire abr_status_valid = rd_ev && (ar_addr_q == AbrStatus) &&
      ((rd_data & AbrStValid) != 32'h0);
  logic abr_keygen_q;
  wire  abr_done = abr_status_valid && abr_keygen_q;
  // SIGNING and VERIFYING are separate MLDSA_CTRL.CTRL commands, so each gets
  // its own pending flag: a VALID read only scores the command that is still
  // outstanding, and a leaf that issued one command cannot fill the other bin.
  wire abr_sign = wr_ev && (aw_addr_q == AbrCtrl) &&
      ((wr_data & AbrCtrlCmdMask) == AbrCmdSign);
  wire abr_verify = wr_ev && (aw_addr_q == AbrCtrl) &&
      ((wr_data & AbrCtrlCmdMask) == AbrCmdVerify);
  // MLDSA_STATUS.VALID is sticky, so a pending flag plus a VALID read is not
  // enough on its own: a command written to a busy engine is dropped, and the
  // previous operation's VALID would then be credited to it. Arming on an
  // observed VALID==0 read is the anchor -- the same problem OTBN solves by
  // requiring an observed busy status between EXECUTE and IDLE.
  wire abr_status_clear = rd_ev && (ar_addr_q == AbrStatus) &&
      ((rd_data & AbrStValid) == 32'h0);
  logic abr_sign_q, abr_verify_q;
  logic abr_sign_armed_q, abr_verify_armed_q;
  wire  abr_sign_done = abr_status_valid && abr_sign_q && abr_sign_armed_q;
  wire  abr_verify_done = abr_status_valid && abr_verify_q && abr_verify_armed_q;

  // ML-KEM. Same pending-plus-armed shape as the ML-DSA pair above, and for the
  // same reason: MLKEM_CTRL is writable only while STATUS.READY is set, so a
  // command issued to a busy engine is dropped silently and the stale VALID
  // would be read as its completion.
  wire kem_status_valid = rd_ev && (ar_addr_q == KemStatus) &&
      ((rd_data & KemStValid) != 32'h0);
  wire kem_status_clear = rd_ev && (ar_addr_q == KemStatus) &&
      ((rd_data & KemStValid) == 32'h0);
  wire kem_keygen = wr_ev && (aw_addr_q == KemCtrl) && (wr_data[2:0] == KemCmdKeygen[2:0]);
  wire kem_encaps = wr_ev && (aw_addr_q == KemCtrl) && (wr_data[2:0] == KemCmdEncaps[2:0]);
  wire kem_decaps = wr_ev && (aw_addr_q == KemCtrl) && (wr_data[2:0] == KemCmdDecaps[2:0]);
  logic kem_keygen_q, kem_encaps_q, kem_decaps_q;
  logic kem_keygen_armed_q, kem_encaps_armed_q, kem_decaps_armed_q;
  wire  kem_keygen_done = kem_status_valid && kem_keygen_q && kem_keygen_armed_q;
  wire  kem_encaps_done = kem_status_valid && kem_encaps_q && kem_encaps_armed_q;
  wire  kem_decaps_done = kem_status_valid && kem_decaps_q && kem_decaps_armed_q;

  // --- ESRC / DRBG / EDN -------------------------------------------------
  logic esrc_seed_q;
  wire esrc_seed = !in_reset && (drbg_seed_valid_i === 1'b1) && !esrc_seed_q;
  logic drbg_gen_q;
  wire drbg_gen  = !in_reset && (drbg_genbits_vld_i === 1'b1) && !drbg_gen_q;
  wire edn_crypto_beat = !in_reset && (axis1_tvalid_i === 1'b1) && (axis1_tready_i === 1'b1);
  wire edn_km_beat = !in_reset && (km_entropy_tvalid_i === 1'b1) &&
      (km_entropy_tready_i === 1'b1);

  // --- Key Manager mailbox ----------------------------------------------
  wire km_wr_data = wr_ev && (aw_addr_q == KM_MAILBOX_SEP_SEP_WRITE_DATA_REG_ADDR);
  wire km_rd_data = rd_ev && (ar_addr_q == KM_MAILBOX_SEP_SEP_READ_DATA_REG_ADDR);

  logic [7:0] km_cmd_len_q;      // declared payload_len
  logic [8:0] km_cmd_idx_q;      // 0 = header
  logic       km_cmd_hdr_next_q; // next WRITE_DATA word starts a frame
  logic [8:0] km_rsp_idx_q;      // 0 = response header
  logic       km_rsp_arm_q;      // a command frame has been sent, response pending
  logic [7:0] km_rsp_cmd_q;      // echoed cmd_id (payload word 2)
  logic [7:0] km_rsp_rc_q;       // rc (payload word 3)
  logic       km_rsp_is_cmd_q;   // outbound header resp_id was RESP_CMD
  logic [7:0] km_rsp_len_q;      // declared RESP payload_len, from the header

  // Generate succeeded: the response frame echoed CMD_KEY_GENERATE with rc 0
  // and a non-null handle. Nothing here is inferred from silence.
  wire km_generate_ok = km_rd_data && km_rsp_arm_q && (km_rsp_idx_q == 9'd4) &&
      (km_rsp_cmd_q == KmCmdGenerate) && (km_rsp_rc_q == 8'h00) && (rd_data[7:0] != 8'h00);
  // Score dest/cmd on a RESP_CMD payload, not on inbound WRITE_DATA.
  // Transfer dest is RETURN_ARG dest_engine[15:8] of a success frame.
  //
  // Completion is the LAST payload word, taken from the header's declared
  // payload_len rather than a fixed word 4. A RESP_CMD is valid at
  // payload_len 3 -- [cmd_seq, cmd_id, rc] with no return arg -- so an
  // arg-less command such as CMD_SRAM_EXEC ends a word early and a fixed
  // index can never see it complete.
  wire km_rsp_last = km_rd_data && km_rsp_arm_q && km_rsp_is_cmd_q &&
      (km_rsp_idx_q == 9'(km_rsp_len_q));
  // On a 3-word frame the rc is being read on this very cycle, so it is not
  // latched yet; take it off the bus in that case.
  wire [7:0] km_rsp_rc_now = (km_rsp_idx_q == 9'd3) ? rd_data[7:0] : km_rsp_rc_q;
  wire km_host_cmd_seen = km_rsp_last &&
      ((km_rsp_cmd_q == KmCmdSramVer) ? (km_rsp_rc_now != 8'h00)
                                      : (km_rsp_rc_now == 8'h00));
  wire km_xfer_scored = km_rd_data && km_rsp_arm_q && km_rsp_is_cmd_q &&
      (km_rsp_idx_q == 9'd4) && (km_rsp_cmd_q == KmCmdTransfer) &&
      (km_rsp_rc_q == 8'h00);
  wire km_wipe = wr_ev && (aw_addr_q == SEP_CPU_CTRL_KM_WIPE_CTRL_REG_ADDR) &&
      wr_strb[0] && wr_data[0];
  wire km_swrst_rel = wr_ev && (aw_addr_q == SEP_RESET_CTRL_SW_RESET_N_REG_ADDR) &&
      wr_strb[0] && wr_data[0];

  // --- Secure DMA --------------------------------------------------------
  wire dma_go = wr_ev && (aw_addr_q == SECURE_DMA_CONTROL_REG_ADDR) &&
      ((wr_data & SECURE_DMA_CONTROL_GO_MASK) != 32'h0);
  wire [3:0] dma_opcode_w = (wr_data & SECURE_DMA_CONTROL_OPCODE_MASK) >>
      SECURE_DMA_CONTROL_OPCODE_SHIFT;
  wire dma_copy_go = dma_go && (dma_opcode_w == DmaOpCopy);
  wire dma_hash_go = dma_go && (dma_opcode_w == DmaOpSha256);
  // Any inline-hash GO, whatever the digest length, so the opcode
  // coverpoint can say WHICH hash the suite walked. dma_hash_go above
  // stays SHA-256-only because the completion pairing below is written
  // against that leaf.
  wire dma_hash_any_go = dma_go && (dma_opcode_w != DmaOpCopy);
  wire dma_hs_go   = dma_go &&
      ((wr_data & SECURE_DMA_CONTROL_HARDWARE_HANDSHAKE_ENABLE_MASK) != 32'h0);
  logic dma_copy_q, dma_hash_q, dma_hs_q;
  // One chunk per GO is the DMA's normal protocol: the engine raises
  // CHUNK_DONE and drops BUSY, and firmware W1Cs it and re-GOes with
  // INITIAL_TRANSFER=0 until the last chunk reports DONE. The loop lives in
  // fw/tests/dma_basic_test/dma_basic_test.c, not the driver header. That loop
  // is why one transfer shows many GO writes.
  wire dma_chunk_done = rd_ev && (ar_addr_q == SECURE_DMA_STATUS_REG_ADDR) &&
      ((rd_data & SECURE_DMA_STATUS_CHUNK_DONE_MASK) != 32'h0) &&
      (dma_copy_q || dma_hash_q);
  wire dma_rego_non_initial = dma_go &&
      ((wr_data & SECURE_DMA_CONTROL_INITIAL_TRANSFER_MASK) == 32'h0);
  wire dma_status_done = rd_ev && (ar_addr_q == SECURE_DMA_STATUS_REG_ADDR) &&
      ((rd_data & SECURE_DMA_STATUS_DONE_MASK) != 32'h0);
  // A DMA transfer can report completion two ways, and the suite uses both:
  // dma_basic_test polls STATUS, while dma_hash_test enables INTR_ENABLE.DMA_DONE,
  // WFIs, and its handler clears STATUS.done before software ever reads it -- so
  // on that path no STATUS read with the DONE bit ever appears on the bus. The
  // interrupt (sep.sv:535 sep_internal_interrupts[8] = intr_dma_done) is the
  // completion event there. Rising edge: the aggregated bit is a level.
  logic irq_dma_done_q;
  wire  dma_irq_done = !in_reset && (irq_dma_done_i === 1'b1) && !irq_dma_done_q;
  wire  dma_complete = dma_status_done || dma_irq_done;

  // Which opcode was GO'd still labels the cell, so an interrupt cannot score
  // the wrong one.
  wire  dma_copy_done = dma_complete && dma_copy_q;
  wire  dma_hash_done = dma_complete && dma_hash_q;

  // --- SPI host ----------------------------------------------------------
  wire spi_csr = (wr_ev && in_win(aw_addr_q, SpiBase, SpiEnd)) ||
                 (rd_ev && in_win(ar_addr_q, SpiBase, SpiEnd));
  logic spi_cs_n_q, spi_sck_q;
  // A real frame on the pads: chip select asserted, then a shift clock edge
  // inside that frame. CSR traffic alone cannot hit these.
  wire  spi_cs_assert = !in_reset && spi_cs_n_q && (spi_cs_n_i === 1'b0);
  wire  spi_sck_edge  = !in_reset && (spi_cs_n_i === 1'b0) && !spi_sck_q &&
      (spi_sck_i === 1'b1);

  // --- Inbound filter ----------------------------------------------------
  wire filt_cfg_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      (((aw_addr_q - FiltBase) % FiltStride) == FiltCfgOff);
  wire filt_start_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      (((aw_addr_q - FiltBase) % FiltStride) == FiltStartOff);
  wire filt_end_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      (((aw_addr_q - FiltBase) % FiltStride) == FiltEndOff);

  // The window has to be latched as ONE entry. Three independent last-writes
  // would build a window out of a START from one entry, an END from another and
  // an ENABLE from a third - a window the DUT never had. The programming order
  // is START, END, then the enabling FILTER_CONFIG (sep_inbound_filter_rule_seq),
  // so the entry is committed at that CONFIG write and only when all three
  // addresses are the same entry.
  function automatic logic [31:0] filt_entry_of(logic [31:0] a);
    return (a - FiltBase) / FiltStride;
  endfunction

  logic [31:0] filt_start_q, filt_end_q;
  logic [31:0] filt_start_entry_q, filt_end_entry_q, filt_win_entry_q;
  logic [31:0] filt_win_lo_q, filt_win_hi_q;
  logic        filt_win_valid_q;

  wire m_aw_hs = !in_reset && (m_axi_awvalid_i === 1'b1) && (m_axi_awready_i === 1'b1);
  wire m_ar_hs = !in_reset && (m_axi_arvalid_i === 1'b1) && (m_axi_arready_i === 1'b1);
  wire m_b_ok  = !in_reset && (m_axi_bvalid_i === 1'b1) && (m_axi_bready_i === 1'b1) &&
      (m_axi_bresp_i == AxiOkay);
  wire m_r_ok  = !in_reset && (m_axi_rvalid_i === 1'b1) && (m_axi_rready_i === 1'b1) &&
      (m_axi_rlast_i === 1'b1) && (m_axi_rresp_i == AxiOkay);

  logic [31:0] m_aw_addr_q, m_ar_addr_q;
  // Same pairing contract as the LSU side: sep_axi_order_sweep_m_axi_test
  // runs several inbound transactions at once, and a plain
  // last-write latch would pair one access's response with another's address.
  logic [3:0] m_aw_out_q, m_ar_out_q;

  // The PROGRAMMED range, not its 4 KB page. traffic_filter.sv compares
  // addr[.:12] only in the allow_burst arm; the other arm compares
  // addr[.:DATA_BUS_WIDTH_LOG2]. A page compare is therefore a superset of the
  // real grant, and would score an OKAY that landed inside the page but
  // outside the window the test programmed. Comparing the range can only
  // MISS a page-widened grant, never invent one.
  function automatic logic in_allow_window(logic [31:0] a);
    return filt_win_valid_q && (a >= filt_win_lo_q) && (a <= filt_win_hi_q);
  endfunction

  wire filt_allow_wr = m_b_ok && (m_aw_out_q == 4'd1) && in_allow_window(m_aw_addr_q);
  wire filt_allow_rd = m_r_ok && (m_ar_out_q == 4'd1) && in_allow_window(m_ar_addr_q);

  // --- peer-side mailbox fill --------------------------------------------
  // A completed external write to the inbound mailbox WRITE_DATA register: the
  // only way anything reaches the host aperture's receive FIFO. The host-side
  // mailbox bins below are all IRQ edges and are hit by the transmit path, so
  // none of them shows the receive direction was ever driven. Both halves of
  // the 8-byte register alias to it, so the compare masks bit 2.
  wire m_mbox_peer_wr = m_b_ok && (m_aw_out_q == 4'd1) &&
      ((m_aw_addr_q & ~32'h4) == AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_REG_ADDR);

  // --- eFuse program x write-lock ----------------------------------------
  // Programming a write-locked field is a LEGAL software action with a
  // specified outcome (refused), not a fault injection -- the same class as a
  // read-only register. sep_efuse_program_lock_matrix_test walks
  // unlocked-program then lock-then-reject on EACH of SPARE0..SPARE8 in order,
  // so the whole cross is filled by ONE seed; only the bit offset inside a
  // spare is seeded.
  //
  // Every operation is frontdoor on EFUSE_PROGRAM_CTRL: the write carries the
  // OTP bit index in EFUSE_ADDR plus PROGRAM_GO, and the outcome reads back as
  // PROGRAM_DONE or PROGRAM_STATUS (the refusal).
  localparam logic [31:0] EfuseProgCtrl = EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR;
  // Two lock bits per spare, and the assigned spare locks end where the RDL
  // reserved field of LOCKS_SPARE starts: 9 spares, slots 32-40
  // (otp_fuse_controller.adoc).
  localparam int unsigned LockBitsPerSlot = 2;
  localparam int unsigned SpareCount =
      SEP_EFUSE_MAP_LOCKS_SPARE_SPARE_LOCK_RSVD_SHIFT / LockBitsPerSlot;
  // Wide enough to index every spare; a narrower index would wrap the last
  // spare onto spare 0 and fill its bins with the wrong field.
  localparam int unsigned SpareIdxW = $clog2(SpareCount);
  // Spare k occupies SPARE_STRIDE bytes of the shadow map, so its OTP bit
  // range starts at (byte offset / 4) * 32 bits.
  localparam int unsigned SpareStrideB  = SEP_EFUSE_MAP_SPARE1_REG_OFFSET -
                                          SEP_EFUSE_MAP_SPARE0_REG_OFFSET;
  localparam int unsigned SpareBitBase = (SEP_EFUSE_MAP_SPARE0_REG_OFFSET / 4) * 32;
  localparam int unsigned SpareBitSpan = (SpareStrideB / 4) * 32;
  // Slot 32+k owns spare k's write lock at bit 2*(32+k) of the LOCKS vector,
  // which is where LOCKS_SPARE starts (otp_fuse_controller.adoc, sep_efuse_pkg).
  localparam int unsigned SpareLockBase = (SEP_EFUSE_MAP_LOCKS_SPARE_REG_OFFSET / 4) * 32;

  wire        efuse_prog_go = wr_ev && (aw_addr_q == EfuseProgCtrl) &&
      ((wr_data & EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_EFUSE_PROGRAM_GO_MASK) != 32'h0);
  wire [15:0] efuse_prog_bit = (wr_data &
      EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_EFUSE_ADDR_MASK) >>
      EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_EFUSE_ADDR_SHIFT;
  wire        efuse_prog_rd = rd_ev && (ar_addr_q == EfuseProgCtrl);
  wire        efuse_prog_done = efuse_prog_rd &&
      ((rd_data & EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_PROGRAM_DONE_MASK) != 32'h0);
  wire        efuse_prog_err = efuse_prog_rd &&
      ((rd_data & EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_PROGRAM_STATUS_MASK) != 32'h0);

  // Which spare a targeted OTP bit belongs to, and whether it is a lock bit.
  wire        prog_is_spare = (efuse_prog_bit >= SpareBitBase) &&
      (efuse_prog_bit < (SpareBitBase + SpareCount * SpareBitSpan));
  wire [SpareIdxW-1:0] prog_spare_idx = (efuse_prog_bit - SpareBitBase) / SpareBitSpan;
  wire        prog_is_lock = (efuse_prog_bit >= SpareLockBase) &&
      (efuse_prog_bit < (SpareLockBase + SpareCount * LockBitsPerSlot)) &&
      (((efuse_prog_bit - SpareLockBase) % LockBitsPerSlot) == 0);
  wire [SpareIdxW-1:0] prog_lock_idx = (efuse_prog_bit - SpareLockBase) / LockBitsPerSlot;

  // NOT cleared on reset: a programmed OTP lock bit is permanent, and the
  // owning test re-senses (which pulses reset) between programming spare k's
  // lock and proving the refusal. A reset-cleared latch would score every
  // post-resense attempt as unlocked.
  logic [SpareCount-1:0] spare_locked_q;   // write-lock programmed for spare k
  logic [SpareIdxW-1:0]  prog_spare_q;     // spare targeted by the pending GO
  logic                  prog_pending_q;   // a data program is awaiting its outcome
  logic                  prog_locked_q;    // was that spare locked when it was issued

  // --- eFuse -------------------------------------------------------------
  // Rising edge, not the held level: the level would score one hit per clock
  // for the rest of the run and make the bin count meaningless.
  // fuse_sense_seen_q is likewise history: a re-sense follows a cold reset by
  // definition, so the latch lives outside the reset-bearing always_ff.
  logic fuse_sense_done_q;
  logic fuse_sense_seen_q;
  wire  fuse_sense = !in_reset && !skip_fuse_sense_q &&
      (fuse_sense_done_i === 1'b1) && !fuse_sense_done_q;
  wire  fuse_sense_episode = fuse_sense_seen_q;

  // --- eFuse FSM fail-closed ---------------------------------------------
  // Both machines encode idle as 2'b01 and wait-for-response as 2'b10, so
  // 2'b00 and 2'b11 are unreachable by design. sep_efuse_illegal_state_fail
  // _closed_test injects them; ordinary traffic scores nothing here because
  // the legal encodings land in no bin.
  localparam logic [1:0] EfuseStIdle = 2'b01;
  localparam logic [1:0] EfuseStWait = 2'b10;
  wire efuse_rd_illegal = !in_reset &&
      !(efuse_read_state_i inside {EfuseStIdle, EfuseStWait});
  wire efuse_pg_illegal = !in_reset &&
      !(efuse_program_state_i inside {EfuseStIdle, EfuseStWait});

  // --- Lifecycle feature control ------------------------------------------
  // FEAT_CTRL is 64-bit, read as two 32-bit halves. Aggregate the DEFINED
  // debug bits into none/partial/full the way the reference coverage does:
  // DBG_1 = sep_debug, chiplet_dbg, sep_fuse_dbg, smc_fuse_dbg (bits 0..3) and
  // DBG_2 = sip_debug (bit 24). env/sep_lcc_golden.py is the layout authority.
  // There is no DFT/test group in this layout, and SECURE_TM does not qualify
  // feature control, so neither is crossed with the debug aggregate.
  localparam logic [31:0] FeatDbg1Mask = 32'h0000_000F;  // bits 3:0
  localparam logic [31:0] FeatDbg2Mask = 32'h0100_0000;  // bit 24
  localparam int unsigned FeatDbgBits = 5;

  logic [31:0] feat_lo_q;
  logic        feat_lo_valid_q;
  wire         feat_ctrl_lo_rd = rd_ev && (ar_addr_q == SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_ADDR);
  wire         feat_ctrl_hi_rd = rd_ev &&
      (ar_addr_q == (SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_ADDR + 32'd4)) && feat_lo_valid_q;

  function automatic int unsigned popcount32(logic [31:0] v);
    int unsigned n;
    n = 0;
    for (int i = 0; i < 32; i++) if (v[i]) n++;
    return n;
  endfunction

  // 0 = none, 1 = partial, 2 = full over the five defined debug bits.
  // Both masks apply to the LO half: DBG_1 is bits [23:0] and DBG_2 starts at
  // bit 24 (sep_lcc_golden.py SIP_DBG_BIT = 24), so all five defined debug bits
  // are inside the first 32-bit word. The hi half is Function only.
  function automatic logic [1:0] debug_class(logic [31:0] lo);
    int unsigned n;
    n = popcount32(lo & FeatDbg1Mask) + popcount32(lo & FeatDbg2Mask);
    if (n == 0) return 2'd0;
    if (n == FeatDbgBits) return 2'd2;
    return 2'd1;
  endfunction

  wire [1:0] feat_dbg_class = debug_class(feat_lo_q);
  // The SENSED state, not a frontdoor read: the W1S leaves verify their start
  // state through the shadow probe, so the probe is the source that sees a
  // state a leaf never reads frontdoor before transitioning.
  wire [3:0] lc_sensed = efuse_lc_raw_i;

  wire       demote_1_set = (demote_1_i == 2'b01);
  wire       demote_2_set = (demote_2_i == 2'b01);

  // --- Lifecycle ---------------------------------------------------------
  wire       lc_read = rd_ev && (ar_addr_q == SEP_EFUSE_MAP_LC_STATE_REG_ADDR);
  wire [3:0] lc_raw  = rd_data[3:0];
  // The shadow word carries {~raw, raw}. Requiring the complement means a
  // stuck-at or half-sensed word lands in no bin instead of scoring one.
  wire       lc_diff_ok = lc_read && (rd_data[7:4] == ~lc_raw);
  // Previous DIFFERENT legal LC code, so a transition can be labelled by its
  // endpoints. sep_lc_shadow_write_seq reads the shadow word ONCE per cell
  // (after its write), so a transition pair is two consecutive cells of the
  // same leaf, not a before/after pair around one write. The stitch chain
  // TEST_DEV -> PROD -> RMA_SIP_1 -> RMA_CHIP_1 is what produces them.
  logic [3:0] lc_prev_q;
  logic       lc_prev_valid_q;
  wire        lc_transition = lc_diff_ok && lc_prev_valid_q && (lc_raw != lc_prev_q);

  // --- SEC_DIS while sensing is open ------------------------------------
  // A match leaves the sense-gated reset held. The sep_reset_n override
  // releases it, and clearing the override holds it again. The LC_STATE
  // shadow read in that window is sampled on its AXI response, including a
  // non-OKAY response (rd_ev is OKAY only).
  wire sense_open = !in_reset && !skip_fuse_sense_q && (fuse_sense_done_i === 1'b0);
  wire sec_dis_on = (sec_dis_i === 1'b1);
  wire sep_reset_ovrd = (jtag_sep_reset_n_ovrd_i === 1'b1) &&
      (jtag_sep_reset_n_val_i === 1'b1);
  logic sec_dis_cpu_reset_n_q;
  logic sec_dis_on_q;
  logic sec_dis_release_seen_q;
  wire sep_reset_rise = !sec_dis_cpu_reset_n_q && (cpu_reset_n_i === 1'b1);
  wire sep_reset_fall = sec_dis_cpu_reset_n_q && (cpu_reset_n_i === 1'b0);
  // Sampled on the SEC_DIS rise, while the reset is held and the override is clear.
  wire sec_dis_hold_ev = sense_open && sec_dis_on && !sec_dis_on_q &&
      (cpu_reset_n_i === 1'b0) && !sep_reset_ovrd;
  wire sec_dis_release_ev = sense_open && sep_reset_ovrd && sep_reset_rise;
  wire sec_dis_rehold_ev = sense_open && !sep_reset_ovrd && sep_reset_fall &&
      sec_dis_release_seen_q;
  wire rd_cmpl = !in_reset && r_hs && (ar_out_q == 4'd1);
  wire sec_dis_map_rd = rd_cmpl && sense_open && sec_dis_on &&
      (ar_addr_q == SEP_EFUSE_MAP_LC_STATE_REG_ADDR);
  // SW_RESET_N is in the sep_reset_n domain. An OKAY read while sensing is
  // still open means the override has released that domain.
  wire sec_dis_reach_rd = rd_okay && sense_open && (cpu_reset_n_i === 1'b1) &&
      (ar_addr_q == SEP_RESET_CTRL_SW_RESET_N_REG_ADDR);

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      sec_dis_cpu_reset_n_q  <= 1'b0;
      sec_dis_on_q           <= 1'b0;
      sec_dis_release_seen_q <= 1'b0;
    end else begin
      sec_dis_cpu_reset_n_q <= (cpu_reset_n_i === 1'b1);
      sec_dis_on_q          <= sec_dis_on;
      if (fuse_sense_done_i === 1'b1) sec_dis_release_seen_q <= 1'b0;
      if (sec_dis_release_ev) sec_dis_release_seen_q <= 1'b1;
    end
  end

  // --- Mailbox / PIC -----------------------------------------------------
  logic irq_mailbox_q, irq_km_mbox_q;
  wire  mbox_any    = !$isunknown(irq_mailbox_i) && (irq_mailbox_i != 8'h00);
  wire  mbox_raise  = !in_reset && mbox_any && !irq_mailbox_q;
  wire  mbox_clear  = !in_reset && !mbox_any && irq_mailbox_q;
  wire  km_mbox_raise = !in_reset && (irq_km_mbox_i === 1'b1) && !irq_km_mbox_q;
  wire  km_mbox_clear = !in_reset && (irq_km_mbox_i === 1'b0) && irq_km_mbox_q;

  // --- WDT ---------------------------------------------------------------
  wire wdt_thold_wr = wr_ev && (aw_addr_q == WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR);
  wire wdt_bark = rd_ev && (ar_addr_q == WDT_TIMER_INTR_STATE_REG_ADDR) &&
      ((rd_data & WdtBarkMask) != 32'h0);
  logic wdt_bark_q;
  // The NMI bin is an exception taken as an interrupt AFTER a bark was
  // observed, so an unrelated interrupt cannot score it.
  wire  wdt_nmi = !in_reset && (cpu_trace_valid_i === 1'b1) &&
      (cpu_trace_exc_i === 1'b1) && (cpu_trace_interrupt_i === 1'b1) && wdt_bark_q;

  // --- Warm / cold scratch ----------------------------------------------
  wire warm_write = wr_ev && in_win(aw_addr_q, WarmBase, WarmEnd);
  wire cold_write = wr_ev && in_win(aw_addr_q, ColdBase, ColdEnd);

  logic [31:0] cold_addr_q, cold_data_q, warm_addr_q;
  logic cold_valid_q, warm_written_q;
  logic cpu_reset_n_q, warm_reset_q;
  logic [4:0]  cpu_reset_hi_q;
  // A warm reset is a cpu_reset_n fall AFTER the reset release has settled and
  // AFTER a scratch value was staged -- which is the scenario the contract is
  // about. Without both guards this bin scores a cold bring-up edge in any
  // test, and (worse) arms the two retention bins off the wrong edge.
  wire         warm_reset_fall = !in_reset && cpu_reset_n_q &&
      (cpu_reset_n_i === 1'b0) && (cpu_reset_hi_q == 5'h1F) &&
      (warm_written_q || cold_valid_q);
  // Read AFTER the warm reset, not on the falling edge itself: an event ANDed
  // with the edge cannot fire, because no read completes in that cycle.
  // Address-matched like the cold bin: otherwise a never-written warm word
  // reading its 0 reset value scores the retention cell.
  wire         warm_zero_after_reset = rd_ev && warm_reset_q && warm_written_q &&
      (ar_addr_q == warm_addr_q) && (rd_data == 32'h0);
  wire         cold_kept_after_reset = rd_ev && warm_reset_q && cold_valid_q &&
      (ar_addr_q == cold_addr_q) && (rd_data == cold_data_q);

  // History that OUTLIVES reset, so it cannot sit in the reset-bearing
  // always_ff above. A programmed OTP lock bit is permanent, and a re-sense
  // follows a cold reset. `initial` seeds them because there is no reset term.
  initial begin
    spare_locked_q    = '0;
    fuse_sense_seen_q = 1'b0;
  end

  always @(posedge clk_i) begin
    if (efuse_prog_go && prog_is_lock) spare_locked_q[prog_lock_idx] <= 1'b1;
    if (fuse_sense) fuse_sense_seen_q <= 1'b1;
  end

  // ------------------------------------------------------------------
  // Sampler state
  // ------------------------------------------------------------------
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      csr_valid_q       <= 1'b0;
      sram_valid_q      <= 1'b0;
      aes_cfg_valid_q   <= 1'b0;
      aes_out_valid_q   <= 1'b0;
      hmac_cfg_valid_q  <= 1'b0;
      hmac_process_q    <= 1'b0;
      kmac_cfg_valid_q  <= 1'b0;
      kmac_keylen_valid_q <= 1'b0;
      kmac_process_q    <= 1'b0;
      otbn_exec_q       <= 1'b0;
      otbn_busy_q       <= 1'b0;
      otbn_idle_q       <= 1'b0;
      abr_keygen_q      <= 1'b0;
      abr_sign_q        <= 1'b0;
      abr_verify_q      <= 1'b0;
      abr_sign_armed_q  <= 1'b0;
      abr_verify_armed_q <= 1'b0;
      kem_keygen_q      <= 1'b0;
      kem_encaps_q      <= 1'b0;
      kem_decaps_q      <= 1'b0;
      kem_keygen_armed_q <= 1'b0;
      kem_encaps_armed_q <= 1'b0;
      kem_decaps_armed_q <= 1'b0;
      km_cmd_hdr_next_q <= 1'b1;
      km_cmd_idx_q      <= '0;
      km_rsp_idx_q      <= '0;
      km_rsp_arm_q      <= 1'b0;
      km_rsp_is_cmd_q   <= 1'b0;
      km_rsp_len_q      <= '0;
      dma_copy_q        <= 1'b0;
      dma_hs_q          <= 1'b0;
      dma_hash_q        <= 1'b0;
      filt_win_valid_q  <= 1'b0;
      m_aw_out_q        <= '0;
      m_ar_out_q        <= '0;
      filt_start_entry_q <= 32'hFFFF_FFFF;
      filt_end_entry_q   <= 32'hFFFF_FFFF;
      filt_win_entry_q   <= 32'hFFFF_FFFF;
      lc_prev_valid_q   <= 1'b0;
      feat_lo_valid_q   <= 1'b0;
      prog_pending_q    <= 1'b0;
      wdt_bark_q        <= 1'b0;
      cold_valid_q      <= 1'b0;
      warm_written_q    <= 1'b0;
      // A cold reset ends the warm-reset window; the retention bins belong to
      // the warm pulse only.
      warm_reset_q      <= 1'b0;
      cpu_reset_n_q     <= 1'b1;
      cpu_reset_hi_q    <= 5'd0;
      fuse_sense_done_q <= 1'b0;
      esrc_seed_q       <= 1'b0;
      drbg_gen_q        <= 1'b0;
      fw_pass_q         <= 1'b0;
      spi_cs_n_q        <= 1'b1;
      spi_sck_q         <= 1'b0;
      irq_mailbox_q     <= 1'b0;
      irq_km_mbox_q     <= 1'b0;
      irq_dma_done_q    <= 1'b0;
    end else begin
      if (csr_write) begin
        csr_addr_q  <= aw_addr_q;
        csr_data_q  <= wr_data;
        // Whole-word writes only. A partial write defines just the strobed
        // bytes, so a readback compare on it would claim more than the write
        // established.
        csr_valid_q <= (wr_strb == 4'hF);
      end

      if (sram_write) begin
        sram_addr_q  <= aw_addr_q;
        sram_data_q  <= w_data_q;
        sram_valid_q <= (w_strb_q == 8'hFF);
      end

      // Latch every legal ENC/DEC configuration; the operation labels the cell,
      // so the round-trip's decrypt leg scores its own cross cell instead of
      // re-scoring the encrypt one.
      if (aes_ctrl_wr && (aes_op_w != 2'b00) && (aes_op_w != 2'b11)) begin
        aes_mode_q      <= aes_mode_w;
        aes_key_q       <= aes_key_w;
        aes_op_q        <= aes_op_w;
        aes_sideload_q  <= aes_sideload_w;
        aes_cfg_valid_q <= 1'b1;
        aes_out_valid_q <= 1'b0;
      end
      if (aes_out_valid) aes_out_valid_q <= 1'b1;
      // Retire the configuration with its cell: without this a later
      // DATA_OUT_0 read re-scores the stale mode/key/op.
      if (aes_cell_done) begin
        aes_out_valid_q <= 1'b0;
        aes_cfg_valid_q <= 1'b0;
      end

      if (hmac_cfg_wr) begin
        hmac_digest_q    <= hmac_digest_w;
        hmac_keylen_q    <= hmac_keylen_w;
        hmac_en_q        <= hmac_en_w;
        hmac_cfg_valid_q <= 1'b1;
        hmac_process_q   <= 1'b0;
      end
      if (hmac_process) hmac_process_q <= 1'b1;
      if (hmac_cell_done) hmac_process_q <= 1'b0;

      if (kmac_cfg_wr) begin
        kmac_en_q        <= kmac_en_w;
        kmac_mode_q      <= kmac_mode_w;
        kmac_str_q       <= kmac_str_w;
        kmac_sideload_q  <= kmac_sideload_w;
        kmac_cfg_valid_q <= 1'b1;
        kmac_process_q   <= 1'b0;
        // KEY_LEN is not invalidated here. Both drivers write KEY_LEN before
        // CFG_SHADOWED (CFG_REGWEN locks at Start), and the register keeps its
        // value across a CFG write.
      end
      if (kmac_keylen_wr) begin
        kmac_keylen_q       <= wr_data[2:0];
        kmac_keylen_valid_q <= 1'b1;
      end
      if (kmac_process) kmac_process_q <= 1'b1;
      if (kmac_cell_done) kmac_process_q <= 1'b0;

      if (otbn_execute) begin
        otbn_exec_q <= 1'b1;
        otbn_busy_q <= 1'b0;
        otbn_idle_q <= 1'b0;
      end
      if (otbn_status_busy && otbn_exec_q) otbn_busy_q <= 1'b1;
      if (otbn_status_idle && otbn_exec_q && otbn_busy_q) otbn_idle_q <= 1'b1;
      if (otbn_done) begin
        otbn_exec_q <= 1'b0;
        otbn_busy_q <= 1'b0;
        otbn_idle_q <= 1'b0;
      end

      if (abr_keygen) abr_keygen_q <= 1'b1;
      if (abr_done) abr_keygen_q <= 1'b0;

      // Each command pends on its CTRL write, arms on a subsequent VALID==0
      // read, and retires with its own completion. The arm is what stops a
      // dropped command from being credited by the previous operation's sticky
      // VALID: that stale VALID is non-zero, so it can never arm anything.
      if (abr_sign) begin
        abr_sign_q       <= 1'b1;
        abr_sign_armed_q <= 1'b0;
      end
      if (abr_sign_q && abr_status_clear) abr_sign_armed_q <= 1'b1;
      if (abr_sign_done) begin
        abr_sign_q       <= 1'b0;
        abr_sign_armed_q <= 1'b0;
      end
      if (abr_verify) begin
        abr_verify_q       <= 1'b1;
        abr_verify_armed_q <= 1'b0;
      end
      if (abr_verify_q && abr_status_clear) abr_verify_armed_q <= 1'b1;
      if (abr_verify_done) begin
        abr_verify_q       <= 1'b0;
        abr_verify_armed_q <= 1'b0;
      end

      if (kem_keygen) begin
        kem_keygen_q       <= 1'b1;
        kem_keygen_armed_q <= 1'b0;
      end
      if (kem_keygen_q && kem_status_clear) kem_keygen_armed_q <= 1'b1;
      if (kem_keygen_done) begin
        kem_keygen_q       <= 1'b0;
        kem_keygen_armed_q <= 1'b0;
      end
      if (kem_encaps) begin
        kem_encaps_q       <= 1'b1;
        kem_encaps_armed_q <= 1'b0;
      end
      if (kem_encaps_q && kem_status_clear) kem_encaps_armed_q <= 1'b1;
      if (kem_encaps_done) begin
        kem_encaps_q       <= 1'b0;
        kem_encaps_armed_q <= 1'b0;
      end
      if (kem_decaps) begin
        kem_decaps_q       <= 1'b1;
        kem_decaps_armed_q <= 1'b0;
      end
      if (kem_decaps_q && kem_status_clear) kem_decaps_armed_q <= 1'b1;
      if (kem_decaps_done) begin
        kem_decaps_q       <= 1'b0;
        kem_decaps_armed_q <= 1'b0;
      end

      // KM command frame: header, payload_len words, then the payload CRC word
      // when payload_len > 0.
      if (km_wr_data) begin
        if (km_cmd_hdr_next_q) begin
          km_cmd_len_q      <= wr_data[23:16];
          km_cmd_idx_q      <= 9'd0;
          km_cmd_hdr_next_q <= (wr_data[23:16] == 8'h00);
          km_rsp_idx_q      <= 9'd0;
          km_rsp_arm_q      <= 1'b1;
        end else begin
          km_cmd_idx_q      <= km_cmd_idx_q + 9'd1;
          // last word of the frame = payload_len + 1 (the CRC word)
          km_cmd_hdr_next_q <= ((km_cmd_idx_q + 9'd1) >= (9'(km_cmd_len_q) + 9'd1));
        end
      end

      // KM response frame: header, then payload [cmd_seq, cmd_id, rc, arg].
      // Index only while a response is pending. The mailbox tests also read
      // READ_DATA outside a frame (FIFO depth, flush), and an unindexed read
      // would shift a later word onto index 4 and false-hit cp_generate.
      if (km_rd_data && km_rsp_arm_q) begin
        km_rsp_idx_q <= km_rsp_idx_q + 9'd1;
        // The header carries the length, so it cannot itself be compared
        // against it: at index 0 the register still holds the PREVIOUS frame's
        // value, and a reset 0 would retire the frame on its own header.
        if (km_rsp_idx_q == 9'd0) begin
          km_rsp_is_cmd_q <= (rd_data[15:8] == KmRespCmd);
          km_rsp_len_q    <= rd_data[23:16];
        end else if (km_rsp_idx_q >= 9'(km_rsp_len_q)) begin
          km_rsp_arm_q <= 1'b0;
        end
        if (km_rsp_idx_q == 9'd2) km_rsp_cmd_q <= rd_data[7:0];
        if (km_rsp_idx_q == 9'd3) km_rsp_rc_q <= rd_data[7:0];
      end

      if (dma_copy_go) begin
        dma_copy_q <= 1'b1;
        dma_hash_q <= 1'b0;
      end
      if (dma_hash_go) begin
        dma_hash_q <= 1'b1;
        dma_copy_q <= 1'b0;
      end
      if (dma_go)
        dma_hs_q <= (wr_data & SECURE_DMA_CONTROL_HARDWARE_HANDSHAKE_ENABLE_MASK) != 32'h0;
      if (dma_complete) begin
        dma_copy_q <= 1'b0;
        dma_hash_q <= 1'b0;
      end

      if (filt_start_wr) begin
        filt_start_q       <= wr_data;
        filt_start_entry_q <= filt_entry_of(aw_addr_q);
      end
      if (filt_end_wr) begin
        filt_end_q       <= wr_data;
        filt_end_entry_q <= filt_entry_of(aw_addr_q);
      end
      if (filt_cfg_wr) begin
        if (((wr_data & FiltEnMask) != 32'h0) && (filt_start_entry_q == filt_entry_of(
                aw_addr_q
            )) && (filt_end_entry_q == filt_entry_of(
                aw_addr_q
            ))) begin
          filt_win_valid_q <= 1'b1;
          filt_win_entry_q <= filt_entry_of(aw_addr_q);
          filt_win_lo_q    <= filt_start_q;
          filt_win_hi_q    <= filt_end_q;
        end else if (((wr_data & FiltEnMask) == 32'h0) && (filt_win_entry_q == filt_entry_of(
                aw_addr_q
            ))) begin
          // disable_all() clears the entry the window came from.
          filt_win_valid_q <= 1'b0;
        end
      end
      if (m_aw_hs) m_aw_addr_q <= m_axi_awaddr_i[31:0];
      if (m_ar_hs) m_ar_addr_q <= m_axi_araddr_i[31:0];
      m_aw_out_q <= m_aw_out_q + (m_aw_hs ? 4'd1 : 4'd0) -
          ((m_axi_bvalid_i === 1'b1 && m_axi_bready_i === 1'b1) ? 4'd1 : 4'd0);
      m_ar_out_q <= m_ar_out_q + (m_ar_hs ? 4'd1 : 4'd0) -
          ((m_axi_rvalid_i === 1'b1 && m_axi_rready_i === 1'b1 &&
            m_axi_rlast_i === 1'b1) ? 4'd1 : 4'd0);

      if (efuse_prog_go && prog_is_spare) begin
        prog_spare_q   <= prog_spare_idx;
        prog_locked_q  <= spare_locked_q[prog_spare_idx];
        prog_pending_q <= 1'b1;
      end
      if (prog_pending_q && (efuse_prog_done || efuse_prog_err)) prog_pending_q <= 1'b0;

      if (feat_ctrl_lo_rd) begin
        feat_lo_q       <= rd_data;
        feat_lo_valid_q <= 1'b1;
      end
      if (feat_ctrl_hi_rd) feat_lo_valid_q <= 1'b0;

      if (lc_diff_ok) begin
        lc_prev_q       <= lc_raw;
        lc_prev_valid_q <= 1'b1;
      end
      // One-shot: the arm is consumed by the NMI it explains. The
      // reset_wdt_sanity firmware has ONE handler for a WDT bark and a D-bus
      // error NMI, so a sticky arm would let the other source score this bin.
      if (wdt_bark) wdt_bark_q <= 1'b1;
      else if (wdt_nmi) wdt_bark_q <= 1'b0;

      if (cold_write && (wr_strb == 4'hF)) begin
        cold_addr_q  <= aw_addr_q;
        cold_data_q  <= wr_data;
        cold_valid_q <= 1'b1;
      end
      if (warm_write) begin
        warm_addr_q    <= aw_addr_q;
        warm_written_q <= 1'b1;
      end
      if (warm_reset_fall) warm_reset_q <= 1'b1;

      cpu_reset_n_q  <= (cpu_reset_n_i === 1'b1);
      cpu_reset_hi_q <= (cpu_reset_n_i === 1'b1) ?
          ((cpu_reset_hi_q == 5'h1F) ? 5'h1F : cpu_reset_hi_q + 5'd1) : 5'd0;
      fuse_sense_done_q <= (fuse_sense_done_i === 1'b1);
      esrc_seed_q       <= (drbg_seed_valid_i === 1'b1);
      drbg_gen_q        <= (drbg_genbits_vld_i === 1'b1);
      fw_pass_q         <= (fw_done_i === 1'b1) && (fw_pass_i === 1'b1);
      spi_cs_n_q    <= (spi_cs_n_i !== 1'b0);
      spi_sck_q     <= (spi_sck_i === 1'b1);
      irq_mailbox_q <= mbox_any;
      irq_km_mbox_q <= (irq_km_mbox_i === 1'b1);
      irq_dma_done_q <= (irq_dma_done_i === 1'b1);
    end
  end

  // ------------------------------------------------------------------
  // Covergroups. The names are the contract: the URG Group report matches
  // instances by hierarchy name, so they stay stable.
  // ------------------------------------------------------------------
  covergroup sep_axi_decode_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_axi_decode_cg";
    cp_reset_value: coverpoint decode_reset_value {bins reset_value_decode = {1'b1};}
    cp_wr_rdback: coverpoint csr_readback {bins write_readback = {1'b1};}
    cp_resp_wr: coverpoint wr_ev {bins okay_write = {1'b1};}
    cp_resp_rd: coverpoint rd_ev {bins okay_read = {1'b1};}
  endgroup

  covergroup sep_sram_access_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_sram_access_cg";
    cp_write: coverpoint sram_write {bins write = {1'b1};}
    cp_match: coverpoint sram_readback {bins write_then_read = {1'b1};}
  endgroup

  covergroup sep_boot_rom_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_boot_rom_cg";
    cp_ifu: coverpoint rom_ifu {bins ifu_fetch = {1'b1};}
    cp_lsu: coverpoint rom_lsu {bins lsu_read = {1'b1};}
  endgroup

  covergroup sep_cpu_boot_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_cpu_boot_cg";
    cp_console: coverpoint cpu_console {bins console_byte = {1'b1};}
    cp_pass: coverpoint cpu_pass {bins fw_pass = {1'b1};}
    cp_pc: coverpoint cpu_pc {bins pc_nonzero = {1'b1};}
  endgroup

  covergroup sep_aes_mode_cg with function sample (
      logic [5:0] mode, logic [2:0] key, logic [1:0] op, logic sideload
  );
    option.per_instance = 1;
    option.name = "sep_aes_mode_cg";
    cp_mode: coverpoint mode {
      bins ecb = {AesModeEcb}; bins cbc = {AesModeCbc}; bins ctr = {AesModeCtr};
    }
    cp_key: coverpoint key {
      bins k128 = {AesKey128}; bins k192 = {AesKey192}; bins k256 = {AesKey256};
    }
    cp_op: coverpoint op {bins enc = {AesOpEnc}; bins dec = {AesOpDec};}
    // Key source: the KM sideload KATs configure SIDELOAD=1, the standalone
    // breadth test uses the KEY_SHARE CSRs.
    cp_sideload: coverpoint sideload {
      bins sw_key = {1'b0}; bins km_key = {1'b1};
    }
    // Each cross cell is one configured mode/key size/operation that reached
    // OUTPUT_VALID and returned a data word. The suite walks nine ENC cells
    // plus the ECB/CBC decrypt legs of the round-trip.
    //
    // CTR x DECRYPT is excluded because the cell has nothing to score, not
    // because no test happens to drive it. CTR is a stream mode: the engine
    // runs the forward cipher whichever way OPERATION is programmed, so
    // decryption is the same operation as encryption and re-encrypting the
    // ciphertext is what recovers the plaintext. A test that programmed
    // DECRYPT here would pass with the OPERATION field disconnected. Filling
    // this cell would record configuration, not consume.
    //
    // The scoreable neighbour is OPERATION's shadowed-register behaviour --
    // one-hot readback and the update/storage-error alerts -- which is
    // mode-independent and belongs on a CSR vehicle, not on a CTR cipher cell.
    x_mode_key_op: cross cp_mode, cp_key, cp_op{
      ignore_bins ctr_decrypt = binsof (cp_mode.ctr) && binsof (cp_op.dec);
    }
  endgroup

  covergroup sep_hmac_mode_cg with function sample (
      logic [3:0] digest, logic [5:0] key_length, logic keyed
  );
    option.per_instance = 1;
    option.name = "sep_hmac_mode_cg";
    cp_digest: coverpoint digest {
      bins sha2_256 = {HmacSha256}; bins sha2_384 = {HmacSha384}; bins sha2_512 = {HmacSha512};
    }
    cp_key_length: coverpoint key_length iff (keyed) {
      bins k128 = {HmacKey128};
      bins k256 = {HmacKey256};
      bins k384 = {HmacKey384};
      bins k512 = {HmacKey512};
      bins k1024 = {HmacKey1024};
    }
    cp_plain: coverpoint digest iff (!keyed) {
      bins sha2_256 = {HmacSha256}; bins sha2_384 = {HmacSha384}; bins sha2_512 = {HmacSha512};
    }
    // SHA-256 with a 1024-bit key is illegal (hmac.sv), so the suite walks
    // fourteen of the fifteen keyed cells; the excluded one is named in the
    // plan rather than binned here.
    x_digest_key: cross cp_digest, cp_key_length{
      ignore_bins illegal_256_1024 = binsof (cp_digest.sha2_256) && binsof (cp_key_length.k1024);
    }
  endgroup

  covergroup sep_kmac_mode_cg with function sample (
      logic en, logic [1:0] mode, logic [2:0] strength, logic [2:0] key_length, logic sideload
  );
    option.per_instance = 1;
    option.name = "sep_kmac_mode_cg";
    cp_sha3: coverpoint strength iff (!en && (mode == KmacSha3)) {
      bins s224 = {KmacL224};
      bins s256 = {KmacL256};
      bins s384 = {KmacL384};
      bins s512 = {KmacL512};
    }
    cp_shake: coverpoint strength iff (!en && (mode == KmacShake)) {
      bins s128 = {KmacL128}; bins s256 = {KmacL256};
    }
    cp_cshake: coverpoint strength iff (!en && (mode == KmacCshake)) {
      bins s128 = {KmacL128}; bins s256 = {KmacL256};
    }
    // KMAC is mode cSHAKE with kmac_en=1 (kmac programmers_guide).
    cp_kmac: coverpoint strength iff (en && (mode == KmacCshake)) {
      bins s128 = {KmacL128}; bins s256 = {KmacL256};
    }
    // Key source, the same contract as the AES cell: the KM KMAC sideload KAT
    // sets CFG.sideload, the standalone breadth test uses the KEY_SHARE CSRs.
    cp_sideload: coverpoint sideload iff (en) {
      bins sw_key = {1'b0}; bins km_key = {1'b1};
    }
    cp_kmac_key_length: coverpoint key_length iff (en) {
      bins k128 = {KmacKey128};
      bins k192 = {KmacKey192};
      bins k256 = {KmacKey256};
      bins k384 = {KmacKey384};
      bins k512 = {KmacKey512};
    }
  endgroup

  covergroup sep_otbn_execute_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_otbn_execute_cg";
    cp_cmd: coverpoint otbn_execute {bins execute = {1'b1};}
    cp_done: coverpoint otbn_done {bins idle_err_bits_zero = {1'b1};}
  endgroup

  covergroup sep_abr_keygen_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_abr_keygen_cg";
    cp_op: coverpoint abr_keygen {bins mldsa_keygen = {1'b1};}
    cp_done: coverpoint abr_done {bins status_valid = {1'b1};}
  endgroup

  // verilog_format: off  // verible splits the concatenated coverpoint
  // expressions across lines and then packs the bins onto one line, which
  // makes the per-operation bins harder to read than the one-bin-per-line
  // form below. Formatting is off for the two covergroups that concatenate
  // their operation strobes; everything else in this file is verible-formatted.
  covergroup sep_abr_sign_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_abr_sign_cg";
    cp_op: coverpoint {abr_verify, abr_sign} {
      bins mldsa_sign = {2'b01};
      bins mldsa_verify = {2'b10};
    }
    // One coverpoint per command, not a concatenation. The two pending flags
    // are independent and each is cleared only by its own completion, so a
    // signature that never reaches VALID leaves its flag set; a later verify
    // that does complete would then present both _done bits at once and a
    // concatenated coverpoint would land in no bin, losing a completion that
    // really happened.
    cp_sign_done: coverpoint abr_sign_done {bins sign_status_valid = {1'b1};}
    cp_verify_done: coverpoint abr_verify_done {bins verify_status_valid = {1'b1};}
  endgroup

  covergroup sep_abr_mlkem_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_abr_mlkem_cg";
    cp_op: coverpoint {kem_decaps, kem_encaps, kem_keygen} {
      bins mlkem_keygen = {3'b001};
      bins mlkem_encaps = {3'b010};
      bins mlkem_decaps = {3'b100};
    }
    // Independent coverpoints for the same reason as sep_abr_sign_cg: a command
    // that never completes holds its pending flag, and a concatenation would
    // then drop a later command's genuine completion into no bin.
    cp_keygen_done: coverpoint kem_keygen_done {bins keygen_status_valid = {1'b1};}
    cp_encaps_done: coverpoint kem_encaps_done {bins encaps_status_valid = {1'b1};}
    cp_decaps_done: coverpoint kem_decaps_done {bins decaps_status_valid = {1'b1};}
  endgroup
  // verilog_format: on

  covergroup sep_esrc_edn_flow_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_esrc_edn_flow_cg";
    cp_seed: coverpoint esrc_seed {bins seed_ready = {1'b1};}
    cp_gen: coverpoint drbg_gen {bins genbits_valid = {1'b1};}
    cp_crypto: coverpoint edn_crypto_beat {bins crypto_sink = {1'b1};}
    cp_km: coverpoint edn_km_beat {bins km_sink = {1'b1};}
    // Which adapter client took the grant. cp_crypto above scores the shared
    // AXIS stream and is hit by any sink, so it cannot show that a given
    // client was ever served. All four clients have a producer.
    // One coverpoint per client rather than one-hot bins on the 4-bit vector.
    // The acks are per-endpoint state machines, not arbiter grants, so two can
    // assert in the same cycle; a one-hot coverpoint would land in no bin and
    // lose BOTH grants, which reads afterwards as a client the test never
    // drove. This is the leaf that must fill all four, and simultaneous acks
    // are likeliest exactly here.
    cp_edn_aes: coverpoint crypto_edn_ack_i[0] iff (!in_reset) {
      bins aes = {1'b1};
    }
    cp_edn_kmac: coverpoint crypto_edn_ack_i[1] iff (!in_reset) {bins kmac = {1'b1};}
    cp_edn_otbn_rnd: coverpoint crypto_edn_ack_i[2] iff (!in_reset) {bins otbn_rnd = {1'b1};}
    cp_edn_otbn_urnd: coverpoint crypto_edn_ack_i[3] iff (!in_reset) {bins otbn_urnd = {1'b1};}
  endgroup

  covergroup sep_km_command_sideload_cg with function sample (logic [7:0] dest);
    option.per_instance = 1;
    option.name = "sep_km_command_sideload_cg";
    // One cell per consumer, taken from RETURN_ARG dest_engine on rc 0. All
    // eight destinations the KM firmware decodes have a cell: the four classic
    // engines, the ABR ML-DSA seed, and the three ML-KEM sideload blocks.
    cp_dest: coverpoint dest {
      bins hmac = {KmDestHmac};
      bins kmac = {KmDestKmac};
      bins aes = {KmDestAes};
      bins otbn = {KmDestOtbn};
      bins abr_mldsa_seed = {KmDestAbrMldsaSeed};
      bins abr_mlkem_seed_d = {KmDestAbrMlkemSeedD};
      bins abr_mlkem_seed_z = {KmDestAbrMlkemSeedZ};
      bins abr_mlkem_msg = {KmDestAbrMlkemMsg};
    }
  endgroup

  covergroup sep_km_host_cmd_cg with function sample (logic [7:0] cmd_id);
    option.per_instance = 1;
    option.name = "sep_km_host_cmd_cg";
    cp_cmd: coverpoint cmd_id {
      bins hw_ver = {KmCmdHwVer};
      bins rom_ver = {KmCmdRomVer};
      bins sram_ver = {KmCmdSramVer};
      bins recov_ack = {KmCmdRecovAck};
      bins exec_rom = {KmCmdExecRom};
      bins sram_load_exec = {KmCmdSramLoadExec};
      bins sram_exec = {KmCmdSramExec};
      bins otp_lock = {KmCmdOtpLock};
    }
  endgroup

  covergroup sep_km_wipe_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_km_wipe_cg";
    cp_wipe: coverpoint km_wipe {bins wipe_state = {1'b1};}
  endgroup

  covergroup sep_km_sw_reset_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_km_sw_reset_cg";
    cp_rel: coverpoint km_swrst_rel {bins km_released = {1'b1};}
  endgroup

  // --- crypto isolate sequencing -----------------------------------------
  // Registered copies so an edge can be named. The reset is active-low, so a
  // fall is the domain going INTO reset.
  // Tracks the live inputs during reset rather than holding constants. Cold
  // reset already presents the isolated, domain-in-reset state -- the isolate
  // FSMs reset to Isolate and the gated domain reset is low -- so seeding these
  // to 1/0 would manufacture both edges below on the first clock of every run,
  // in every test, whether or not anything sequenced an isolate.
  logic hmac_rst_n_q, hmac_km_iso_q;
  logic abr_rst_n_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      hmac_rst_n_q  <= hmac_gated_rst_n_i;
      hmac_km_iso_q <= hmac_km_isolated_i;
      abr_rst_n_q   <= abr_gated_rst_n_i;
    end else begin
      hmac_rst_n_q  <= hmac_gated_rst_n_i;
      hmac_km_iso_q <= hmac_km_isolated_i;
      abr_rst_n_q   <= abr_gated_rst_n_i;
    end
  end

  // The cycle the HMAC domain enters reset. Sampling the state instead would
  // bin a steady condition that holds for the whole window, and both isolate
  // bits are high throughout it -- so the ordering bin would fill whatever the
  // sequencer did. Every edge is additionally qualified on being out of reset:
  // the cold-reset window presents the same levels a real isolate does, and an
  // edge derived from it says nothing about the sequencer.
  wire hmac_rst_fall   = !in_reset && hmac_rst_n_q && !hmac_gated_rst_n_i;
  wire hmac_km_iso_rise = !in_reset && !hmac_km_iso_q && hmac_km_isolated_i;
  wire hmac_km_iso_fall = !in_reset && hmac_km_iso_q && !hmac_km_isolated_i;
  wire hmac_rst_ordered = hmac_rst_fall && hmac_host_isolated_i && hmac_km_isolated_i;
  wire abr_rst_fall    = !in_reset && abr_rst_n_q && !abr_gated_rst_n_i;
  wire abr_rst_ordered = abr_rst_fall && abr_host_isolated_i && abr_km_isolated_i;

  covergroup sep_crypto_isolate_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_crypto_isolate_cg";
    cp_km_iso: coverpoint hmac_km_iso_rise {bins km_path_isolated = {1'b1};}
    cp_rst_ordered: coverpoint hmac_rst_ordered {bins reset_after_both_isolated = {1'b1};}
    cp_reopen: coverpoint hmac_km_iso_fall {bins km_path_reopened = {1'b1};}
    cp_abr_rst_ordered: coverpoint abr_rst_ordered {bins reset_after_both_isolated = {1'b1};}
  endgroup

  covergroup sep_km_generate_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_km_generate_cg";
    cp_generate: coverpoint km_generate_ok {bins rc0_nonnull_handle = {1'b1};}
  endgroup

  covergroup sep_dma_copy_hash_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_dma_copy_hash_cg";
    cp_copy: coverpoint dma_copy_go {bins copy_go = {1'b1};}
    cp_hash: coverpoint dma_hash_go {bins hash_go = {1'b1};}
    // Completion is STATUS.done OR the DMA-done interrupt: the two routes the
    // suite's firmware actually takes.
    cp_copy_done: coverpoint dma_copy_done {
      bins copy_done = {1'b1};
    }
    cp_hash_done: coverpoint dma_hash_done {bins hash_done = {1'b1};}
    // The multi-chunk path, which the single copy/hash bins hide.
    cp_chunk: coverpoint dma_chunk_done {
      bins chunk_done = {1'b1};
    }
    cp_rego: coverpoint dma_rego_non_initial {bins rego_not_initial = {1'b1};}
    // Which inline-hash opcode was commanded. cp_hash above is SHA-256 only,
    // so it does not distinguish a SHA-384 transfer. SHA-512 is a legal opcode
    // with no leaf that commands it, so it has no bin rather than a permanent
    // hole.
    // verilog_format: off  // verible packs these two bins onto one line.
    cp_hash_opcode: coverpoint dma_opcode_w iff (dma_hash_any_go) {
      bins sha256 = {DmaOpSha256};
      bins sha384 = {DmaOpSha384};
    }
    // verilog_format: on
  endgroup

  covergroup sep_dma_completion_route_cg with function sample (logic irq_route, logic handshake);
    option.per_instance = 1;
    option.name = "sep_dma_completion_route_cg";
    // The DMA reports completion two ways and the suite walks both:
    // dma_basic_test polls STATUS.done, dma_hash_test takes the DMA_DONE
    // interrupt whose handler clears STATUS.done before software reads it.
    // Recording only "completed" would hide which route the transfer took.
    cp_route: coverpoint irq_route {
      bins status_poll = {1'b0}; bins interrupt = {1'b1};
    }
    cp_mode: coverpoint handshake {bins normal = {1'b0}; bins handshake = {1'b1};}
    // The handshake leaves (SPI DMA firmware) do not complete through the
    // DMA-done ISR, so that cell has no producer and is ignored rather than
    // left as a permanent hole.
    x_route_mode: cross cp_route, cp_mode{
      ignore_bins irq_handshake = binsof (cp_route.interrupt) && binsof (cp_mode.handshake);
    }
  endgroup

  covergroup sep_spi_flash_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_spi_flash_cg";
    cp_csr: coverpoint spi_csr {bins csr_access = {1'b1};}
    cp_frame: coverpoint spi_cs_assert {bins cs_assert = {1'b1};}
    cp_sck: coverpoint spi_sck_edge {bins shift_in_frame = {1'b1};}
    cp_hs: coverpoint dma_hs_go {bins dma_handshake = {1'b1};}
  endgroup

  covergroup sep_inbound_filter_allow_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_inbound_filter_allow_cg";
    cp_allow_wr: coverpoint filt_allow_wr {bins write_okay_in_window = {1'b1};}
    cp_allow_rd: coverpoint filt_allow_rd {bins read_okay_in_window = {1'b1};}
  endgroup

  covergroup sep_efuse_sense_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_efuse_sense_cg";
    cp_done: coverpoint fuse_sense {bins sense_done = {1'b1};}
    // First sense after cold-reset release vs a later re-sense: programming a
    // fuse and re-sensing is a distinct episode. Producers are
    // sep_efuse_otp_program_seq and sep_lcc_demote_matrix_seq; the scratch
    // leaf cannot, because it passes +skip_fuse_sense, which disqualifies the
    // sense bin above.
    cp_episode: coverpoint fuse_sense_episode iff (fuse_sense) {
      bins first_sense = {1'b0}; bins re_sense = {1'b1};
    }
  endgroup

  covergroup sep_efuse_program_lock_cg with function sample (
      logic [SpareIdxW-1:0] spare, logic locked, logic rejected
  );
    option.per_instance = 1;
    option.name = "sep_efuse_program_lock_cg";
    cp_field: coverpoint spare {bins spare[] = {[0 : SpareCount - 1]};}
    cp_lock: coverpoint locked {bins unlocked = {1'b0}; bins locked = {1'b1};}
    // 18 cells, all walked by one seed: the owning test programs then locks
    // then re-programs each of the nine spares in order.
    x_field_lock: cross cp_field, cp_lock;
    // The outcome is its own coverpoint, not a third cross dimension: crossing
    // it would declare 18 cells that only a broken DUT could fill, and the
    // program/reject contract belongs to the test's checker.
    cp_outcome: coverpoint rejected {
      bins programmed = {1'b0}; bins refused = {1'b1};
    }
  endgroup

  covergroup sep_efuse_fail_closed_cg with function sample (logic [1:0] state, logic is_program);
    option.per_instance = 1;
    option.name = "sep_efuse_fail_closed_cg";
    // The two illegal encodings are separate cells on purpose: they fail the
    // legal-set test for different reasons, so a recovery written as a compare
    // against one value would fill one cell and leave the other dead.
    cp_illegal: coverpoint state {
      bins zero = {2'b00}; bins ones = {2'b11};
    }
    // `program` is a SystemVerilog keyword, so the bin is named for the block.
    cp_fsm: coverpoint is_program {
      bins read_if = {1'b0}; bins program_if = {1'b1};
    }
    // Four cells, all filled by one seed: the owning leaf walks the product.
    x_fsm_illegal: cross cp_fsm, cp_illegal;
  endgroup

  covergroup sep_lc_state_cg with function sample (logic [3:0] raw);
    option.per_instance = 1;
    option.name = "sep_lc_state_cg";
    // Named legal encodings only (efuse_pkg::lc_state_raw_e). An illegal or
    // half-sensed code lands in no bin.
    cp_lc: coverpoint raw {
      bins test_dev = {LcTestDev};
      bins prod = {LcProd};
      bins rma_sip_0 = {LcRmaSip0};
      bins rma_sip_1 = {LcRmaSip1};
      bins rma_chip_0 = {LcRmaChip0};
      bins rma_chip_1 = {LcRmaChip1};
      bins prod_end = {LcProdEnd};
    }
  endgroup

  covergroup sep_lc_transition_cg with function sample (logic [3:0] from, logic [3:0] to);
    option.per_instance = 1;
    option.name = "sep_lc_transition_cg";
    // ONE coverpoint over the packed {from,to} pair rather than a cross of two
    // 7-bin coverpoints: a cross auto-generates the full 7x7 product and the
    // named bins do not suppress it.
    //
    // A pair is two LC_STATE reads in the same leaf. sep_lc_shadow_write_seq
    // reads ONCE per cell, after its write, so the pair is two consecutive
    // cells of one leaf; the sep_lcc_lc_state_w1s_* leaves are the sources. The
    // stitch test cannot produce a pair: it re-senses between states, and a
    // re-sense pulses reset, which clears lc_prev_valid_q.
    // TEST_DEV->PROD_END and TEST_DEV->RMA_SIP have no walk (those leaves start
    // sensed in the destination), and PROD->PROD_END is impossible under
    // write-1-to-set: 0x1 | 0x8 is 0x9.
    // Two bins. A pair needs two LC_STATE reads inside ONE leaf, and the
    // +lc_start leaves are sensed at PROD, RMA_SIP_0, RMA_CHIP_0 or PROD_END
    // -- none at TEST_DEV -- so TEST_DEV to PROD has no producer. The
    // PROD_END/transient leaf advances 0x8 to 0xA, which is not a named pair,
    // so it produces nothing here either.
    cp_transition: coverpoint {
      from, to
    } {
      bins prod_to_rma_sip = {{LcProd, LcRmaSip1}};
      bins rma_sip_to_chiplet = {{LcRmaSip1, LcRmaChip1}};
    }
  endgroup

  covergroup sep_feat_ctrl_cg with function sample (
      logic [3:0] lc, logic [1:0] dbg, logic sec_dis, logic secure_tm
  );
    option.per_instance = 1;
    option.name = "sep_feat_ctrl_cg";
    cp_state: coverpoint lc {
      bins test_dev = {LcTestDev};
      bins prod = {LcProd};
      bins rma_sip_0 = {LcRmaSip0};
      bins rma_sip_1 = {LcRmaSip1};
      bins rma_chip_0 = {LcRmaChip0};
      bins rma_chip_1 = {LcRmaChip1};
      bins prod_end = {LcProdEnd};
    }
    cp_debug: coverpoint dbg {bins none = {2'd0}; bins partial = {2'd1}; bins full = {2'd2};}
    // No state x debug cross: the decode fixes one legal profile per lifecycle
    // state (plus the SEC_DIS all-ones override), so most of the 21 products
    // are illegal and would be permanent holes. Stating which are legal means
    // restating sep_lcc_golden.feat_ctrl_expected, which is the checker's job,
    // not coverage's. cp_state and cp_debug carry the axes on their own.
    // SEC_DIS forces FEAT_CTRL to all-ones, so it is crossed with the profile.
    cp_sec_dis: coverpoint sec_dis {
      bins off = {1'b0}; bins on = {1'b1};
    }
    // SEC_DIS forces FEAT_CTRL to all-ones, so `on` can only ever pair with
    // `full`; the other two products are illegal.
    x_sec_dis_debug: cross cp_sec_dis, cp_debug{
      ignore_bins sec_dis_not_full = binsof(cp_sec_dis.on) &&
          (binsof(cp_debug.none) || binsof(cp_debug.partial));
    }
    // SECURE_TM does NOT qualify feature control in this layout
    // (env/sep_lcc_golden.py), so it is recorded on its own rather than
    // crossed: the stitch test drives the strap both ways.
    cp_secure_tm: coverpoint secure_tm {
      bins off = {1'b0}; bins on = {1'b1};
    }
  endgroup

  // Sampled on the window edges, not on a held level. The map coverpoint
  // records the LC_STATE read response while sensing is still open.
  // reach records an OKAY SW_RESET_N read in that window.
  covergroup sep_sec_dis_boot_cg with function sample (
      logic hold,
      logic released,
      logic rehold,
      logic sec_dis,
      logic [1:0] map_resp,
      logic map_hit,
      logic reach
  );
    option.per_instance = 1;
    option.name = "sep_sec_dis_boot_cg";
    cp_hold: coverpoint hold {bins match_holds_reset = {1'b1};}
    cp_release: coverpoint released {bins override_releases = {1'b1};}
    cp_rehold: coverpoint rehold {bins override_reholds = {1'b1};}
    // The override sampled while SEC_DIS is still off: feature control stays closed.
    cp_alone: coverpoint sec_dis iff (released) {
      bins override_closed = {1'b0};
    }
    cp_map_resp: coverpoint map_resp iff (map_hit) {bins okay = {AxiOkay}; bins slverr = {2'b10};}
    cp_reach: coverpoint reach {bins sw_reset_n_while_open = {1'b1};}
  endgroup

  covergroup sep_lc_demote_cg with function sample (logic [3:0] lc, logic d1, logic d2);
    option.per_instance = 1;
    option.name = "sep_lc_demote_cg";
    // Demotion is volatile PROD debug state, so the state is recorded on its
    // own and only the demote pair is crossed: crossing all seven states would
    // declare 28 cells for a walk that only exercises the PROD rows.
    cp_state: coverpoint lc {
      bins test_dev = {LcTestDev};
      bins prod = {LcProd};
      bins prod_end = {LcProdEnd};
      bins rma = {LcRmaSip0, LcRmaSip1, LcRmaChip0, LcRmaChip1};
    }
    cp_demote_1: coverpoint d1 {bins clear = {1'b0}; bins set = {1'b1};}
    cp_demote_2: coverpoint d2 {bins clear = {1'b0}; bins set = {1'b1};}
    x_demote: cross cp_demote_1, cp_demote_2;
  endgroup

  covergroup sep_mailbox_pic_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_mailbox_pic_cg";
    // SEP AXI mailbox sources, sep_internal_interrupts[7:0].
    // Owner: sep_axil_mailbox_iface_rand_test, sep_mailbox_plic_test.
    cp_raise: coverpoint mbox_raise {
      bins raise = {1'b1};
    }
    cp_clear: coverpoint mbox_clear {bins clear = {1'b1};}
    // KM mailbox, sep_internal_interrupts[14]. A different source with a
    // different owner (sep_km_mailbox_protocol_rand_test), so it is its own
    // pair rather than folded into the bins above.
    cp_km_raise: coverpoint km_mbox_raise {
      bins km_raise = {1'b1};
    }
    cp_km_clear: coverpoint km_mbox_clear {bins km_clear = {1'b1};}
    // The receive direction. Owner: sep_mailbox_peer_rx_rirqt_test, the only
    // leaf that drives the peer aperture; every other mailbox leaf is transmit
    // side and cannot fill this.
    cp_peer_fill: coverpoint m_mbox_peer_wr {
      bins peer_write = {1'b1};
    }
  endgroup

  covergroup sep_wdt_bark_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_wdt_bark_cg";
    cp_thold: coverpoint wdt_thold_wr {bins bark_thold_write = {1'b1};}
    cp_bark: coverpoint wdt_bark {bins bark_status = {1'b1};}
    cp_nmi: coverpoint wdt_nmi {bins nmi_after_bark = {1'b1};}
  endgroup

  covergroup sep_scratch_reset_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_scratch_reset_cg";
    cp_warm_wr: coverpoint warm_write {bins warm_write = {1'b1};}
    cp_cold_wr: coverpoint cold_write {bins cold_write = {1'b1};}
    cp_warm_rst: coverpoint warm_reset_fall {bins warm_reset = {1'b1};}
    cp_warm_rd: coverpoint warm_zero_after_reset {bins warm_zero_after_reset = {1'b1};}
    cp_cold_rd: coverpoint cold_kept_after_reset {bins cold_kept_after_reset = {1'b1};}
  endgroup

  sep_axi_decode_cg           u_sep_axi_decode_cg           = new();
  sep_sram_access_cg          u_sep_sram_access_cg          = new();
  sep_boot_rom_cg             u_sep_boot_rom_cg             = new();
  sep_cpu_boot_cg             u_sep_cpu_boot_cg             = new();
  sep_aes_mode_cg             u_sep_aes_mode_cg             = new();
  sep_hmac_mode_cg            u_sep_hmac_mode_cg            = new();
  sep_kmac_mode_cg            u_sep_kmac_mode_cg            = new();
  sep_otbn_execute_cg         u_sep_otbn_execute_cg         = new();
  sep_abr_keygen_cg           u_sep_abr_keygen_cg           = new();
  sep_abr_sign_cg             u_sep_abr_sign_cg             = new();
  sep_abr_mlkem_cg            u_sep_abr_mlkem_cg            = new();
  sep_esrc_edn_flow_cg        u_sep_esrc_edn_flow_cg        = new();
  sep_km_command_sideload_cg  u_sep_km_command_sideload_cg  = new();
  sep_km_host_cmd_cg          u_sep_km_host_cmd_cg          = new();
  sep_km_wipe_cg              u_sep_km_wipe_cg              = new();
  sep_km_sw_reset_cg          u_sep_km_sw_reset_cg          = new();
  sep_crypto_isolate_cg       u_sep_crypto_isolate_cg       = new();
  sep_km_generate_cg          u_sep_km_generate_cg          = new();
  sep_dma_copy_hash_cg        u_sep_dma_copy_hash_cg        = new();
  sep_spi_flash_cg            u_sep_spi_flash_cg            = new();
  sep_inbound_filter_allow_cg u_sep_inbound_filter_allow_cg = new();
  sep_efuse_sense_cg          u_sep_efuse_sense_cg          = new();
  sep_efuse_program_lock_cg   u_sep_efuse_program_lock_cg   = new();
  sep_efuse_fail_closed_cg    u_sep_efuse_fail_closed_cg    = new();
  sep_lc_state_cg             u_sep_lc_state_cg             = new();
  sep_lc_transition_cg        u_sep_lc_transition_cg        = new();
  sep_dma_completion_route_cg u_sep_dma_completion_route_cg = new();
  sep_feat_ctrl_cg            u_sep_feat_ctrl_cg            = new();
  sep_sec_dis_boot_cg         u_sep_sec_dis_boot_cg         = new();
  sep_lc_demote_cg            u_sep_lc_demote_cg            = new();
  sep_mailbox_pic_cg          u_sep_mailbox_pic_cg          = new();
  sep_wdt_bark_cg             u_sep_wdt_bark_cg             = new();
  sep_scratch_reset_cg        u_sep_scratch_reset_cg        = new();

  // Event-sampled groups: sample only on the completing event, so a cell
  // records one completed operation rather than one clock of a held state.
  always_ff @(posedge clk_i) begin
    if (!in_reset) begin
      if (aes_cell_done) u_sep_aes_mode_cg.sample(aes_mode_q, aes_key_q, aes_op_q, aes_sideload_q);
      if (hmac_cell_done) u_sep_hmac_mode_cg.sample(hmac_digest_q, hmac_keylen_q, hmac_en_q);
      if (kmac_cell_done)
        u_sep_kmac_mode_cg.sample(kmac_en_q, kmac_mode_q, kmac_str_q,
                                  kmac_keylen_valid_q ? kmac_keylen_q : 3'd7, kmac_sideload_q);
      if (km_xfer_scored) u_sep_km_command_sideload_cg.sample(rd_data[15:8]);
      if (km_host_cmd_seen) u_sep_km_host_cmd_cg.sample(km_rsp_cmd_q);
      if (efuse_rd_illegal) u_sep_efuse_fail_closed_cg.sample(efuse_read_state_i, 1'b0);
      if (efuse_pg_illegal) u_sep_efuse_fail_closed_cg.sample(efuse_program_state_i, 1'b1);
      if (lc_diff_ok) u_sep_lc_state_cg.sample(lc_raw);
      if (lc_transition) u_sep_lc_transition_cg.sample(lc_prev_q, lc_raw);
      // Sampled when the second FEAT_CTRL half completes, against the SENSED
      // lifecycle state and the live override/demote probes.
      if (feat_ctrl_hi_rd) begin
        u_sep_feat_ctrl_cg.sample(lc_sensed, feat_dbg_class, (sec_dis_i === 1'b1),
                                  (secure_tm_i === 1'b1));
        u_sep_lc_demote_cg.sample(lc_sensed, demote_1_set, demote_2_set);
      end
      if (sec_dis_hold_ev || sec_dis_release_ev || sec_dis_rehold_ev || sec_dis_map_rd ||
          sec_dis_reach_rd) begin
        u_sep_sec_dis_boot_cg.sample(sec_dis_hold_ev, sec_dis_release_ev, sec_dis_rehold_ev,
                                     sec_dis_on, lsu_r_resp_i, sec_dis_map_rd, sec_dis_reach_rd);
      end
      if (dma_copy_done || dma_hash_done) begin
        u_sep_dma_completion_route_cg.sample(dma_irq_done, dma_hs_q);
      end
      // Sampled at the outcome, so the cell records a completed program
      // attempt rather than the request.
      if (prog_pending_q && (efuse_prog_done || efuse_prog_err)) begin
        u_sep_efuse_program_lock_cg.sample(prog_spare_q, prog_locked_q, efuse_prog_err);
      end
    end
  end

endmodule : sep_fcov

`endif

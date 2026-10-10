// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OSS functional-coverage sampler (docs/SEP_FCOV.adoc). SystemVerilog
// covergroups only, compiled where VERILATOR is not defined.
//
// One passive instance in tb_top (`u_sep_fcov`). It drives nothing.
//
// ATTACH. The CSR side is the post-remap CPU-LSU AXI bus that tb_top already
// mirrors to its flat `s_axi_*` ports and force-splices on the no-CPU builds.
// Sampling that bus (not the flat ports) is what makes a bin reachable in BOTH
// run modes: under `+cpu_boot` the EL2 owns the bus and the flat request ports
// are idle, so a port-side sampler would see no firmware traffic at all. The
// external inbound master is the real `m_axi_*` DUT port. Everything else is a
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
  input wire [2:0]  lsu_ar_size_i,
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
  input wire        sep_reset_n_i,        // sep_reset_n, the SEP subsystem reset
  input wire        spi_cs_n_i,
  input wire        spi_sck_i,
  input wire        spi_mosi_i,           // sd[0], the host's serial output
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
  // The HMAC sequencer's own isolate request. The KM-path isolate is also
  // raised by a Key Manager reset (sep_reset_ctrl.sv: km_hmac = hmac | km), so
  // this request is what ties a KM-path edge to an HMAC isolate.
  input wire        hmac_host_isolate_req_i,
  // The same four for the Adams Bridge domain. Its host path is a full-AXI
  // isolate and its Key Manager path is shared with the KM domain.
  input wire        abr_gated_rst_n_i,
  input wire        abr_host_isolated_i,
  input wire        abr_km_isolated_i,
  input wire        abr_host_isolate_req_i,

  // WDT bark interrupt, which is the CPU NMI input (sep.sv nmi_int_i).
  input wire        wdt_bark_irq_i,

  // ---------------------------------------------------------------------
  // Phase 2 fabric and remap taps (docs/SEP_FCOV.adoc, fabric and remap
  // groups, Sampler taps). Read-only copies of DUT nets.
  // ---------------------------------------------------------------------
  // in_req / in_resp: the SMN-inbound port (System Interface).
  input sep_pkg::sep_system_peripherals_internal_axi_req_t  in_req_i,
  input sep_pkg::sep_system_peripherals_internal_axi_resp_t in_resp_i,
  // xbar_ext_req: the local crossbar `ext` initiator (PR-XEXT).
  input sep_pkg::sep_32_64_3_12_axi_req_t  xbar_req_i,
  input sep_pkg::sep_32_64_3_12_axi_resp_t xbar_resp_i,
  // sys_csr_req: the system-CSR AXI-Lite handshakes (PR-CSR).
  input wire        sys_csr_arvalid_i,
  input wire        sys_csr_arready_i,
  input wire        sys_csr_awvalid_i,
  input wire        sys_csr_awready_i,
  // lsu_req / lsu_resp after the CPU alias remap, and lsu_req_raw before it
  // (real CPU only; lsu_raw_live_i is 0 on the CPU-stub build).
  input sep_pkg::sep_32_64_3_12_axi_req_t  lsu_req_i,
  input sep_pkg::sep_32_64_3_12_axi_resp_t lsu_resp_i,
  input sep_pkg::sep_32_64_3_12_axi_req_t  lsu_raw_req_i,
  input wire        lsu_raw_live_i,
  // alias_out: input and output of u_local_master_remap_wrap (PR-ALIAS).
  input sep_pkg::sep_system_peripherals_internal_axi_req_t  alias_in_req_i,
  input sep_pkg::sep_system_peripherals_internal_axi_resp_t alias_in_resp_i,
  input sep_pkg::sep_system_peripherals_internal_axi_req_t  alias_out_req_i,
  // The route demux input (after the alias remap and its cut) and its select.
  input sep_pkg::sep_system_peripherals_internal_axi_req_t  route_req_i,
  input sep_pkg::sep_system_peripherals_internal_axi_resp_t route_resp_i,
  input wire [2:0]  route_sel_aw_i,
  input wire [2:0]  route_sel_ar_i,
  // pre_out_filter: the outbound filter input. out_req: the outbound port (PR-OUT).
  input sep_pkg::sep_system_peripherals_outbound_axi_req_t  pre_out_req_i,
  input sep_pkg::sep_system_peripherals_outbound_axi_resp_t pre_out_resp_i,
  input sep_pkg::sep_system_peripherals_outbound_axi_req_t  out_req_i,
  input sep_pkg::sep_system_peripherals_outbound_axi_resp_t out_resp_i,
  // smc_req: the SEP->SMC port (PR-SMC). ext_req: the AXI Extension port (PR-EXT).
  input sep_pkg::sep_system_peripherals_internal_axi_req_t  smc_req_i,
  input sep_pkg::sep_system_peripherals_internal_axi_resp_t smc_resp_i,
  input sep_pkg::sep_32_64_6_12_axi_req_t  ext_req_i,
  input sep_pkg::sep_32_64_6_12_axi_resp_t ext_resp_i,
  // dma_req after the DMA window remap, dma_req_raw before it, dma_csr_req
  // at the DMA CSR target (PR-DMACSR).
  input sep_pkg::sep_32_64_3_12_axi_req_t  dma_req_i,
  input sep_pkg::sep_32_64_3_12_axi_resp_t dma_resp_i,
  input sep_pkg::sep_32_64_3_12_axi_req_t  dma_raw_req_i,
  input sep_pkg::sep_32_64_6_12_axi_req_t  dma_csr_req_i,
  input sep_pkg::sep_32_64_6_12_axi_resp_t dma_csr_resp_i,
  input wire        irq_dma_error_i,
  // rom_req: the boot ROM macro port (PR-ROM). tcm_*: the CPU TCM macro
  // port enables (the DMA TCM cells only).
  input sep_pkg::sep_sram_req_t rom_req_i,
  input sep_pkg::sep_sram_rsp_t rom_rsp_i,
  input wire        tcm_clken_i,
  input wire        tcm_wren_i,
  // in_filter / out_filter: FILTER_CONFIG, START_ADDR, END_ADDR of every entry.
  input wire [15:0]       in_f_en_i,
  input wire [15:0]       in_f_rd_i,
  input wire [15:0]       in_f_wr_i,
  input wire [15:0]       in_f_ns_i,
  input wire [15:0]       in_f_burst_i,
  input wire [15:0][3:0]  in_f_src_i,
  input wire [15:0][55:0] in_f_start_i,
  input wire [15:0][55:0] in_f_end_i,
  input wire [31:0]       out_f_en_i,
  input wire [31:0]       out_f_rd_i,
  input wire [31:0]       out_f_wr_i,
  input wire [31:0]       out_f_ns_i,
  input wire [31:0]       out_f_burst_i,
  input wire [31:0][3:0]  out_f_src_i,
  input wire [31:0][55:0] out_f_start_i,
  input wire [31:0][55:0] out_f_end_i,
  // alias_remap: the 16 local-master alias regions (start and end hold
  // address bits [55:12]; end is non-inclusive).
  input wire [15:0]       al_valid_i,
  input wire [15:0][3:0]  al_cache_i,
  input wire [15:0][43:0] al_start_i,
  input wire [15:0][43:0] al_end_i,
  input wire [15:0][43:0] al_offset_i,
  // ap_remap / stee_remap: valid bit of each output remap region.
  input wire [15:0]       ap_valid_i,
  input wire [15:0]       stee_valid_i,
  // aperture, smu_aperture, local_base, smc_aperture, smc_fuse_done, sep_debug.
  input wire [55:0] sep_base_i,
  input wire [55:0] sep_size_i,
  input wire [55:0] smu_base_i,
  input wire [55:0] smu_size_i,
  input wire [55:0] local_base_i,
  input wire [55:0] smc_base_i,
  input wire [55:0] smc_size_i,
  input wire        smc_fuse_done_i,
  input wire        sep_debug_i,

  // ---------------------------------------------------------------------
  // Phase 2 SPI and DMA taps (docs/SEP_FCOV.adoc, SPI and DMA groups,
  // Sampled signals). Read-only copies of DUT nets and probe ports.
  // ---------------------------------------------------------------------
  // spi_host: u_sep_io.u_sep_ot_spi_wrap.u_spi_host (activity, stalls,
  // queue depths, FIFO flags, command_busy, reg2hw). spi_tx_qd_i is the
  // probe spi_tx_qd_probe_o.
  input wire        spi_active_i,
  input wire        spi_tx_stall_i,
  input wire        spi_rx_stall_i,
  input wire [7:0]  spi_tx_qd_i,
  input wire [7:0]  spi_rx_qd_i,
  input wire [3:0]  spi_cmd_qd_i,
  input wire        spi_tx_wm_i,
  input wire        spi_tx_empty_i,
  input wire        spi_tx_full_i,
  input wire        spi_rx_wm_i,
  input wire        spi_rx_empty_i,
  input wire        spi_rx_full_i,
  input wire        spi_cmd_busy_i,
  input spi_host_reg_pkg::spi_host_reg2hw_t spi_reg2hw_i,
  // secure DMA: u_sep_dma_wrap.u_secure_dma (reg2hw, STATUS.ABORTED and
  // ERROR_CODE register nets). dma_busy_i is the probe dma_busy_probe_o.
  input secure_dma_reg_pkg::dma_reg2hw_t dma_reg2hw_i,
  input wire        dma_aborted_i,
  input wire [7:0]  dma_err_code_i,      // bit i = ERROR_CODE bit i
  input wire        dma_busy_i,
  // sep_internal_interrupts_probe_o[9] (PIC source 10, DMA chunk done) and
  // [13] (PIC source 14, SPI). [8] and [10] are irq_dma_done_i and
  // irq_dma_error_i above.
  input wire        irq_dma_chunk_i,
  input wire        irq_spi_i
);

  import sep_top_addrmap_pkg::*;
  `include "sep_reg.svh"
  `include "sep_fcov_owner_codes.svh"

  // Graded-window gate of the Phase 2 groups (docs/SEP_FCOV.adoc, graded
  // window): the code of the owning test whose window is open, 0 when none
  // is. A leaf writes it through the u_sep_fcov handle. It drives nothing.
  int unsigned graded_owner = FcovOwnNone;

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
  localparam int unsigned FiltEntries = sep_pkg::InboundFilterNumFilters;
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
  // the adams-bridge abr_reg.rdl MLKEM block.
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
  localparam logic [3:0] DmaOpSha512 = 4'h3;  // dma.hjson CONTROL.OPCODE

  // aon_timer INTR_STATE: wkup_timer_expired[0], wdog_timer_bark[1]. The
  // vendored block exports no field symbol into sep_reg.svh; the position is
  // the one cocotb/seq_lib/sep_wdt_aon_seq.py resolves from the register metadata.
  localparam logic [31:0] WdtBarkMask = 32'h2;

  // LC_STATE shadow word: bits[7:0] hold the differential {~raw, raw}
  // (cocotb/env/sep_efuse_image.py lc_encode). Legal raw codes are
  // efuse_pkg::lc_state_raw_e.
  localparam logic [3:0] LcTestDev = 4'h0;
  localparam logic [3:0] LcProd = 4'h1;
  localparam logic [3:0] LcRmaSip0 = 4'h2;
  localparam logic [3:0] LcRmaSip1 = 4'h3;
  localparam logic [3:0] LcRmaChip0 = 4'h6;
  localparam logic [3:0] LcRmaChip1 = 4'h7;
  localparam logic [3:0] LcProdEnd = 4'h8;

  // KM mailbox frame (cocotb/seq_lib/sep_km_mailbox_seq.py):
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
  // bring-up window before the bench drives rst_ni scores nothing.
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

  wire r_beat = (lsu_r_valid_i === 1'b1) && (lsu_r_ready_i === 1'b1);

  logic [3:0] aw_out_q, ar_out_q;
  logic [31:0] aw_addr_q, ar_addr_q;
  logic [2:0]  ar_size_q;
  logic [63:0] w_data_q;
  logic [7:0]  w_strb_q;
  // W beats since the last B, and whether the read in flight has returned a
  // beat before its last one. A data-bearing event needs a single-beat
  // transaction: a burst would pair its start address with a later beat's
  // data, and a W beat accepted ahead of its own AW belongs to the next
  // transaction. Both cases are skipped, which is a missed hit, never a false
  // one.
  logic [1:0] w_beats_q;
  logic       r_multi_q;

  // The LSU demux is inside sep_cpu, which resets on sep_cpu_reset_n
  // (sep.sv u_sep_cpu). A warm reset can drop a transaction in flight, so the
  // counters restart when that reset asserts; a stale count would gate off
  // every bus-decoded bin for the rest of the run. Counting goes on while the
  // reset is held: the no-CPU bus still completes transactions then (the
  // SEC_DIS leaves read LC_STATE with sep_cpu_reset_n low).
  logic lsu_cpu_rst_n_q;
  wire  lsu_clear = in_reset || (lsu_cpu_rst_n_q && (cpu_reset_n_i === 1'b0));

  always_ff @(posedge clk_i) begin
    lsu_cpu_rst_n_q <= (cpu_reset_n_i !== 1'b0);
    if (lsu_clear) begin
      aw_out_q  <= '0;
      ar_out_q  <= '0;
      w_beats_q <= '0;
      r_multi_q <= 1'b0;
    end else begin
      // A response with no count belongs to a transaction a reset dropped.
      aw_out_q <= aw_out_q + (aw_hs ? 4'd1 : 4'd0) -
          ((b_hs && ((aw_out_q != 4'd0) || aw_hs)) ? 4'd1 : 4'd0);
      ar_out_q <= ar_out_q + (ar_hs ? 4'd1 : 4'd0) -
          ((r_hs && ((ar_out_q != 4'd0) || ar_hs)) ? 4'd1 : 4'd0);
      if (aw_hs) aw_addr_q <= lsu_aw_addr_i;
      if (ar_hs) begin
        ar_addr_q <= lsu_ar_addr_i;
        ar_size_q <= lsu_ar_size_i;
      end
      if (w_hs) begin
        w_data_q <= lsu_w_data_i;
        w_strb_q <= lsu_w_strb_i;
      end
      // A W beat in the B cycle belongs to a later transaction.
      if (b_hs) w_beats_q <= w_hs ? 2'd1 : 2'd0;
      else if (w_hs && (w_beats_q != 2'd3)) w_beats_q <= w_beats_q + 2'd1;
      if (r_hs) r_multi_q <= 1'b0;
      else if (r_beat) r_multi_q <= 1'b1;
    end
  end

  // Exactly one outstanding single-beat transaction, so the latched address
  // belongs to this response and the latched data to this address. See
  // TRANSACTION PAIRING at the head of the file.
  wire wr_okay = !in_reset && b_hs && (aw_out_q == 4'd1) && (w_beats_q == 2'd1) &&
      (lsu_b_resp_i == AxiOkay);
  wire rd_okay = !in_reset && r_hs && (ar_out_q == 4'd1) && !r_multi_q &&
      (lsu_r_resp_i == AxiOkay);

  // A 4-byte beat on a 64-bit bus sits in the address-selected lane. Reading
  // bits [31:0] unconditionally would miss every odd-word register (AES
  // CTRL_SHADOWED, OTBN CMD, the ABR STATUS at +0x14, ...).
  wire [31:0] wr_data = aw_addr_q[2] ? w_data_q[63:32]  : w_data_q[31:0];
  wire [3:0]  wr_strb = aw_addr_q[2] ? w_strb_q[7:4]    : w_strb_q[3:0];
  wire [31:0] rd_data = ar_addr_q[2] ? lsu_r_data_i[63:32] : lsu_r_data_i[31:0];

  function automatic logic in_win(logic [31:0] a, logic [31:0] lo, logic [31:0] hi);
    return (a >= lo) && (a < hi);
  endfunction

  // --- CSR block decode --------------------------------------------------
  // One value per LSU-reachable register block in sep_reg.svh. SRAM and the
  // boot ROM have their own groups. The PIC is inside the VeeR core and never
  // reaches the LSU bus, and SEP_EXTERNAL is the outbound port, not a SEP
  // block, so neither has a value. TRNG has none either: no leaf of the `all`
  // regression makes an OKAY read of it.
  typedef enum logic [4:0] {
    BLK_NONE,
    BLK_CPU_CTRL,
    BLK_DMA,
    BLK_WDT,
    BLK_SCRATCH_COLD,
    BLK_SCRATCH_WARM,
    BLK_RESET_CTRL,
    BLK_OTBN,
    BLK_AES,
    BLK_HMAC,
    BLK_KMAC,
    BLK_CSRNG,
    BLK_EDN,
    BLK_ESRC,
    BLK_LIFECYCLE,
    BLK_KM_MBOX,
    BLK_EFUSE_MAP,
    BLK_EFUSE_CTRL,
    BLK_EFUSE_MMR,
    BLK_ABR,
    BLK_POOL,
    BLK_AXIL_MBOX,
    BLK_ALIAS_REMAP,
    BLK_AP_REMAP,
    BLK_STEE_REMAP,
    BLK_OUT_FILTER,
    BLK_IN_FILTER,
    BLK_SPI
  } blk_e;

  // The remap and filter banks are arrays of RDL entries; each window runs
  // from entry 0 to the end of the last entry.
  localparam logic [31:0] AliasBankBase = LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] AliasBankEnd = LOCAL_MASTER_ALIAS_REMAP_CTRL_15__REG_MAP_BASE_ADDR +
      LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_SIZE;
  localparam logic [31:0] ApBankBase = AP_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] ApBankEnd = AP_OUTPUT_REMAP_CTRL_15__REG_MAP_BASE_ADDR +
      AP_OUTPUT_REMAP_CTRL_0__REG_MAP_SIZE;
  localparam logic [31:0] SteeBankBase = STEE_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] SteeBankEnd = STEE_OUTPUT_REMAP_CTRL_15__REG_MAP_BASE_ADDR +
      STEE_OUTPUT_REMAP_CTRL_0__REG_MAP_SIZE;
  localparam logic [31:0] OutFiltBankBase = OUTBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] OutFiltBankEnd = OUTBOUND_FILTER_CTRL_31__REG_MAP_BASE_ADDR +
      OUTBOUND_FILTER_CTRL_0__REG_MAP_SIZE;

  function automatic logic in_blk(logic [31:0] a, logic [31:0] base, logic [31:0] size);
    return in_win(a, base, base + size);
  endfunction

  function automatic blk_e blk_of(logic [31:0] a);
    if (in_blk(a, SEP_CPU_CTRL_REG_MAP_BASE_ADDR, SEP_CPU_CTRL_REG_MAP_SIZE)) return BLK_CPU_CTRL;
    if (in_blk(a, SECURE_DMA_REG_MAP_BASE_ADDR, SECURE_DMA_REG_MAP_SIZE)) return BLK_DMA;
    if (in_blk(a, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE)) return BLK_WDT;
    if (in_blk(a, ColdBase, SEP_SCRATCH_COLD_REG_MAP_SIZE)) return BLK_SCRATCH_COLD;
    if (in_blk(a, WarmBase, SEP_SCRATCH_WARM_REG_MAP_SIZE)) return BLK_SCRATCH_WARM;
    if (in_blk(a, SEP_RESET_CTRL_REG_MAP_BASE_ADDR, SEP_RESET_CTRL_REG_MAP_SIZE))
      return BLK_RESET_CTRL;
    if (in_blk(a, OTBN_REG_MAP_BASE_ADDR, OTBN_REG_MAP_SIZE)) return BLK_OTBN;
    if (in_blk(a, AES_REG_MAP_BASE_ADDR, AES_REG_MAP_SIZE)) return BLK_AES;
    if (in_blk(a, HMAC_REG_MAP_BASE_ADDR, HMAC_REG_MAP_SIZE)) return BLK_HMAC;
    if (in_blk(a, KMAC_REG_MAP_BASE_ADDR, KMAC_REG_MAP_SIZE)) return BLK_KMAC;
    if (in_blk(a, CSRNG_REG_MAP_BASE_ADDR, CSRNG_REG_MAP_SIZE)) return BLK_CSRNG;
    if (in_blk(a, EDN_REG_MAP_BASE_ADDR, EDN_REG_MAP_SIZE)) return BLK_EDN;
    if (in_blk(a, ENTROPY_SOURCE_REG_MAP_BASE_ADDR, ENTROPY_SOURCE_REG_MAP_SIZE)) return BLK_ESRC;
    if (in_blk(a, SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR, SEP_LIFECYCLE_CTRL_REG_MAP_SIZE))
      return BLK_LIFECYCLE;
    if (in_blk(a, KM_MAILBOX_SEP_REG_MAP_BASE_ADDR, KM_MAILBOX_SEP_REG_MAP_SIZE))
      return BLK_KM_MBOX;
    if (in_blk(a, SEP_EFUSE_MAP_REG_MAP_BASE_ADDR, SEP_EFUSE_MAP_REG_MAP_SIZE))
      return BLK_EFUSE_MAP;
    if (in_blk(a, EFUSE_INTERFACE_CTRL_REG_MAP_BASE_ADDR, EFUSE_INTERFACE_CTRL_REG_MAP_SIZE))
      return BLK_EFUSE_CTRL;
    if (in_blk(a, EFUSE_MMR_REG_MAP_BASE_ADDR, EFUSE_MMR_REG_MAP_SIZE)) return BLK_EFUSE_MMR;
    if (in_blk(a, ABR_REG_MAP_BASE_ADDR, ABR_REG_MAP_SIZE)) return BLK_ABR;
    if (in_blk(a, ENTROPY_POOL_REG_MAP_BASE_ADDR, ENTROPY_POOL_REG_MAP_SIZE)) return BLK_POOL;
    if (in_blk(a, AXIL_MAILBOX_REG_MAP_BASE_ADDR, AXIL_MAILBOX_REG_MAP_SIZE)) return BLK_AXIL_MBOX;
    if (in_win(a, AliasBankBase, AliasBankEnd)) return BLK_ALIAS_REMAP;
    if (in_win(a, ApBankBase, ApBankEnd)) return BLK_AP_REMAP;
    if (in_win(a, SteeBankBase, SteeBankEnd)) return BLK_STEE_REMAP;
    if (in_win(a, OutFiltBankBase, OutFiltBankEnd)) return BLK_OUT_FILTER;
    if (in_win(a, FiltBase, FiltEnd)) return BLK_IN_FILTER;
    if (in_blk(a, SpiBase, SPI_CONTROLLER_REG_MAP_SIZE)) return BLK_SPI;
    return BLK_NONE;
  endfunction

  blk_e rd_blk;
  assign rd_blk = blk_of(ar_addr_q);

  // --- AXI request shape -------------------------------------------------
  // Which of AW and W the master presented first for a write, taken from the
  // VALIDs at the first cycle either is high with no write outstanding. It is
  // scored on that write's OKAY B, so a write the DUT refused does not count.
  localparam logic [1:0] OrdAwFirst = 2'd0;
  localparam logic [1:0] OrdWFirst = 2'd1;
  localparam logic [1:0] OrdSame = 2'd2;
  wire        aw_v = (lsu_aw_valid_i === 1'b1);
  wire        w_v = (lsu_w_valid_i === 1'b1);
  logic [1:0] wr_order_q;
  logic       wr_order_valid_q;
  // A read accepted while a write has its address accepted and no data yet.
  wire        ar_during_write = !in_reset && ar_hs && ((aw_out_q != 4'd0) || aw_hs) &&
      (w_beats_q == 2'd0) && !w_hs;
  // Byte lanes of a completed write.
  function automatic logic [3:0] popcount8(logic [7:0] v);
    logic [3:0] n;
    n = 4'd0;
    for (int i = 0; i < 8; i++) n += 4'(v[i]);
    return n;
  endfunction
  wire  [3:0] wr_lanes = popcount8(w_strb_q);
  // Reads in flight when a new one is accepted, this one included.
  wire  [4:0] rd_depth = 5'(ar_out_q) + 5'd1;

  always_ff @(posedge clk_i) begin
    if (lsu_clear) begin
      wr_order_valid_q <= 1'b0;
    end else begin
      if (b_hs) wr_order_valid_q <= 1'b0;
      if (!wr_order_valid_q && (aw_out_q == 4'd0) && (w_beats_q == 2'd0) && (aw_v || w_v)) begin
        wr_order_q       <= (aw_v && w_v) ? OrdSame : (aw_v ? OrdAwFirst : OrdWFirst);
        wr_order_valid_q <= 1'b1;
      end
    end
  end



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
  wire cpu_console = !in_reset && (fw_char_valid_i === 1'b1);
  wire cpu_pc      = !in_reset && (cpu_trace_valid_i === 1'b1) && (cpu_trace_addr_i != 32'h0);
  // The PASS edge has its own sample (see the end of the module).
  logic cpu_pass_seen;
  initial cpu_pass_seen = 1'b0;

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

  // IMEM / DMEM write and readback: the last whole-word write to the memory,
  // then an OKAY read of that address returns it. A read of a word that was
  // never written does not score.
  localparam logic [31:0] OtbnImemEnd = OTBN_IMEM_MEM_BASE_ADDR + OTBN_IMEM_MEM_SIZE;
  localparam logic [31:0] OtbnDmemEnd = OTBN_DMEM_MEM_BASE_ADDR + OTBN_DMEM_MEM_SIZE;
  wire otbn_imem_wr = wr_ev && (wr_strb == 4'hF) &&
      in_win(aw_addr_q, OTBN_IMEM_MEM_BASE_ADDR, OtbnImemEnd);
  wire otbn_dmem_wr = wr_ev && (wr_strb == 4'hF) &&
      in_win(aw_addr_q, OTBN_DMEM_MEM_BASE_ADDR, OtbnDmemEnd);
  logic [31:0] otbn_imem_addr_q, otbn_imem_data_q, otbn_dmem_addr_q, otbn_dmem_data_q;
  logic otbn_imem_valid_q, otbn_dmem_valid_q;
  wire otbn_imem_rdback = rd_ev && otbn_imem_valid_q && (ar_addr_q == otbn_imem_addr_q) &&
      (rd_data == otbn_imem_data_q);
  wire otbn_dmem_rdback = rd_ev && otbn_dmem_valid_q && (ar_addr_q == otbn_dmem_addr_q) &&
      (rd_data == otbn_dmem_data_q);

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      otbn_imem_valid_q <= 1'b0;
      otbn_dmem_valid_q <= 1'b0;
    end else begin
      if (otbn_imem_wr) begin
        otbn_imem_addr_q  <= aw_addr_q;
        otbn_imem_data_q  <= wr_data;
        otbn_imem_valid_q <= 1'b1;
      end
      if (otbn_dmem_wr) begin
        otbn_dmem_addr_q  <= aw_addr_q;
        otbn_dmem_data_q  <= wr_data;
        otbn_dmem_valid_q <= 1'b1;
      end
    end
  end

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
  logic abr_keygen_q, abr_keygen_armed_q;
  // Armed on an observed VALID==0 read, like the sign/verify/ML-KEM bins below:
  // MLDSA_STATUS.VALID is sticky, and a KEYGEN written to a busy engine is
  // dropped, so without the arm the previous operation's VALID is credited.
  wire  abr_done = abr_status_valid && abr_keygen_q && abr_keygen_armed_q;
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
  // A completed read of the entropy-pool FIFO data register.
  wire pool_pop = rd_ev && (ar_addr_q == ENTROPY_POOL_DATA_REG_ADDR);
  // HT_WATERMARK_NUM selector writes. 0..4 are the WATERMARK_TEST encodings
  // in entropy_source.rdl; any other value is unsupported and maps to
  // REPCNT_HI.
  wire esrc_ht_sel_wr = wr_ev && (aw_addr_q == ENTROPY_SOURCE_HT_WATERMARK_NUM_REG_ADDR);
  wire [3:0] esrc_ht_sel = 4'((wr_data & ENTROPY_SOURCE_HT_WATERMARK_NUM_WATERMARK_NUM_MASK) >>
                              ENTROPY_SOURCE_HT_WATERMARK_NUM_WATERMARK_NUM_SHIFT);

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
  logic [7:0] km_cmd_id_q;       // cmd_id of the frame being written (header [15:8])
  logic [15:0] km_load_words_q;  // FW_WORDS of the last CMD_SRAM_LOAD_EXEC payload
  logic [16:0] km_raw_left_q;    // raw image words + CRC trailer still to come

  // Generate succeeded: the response frame echoed CMD_KEY_GENERATE with rc 0
  // and a non-null handle. Nothing here is inferred from silence.
  wire km_generate_ok = km_rd_data && km_rsp_arm_q && km_rsp_is_cmd_q && (km_rsp_idx_q == 9'd4) &&
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
  // CMD_SRAM_LOAD_EXEC accepted: the raw image stream follows.
  wire km_load_accepted = km_rsp_last && (km_rsp_cmd_q == KmCmdSramLoadExec) &&
      (km_rsp_rc_now == 8'h00);
  // SW_RESET_N write that holds the KM in reset (km_sw_rst_n = 0).
  wire km_reset_wr = wr_ev && (aw_addr_q == SEP_RESET_CTRL_SW_RESET_N_REG_ADDR) &&
      wr_strb[0] && ((wr_data & SEP_RESET_CTRL_SW_RESET_N_KM_SW_RST_N_MASK) == 32'h0);
  wire km_wipe = wr_ev && (aw_addr_q == SEP_CPU_CTRL_KM_WIPE_CTRL_REG_ADDR) &&
      wr_strb[0] && wr_data[0];
  // KM_SW_RST_N as last written or read back. SW_RESET_N resets with
  // sep_reset_n, which the sampler cannot see; the tracker follows the cold
  // reset only, so a warm reset can leave it stale at 1 and miss a release,
  // never invent one.
  localparam logic KmSwRstDefault = 1'(SEP_RESET_CTRL_SW_RESET_N_REG_DEFAULT &
                                       SEP_RESET_CTRL_SW_RESET_N_KM_SW_RST_N_MASK);
  logic km_sw_rst_n_q;
  wire  km_swrst_wr = wr_ev && (aw_addr_q == SEP_RESET_CTRL_SW_RESET_N_REG_ADDR) && wr_strb[0];
  wire  km_swrst_rd = rd_ev && (ar_addr_q == SEP_RESET_CTRL_SW_RESET_N_REG_ADDR);
  // The release edge: KM_SW_RST_N goes 0 -> 1. A write that sets the bit while
  // the KM is already released changes nothing and does not score.
  wire  km_swrst_rel = km_swrst_wr && wr_data[0] && !km_sw_rst_n_q;

  always_ff @(posedge clk_i) begin
    if (in_reset) km_sw_rst_n_q <= KmSwRstDefault;
    else if (km_swrst_wr) km_sw_rst_n_q <= wr_data[0];
    else if (km_swrst_rd) km_sw_rst_n_q <= rd_data[0];
  end

  // --- Secure DMA --------------------------------------------------------
  wire dma_go = wr_ev && (aw_addr_q == SECURE_DMA_CONTROL_REG_ADDR) &&
      ((wr_data & SECURE_DMA_CONTROL_GO_MASK) != 32'h0);
  wire [3:0] dma_opcode_w = (wr_data & SECURE_DMA_CONTROL_OPCODE_MASK) >>
      SECURE_DMA_CONTROL_OPCODE_SHIFT;
  wire dma_copy_go = dma_go && (dma_opcode_w == DmaOpCopy);
  wire dma_hash_go = dma_go && (dma_opcode_w == DmaOpSha256);
  wire dma_total_wr = wr_ev && (aw_addr_q == SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR);
  // TOTAL_DATA_SIZE is scored at the COPY GO that uses it. A register walk
  // writes the size but never issues GO.
  logic [31:0] dma_total_q;
  logic        dma_total_valid_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      dma_total_valid_q <= 1'b0;
    end else if (dma_total_wr) begin
      dma_total_q       <= wr_data;
      dma_total_valid_q <= 1'b1;
    end
  end
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
  // sep_dma_basic_test polls STATUS, while sep_dma_hash_test enables
  // INTR_ENABLE.DMA_DONE, WFIs, and its handler clears STATUS.done before
  // software ever reads it -- so
  // on that path no STATUS read with the DONE bit ever appears on the bus. The
  // interrupt (sep.sv, sep_internal_interrupts[8] = intr_dma_done) is the
  // completion event there. Rising edge: the aggregated bit is a level.
  logic irq_dma_done_q;
  wire  dma_irq_done = !in_reset && (irq_dma_done_i === 1'b1) && !irq_dma_done_q;
  wire  dma_complete = dma_status_done || dma_irq_done;

  // Which opcode was GO'd still labels the cell, so an interrupt cannot score
  // the wrong one.
  wire  dma_copy_done = dma_complete && dma_copy_q;
  wire  dma_hash_done = dma_complete && dma_hash_q;

  // --- SPI host ----------------------------------------------------------
  logic spi_cs_n_q, spi_sck_q;
  // A real frame on the pads: chip select asserted, then a shift clock edge
  // inside that frame. CSR traffic alone cannot hit these.
  wire  spi_cs_assert = !in_reset && spi_cs_n_q && (spi_cs_n_i === 1'b0);
  wire  spi_sck_edge  = !in_reset && (spi_cs_n_i === 1'b0) && !spi_sck_q &&
      (spi_sck_i === 1'b1);
  // A COMMAND write that the host acted on: chip select asserts after it. A
  // register walk reaches the SPI window too, but it does not start a segment
  // with the pads, so it cannot fill this bin.
  wire  spi_cmd_wr = wr_ev && (aw_addr_q == SPI_CONTROLLER_COMMAND_REG_ADDR);
  logic spi_cmd_q;
  wire  spi_csr = spi_cs_assert && spi_cmd_q;
  // The first byte of a frame on sd[0], MSB first, taken on the SCK rising
  // edges inside chip select. That byte is the flash opcode.
  logic [7:0] spi_shift_q;
  logic [3:0] spi_bits_q;
  wire  [7:0] spi_opcode = {spi_shift_q[6:0], (spi_mosi_i === 1'b1)};
  wire        spi_opcode_ev = spi_sck_edge && (spi_bits_q == 4'd7);
  // CONTROL.TX_WATERMARK as written.
  wire        spi_ctrl_wr = wr_ev && (aw_addr_q == SPI_CONTROLLER_CONTROL_REG_ADDR);
  wire  [7:0] spi_tx_wm = 8'((wr_data & SPI_CONTROLLER_CONTROL_TX_WATERMARK_MASK) >>
                             SPI_CONTROLLER_CONTROL_TX_WATERMARK_SHIFT);

  always_ff @(posedge clk_i) begin
    if (in_reset || (spi_cs_n_i !== 1'b0)) begin
      spi_bits_q <= 4'd0;
    end else if (spi_sck_edge && (spi_bits_q != 4'd8)) begin
      spi_shift_q <= spi_opcode;
      spi_bits_q  <= spi_bits_q + 4'd1;
    end
  end

  // =====================================================================
  // Phase 2: SPI and DMA decode (docs/SEP_FCOV.adoc, SPI and DMA groups).
  //
  // GATE. Every Phase 2 bin of this area samples only while `graded_owner`
  // holds the code of an owning test (own_spi_* and own_dma_* below). The
  // Phase 1 groups keep their own sampling; the bins this area adds to them
  // carry the gate.
  //
  // INPUTS. The register write and read decode of the LSU bus (wr_ev, rd_ev),
  // the pad ports, the reset ports, the PIC lines and the read-only taps of
  // the SPI host and the secure DMA (spi_*_i, spi_reg2hw_i, dma_reg2hw_i,
  // dma_err_code_i, dma_aborted_i, dma_busy_i, dma_req_i). Nothing here
  // drives the DUT.
  //
  // LATCHES. A field marked "latched" is the field of the last OKAY write of
  // that register. It takes the register description reset value while
  // sep_reset_n is low, because the SPI host and the DMA reset on it.
  //
  // ISSUE. A write is "issued" on the clock its AW and W are both accepted.
  // A register write lands after that clock and before its B, so a value
  // read on the issue clock is the value before the write.
  // =====================================================================
  wire own_spi_matrix = (graded_owner == FcovOwnSepSpiPadSpeedDirMatrixTest);
  wire own_spi_timing = (graded_owner == FcovOwnSepSpiPadTimingCfgRandTest);
  wire own_spi_fifo = (graded_owner == FcovOwnSepSpiFifoStallWatermarkRandTest);
  wire own_spi_csr = (graded_owner == FcovOwnSepSpiOtHostCsrIrqRandTest);
  wire own_spi_coldrst = (graded_owner == FcovOwnSepSpiColdResetValuesRandTest);
  wire own_dma_matrix = (graded_owner == FcovOwnSepDmaTransferMatrixRandTest);
  wire own_dma_irq = (graded_owner == FcovOwnSepDmaIrqErrorLockRandTest);
  wire own_dma_abort = (graded_owner == FcovOwnSepDmaAbortRecoveryRandTest);
  wire own_spi_dma_hs = (graded_owner == FcovOwnSepSpiDmaHandshakeRandTest);

  // --- Register access helpers ------------------------------------------
  // A 4-byte register at `a` takes a write beat when the 8-byte word holds
  // it and its half carries strobes. An 8-byte write to a pair is one
  // transaction that writes both halves.
  function automatic logic hit4(input logic [31:0] addr, input logic [7:0] strb,
                                input logic [31:0] a);
    return (addr[31:3] == a[31:3]) && (a[2] ? (strb[7:4] != 4'h0) : (strb[3:0] != 4'h0));
  endfunction
  function automatic logic [31:0] word4(input logic [63:0] data, input logic [31:0] a);
    return a[2] ? data[63:32] : data[31:0];
  endfunction
  function automatic logic [31:0] merge4(input logic [31:0] old, input logic [63:0] data,
                                         input logic [7:0] strb, input logic [31:0] a);
    logic [3:0]  s;
    logic [31:0] m;
    s = a[2] ? strb[7:4] : strb[3:0];
    m = {{8{s[3]}}, {8{s[2]}}, {8{s[1]}}, {8{s[0]}}};
    return (old & ~m) | (word4(data, a) & m);
  endfunction
  // A read returns register `a` when it addresses `a`, or when it is an
  // 8-byte read of the aligned pair that holds `a`.
  function automatic logic rhit4(input logic [31:0] addr, input logic [2:0] size,
                                 input logic [31:0] a);
    return (addr == a) || ((size == 3'd3) && (addr == {a[31:3], 3'b000}));
  endfunction
  function automatic logic [31:0] fld(input logic [31:0] v, input logic [31:0] m,
                                      input int unsigned s);
    return (v & m) >> s;
  endfunction

  // Write issue: the clock at which the second of AW and W of a single
  // outstanding write is accepted. wi_* are the address and data of it.
  wire        wr_issue = !lsu_clear &&
      ((aw_hs && (aw_out_q == 4'd0) && (w_hs || (w_beats_q == 2'd1))) ||
       (w_hs && !aw_hs && (aw_out_q == 4'd1) && (w_beats_q == 2'd0)));
  wire [31:0] wi_addr = aw_hs ? lsu_aw_addr_i : aw_addr_q;
  wire [63:0] wi_data = w_hs ? lsu_w_data_i : w_data_q;
  wire [7:0]  wi_strb = w_hs ? lsu_w_strb_i : w_strb_q;

  // --- SPI host: addresses and levels ------------------------------------
  localparam logic [31:0] SpiIntrState = SPI_CONTROLLER_INTR_STATE_REG_ADDR;
  localparam logic [31:0] SpiIntrTest = SPI_CONTROLLER_INTR_TEST_REG_ADDR;
  localparam logic [31:0] SpiControl = SPI_CONTROLLER_CONTROL_REG_ADDR;
  localparam logic [31:0] SpiStatus = SPI_CONTROLLER_STATUS_REG_ADDR;
  localparam logic [31:0] SpiConfigopts = SPI_CONTROLLER_CONFIGOPTS_REG_ADDR;
  localparam logic [31:0] SpiCsid = SPI_CONTROLLER_CSID_REG_ADDR;
  localparam logic [31:0] SpiCommand = SPI_CONTROLLER_COMMAND_REG_ADDR;
  localparam logic [31:0] SpiRxdata = SPI_CONTROLLER_RXDATA_0__MEM_BASE_ADDR;
  localparam logic [31:0] SpiTxdata = SPI_CONTROLLER_TXDATA_0__MEM_BASE_ADDR;
  localparam logic [31:0] SpiErrEnable = SPI_CONTROLLER_ERROR_ENABLE_REG_ADDR;
  localparam logic [31:0] SpiErrStatus = SPI_CONTROLLER_ERROR_STATUS_REG_ADDR;
  localparam logic [31:0] SpiEvtEnable = SPI_CONTROLLER_EVENT_ENABLE_REG_ADDR;
  localparam logic [31:0] SpiIntrEnable = SPI_CONTROLLER_INTR_ENABLE_REG_ADDR;

  // spi_controller.adoc COMMAND.DIRECTION: 0 dummy, 1 Rx, 2 Tx, 3 bidirectional.
  localparam logic [1:0] SpiDirDummy = 2'd0;
  localparam logic [1:0] SpiDirRx = 2'd1;
  localparam logic [1:0] SpiDirTx = 2'd2;
  localparam logic [1:0] SpiDirBidir = 2'd3;
  localparam int SpiQ = 16;  // sampler-side copy of the accepted command queue

  wire spi_on = (sep_reset_n_i === 1'b1);
  wire s_act = (spi_active_i === 1'b1);
  wire s_cb = (spi_cmd_busy_i === 1'b1);  // STATUS.READY is the inverse
  wire s_txst = (spi_tx_stall_i === 1'b1);
  wire s_rxst = (spi_rx_stall_i === 1'b1);
  wire s_txwm = (spi_tx_wm_i === 1'b1);
  wire s_txe = (spi_tx_empty_i === 1'b1);
  wire s_txf = (spi_tx_full_i === 1'b1);
  wire s_rxwm = (spi_rx_wm_i === 1'b1);
  wire s_rxe = (spi_rx_empty_i === 1'b1);
  wire s_rxf = (spi_rx_full_i === 1'b1);
  wire [7:0] s_txqd = spi_tx_qd_i;
  wire [7:0] s_rxqd = spi_rx_qd_i;
  wire [3:0] s_cmdqd = spi_cmd_qd_i;
  wire cs_low = (spi_cs_n_i === 1'b0);
  wire cs_high = (spi_cs_n_i === 1'b1);
  wire sck_v = (spi_sck_i === 1'b1);
  wire mosi_known = (spi_mosi_i === 1'b1) || (spi_mosi_i === 1'b0);
  wire irq_spi = (irq_spi_i === 1'b1);

  // ERROR_STATUS and ERROR_ENABLE by class: 0 CSIDINVAL, 1 CMDINVAL,
  // 2 UNDERFLOW, 3 OVERFLOW, 4 CMDBUSY, 5 ACCESSINVAL (ERROR_ENABLE has no
  // ACCESSINVAL). es_shift gives the register bit of each class.
  function automatic int unsigned es_shift(input int c);
    case (c)
      0: return SPI_CONTROLLER_ERROR_STATUS_CSIDINVAL_SHIFT;
      1: return SPI_CONTROLLER_ERROR_STATUS_CMDINVAL_SHIFT;
      2: return SPI_CONTROLLER_ERROR_STATUS_UNDERFLOW_SHIFT;
      3: return SPI_CONTROLLER_ERROR_STATUS_OVERFLOW_SHIFT;
      4: return SPI_CONTROLLER_ERROR_STATUS_CMDBUSY_SHIFT;
      default: return SPI_CONTROLLER_ERROR_STATUS_ACCESSINVAL_SHIFT;
    endcase
  endfunction
  wire [5:0] s_es = {spi_reg2hw_i.error_status.accessinval.q === 1'b1,
                     spi_reg2hw_i.error_status.cmdbusy.q === 1'b1,
                     spi_reg2hw_i.error_status.overflow.q === 1'b1,
                     spi_reg2hw_i.error_status.underflow.q === 1'b1,
                     spi_reg2hw_i.error_status.cmdinval.q === 1'b1,
                     spi_reg2hw_i.error_status.csidinval.q === 1'b1};
  wire s_een_unf = (spi_reg2hw_i.error_enable.underflow.q === 1'b1);
  wire s_een_ovf = (spi_reg2hw_i.error_enable.overflow.q === 1'b1);
  // Event sources by class: 0 IDLE (not ACTIVE), 1 READY (not command_busy),
  // 2 TXWM, 3 RXWM, 4 TXEMPTY, 5 RXFULL, and their EVENT_ENABLE bits.
  wire [5:0] s_src = {s_rxf, s_txe, s_rxwm, s_txwm, !s_cb, !s_act};
  wire [5:0] s_evten = {spi_reg2hw_i.event_enable.rxfull.q === 1'b1,
                        spi_reg2hw_i.event_enable.txempty.q === 1'b1,
                        spi_reg2hw_i.event_enable.rxwm.q === 1'b1,
                        spi_reg2hw_i.event_enable.txwm.q === 1'b1,
                        spi_reg2hw_i.event_enable.ready.q === 1'b1,
                        spi_reg2hw_i.event_enable.idle.q === 1'b1};
  wire s_ist_err = (spi_reg2hw_i.intr_state.error.q === 1'b1);
  wire s_ist_evt = (spi_reg2hw_i.intr_state.spi_event.q === 1'b1);
  wire s_ien_err = (spi_reg2hw_i.intr_enable.error.q === 1'b1);
  wire s_ien_evt = (spi_reg2hw_i.intr_enable.spi_event.q === 1'b1);
  wire [7:0] s_txwm_cfg = spi_reg2hw_i.control.tx_watermark.q;
  wire [7:0] s_rxwm_cfg = spi_reg2hw_i.control.rx_watermark.q;

  // --- SPI host: register decode -----------------------------------------
  logic [31:0] spi_cfg_q, spi_ctrl_q, spi_csid_q;  // latched CONFIGOPTS, CONTROL, CSID
  wire        sw_cmd = wr_ev && hit4(aw_addr_q, w_strb_q, SpiCommand);
  wire [31:0] sw_cmd_d = word4(w_data_q, SpiCommand);
  wire [19:0] sc_len = 20'(fld(sw_cmd_d, SPI_CONTROLLER_COMMAND_LEN_MASK,
                               SPI_CONTROLLER_COMMAND_LEN_SHIFT));
  wire        sc_csaat = (sw_cmd_d & SPI_CONTROLLER_COMMAND_CSAAT_MASK) != 32'h0;
  wire [1:0]  sc_speed = 2'(fld(sw_cmd_d, SPI_CONTROLLER_COMMAND_SPEED_MASK,
                                SPI_CONTROLLER_COMMAND_SPEED_SHIFT));
  wire [1:0]  sc_dir = 2'(fld(sw_cmd_d, SPI_CONTROLLER_COMMAND_DIRECTION_MASK,
                              SPI_CONTROLLER_COMMAND_DIRECTION_SHIFT));
  // spi_controller.adoc COMMAND: SPEED 3 is reserved, and DIRECTION 3 is
  // legal only at standard speed.
  wire        sc_legal = (sc_speed != 2'd3) && !((sc_dir == SpiDirBidir) && (sc_speed != 2'd0));

  wire        sw_ctrl = wr_ev && hit4(aw_addr_q, w_strb_q, SpiControl);
  wire [31:0] sw_ctrl_d = merge4(spi_ctrl_q, w_data_q, w_strb_q, SpiControl);
  wire        sw_cfg = wr_ev && hit4(aw_addr_q, w_strb_q, SpiConfigopts);
  wire        sw_csid = wr_ev && hit4(aw_addr_q, w_strb_q, SpiCsid);
  wire        sw_txdata = wr_ev && hit4(aw_addr_q, w_strb_q, SpiTxdata);
  wire        sw_errst = wr_ev && hit4(aw_addr_q, w_strb_q, SpiErrStatus) &&
      (SpiErrStatus[2] ? w_strb_q[4] : w_strb_q[0]);
  wire [31:0] sw_errst_d = word4(w_data_q, SpiErrStatus);
  wire        sw_ist = wr_ev && hit4(aw_addr_q, w_strb_q, SpiIntrState);
  wire        sw_itest = wr_ev && hit4(aw_addr_q, w_strb_q, SpiIntrTest);
  wire        sw_spi_any = wr_ev && in_win(aw_addr_q, SpiBase, SpiEnd);
  wire        sr_spi_any = rd_ev && in_win(ar_addr_q, SpiBase, SpiEnd);
  wire        sr_rxdata = rd_ev && rhit4(ar_addr_q, ar_size_q, SpiRxdata);
  wire        sr_errst = rd_ev && rhit4(ar_addr_q, ar_size_q, SpiErrStatus);
  wire [31:0] sr_errst_d = word4(lsu_r_data_i, SpiErrStatus);
  wire        sr_ist = rd_ev && rhit4(ar_addr_q, ar_size_q, SpiIntrState);
  wire [31:0] sr_ist_d = word4(lsu_r_data_i, SpiIntrState);
  wire        sr_ctrl = rd_ev && rhit4(ar_addr_q, ar_size_q, SpiControl);
  wire [31:0] sr_ctrl_d = word4(lsu_r_data_i, SpiControl);

  // Issue-time decode of the SPI writes whose effect lands before the B.
  wire wi_errst = wr_issue && hit4(wi_addr, wi_strb, SpiErrStatus) &&
      (SpiErrStatus[2] ? wi_strb[4] : wi_strb[0]);
  wire [31:0] wi_errst_d = word4(wi_data, SpiErrStatus);
  wire wi_ist = wr_issue && hit4(wi_addr, wi_strb, SpiIntrState) &&
      (SpiIntrState[2] ? wi_strb[4] : wi_strb[0]);
  wire [31:0] wi_ist_d = word4(wi_data, SpiIntrState);

  // --- SPI host: latched fields and issue snapshots ----------------------
  wire  [15:0] cfg_clkdiv = 16'(fld(spi_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CLKDIV_MASK,
                                    SPI_CONTROLLER_CONFIGOPTS_CLKDIV_SHIFT));
  wire  [3:0]  cfg_idle = 4'(fld(spi_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CSNIDLE_MASK,
                                 SPI_CONTROLLER_CONFIGOPTS_CSNIDLE_SHIFT));
  wire  [3:0]  cfg_trail = 4'(fld(spi_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CSNTRAIL_MASK,
                                  SPI_CONTROLLER_CONFIGOPTS_CSNTRAIL_SHIFT));
  wire  [3:0]  cfg_lead = 4'(fld(spi_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CSNLEAD_MASK,
                                 SPI_CONTROLLER_CONFIGOPTS_CSNLEAD_SHIFT));
  wire         cfg_fullcyc = (spi_cfg_q & SPI_CONTROLLER_CONFIGOPTS_FULLCYC_MASK) != 32'h0;
  wire         cfg_cpha = (spi_cfg_q & SPI_CONTROLLER_CONFIGOPTS_CPHA_MASK) != 32'h0;
  wire         cfg_cpol = (spi_cfg_q & SPI_CONTROLLER_CONFIGOPTS_CPOL_MASK) != 32'h0;
  wire  [2:0]  cfg_mode = {cfg_cpol, cfg_cpha, cfg_fullcyc};
  wire         ctl_spien = (spi_ctrl_q & SPI_CONTROLLER_CONTROL_SPIEN_MASK) != 32'h0;
  wire         ctl_swrst = (spi_ctrl_q & SPI_CONTROLLER_CONTROL_SW_RST_MASK) != 32'h0;
  wire         new_spien = (sw_ctrl_d & SPI_CONTROLLER_CONTROL_SPIEN_MASK) != 32'h0;
  wire         new_swrst = (sw_ctrl_d & SPI_CONTROLLER_CONTROL_SW_RST_MASK) != 32'h0;
  // CLKDIV class: 0 zero, 1 small (1..3), 2 mid (4..15), 3 other.
  wire  [1:0]  clk_cls = (cfg_clkdiv == 16'd0) ? 2'd0 :
                         (cfg_clkdiv <= 16'd3) ? 2'd1 :
                         (cfg_clkdiv <= 16'd15) ? 2'd2 : 2'd3;
  // CSN class: 0 zero, 1 mid (1..14), 2 max (15).
  function automatic logic [1:0] csn_cls(input logic [3:0] v);
    return (v == 4'd0) ? 2'd0 : ((v == 4'd15) ? 2'd2 : 2'd1);
  endfunction

  // Snapshots on the issue clock of a write and on the AR clock of a read.
  logic si_cb_q, si_act_q, si_cslow_q, si_txe_q, si_txf_q, si_ovf_en_q, si_ovf_q;
  logic [5:0] si_es_q;
  logic ra_rxe_q, ra_rxf_q, ra_act_q, ra_unf_q, ra_unf_en_q, ra_prev_status_q;
  logic [7:0] ra_rxqd_q;
  logic       spi_last_status_q;  // the last SPI-window access was a STATUS read

  // An accepted command: legal, READY at the issue clock, CSID 0.
  wire sc_accept = sw_cmd && sc_legal && !si_cb_q && (spi_csid_q == 32'h0);

  // Last accepted command, and a CONFIGOPTS write since the last command.
  logic sp_v_q, sp_csaat_q;
  logic [1:0] sp_speed_q, sp_dir_q;
  logic       cfg_new_q;

  // --- SPI host: command queue copy and frames ---------------------------
  // Each accepted command is queued with the owner flag at its write. A
  // frame (chip select low to high) takes commands from the head up to the
  // first one with CSAAT = 0. The frame gate holds when the leading sck
  // edges of the frame equal the sum of the segment cycles.
  logic [19:0] sq_len_q   [SpiQ];
  logic        sq_csaat_q [SpiQ];
  logic [1:0]  sq_speed_q [SpiQ];
  logic [1:0]  sq_dir_q   [SpiQ];
  logic        sq_own_q   [SpiQ];
  logic [4:0]  sq_n_q;
  logic [3:0]  sq_idle_q;

  // sck cycles of one segment: LEN + 1 for a dummy segment, and
  // (LEN + 1) x 8 / lanes for data, with 1, 2 and 4 lanes by SPEED.
  function automatic logic [31:0] seg_cyc(input logic [19:0] len, input logic [1:0] speed,
                                          input logic [1:0] dir);
    logic [31:0] n;
    n = 32'(len) + 32'd1;
    if (dir == SpiDirDummy) return n;
    return (n << 3) >> speed;
  endfunction

  logic [31:0] fr_sum;
  logic [4:0]  fr_k;
  logic        fr_term;
  always_comb begin
    fr_sum = '0;
    fr_k = '0;
    fr_term = 1'b0;
    for (int i = 0; i < SpiQ; i++) begin
      if (!fr_term && (5'(i) < sq_n_q)) begin
        fr_sum += seg_cyc(sq_len_q[i], sq_speed_q[i], sq_dir_q[i]);
        fr_k = 5'(i + 1);
        if (!sq_csaat_q[i]) fr_term = 1'b1;
      end
    end
  end

  logic fr_on_q, fr_idle_q, fr_first_q, fr_lead_v_q, fr_per_v_q;
  logic sck_q, mosi_q, cs_low_q;
  logic [31:0] fr_clk_q, fr_edges_q, fr_lead_q, fr_last_q, fr_lastlead_q, fr_minper_q;
  logic [1:0] fr_kind_q;  // last sck edge: 0 none, 1 leading, 2 trailing
  logic fr_chg_lead_q, fr_chg_trail_q;
  logic [31:0] fr_cfg_q;  // CONFIGOPTS at the chip-select fall
  logic [31:0] gap_q;
  logic        gap_v_q;

  wire fr_start = !fr_on_q && cs_low;
  wire fr_end = fr_on_q && !cs_low;
  // Queue count after the pop of a finished frame (a frame whose commands
  // do not end with CSAAT = 0 empties the copy), the push of an accepted
  // command, and the clears.
  wire [4:0] sq_popped = fr_end ? (fr_term ? (sq_n_q - fr_k) : 5'd0) : sq_n_q;
  wire sq_push = sc_accept && (sq_popped < 5'(SpiQ));
  wire sq_idle_run = cs_high && !s_act && (s_cmdqd == 4'd0) && !sc_accept;
  wire [4:0] sq_n_nxt = ((sw_ctrl && new_swrst) || (sq_idle_run && (sq_idle_q == 4'd8))) ? 5'd0 :
      (sq_popped + (sq_push ? 5'd1 : 5'd0));

  wire fr_sck_chg = fr_on_q && cs_low && (sck_v != sck_q);
  wire fr_lead_edge = fr_sck_chg && (sck_q == fr_idle_q);
  wire fr_trail_edge = fr_sck_chg && (sck_q != fr_idle_q);
  wire [1:0] fr_kind_now = fr_lead_edge ? 2'd1 : (fr_trail_edge ? 2'd2 : fr_kind_q);
  wire fr_mosi_chg = fr_on_q && cs_low && mosi_known && (spi_mosi_i !== mosi_q);
  wire fr_gate = fr_term && (fr_edges_q == fr_sum);
  wire [15:0] fr_div = 16'(fld(fr_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CLKDIV_MASK,
                               SPI_CONTROLLER_CONFIGOPTS_CLKDIV_SHIFT));
  wire [31:0] fr_d1 = 32'(fr_div) + 32'd1;
  wire [31:0] fr_lead_exp = (32'(fld(fr_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CSNLEAD_MASK,
                                     SPI_CONTROLLER_CONFIGOPTS_CSNLEAD_SHIFT)) + 32'd1) * fr_d1;
  wire [31:0] fr_trail_exp = (32'(fld(fr_cfg_q, SPI_CONTROLLER_CONFIGOPTS_CSNTRAIL_MASK,
                                      SPI_CONTROLLER_CONFIGOPTS_CSNTRAIL_SHIFT)) + 32'd1) * fr_d1;
  wire fr_cpha = (fr_cfg_q & SPI_CONTROLLER_CONFIGOPTS_CPHA_MASK) != 32'h0;
  wire fr_fullcyc = (fr_cfg_q & SPI_CONTROLLER_CONFIGOPTS_FULLCYC_MASK) != 32'h0;
  // Pad timing bins at the chip-select rise (cp_pad_timing_ok). CSNLEAD and
  // CSNTRAIL are minimum bounds, so lead and trail score at or above them.
  wire pt_period = fr_end && fr_per_v_q && (fr_minper_q == (fr_d1 << 1));
  wire pt_lead = fr_end && fr_lead_v_q && (fr_lead_q >= fr_lead_exp);
  wire pt_trail = fr_end && fr_lead_v_q && ((fr_clk_q - fr_last_q) >= fr_trail_exp);
  wire pt_gap = fr_start && gap_v_q &&
      (gap_q >= ((32'(cfg_idle) + 32'd1) * (32'(cfg_clkdiv) + 32'd1)));
  // CPHA edge bins at the chip-select rise (cp_cpha_edge).
  wire cph0 = fr_end && (fr_div != 16'd0) && !fr_cpha && fr_chg_trail_q && !fr_chg_lead_q;
  wire cph1 = fr_end && (fr_div != 16'd0) && fr_cpha && !fr_fullcyc && fr_chg_lead_q &&
      !fr_chg_trail_q;

  // --- SPI host: FIFO effect window (cp_fifo_effect) ---------------------
  logic fe_on_q, fe_rx_q, fe_tx_q, fe_act_q, fe_own_q;
  logic [1:0] fe_dir_q;
  logic       act_q;
  logic [7:0] txqd_q, rxqd_q;
  wire fe_close = fe_on_q && fe_act_q && act_q && !s_act;

  // --- SPI host: error and event history ---------------------------------
  logic il_v_q, il_own_q;  // illegal COMMAND waiting for its ERROR_STATUS read
  logic [3:0] il_cell_q;  // {SPEED, DIRECTION}
  logic cbz_v_q, cbz_act_q;  // COMMAND written while READY = 0
  logic [6:0] cbz_cnt_q;
  logic sz_v_q, sz_spoil_q;  // COMMAND written while SPIEN = 0
  logic run_arm_q;  // waiting for the chip-select fall after SPIEN = 1
  logic txwm_fell_q, txf_q, rxwm_q, txwm_q, txst_q, rxst_q, txe_q, rxe_q, rxf_q, cb_q;
  logic [3:0] cmdqd_q;
  logic [4:0] rxpop_q;                    // clocks left of the RXDATA pop window
  logic [5:0] src_q1, src_q2, evten_q1, evten_q2, held_q;
  logic evt_q, err_q;
  logic       force_seen_q;
  logic [4:0] ies_q;                      // {INTR_ENABLE, INTR_STATE, PIC line}
  logic [1:0] ies_settle_q;
  logic [5:0] es_q, es_arm_q;
  logic       esz_v_q;
  logic [1:0] esz_cnt_q;
  logic       ist_arm_q;
  logic       csr_v_q;
  logic [31:0] csr_val_q;
  logic       swr_clr_q;
  logic       re_arm_q;
  logic [7:0] re_seen_q;
  logic       sep_on_q;

  wire [4:0] ies_now = {s_ien_evt, s_ien_err, s_ist_evt, s_ist_err, irq_spi};
  wire       ev_rise = s_ist_evt && !evt_q;
  wire       ev_fall = !s_ist_evt && evt_q;
  wire [5:0] sel_prev = src_q1 & evten_q1;
  // Index of the register of the first read after a reset (cp_rst_entry_midseg).
  function automatic logic [3:0] rst_reg_idx(input logic [31:0] a);
    if (a == SpiIntrState) return 4'd0;
    if (a == SpiIntrEnable) return 4'd1;
    if (a == SpiControl) return 4'd2;
    if (a == SpiConfigopts) return 4'd3;
    if (a == SpiCsid) return 4'd4;
    if (a == SpiErrEnable) return 4'd5;
    if (a == SpiErrStatus) return 4'd6;
    if (a == SpiEvtEnable) return 4'd7;
    return 4'd8;
  endfunction
  wire [3:0] re_idx = rst_reg_idx(ar_addr_q);
  wire       re_hit = re_arm_q && spi_on && rd_ev && (re_idx != 4'd8) && !re_seen_q[re_idx[2:0]];

  always_ff @(posedge clk_i) begin
    sep_on_q <= spi_on;
    cs_low_q <= cs_low;
    // Issue and AR snapshots. They hold the value before the access lands.
    if (wr_issue) begin
      si_cb_q     <= s_cb;
      si_act_q    <= s_act;
      si_cslow_q  <= cs_low;
      si_txe_q    <= s_txe;
      si_txf_q    <= s_txf;
      si_es_q     <= s_es;
      si_ovf_en_q <= s_een_ovf;
      si_ovf_q    <= s_es[3];
    end
    if (ar_hs) begin
      ra_rxqd_q        <= s_rxqd;
      ra_rxe_q         <= s_rxe;
      ra_rxf_q         <= s_rxf;
      ra_act_q         <= s_act;
      ra_unf_q         <= s_es[2];
      ra_unf_en_q      <= s_een_unf;
      ra_prev_status_q <= spi_last_status_q;
    end
    act_q   <= s_act;
    txqd_q  <= s_txqd;
    rxqd_q  <= s_rxqd;
    cmdqd_q <= s_cmdqd;
    txf_q   <= s_txf;
    txe_q   <= s_txe;
    rxf_q   <= s_rxf;
    rxe_q   <= s_rxe;
    cb_q    <= s_cb;
    txwm_q  <= s_txwm;
    rxwm_q  <= s_rxwm;
    txst_q  <= s_txst;
    rxst_q  <= s_rxst;
    src_q1  <= s_src;
    src_q2  <= src_q1;
    evten_q1 <= s_evten;
    evten_q2 <= evten_q1;
    evt_q   <= s_ist_evt;
    err_q   <= s_ist_err;
    es_q    <= s_es;
    sck_q   <= sck_v;
    if (mosi_known) mosi_q <= (spi_mosi_i === 1'b1);
    ies_q   <= ies_now;
    ies_settle_q <= (ies_now != ies_q) ? 2'd3 : ((ies_settle_q != 2'd0) ? ies_settle_q - 2'd1 : 2'd0);

    // First reads after a reset asserted with chip select low. The window
    // of the owning test is open across the reset, so this state survives
    // it; a write to the SPI window ends it.
    if (sep_on_q && !spi_on && (cs_low || cs_low_q) && own_spi_coldrst) begin
      re_arm_q  <= 1'b1;
      re_seen_q <= '0;
    end else if (re_hit) begin
      re_seen_q[re_idx[2:0]] <= 1'b1;
    end else if (re_arm_q !== 1'b1) begin
      re_arm_q <= 1'b0;  // starts unarmed
    end
    if (spi_on && sw_spi_any) re_arm_q <= 1'b0;

    if (!spi_on) begin
      spi_cfg_q   <= 32'(SPI_CONTROLLER_CONFIGOPTS_REG_DEFAULT);
      spi_ctrl_q  <= 32'(SPI_CONTROLLER_CONTROL_REG_DEFAULT);
      spi_csid_q  <= 32'(SPI_CONTROLLER_CSID_REG_DEFAULT);
      sp_v_q      <= 1'b0;
      sp_csaat_q  <= 1'b0;
      sp_speed_q  <= 2'd0;
      sp_dir_q    <= 2'd0;
      cfg_new_q   <= 1'b0;
      sq_n_q      <= '0;
      sq_idle_q   <= '0;
      fr_on_q     <= 1'b0;
      gap_v_q     <= 1'b0;
      fe_on_q     <= 1'b0;
      il_v_q      <= 1'b0;
      cbz_v_q     <= 1'b0;
      sz_v_q      <= 1'b0;
      run_arm_q   <= 1'b0;
      txwm_fell_q <= 1'b0;
      rxpop_q     <= '0;
      held_q      <= '0;
      force_seen_q <= 1'b0;
      es_arm_q    <= '0;
      esz_v_q     <= 1'b0;
      ist_arm_q   <= 1'b0;
      csr_v_q     <= 1'b0;
      swr_clr_q   <= 1'b0;
      spi_last_status_q <= 1'b0;
    end else begin
      // Latches.
      if (sw_cfg) begin
        spi_cfg_q <= merge4(spi_cfg_q, w_data_q, w_strb_q, SpiConfigopts);
        cfg_new_q <= 1'b1;
      end
      if (sw_ctrl) spi_ctrl_q <= sw_ctrl_d;
      if (sw_csid) spi_csid_q <= merge4(spi_csid_q, w_data_q, w_strb_q, SpiCsid);
      if (sc_accept) begin
        sp_v_q     <= 1'b1;
        sp_csaat_q <= sc_csaat;
        sp_speed_q <= sc_speed;
        sp_dir_q   <= sc_dir;
        cfg_new_q  <= 1'b0;
      end
      if (sr_spi_any) spi_last_status_q <= rhit4(ar_addr_q, ar_size_q, SpiStatus);
      else if (sw_spi_any) spi_last_status_q <= 1'b0;

      // Command queue copy: pop a finished frame, then push. SW_RST clears
      // the queue, and so does a host that has been idle with an empty
      // queue for eight clocks (a command the host did not take).
      if (fr_end && fr_term) begin
        for (int i = 0; i < SpiQ; i++) begin
          if ((i + 32'(fr_k)) < SpiQ) begin
            sq_len_q[i]   <= sq_len_q[i+fr_k];
            sq_csaat_q[i] <= sq_csaat_q[i+fr_k];
            sq_speed_q[i] <= sq_speed_q[i+fr_k];
            sq_dir_q[i]   <= sq_dir_q[i+fr_k];
            sq_own_q[i]   <= sq_own_q[i+fr_k];
          end
        end
      end
      if (sq_push) begin
        sq_len_q[sq_popped]   <= sc_len;
        sq_csaat_q[sq_popped] <= sc_csaat;
        sq_speed_q[sq_popped] <= sc_speed;
        sq_dir_q[sq_popped]   <= sc_dir;
        sq_own_q[sq_popped]   <= own_spi_matrix;
      end
      sq_idle_q <= sq_idle_run ? ((sq_idle_q == 4'd8) ? sq_idle_q : sq_idle_q + 4'd1) : 4'd0;
      sq_n_q <= sq_n_nxt;

      // Frame metrics.
      if (fr_start) begin
        fr_on_q       <= 1'b1;
        fr_idle_q     <= sck_v;
        fr_clk_q      <= 32'd1;
        fr_edges_q    <= '0;
        fr_first_q    <= 1'b0;
        fr_lead_v_q   <= 1'b0;
        fr_per_v_q    <= 1'b0;
        fr_minper_q   <= '1;
        fr_kind_q     <= 2'd0;
        fr_chg_lead_q <= 1'b0;
        fr_chg_trail_q <= 1'b0;
        fr_cfg_q      <= spi_cfg_q;
        gap_v_q       <= 1'b0;
      end else if (fr_end) begin
        fr_on_q <= 1'b0;
        gap_q   <= 32'd1;
        gap_v_q <= 1'b1;
      end else if (fr_on_q) begin
        fr_clk_q <= fr_clk_q + 32'd1;
        if (fr_sck_chg) begin
          fr_last_q <= fr_clk_q;
          if (!fr_lead_v_q) begin
            fr_lead_q   <= fr_clk_q;
            fr_lead_v_q <= 1'b1;
          end
        end
        if (fr_lead_edge) begin
          fr_edges_q    <= fr_edges_q + 32'd1;
          fr_lastlead_q <= fr_clk_q;
          if (fr_first_q) begin
            fr_per_v_q <= 1'b1;
            if ((fr_clk_q - fr_lastlead_q) < fr_minper_q) fr_minper_q <= fr_clk_q - fr_lastlead_q;
          end
          fr_first_q <= 1'b1;
        end
        fr_kind_q <= fr_kind_now;
        if (fr_mosi_chg) begin
          if (fr_kind_now == 2'd1) fr_chg_lead_q <= 1'b1;
          if (fr_kind_now == 2'd2) fr_chg_trail_q <= 1'b1;
        end
      end else if (gap_v_q) begin
        gap_q <= gap_q + 32'd1;
      end

      // FIFO effect window: from an accepted COMMAND written with ACTIVE = 0
      // to the fall of ACTIVE. A second COMMAND or SW_RST in the window
      // ends it with no sample.
      if (sc_accept) begin
        fe_on_q  <= !fe_on_q && !si_act_q;
        fe_dir_q <= sc_dir;
        fe_rx_q  <= 1'b0;
        fe_tx_q  <= 1'b0;
        fe_act_q <= 1'b0;
        fe_own_q <= own_spi_matrix;
      end else if (sw_ctrl && new_swrst) begin
        fe_on_q <= 1'b0;
      end else if (fe_on_q) begin
        if (s_act) fe_act_q <= 1'b1;
        if (s_rxqd > rxqd_q) fe_rx_q <= 1'b1;
        if (s_txqd < txqd_q) fe_tx_q <= 1'b1;
        if (fe_close) fe_on_q <= 1'b0;
      end

      // An illegal COMMAND waits for the next ERROR_STATUS read.
      if (sw_cmd && !sc_legal) begin
        il_v_q    <= 1'b1;
        il_cell_q <= {sc_speed, sc_dir};
        il_own_q  <= own_spi_matrix;
      end else if (sr_errst) begin
        il_v_q <= 1'b0;
      end

      // A COMMAND written while READY = 0 waits up to 64 clocks for the
      // rise of ERROR_STATUS.CMDBUSY.
      if (sw_cmd && si_cb_q) begin
        cbz_v_q   <= 1'b1;
        cbz_act_q <= si_act_q;
        cbz_cnt_q <= 7'd64;
      end else if (cbz_v_q) begin
        if ((s_es[4] && !es_q[4]) || (cbz_cnt_q == 7'd0)) cbz_v_q <= 1'b0;
        else cbz_cnt_q <= cbz_cnt_q - 7'd1;
      end

      // A COMMAND written while SPIEN = 0: the pads stay quiet up to the
      // write of SPIEN = 1, and then chip select falls.
      if (sw_cmd && !ctl_spien && !sz_v_q) begin
        sz_v_q     <= 1'b1;
        sz_spoil_q <= !cs_high;
      end else if (sz_v_q) begin
        if (!cs_high || (sck_v != sck_q)) sz_spoil_q <= 1'b1;
        if (sw_ctrl && new_spien) begin
          sz_v_q    <= 1'b0;
          run_arm_q <= !sz_spoil_q && !(!cs_high || (sck_v != sck_q));
        end
      end
      if (run_arm_q && fr_start) run_arm_q <= 1'b0;

      // TXWM stays 1 from the last CONTROL write.
      if (sw_ctrl) txwm_fell_q <= 1'b0;
      else if (txwm_q && !s_txwm) txwm_fell_q <= 1'b1;
      // RXDATA pop window for the RXWM fall.
      if (ar_hs && rhit4(lsu_ar_addr_i, lsu_ar_size_i, SpiRxdata)) rxpop_q <= 5'd16;
      else if (rxpop_q != 5'd0) rxpop_q <= rxpop_q - 5'd1;

      // Selected sources held since the SPI_EVENT rise.
      if (ev_rise) held_q <= sel_prev;
      else held_q <= held_q & s_src & s_evten;

      if (sw_itest && ((word4(w_data_q, SpiIntrTest) & SPI_CONTROLLER_INTR_TEST_ERROR_MASK) != 0))
        force_seen_q <= 1'b1;
      else if (sw_ist && ((word4(
              w_data_q, SpiIntrState
          ) & SPI_CONTROLLER_INTR_STATE_ERROR_MASK) != 0))
        force_seen_q <= 1'b0;

      // Write-one-to-clear armed per ERROR_STATUS class at the issue clock.
      for (int c = 0; c < 6; c++) begin
        if (wi_errst && wi_errst_d[es_shift(c)]) es_arm_q[c] <= 1'b1;
        else if (es_q[c] && !s_es[c]) es_arm_q[c] <= 1'b0;
      end
      // ERROR_STATUS all clear while INTR_STATE.ERROR is 1: check two
      // clocks later that INTR_STATE.ERROR is still 1.
      if ((es_q != 6'd0) && (s_es == 6'd0) && s_ist_err) begin
        esz_v_q   <= 1'b1;
        esz_cnt_q <= 2'd2;
      end else if (esz_v_q) begin
        if (esz_cnt_q != 2'd0) esz_cnt_q <= esz_cnt_q - 2'd1;
        else esz_v_q <= 1'b0;
      end
      if (wi_ist && wi_ist_d[SPI_CONTROLLER_INTR_STATE_ERROR_SHIFT]) ist_arm_q <= 1'b1;
      else if (err_q && !s_ist_err) ist_arm_q <= 1'b0;

      // CSID range: a COMMAND written with CSID not 0, up to the next
      // ERROR_STATUS write.
      if (sw_cmd && (spi_csid_q != 32'h0)) begin
        csr_v_q   <= 1'b1;
        csr_val_q <= spi_csid_q;
      end else if (sw_errst) begin
        csr_v_q <= 1'b0;
      end

      // SW_RST written 0 after 1: the next CONTROL read shows SW_RST.
      if (sw_ctrl && ctl_swrst && !new_swrst) swr_clr_q <= 1'b1;
      else if (sr_ctrl) swr_clr_q <= 1'b0;
    end
  end

  // --- Secure DMA: addresses and levels ----------------------------------
  localparam logic [31:0] DmaIntrState = SECURE_DMA_INTR_STATE_REG_ADDR;
  localparam logic [31:0] DmaIntrEnable = SECURE_DMA_INTR_ENABLE_REG_ADDR;
  localparam logic [31:0] DmaSrcLo = SECURE_DMA_SRC_ADDR_LO_REG_ADDR;
  localparam logic [31:0] DmaDstLo = SECURE_DMA_DST_ADDR_LO_REG_ADDR;
  localparam logic [31:0] DmaBase = SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR;
  localparam logic [31:0] DmaLimit = SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR;
  localparam logic [31:0] DmaRangeValid = SECURE_DMA_RANGE_VALID_REG_ADDR;
  localparam logic [31:0] DmaTotal = SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR;
  localparam logic [31:0] DmaChunk = SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR;
  localparam logic [31:0] DmaWidth = SECURE_DMA_TRANSFER_WIDTH_REG_ADDR;
  localparam logic [31:0] DmaControl = SECURE_DMA_CONTROL_REG_ADDR;
  localparam logic [31:0] DmaSrcCfg = SECURE_DMA_SRC_CONFIG_REG_ADDR;
  localparam logic [31:0] DmaDstCfg = SECURE_DMA_DST_CONFIG_REG_ADDR;
  localparam logic [31:0] DmaStatus = SECURE_DMA_STATUS_REG_ADDR;
  localparam logic [31:0] DmaDigest0 = SECURE_DMA_SHA2_DIGEST_0_0__REG_ADDR;
  localparam logic [31:0] DmaDigestEnd = SECURE_DMA_SHA2_DIGEST_0_15__REG_ADDR + 32'd4;

  wire d_go_q    = (dma_reg2hw_i.control.go.q === 1'b1);
  wire d_abort   = (dma_reg2hw_i.control.abort.q === 1'b1);
  wire d_busy    = (dma_busy_i === 1'b1);
  wire d_done    = (dma_reg2hw_i.status.done.q === 1'b1);
  wire d_chunk   = (dma_reg2hw_i.status.chunk_done.q === 1'b1);
  wire d_err     = (dma_reg2hw_i.status.error.q === 1'b1);
  wire d_dvalid  = (dma_reg2hw_i.status.sha2_digest_valid.q === 1'b1);
  wire d_ist_err = (dma_reg2hw_i.intr_state.dma_error.q === 1'b1);
  wire d_aborted = (dma_aborted_i === 1'b1);
  wire d_size_err = (dma_err_code_i[SECURE_DMA_ERROR_CODE_SIZE_ERROR_SHIFT] === 1'b1);
  wire d_no_err = (dma_err_code_i === 8'h00);
  wire [3:0]  d_regwen = dma_reg2hw_i.range_regwen.q;
  wire [31:0] d_base_now = dma_reg2hw_i.enabled_memory_range_base.q;
  wire [31:0] d_limit_now = dma_reg2hw_i.enabled_memory_range_limit.q;
  wire        d_valid_now = (dma_reg2hw_i.range_valid.q === 1'b1);
  wire irq_d_done  = (irq_dma_done_i === 1'b1);
  wire irq_d_chunk = (irq_dma_chunk_i === 1'b1);
  wire irq_d_err   = (irq_dma_error_i === 1'b1);
  // DMA master AR and AW handshakes after the alias remap (dma_req_i).
  wire dm_ar = !in_reset && (dma_req_i.ar_valid === 1'b1) && (dma_resp_i.ar_ready === 1'b1);
  wire dm_aw = !in_reset && (dma_req_i.aw_valid === 1'b1) && (dma_resp_i.aw_ready === 1'b1);

  // --- Secure DMA: register decode ---------------------------------------
  wire        dw_ctrl = wr_ev && hit4(aw_addr_q, w_strb_q, DmaControl);
  wire [31:0] dw_ctrl_d = word4(w_data_q, DmaControl);
  wire        d_go = dw_ctrl && ((dw_ctrl_d & SECURE_DMA_CONTROL_GO_MASK) != 32'h0);
  wire [3:0]  dg_op = 4'(fld(dw_ctrl_d, SECURE_DMA_CONTROL_OPCODE_MASK,
                             SECURE_DMA_CONTROL_OPCODE_SHIFT));
  wire        dg_hs = (dw_ctrl_d & SECURE_DMA_CONTROL_HARDWARE_HANDSHAKE_ENABLE_MASK) != 32'h0;
  wire        dg_init = (dw_ctrl_d & SECURE_DMA_CONTROL_INITIAL_TRANSFER_MASK) != 32'h0;
  wire        dg_swap = (dw_ctrl_d & SECURE_DMA_CONTROL_DIGEST_SWAP_MASK) != 32'h0;
  // The GO write at its issue clock (the DMA reacts before the B).
  wire        di_ctrl = wr_issue && hit4(wi_addr, wi_strb, DmaControl);
  wire [31:0] di_ctrl_d = word4(wi_data, DmaControl);
  wire        di_go = di_ctrl && ((di_ctrl_d & SECURE_DMA_CONTROL_GO_MASK) != 32'h0);
  wire [3:0]  di_op = 4'(fld(di_ctrl_d, SECURE_DMA_CONTROL_OPCODE_MASK,
                             SECURE_DMA_CONTROL_OPCODE_SHIFT));
  wire        di_init = (di_ctrl_d & SECURE_DMA_CONTROL_INITIAL_TRANSFER_MASK) != 32'h0;
  wire        di_status = wr_issue && hit4(wi_addr, wi_strb, DmaStatus);
  wire [31:0] di_status_d = word4(wi_data, DmaStatus);
  wire        dr_ctrl = rd_ev && rhit4(ar_addr_q, ar_size_q, DmaControl);
  wire        dr_status = rd_ev && rhit4(ar_addr_q, ar_size_q, DmaStatus);
  wire [31:0] dr_status_d = word4(lsu_r_data_i, DmaStatus);
  wire        dr_ist = rd_ev && rhit4(ar_addr_q, ar_size_q, DmaIntrState);

  // --- Secure DMA: latched fields ----------------------------------------
  logic [31:0] d_src_q, d_dst_q, d_total_q, d_chunk_q, d_base_q, d_limit_q;
  logic [1:0] d_width_q;
  logic d_sinc_q, d_swrap_q, d_dinc_q, d_dwrap_q;
  logic [2:0] d_ien_q;
  logic d_rvalid_q, d_hs_q, d_cgo_q, d_swap_q;
  logic [3:0]  d_op_q;

  wire d_src_sram = in_win(d_src_q, SramBase, SramEnd);
  wire d_dst_sram = in_win(d_dst_q, SramBase, SramEnd);
  wire d_src_spi = in_win(d_src_q, SpiBase, SpiEnd);
  wire d_dst_spi = in_win(d_dst_q, SpiBase, SpiEnd);
  wire [3:0] d_mode = {d_sinc_q, d_swrap_q, d_dinc_q, d_dwrap_q};
  wire d_sizes_ok = (d_total_q != 32'h0) && (d_chunk_q != 32'h0) && (d_total_q >= d_chunk_q);
  wire d_single = d_sizes_ok && (d_total_q == d_chunk_q);
  wire d_multi = d_sizes_ok && (d_total_q > d_chunk_q);
  wire d_multi_exact = d_multi && ((d_total_q % d_chunk_q) == 32'h0);


  // --- Secure DMA: transfer context --------------------------------------
  // Opened by the issue of a GO with INITIAL_TRANSFER = 1. AR and AW count
  // the DMA master handshakes since then.
  logic x_on_q, x_swrap_q, x_dwrap_q;
  logic [31:0] x_ar_q, x_aw_q, x_src_q, x_dst_q, x_total_q, x_chunk_q;
  logic [1:0] x_width_q;
  logic wi_ok_q, wi_ar_q, wi_aw_q;
  logic [7:0] wi_n_q;
  logic cc_rose_q, cdc_wr_q, dc_w1_q, dc_go_q;
  logic        hs_chunk_rose_q;
  logic [31:0] hs_aw_q;
  logic dci_v_q, dci_go_q, dci_hs_q;  // a CONTROL write in flight, its GO and HS bits
  logic d_gswap_q;  // CONTROL.DIGEST_SWAP of the last GO
  logic go_q, busy_q, done_q, chunk_q, dvalid_q, aborted_q, abort_q, size_err_q;
  logic ir_v_q;
  logic [1:0] ir_src_q, ir_dst_q;
  logic dv_arm_q, dv_hash_q;
  logic szk_v_q, hwf_v_q;
  logic [1:0]  szk_q;
  logic        hwf_q;
  logic        ea_v_q;
  logic ab_beat_q, ab_on_q, ab_after_q;
  logic        uc_v_q;
  logic [2:0]  uc_q;
  logic        it_on_q;
  logic [2:0] it_en_q, it_l_q;
  logic [1:0]  it_cls_q;
  logic [3:0]  rv_old_q;   // RANGE_REGWEN at the issue of a range write
  logic [31:0] rb_old_q, rl_old_q;
  logic rvv_old_q;

  // Position of a region against the range: 0 at BASE, 1 interior,
  // 2 at LIMIT (last byte at LIMIT), 3 other.
  function automatic logic [1:0] rng_pos(input logic [31:0] a, input logic [31:0] n,
                                         input logic [31:0] base, input logic [31:0] limit);
    logic [31:0] last;
    last = a + n - 32'd1;
    if (a == base) return 2'd0;
    if (last == limit) return 2'd2;
    if ((a > base) && (last < limit)) return 2'd1;
    return 2'd3;
  endfunction

  // Abort phase class from the read handshakes since the initial GO:
  // 0 first transaction, 1 mid chunk, 2 chunk boundary, 3 final transaction.
  function automatic logic [1:0] abort_cls(input logic [31:0] b, input logic [31:0] total,
                                           input logic [31:0] chunk, input logic [1:0] width);
    logic [31:0] k, n_all, r;
    k = chunk >> width;
    n_all = total >> width;
    if (b <= 32'd1) return 2'd0;
    if ((n_all != 32'd0) && (b + 32'd1 >= n_all)) return 2'd3;
    if (k != 32'd0) begin
      r = b % k;
      if ((b + 32'd1 >= k) && (b <= n_all - k + 32'd1) && ((r <= 32'd1) || (r + 32'd1 >= k)))
        return 2'd2;
    end
    return 2'd1;
  endfunction

  // Last digest word of the GO'd hash: SHA-256 8 words, SHA-384 12, SHA-512 16.
  function automatic logic [4:0] dg_last(input logic [3:0] op);
    case (op)
      DmaOpSha256: return 5'd7;
      DmaOpSha384: return 5'd11;
      DmaOpSha512: return 5'd15;
      default: return 5'd31;
    endcase
  endfunction

  // cp_irq_x_enable cell and its sample strobe. sep_dma_rand_cg samples on
  // the clock, so the cell is a flop set at the INTR_STATE read.
  logic [4:0] dma_irq_cell_q;
  logic       dma_irq_cell_ev_q;
  // The PIC lines {source 11, 10, 9} held from the GO write, checked
  // against the enable and the event on the lines CHK-DMA-IRQ grades: a
  // disabled line is 0; an enabled line is 1 for its event and 0 for an
  // error-free copy (source 11). Not compared: source 10 of a single-chunk
  // copy, and sources 9 and 10 of the zero-size error.
  function automatic logic irq_gate(input logic [2:0] en, input logic [2:0] l,
                                    input logic [1:0] cls);
    logic ok;
    ok = 1'b1;
    for (int i = 0; i < 3; i++) if (!en[i] && l[i]) ok = 1'b0;
    case (cls)
      2'd0: begin  // single_chunk_done
        if (en[0] && !l[0]) ok = 1'b0;
        if (en[2] && l[2]) ok = 1'b0;
      end
      2'd1: begin  // multi_chunk_done
        if (en[0] && !l[0]) ok = 1'b0;
        if (en[1] && !l[1]) ok = 1'b0;
        if (en[2] && l[2]) ok = 1'b0;
      end
      2'd2: begin  // error_zero_size
        if (en[2] && !l[2]) ok = 1'b0;
      end
      default: ok = 1'b0;
    endcase
    return ok;
  endfunction

  always_ff @(posedge clk_i) begin
    go_q       <= d_go_q;
    busy_q     <= d_busy;
    done_q     <= d_done;
    chunk_q    <= d_chunk;
    dvalid_q   <= d_dvalid;
    aborted_q  <= d_aborted;
    abort_q    <= d_abort;
    size_err_q <= d_size_err;
    dma_irq_cell_ev_q <= 1'b0;
    if (wr_issue) begin
      rv_old_q  <= d_regwen;
      rb_old_q  <= d_base_now;
      rl_old_q  <= d_limit_now;
      rvv_old_q <= d_valid_now;
    end
    if (!spi_on) begin
      d_src_q    <= 32'(SECURE_DMA_SRC_ADDR_LO_REG_DEFAULT);
      d_dst_q    <= 32'(SECURE_DMA_DST_ADDR_LO_REG_DEFAULT);
      d_total_q  <= 32'(SECURE_DMA_TOTAL_DATA_SIZE_REG_DEFAULT);
      d_chunk_q  <= 32'(SECURE_DMA_CHUNK_DATA_SIZE_REG_DEFAULT);
      d_base_q   <= 32'(SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_DEFAULT);
      d_limit_q  <= 32'(SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_DEFAULT);
      d_width_q  <= 2'(SECURE_DMA_TRANSFER_WIDTH_REG_DEFAULT);
      {d_swrap_q, d_sinc_q} <= 2'(SECURE_DMA_SRC_CONFIG_REG_DEFAULT);
      {d_dwrap_q, d_dinc_q} <= 2'(SECURE_DMA_DST_CONFIG_REG_DEFAULT);
      d_ien_q    <= 3'(SECURE_DMA_INTR_ENABLE_REG_DEFAULT);
      d_rvalid_q <= 1'(SECURE_DMA_RANGE_VALID_REG_DEFAULT);
      d_hs_q     <= 1'b0;
      d_cgo_q    <= 1'b0;
      d_swap_q   <= 1'b0;
      d_op_q     <= 4'h0;
      d_gswap_q  <= 1'b0;
      x_on_q     <= 1'b0;
      dci_v_q    <= 1'b0;
      ir_v_q     <= 1'b0;
      dv_arm_q   <= 1'b0;
      dv_hash_q  <= 1'b0;
      szk_v_q    <= 1'b0;
      hwf_v_q    <= 1'b0;
      ea_v_q     <= 1'b0;
      ab_on_q    <= 1'b0;
      ab_beat_q  <= 1'b0;
      uc_v_q     <= 1'b0;
      it_on_q    <= 1'b0;
      dc_w1_q    <= 1'b0;
      dc_go_q    <= 1'b0;
      cdc_wr_q   <= 1'b0;
      cc_rose_q  <= 1'b0;
      hs_chunk_rose_q <= 1'b0;
      hs_aw_q    <= '0;
    end else begin
      // Latches.
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaSrcLo))
        d_src_q <= merge4(d_src_q, w_data_q, w_strb_q, DmaSrcLo);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaDstLo))
        d_dst_q <= merge4(d_dst_q, w_data_q, w_strb_q, DmaDstLo);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaTotal))
        d_total_q <= merge4(d_total_q, w_data_q, w_strb_q, DmaTotal);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaChunk))
        d_chunk_q <= merge4(d_chunk_q, w_data_q, w_strb_q, DmaChunk);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaBase))
        d_base_q <= merge4(d_base_q, w_data_q, w_strb_q, DmaBase);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaLimit))
        d_limit_q <= merge4(d_limit_q, w_data_q, w_strb_q, DmaLimit);
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaWidth))
        d_width_q <= 2'(fld(
            word4(
                w_data_q, DmaWidth
            ),
            SECURE_DMA_TRANSFER_WIDTH_TRANSACTION_WIDTH_MASK,
            SECURE_DMA_TRANSFER_WIDTH_TRANSACTION_WIDTH_SHIFT
        ));
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaSrcCfg)) begin
        d_sinc_q  <= (word4(w_data_q, DmaSrcCfg) & SECURE_DMA_SRC_CONFIG_INCREMENT_MASK) != 0;
        d_swrap_q <= (word4(w_data_q, DmaSrcCfg) & SECURE_DMA_SRC_CONFIG_WRAP_MASK) != 0;
      end
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaDstCfg)) begin
        d_dinc_q  <= (word4(w_data_q, DmaDstCfg) & SECURE_DMA_DST_CONFIG_INCREMENT_MASK) != 0;
        d_dwrap_q <= (word4(w_data_q, DmaDstCfg) & SECURE_DMA_DST_CONFIG_WRAP_MASK) != 0;
      end
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaIntrEnable))
        d_ien_q <= 3'(word4(w_data_q, DmaIntrEnable));
      if (wr_ev && hit4(aw_addr_q, w_strb_q, DmaRangeValid))
        d_rvalid_q <= (word4(
            w_data_q, DmaRangeValid
        ) & SECURE_DMA_RANGE_VALID_RANGE_VALID_MASK) != 0;
      if (dw_ctrl) begin
        d_hs_q   <= dg_hs;
        d_cgo_q  <= (dw_ctrl_d & SECURE_DMA_CONTROL_GO_MASK) != 32'h0;
        d_swap_q <= dg_swap;
        if (d_go) begin
          d_op_q    <= dg_op;
          d_gswap_q <= dg_swap;
        end
      end

      // A CONTROL write in flight, from its issue to its B.
      if (di_ctrl) begin
        dci_v_q  <= 1'b1;
        dci_go_q <= di_go;
        dci_hs_q <= (di_ctrl_d & SECURE_DMA_CONTROL_HARDWARE_HANDSHAKE_ENABLE_MASK) != 32'h0;
      end else if (b_hs) begin
        dci_v_q <= 1'b0;
      end

      // Transfer context.
      if (di_go && di_init) begin
        x_on_q    <= 1'b1;
        x_ar_q    <= '0;
        x_aw_q    <= '0;
        x_src_q   <= d_src_q;
        x_dst_q   <= d_dst_q;
        x_total_q <= d_total_q;
        x_chunk_q <= d_chunk_q;
        x_width_q <= d_width_q;
        x_swrap_q <= d_swrap_q;
        x_dwrap_q <= d_dwrap_q;
        wi_ok_q   <= 1'b1;
        wi_n_q    <= '0;
        wi_ar_q   <= 1'b0;
        wi_aw_q   <= 1'b0;
        cc_rose_q <= 1'b0;
        ab_beat_q <= 1'b0;
      end else begin
        if (di_go && !di_init) begin
          // A later chunk: its first beat on a WRAP side is checked.
          wi_ar_q <= x_swrap_q;
          wi_aw_q <= x_dwrap_q;
        end
        if (dm_ar) begin
          x_ar_q <= x_ar_q + 32'd1;
          if (wi_ar_q) begin
            wi_ar_q <= 1'b0;
            wi_n_q  <= wi_n_q + 8'd1;
            if (dma_req_i.ar.addr[31:2] != x_src_q[31:2]) wi_ok_q <= 1'b0;
          end
        end
        if (dm_aw) begin
          x_aw_q <= x_aw_q + 32'd1;
          if (wi_aw_q) begin
            wi_aw_q <= 1'b0;
            wi_n_q  <= wi_n_q + 8'd1;
            if (dma_req_i.aw.addr[31:2] != x_dst_q[31:2]) wi_ok_q <= 1'b0;
          end
        end
        if (dm_ar || dm_aw) ab_beat_q <= 1'b1;
        if (d_chunk && !chunk_q) cc_rose_q <= 1'b1;
      end

      // GO rise in handshake mode: write beats and CHUNK_DONE since then.
      if (d_go_q && !go_q) begin
        hs_aw_q         <= '0;
        hs_chunk_rose_q <= 1'b0;
      end else begin
        if (dm_aw) hs_aw_q <= hs_aw_q + 32'd1;
        if (d_chunk && !chunk_q) hs_chunk_rose_q <= 1'b1;
      end

      // DONE clear path: since the DONE rise, a GO and no write of 1 to
      // STATUS.DONE.
      if (d_done && !done_q) begin
        dc_w1_q <= 1'b0;
        dc_go_q <= 1'b0;
      end else begin
        if (di_status && ((di_status_d & SECURE_DMA_STATUS_DONE_MASK) != 0)) dc_w1_q <= 1'b1;
        if (di_go) dc_go_q <= 1'b1;
      end
      // CHUNK_DONE clear: no STATUS write since the CHUNK_DONE rise.
      if (d_chunk && !chunk_q) cdc_wr_q <= 1'b0;
      else if (di_status) cdc_wr_q <= 1'b1;

      // In-range position of each side at the initial GO, scored at DONE.
      if (d_go && dg_init) begin
        ir_v_q   <= 1'b1;
        ir_src_q <= rng_pos(d_src_q, d_total_q, d_base_q, d_limit_q);
        ir_dst_q <= rng_pos(d_dst_q, d_total_q, d_base_q, d_limit_q);
      end else if (d_done && !done_q) begin
        ir_v_q <= 1'b0;
      end

      // Digest valid lifecycle.
      if (di_go && di_init && (di_op != DmaOpCopy)) dv_arm_q <= 1'b1;
      else if ((dvalid_q && !d_dvalid) ||
               (dr_status && ((dr_status_d & SECURE_DMA_STATUS_BUSY_MASK) != 0) &&
                ((dr_status_d & SECURE_DMA_STATUS_SHA2_DIGEST_VALID_MASK) == 0)))
        dv_arm_q <= 1'b0;
      if (di_go && (di_op != DmaOpCopy)) dv_hash_q <= 1'b1;
      else if (d_dvalid && !dvalid_q) dv_hash_q <= 1'b0;

      // Configuration faults: the GO kind waits for the SIZE_ERROR rise.
      if (di_go) begin
        szk_v_q <= (d_total_q == 32'h0) || (d_chunk_q == 32'h0);
        szk_q   <= (d_total_q == 32'h0) ? ((d_chunk_q == 32'h0) ? 2'd2 : 2'd0) : 2'd1;
        hwf_v_q <= (di_op != DmaOpCopy) && (d_width_q <= 2'd1);
        hwf_q   <= d_width_q[0];
      end else if (d_size_err && !size_err_q) begin
        szk_v_q <= 1'b0;
        hwf_v_q <= 1'b0;
      end
      // SIZE_ERROR rise to STATUS.ERROR and INTR_STATE.DMA_ERROR both 1,
      // before a write of 1 to STATUS.ERROR.
      if (d_size_err && !size_err_q) ea_v_q <= 1'b1;
      else if (ea_v_q && ((d_err && d_ist_err) ||
                          (di_status && ((di_status_d & SECURE_DMA_STATUS_ERROR_MASK) != 0))))
        ea_v_q <= 1'b0;

      // Abort: beats while ABORTED is 1.
      if (d_aborted && !aborted_q) begin
        ab_on_q    <= ab_beat_q;
        ab_after_q <= 1'b0;
      end else if (ab_on_q) begin
        if (dm_ar || dm_aw) ab_after_q <= 1'b1;
        if (aborted_q && !d_aborted) ab_on_q <= 1'b0;
      end

      // SPI-to-SRAM handshake use case: armed at the GO, scored at the
      // first Rx COMMAND write while the latched GO is 1.
      if (d_go && d_src_spi) begin
        uc_v_q <= 1'b1;
        uc_q   <= {d_dst_sram, (dg_op == DmaOpCopy), dg_hs};
      end else if (sw_cmd && (sc_dir == SpiDirRx)) begin
        uc_v_q <= 1'b0;
      end

      // Interrupt trial: lines held from the GO issue to the INTR_STATE read.
      if (di_go && di_init && (di_op == DmaOpCopy)) begin
        it_on_q  <= 1'b1;
        it_en_q  <= d_ien_q;
        it_l_q   <= {irq_d_err, irq_d_chunk, irq_d_done};
        it_cls_q <= (d_total_q == 32'h0) ? 2'd2 : (d_single ? 2'd0 : (d_multi ? 2'd1 : 2'd3));
      end else if (it_on_q) begin
        it_l_q <= it_l_q | {irq_d_err, irq_d_chunk, irq_d_done};
        if (dr_ist) begin
          it_on_q           <= 1'b0;
          dma_irq_cell_q    <= {it_en_q, it_cls_q};
          dma_irq_cell_ev_q <= own_dma_irq && (it_cls_q != 2'd3) &&
              irq_gate(it_en_q, it_l_q | {irq_d_err, irq_d_chunk, irq_d_done}, it_cls_q);
        end
      end
    end
  end

  // --- Inbound filter ----------------------------------------------------
  wire filt_cfg_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      (((aw_addr_q - FiltBase) % FiltStride) == FiltCfgOff);
  // START_ADDR and END_ADDR are 64-bit registers that hold a 56-bit address.
  // Each is written as two 32-bit halves (or one 64-bit beat); the byte lanes
  // say which half a write carries.
  wire filt_start_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      ((((aw_addr_q - FiltBase) % FiltStride) & ~32'h4) == FiltStartOff);
  wire filt_end_wr = wr_ev && in_win(aw_addr_q, FiltBase, FiltEnd) &&
      ((((aw_addr_q - FiltBase) % FiltStride) & ~32'h4) == FiltEndOff);
  wire filt_lo_lane = (w_strb_q[3:0] == 4'hF);
  wire filt_hi_lane = (w_strb_q[7:4] == 4'hF);
  wire filt_read_ok_w = (wr_data & 32'(FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_MASK)) != 32'h0;
  wire filt_write_ok_w = (wr_data & 32'(FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_MASK)) != 32'h0;

  // The window has to be latched as ONE entry. Independent last-writes would
  // build a window out of a START from one entry, an END from another and an
  // ENABLE from a third - a window the DUT never had. The programming order is
  // START, END, then the enabling FILTER_CONFIG (sep_inbound_filter_rule_seq,
  // sep_fabric_entry_walk_seq), so the entry is committed at that CONFIG write
  // and only when all four address halves came from the same entry.
  function automatic logic [31:0] filt_entry_of(logic [31:0] a);
    return (a - FiltBase) / FiltStride;
  endfunction

  logic [55:0] filt_start_q, filt_end_q;
  logic [31:0] filt_sl_entry_q, filt_sh_entry_q, filt_el_entry_q, filt_eh_entry_q;
  logic [31:0] filt_win_entry_q;
  logic [55:0] filt_win_lo_q, filt_win_hi_q;
  logic filt_win_valid_q;
  // FILTER_CONFIG READ_ALLOWED / WRITE_ALLOWED of the committed entry. An OKAY
  // in a direction the entry does not allow came from another entry or the
  // default policy, so it does not score this window.
  logic filt_win_rd_q, filt_win_wr_q;
  wire [31:0] filt_cfg_entry = filt_entry_of(aw_addr_q);
  wire filt_halves_match = (filt_sl_entry_q == filt_cfg_entry) &&
      (filt_sh_entry_q == filt_cfg_entry) && (filt_el_entry_q == filt_cfg_entry) &&
      (filt_eh_entry_q == filt_cfg_entry);

  wire m_aw_hs = !in_reset && (m_axi_awvalid_i === 1'b1) && (m_axi_awready_i === 1'b1);
  wire m_ar_hs = !in_reset && (m_axi_arvalid_i === 1'b1) && (m_axi_arready_i === 1'b1);
  wire m_b_ok  = !in_reset && (m_axi_bvalid_i === 1'b1) && (m_axi_bready_i === 1'b1) &&
      (m_axi_bresp_i == AxiOkay);
  wire m_r_ok  = !in_reset && (m_axi_rvalid_i === 1'b1) && (m_axi_rready_i === 1'b1) &&
      (m_axi_rlast_i === 1'b1) && (m_axi_rresp_i == AxiOkay);

  logic [55:0] m_aw_addr_q, m_ar_addr_q;
  // Same pairing contract as the LSU side: sep_axi_order_sweep_m_axi_test
  // runs several inbound transactions at once, and a plain
  // last-write latch would pair one access's response with another's address.
  logic [3:0] m_aw_out_q, m_ar_out_q;
  wire [4:0] m_rd_depth = 5'(m_ar_out_q) + 5'd1;
  // The inbound filter sits in sep_system_peripherals, which resets on
  // sep_reset_n (sep.sv u_sep_system_peripherals), so the counts restart
  // when that reset asserts. A response with no count is a transaction that
  // reset dropped and does not decrement.
  logic      m_sep_rst_n_q;
  wire       m_clear = in_reset || (m_sep_rst_n_q && (sep_reset_n_i === 1'b0));
  wire       m_b_hs = (m_axi_bvalid_i === 1'b1) && (m_axi_bready_i === 1'b1);
  wire       m_r_last_hs = (m_axi_rvalid_i === 1'b1) && (m_axi_rready_i === 1'b1) &&
      (m_axi_rlast_i === 1'b1);

  always_ff @(posedge clk_i) begin
    m_sep_rst_n_q <= (sep_reset_n_i !== 1'b0);
    if (m_clear) begin
      m_aw_out_q <= '0;
      m_ar_out_q <= '0;
    end else begin
      m_aw_out_q <= m_aw_out_q + (m_aw_hs ? 4'd1 : 4'd0) -
          ((m_b_hs && ((m_aw_out_q != 4'd0) || m_aw_hs)) ? 4'd1 : 4'd0);
      m_ar_out_q <= m_ar_out_q + (m_ar_hs ? 4'd1 : 4'd0) -
          ((m_r_last_hs && ((m_ar_out_q != 4'd0) || m_ar_hs)) ? 4'd1 : 4'd0);
    end
  end

  // The PROGRAMMED range, not its 4 KB page. traffic_filter.sv compares
  // addr[.:12] only in the allow_burst arm; the other arm compares
  // addr[.:DATA_BUS_WIDTH_LOG2]. A page compare is therefore a superset of the
  // real grant, and would score an OKAY that landed inside the page but
  // outside the window the test programmed. Comparing the range can only
  // MISS a page-widened grant, never invent one.
  // The compare is on all 56 address bits.
  function automatic logic in_allow_window(logic [55:0] a);
    return filt_win_valid_q && (a >= filt_win_lo_q) && (a <= filt_win_hi_q);
  endfunction

  wire filt_allow_wr = m_b_ok && (m_aw_out_q == 4'd1) && filt_win_wr_q &&
      in_allow_window(m_aw_addr_q);
  wire filt_allow_rd = m_r_ok && (m_ar_out_q == 4'd1) && filt_win_rd_q &&
      in_allow_window(m_ar_addr_q);

  // --- peer-side mailbox fill --------------------------------------------
  // A completed external write to the inbound mailbox WRITE_DATA register: the
  // only way anything reaches the host aperture's receive FIFO. The host-side
  // mailbox bins below are all IRQ edges and are hit by the transmit path, so
  // none of them shows the receive direction was ever driven. Both halves of
  // the 8-byte register alias to it, so the compare masks bit 2.
  wire m_mbox_peer_wr = m_b_ok && (m_aw_out_q == 4'd1) &&
      ((m_aw_addr_q[31:0] & ~32'h4) == AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_REG_ADDR);

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
  // PROGRAM_STATUS is the outcome only on a read that also shows DONE: GO
  // clears DONE but not STATUS, and both update together when the program
  // ends (efuse_program_interface.sv), so a STATUS read while busy still holds
  // the previous program's outcome.
  wire        efuse_prog_err = efuse_prog_done &&
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
  logic [SpareCount-1:0] spare_locked_q;   // write-lock program completed for spare k
  logic [SpareIdxW-1:0]  prog_spare_q;     // spare targeted by the pending GO
  logic                  prog_pending_q;   // a data program is awaiting its outcome
  logic                  prog_locked_q;    // was that spare locked when it was issued
  // A lock-bit program marks the spare locked only when it completes with
  // DONE and a clear STATUS. A refused lock program leaves the spare open.
  logic [SpareIdxW-1:0]  lock_spare_q;
  logic                  lock_pending_q;
  wire                   lock_done = lock_pending_q && efuse_prog_done && !efuse_prog_err;

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
  // 2'b00 and 2'b11 are unreachable by design.
  // sep_efuse_illegal_state_fail_closed_test injects them; ordinary traffic
  // scores nothing here because the legal encodings land in no bin.
  localparam logic [1:0] EfuseStIdle = 2'b01;
  localparam logic [1:0] EfuseStWait = 2'b10;
  wire efuse_rd_illegal = !in_reset &&
      !(efuse_read_state_i inside {EfuseStIdle, EfuseStWait});
  wire efuse_pg_illegal = !in_reset &&
      !(efuse_program_state_i inside {EfuseStIdle, EfuseStWait});

  // --- Lifecycle feature control ------------------------------------------
  // FEAT_CTRL is 64-bit, read as two 32-bit halves. Aggregate the DEFINED
  // debug bits into none/partial/full:
  // DBG_1 = sep_debug, chiplet_dbg, sep_fuse_dbg, smc_fuse_dbg (bits 0..3) and
  // DBG_2 = sip_debug (bit 24). cocotb/env/sep_lcc_golden.py is the layout
  // authority.
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
  // The state axis comes from the sensed shadow, which reads 0x0 (TEST_DEV)
  // until a real sense completes. A read before that, or on a +skip_fuse_sense
  // run, describes no sensed state and does not sample.
  wire         feat_ctrl_sample = feat_ctrl_hi_rd && !skip_fuse_sense_q &&
      (fuse_sense_done_i === 1'b1);

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
  wire rd_cmpl = !in_reset && r_hs && (ar_out_q == 4'd1) && !r_multi_q;
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
  // Per-channel edges. The OR above hides a channel stuck at 0 behind any
  // other channel; these name the channel.
  logic [7:0] irq_mailbox_vec_q;
  wire  [7:0] mbox_ch_raise = (in_reset || $isunknown(irq_mailbox_i)) ? 8'h00 :
      (irq_mailbox_i & ~irq_mailbox_vec_q);
  wire  [7:0] mbox_ch_clear = (in_reset || $isunknown(irq_mailbox_i)) ? 8'h00 :
      (~irq_mailbox_i & irq_mailbox_vec_q);
  // WIRQT writes on any mailbox. The banks interleave at 0x800, so the
  // offset inside a bank names the register.
  localparam logic [31:0] MboxBankMask = 32'h7FF;
  wire        mbox_wirqt_wr = wr_ev &&
      in_blk(aw_addr_q, AXIL_MAILBOX_REG_MAP_BASE_ADDR, AXIL_MAILBOX_REG_MAP_SIZE) &&
      (((aw_addr_q - AXIL_MAILBOX_REG_MAP_BASE_ADDR) & MboxBankMask) ==
       AXIL_MAILBOX_INBOUND_MAILBOX_0_WIRQT_REG_OFFSET);
  // A WIRQT value is scored at the next push to the same mailbox, so the
  // threshold was in place for a transfer. A register walk that writes WIRQT
  // and never pushes after it does not score.
  wire  [31:0] mbox_off = aw_addr_q - AXIL_MAILBOX_REG_MAP_BASE_ADDR;
  wire  [3:0] mbox_bank = 4'(mbox_off >> 11);
  wire        mbox_push = wr_ev &&
      in_blk(aw_addr_q, AXIL_MAILBOX_REG_MAP_BASE_ADDR, AXIL_MAILBOX_REG_MAP_SIZE) &&
      ((mbox_off & MboxBankMask & ~32'h4) == AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_REG_OFFSET);
  logic [7:0] mbox_wirqt_q;
  logic [3:0] mbox_wirqt_bank_q;
  logic       mbox_wirqt_pend_q;
  wire        mbox_wirqt_used = mbox_push && mbox_wirqt_pend_q && (mbox_bank == mbox_wirqt_bank_q);

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      mbox_wirqt_pend_q <= 1'b0;
    end else if (mbox_wirqt_wr) begin
      mbox_wirqt_q      <= 8'(wr_data & AXIL_MAILBOX_WIRQT_WIRQT_MASK);
      mbox_wirqt_bank_q <= mbox_bank;
      mbox_wirqt_pend_q <= 1'b1;
    end else if (mbox_wirqt_used) begin
      mbox_wirqt_pend_q <= 1'b0;
    end
  end
  // The KM mailbox edges count once software enabled a KM mailbox interrupt
  // (a non-zero SEP_IRQ_ENABLE write). A leaf that never enables one is not
  // exercising the mailbox interrupt path.
  logic km_irq_en_q;
  wire  km_irq_en_wr = wr_ev && (aw_addr_q == KM_MAILBOX_SEP_SEP_IRQ_ENABLE_REG_ADDR);
  wire  km_mbox_raise = !in_reset && km_irq_en_q && (irq_km_mbox_i === 1'b1) && !irq_km_mbox_q;
  wire  km_mbox_clear = !in_reset && km_irq_en_q && (irq_km_mbox_i === 1'b0) && irq_km_mbox_q;

  // --- WDT ---------------------------------------------------------------
  wire wdt_thold_wr_ev = wr_ev && (aw_addr_q == WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR);
  wire wdt_bark = rd_ev && (ar_addr_q == WDT_TIMER_INTR_STATE_REG_ADDR) &&
      ((rd_data & WdtBarkMask) != 32'h0);
  logic wdt_bark_irq_q, wdt_thold_q;
  wire  wdt_bark_rise = !in_reset && (wdt_bark_irq_i === 1'b1) && !wdt_bark_irq_q;
  // A bark-threshold write that the watchdog then acted on: the bark
  // interrupt rises after it. A register walk writes the threshold with the
  // watchdog disabled, so no bark follows and the bin stays empty.
  wire  wdt_thold_wr = wdt_bark_rise && wdt_thold_q;
  // The NMI bin is an exception taken as an interrupt while the bark
  // interrupt, which is the CPU NMI input, is high. This does not depend on
  // when firmware reads INTR_STATE: the handler reads it after the trap.
  wire  wdt_nmi = !in_reset && (cpu_trace_valid_i === 1'b1) &&
      (cpu_trace_exc_i === 1'b1) && (cpu_trace_interrupt_i === 1'b1) &&
      (wdt_bark_irq_i === 1'b1);

  // --- Warm / cold scratch ----------------------------------------------
  wire warm_wr_ev = wr_ev && in_win(aw_addr_q, WarmBase, WarmEnd);
  wire cold_wr_ev = wr_ev && in_win(aw_addr_q, ColdBase, ColdEnd);

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
  // A staged write is scored at the warm reset that it was staged for. Many
  // bus leaves use scratch as plain storage and never reset it; those writes
  // do not fill the scratch-reset group.
  wire         warm_write = warm_reset_fall && warm_written_q;
  wire         cold_write = warm_reset_fall && cold_valid_q;

  // History that OUTLIVES reset, so it cannot sit in the reset-bearing
  // always_ff above. A programmed OTP lock bit is permanent, and a re-sense
  // follows a cold reset. `initial` seeds them because there is no reset term.
  initial begin
    spare_locked_q    = '0;
    fuse_sense_seen_q = 1'b0;
  end

  always @(posedge clk_i) begin
    if (lock_done) spare_locked_q[lock_spare_q] <= 1'b1;
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
      abr_keygen_armed_q <= 1'b0;
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
      km_cmd_id_q       <= '0;
      km_load_words_q   <= '0;
      km_raw_left_q     <= '0;
      dma_copy_q        <= 1'b0;
      dma_hs_q          <= 1'b0;
      dma_hash_q        <= 1'b0;
      filt_win_valid_q  <= 1'b0;
      filt_sl_entry_q    <= 32'hFFFF_FFFF;
      filt_sh_entry_q    <= 32'hFFFF_FFFF;
      filt_el_entry_q    <= 32'hFFFF_FFFF;
      filt_eh_entry_q    <= 32'hFFFF_FFFF;
      filt_win_entry_q   <= 32'hFFFF_FFFF;
      lc_prev_valid_q   <= 1'b0;
      feat_lo_valid_q   <= 1'b0;
      prog_pending_q    <= 1'b0;
      lock_pending_q    <= 1'b0;
      wdt_bark_irq_q    <= 1'b0;
      wdt_thold_q       <= 1'b0;
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
      spi_cs_n_q        <= 1'b1;
      spi_cmd_q         <= 1'b0;
      spi_sck_q         <= 1'b0;
      irq_mailbox_q     <= 1'b0;
      irq_mailbox_vec_q <= 8'h00;
      irq_km_mbox_q     <= 1'b0;
      km_irq_en_q       <= 1'b0;
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

      if (abr_keygen) begin
        abr_keygen_q       <= 1'b1;
        abr_keygen_armed_q <= 1'b0;
      end
      if (abr_keygen_q && abr_status_clear) abr_keygen_armed_q <= 1'b1;
      if (abr_done) begin
        abr_keygen_q       <= 1'b0;
        abr_keygen_armed_q <= 1'b0;
      end

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
      // when payload_len > 0. After a CMD_SRAM_LOAD_EXEC success the SEP
      // streams exactly FW_WORDS raw image words and a CRC-32C trailer outside
      // the message framing (hw/ip/key_manager/doc/firmware.adoc,
      // CMD_SRAM_LOAD_EXEC), so those writes are counted off, not parsed.
      if (km_reset_wr) begin
        // A KM software reset restarts the ROM's frame state; an abandoned
        // frame on either side does not carry over.
        km_cmd_hdr_next_q <= 1'b1;
        km_cmd_idx_q      <= '0;
        km_rsp_idx_q      <= '0;
        km_rsp_arm_q      <= 1'b0;
        km_raw_left_q     <= '0;
      end else if (km_wr_data && (km_raw_left_q != '0)) begin
        km_raw_left_q <= km_raw_left_q - 17'd1;
      end else if (km_wr_data) begin
        if (km_cmd_hdr_next_q) begin
          km_cmd_len_q      <= wr_data[23:16];
          km_cmd_id_q       <= wr_data[15:8];
          km_cmd_idx_q      <= 9'd0;
          km_cmd_hdr_next_q <= (wr_data[23:16] == 8'h00);
          km_rsp_idx_q      <= 9'd0;
          km_rsp_arm_q      <= 1'b1;
        end else begin
          if ((km_cmd_idx_q == 9'd0) && (km_cmd_id_q == KmCmdSramLoadExec))
            km_load_words_q <= wr_data[15:0];
          km_cmd_idx_q      <= km_cmd_idx_q + 9'd1;
          // last word of the frame = payload_len + 1 (the CRC word)
          km_cmd_hdr_next_q <= ((km_cmd_idx_q + 9'd1) >= (9'(km_cmd_len_q) + 9'd1));
        end
      end
      if (km_load_accepted) km_raw_left_q <= 17'(km_load_words_q) + 17'd1;

      // KM response frame: header, then payload [cmd_seq, cmd_id, rc, arg].
      // Index only while a response is pending. The mailbox tests also read
      // READ_DATA outside a frame (FIFO depth, flush), and an unindexed read
      // would shift a later word onto index 4 and false-hit cp_generate.
      if (km_rd_data && km_rsp_arm_q && !km_reset_wr) begin
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

      if (filt_start_wr && filt_lo_lane) begin
        filt_start_q[31:0] <= w_data_q[31:0];
        filt_sl_entry_q    <= filt_entry_of(aw_addr_q);
      end
      if (filt_start_wr && filt_hi_lane) begin
        filt_start_q[55:32] <= w_data_q[55:32];
        filt_sh_entry_q     <= filt_entry_of(aw_addr_q);
      end
      if (filt_end_wr && filt_lo_lane) begin
        filt_end_q[31:0] <= w_data_q[31:0];
        filt_el_entry_q  <= filt_entry_of(aw_addr_q);
      end
      if (filt_end_wr && filt_hi_lane) begin
        filt_end_q[55:32] <= w_data_q[55:32];
        filt_eh_entry_q   <= filt_entry_of(aw_addr_q);
      end
      if (filt_cfg_wr) begin
        if (((wr_data & FiltEnMask) != 32'h0) && filt_halves_match) begin
          filt_win_valid_q <= 1'b1;
          filt_win_entry_q <= filt_entry_of(aw_addr_q);
          filt_win_lo_q    <= filt_start_q;
          filt_win_hi_q    <= filt_end_q;
          filt_win_rd_q    <= filt_read_ok_w;
          filt_win_wr_q    <= filt_write_ok_w;
        end else if (((wr_data & FiltEnMask) == 32'h0) && (filt_win_entry_q == filt_entry_of(
                aw_addr_q
            ))) begin
          // disable_all() clears the entry the window came from.
          filt_win_valid_q <= 1'b0;
        end
      end
      if (m_aw_hs) m_aw_addr_q <= m_axi_awaddr_i;
      if (m_ar_hs) m_ar_addr_q <= m_axi_araddr_i;

      if (efuse_prog_go && prog_is_spare) begin
        prog_spare_q   <= prog_spare_idx;
        prog_locked_q  <= spare_locked_q[prog_spare_idx];
        prog_pending_q <= 1'b1;
      end
      if (prog_pending_q && efuse_prog_done) prog_pending_q <= 1'b0;
      if (efuse_prog_go && prog_is_lock) begin
        lock_spare_q   <= prog_lock_idx;
        lock_pending_q <= 1'b1;
      end else if (efuse_prog_go) begin
        lock_pending_q <= 1'b0;
      end
      if (lock_pending_q && efuse_prog_done) lock_pending_q <= 1'b0;

      if (feat_ctrl_lo_rd) begin
        feat_lo_q       <= rd_data;
        feat_lo_valid_q <= 1'b1;
      end
      if (feat_ctrl_hi_rd) feat_lo_valid_q <= 1'b0;

      if (lc_diff_ok) begin
        lc_prev_q       <= lc_raw;
        lc_prev_valid_q <= 1'b1;
      end
      wdt_bark_irq_q <= (wdt_bark_irq_i === 1'b1);
      if (wdt_thold_wr_ev) wdt_thold_q <= 1'b1;
      else if (wdt_thold_wr) wdt_thold_q <= 1'b0;

      if (cold_wr_ev && (wr_strb == 4'hF)) begin
        cold_addr_q  <= aw_addr_q;
        cold_data_q  <= wr_data;
        cold_valid_q <= 1'b1;
      end
      if (warm_wr_ev) begin
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
      spi_cs_n_q    <= (spi_cs_n_i !== 1'b0);
      if (spi_cmd_wr) spi_cmd_q <= 1'b1;
      else if (spi_csr) spi_cmd_q <= 1'b0;
      spi_sck_q     <= (spi_sck_i === 1'b1);
      irq_mailbox_q <= mbox_any;
      if (!$isunknown(irq_mailbox_i)) irq_mailbox_vec_q <= irq_mailbox_i;
      irq_km_mbox_q <= (irq_km_mbox_i === 1'b1);
      if (km_irq_en_wr && (wr_data != 32'h0)) km_irq_en_q <= 1'b1;
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
    // An OKAY read decoded in each LSU-reachable register block.
    cp_block: coverpoint rd_blk iff (rd_ev) {
      bins cpu_ctrl = {BLK_CPU_CTRL};
      bins dma = {BLK_DMA};
      bins wdt = {BLK_WDT};
      bins scratch_cold = {BLK_SCRATCH_COLD};
      bins scratch_warm = {BLK_SCRATCH_WARM};
      bins reset_ctrl = {BLK_RESET_CTRL};
      bins otbn = {BLK_OTBN};
      bins aes = {BLK_AES};
      bins hmac = {BLK_HMAC};
      bins kmac = {BLK_KMAC};
      bins csrng = {BLK_CSRNG};
      bins edn = {BLK_EDN};
      bins esrc = {BLK_ESRC};
      bins lifecycle = {BLK_LIFECYCLE};
      bins km_mailbox = {BLK_KM_MBOX};
      bins efuse_map = {BLK_EFUSE_MAP};
      bins efuse_ctrl = {BLK_EFUSE_CTRL};
      bins efuse_mmr = {BLK_EFUSE_MMR};
      bins abr = {BLK_ABR};
      bins entropy_pool = {BLK_POOL};
      bins axil_mailbox = {BLK_AXIL_MBOX};
      bins alias_remap = {BLK_ALIAS_REMAP};
      bins ap_remap = {BLK_AP_REMAP};
      bins stee_remap = {BLK_STEE_REMAP};
      bins outbound_filter = {BLK_OUT_FILTER};
      bins inbound_filter = {BLK_IN_FILTER};
      bins spi = {BLK_SPI};
    }
    // Which VALID the master raised first for a write that completed OKAY.
    cp_aw_w_order: coverpoint wr_order_q iff (wr_ev && wr_order_valid_q) {
      bins aw_first = {OrdAwFirst}; bins w_first = {OrdWFirst}; bins same_cycle = {OrdSame};
    }
    cp_ar_during_write: coverpoint ar_during_write {bins ar_while_w_pending = {1'b1};}
    // Byte lanes of a completed write.
    cp_wstrb: coverpoint wr_lanes iff (wr_ev) {
      bins byte_lane = {4'd1}; bins half = {4'd2}; bins word = {4'd4}; bins dword = {4'd8};
    }
    // Reads in flight when a read is accepted.
    cp_rd_depth: coverpoint rd_depth iff (!in_reset && ar_hs) {
      bins one = {5'd1}; bins few = {[5'd2 : 5'd4]}; bins many = {[5'd5 : 5'd16]};
    }
    // ARSIZE of a completed read.
    cp_arsize: coverpoint ar_size_q iff (rd_ev) {
      bins b1 = {3'd0}; bins b2 = {3'd1}; bins b4 = {3'd2}; bins b8 = {3'd3};
    }
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

  // Sampled every clock from the event sampler, plus once at the PASS edge,
  // which VCS does not allow on a group with a clocking event.
  covergroup sep_cpu_boot_cg with function sample (logic console, logic pass, logic pc);
    option.per_instance = 1;
    option.name = "sep_cpu_boot_cg";
    cp_console: coverpoint console {bins console_byte = {1'b1};}
    cp_pass: coverpoint pass {bins fw_pass = {1'b1};}
    cp_pc: coverpoint pc {bins pc_nonzero = {1'b1};}
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
    // CTR x DECRYPT has nothing to score. CTR is a stream mode: the engine
    // runs the forward cipher whichever way OPERATION is programmed, so
    // decryption is the same operation as encryption and re-encrypting the
    // ciphertext recovers the plaintext. A test that programmed DECRYPT here
    // would pass with the OPERATION field disconnected, so the cell would
    // record configuration, not consumption.
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
    // fourteen of the fifteen keyed cells; the excluded one is named in
    // docs/SEP_FCOV.adoc rather than binned here.
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
    // KMAC is mode cSHAKE with kmac_en=1 (kmac_en in
    // vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson).
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
    cp_imem_rdback: coverpoint otbn_imem_rdback {bins write_then_read = {1'b1};}
    cp_dmem_rdback: coverpoint otbn_dmem_rdback {bins write_then_read = {1'b1};}
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
    // drove. sep_crypto_edn_round_robin_grant_test must fill all four, and
    // simultaneous acks are likeliest there.
    cp_edn_aes: coverpoint crypto_edn_ack_i[0] iff (!in_reset) {
      bins aes = {1'b1};
    }
    cp_edn_kmac: coverpoint crypto_edn_ack_i[1] iff (!in_reset) {bins kmac = {1'b1};}
    cp_edn_otbn_rnd: coverpoint crypto_edn_ack_i[2] iff (!in_reset) {bins otbn_rnd = {1'b1};}
    cp_edn_otbn_urnd: coverpoint crypto_edn_ack_i[3] iff (!in_reset) {bins otbn_urnd = {1'b1};}
    cp_pool_pop: coverpoint pool_pop {bins pool_pop_okay = {1'b1};}
    // HT_WATERMARK_NUM selector writes: each supported encoding, and one
    // unsupported value (which one is seeded, so the range is one bin).
    cp_ht_sel: coverpoint esrc_ht_sel iff (esrc_ht_sel_wr) {
      bins repcnt_hi = {4'h0};
      bins apt_hi = {4'h1};
      bins apt_lo = {4'h2};
      bins markov_hi = {4'h3};
      bins markov_lo = {4'h4};
      bins unsupported = {[4'h5 : 4'hF]};
    }
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
  logic abr_rst_n_q, abr_host_iso_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      hmac_rst_n_q  <= hmac_gated_rst_n_i;
      hmac_km_iso_q <= hmac_km_isolated_i;
      abr_rst_n_q   <= abr_gated_rst_n_i;
      abr_host_iso_q <= abr_host_isolated_i;
    end else begin
      hmac_rst_n_q  <= hmac_gated_rst_n_i;
      hmac_km_iso_q <= hmac_km_isolated_i;
      abr_rst_n_q   <= abr_gated_rst_n_i;
      abr_host_iso_q <= abr_host_isolated_i;
    end
  end

  // The cycle the HMAC domain enters reset. Sampling the state instead would
  // bin a steady condition that holds for the whole window, and both isolate
  // bits are high throughout it -- so the ordering bin would fill whatever the
  // sequencer did. Every edge is additionally qualified on being out of reset:
  // the cold-reset window presents the same levels a real isolate does, and an
  // edge derived from it says nothing about the sequencer.
  //
  // The KM-path bits are also raised by a Key Manager reset
  // (sep_reset_ctrl.sv: km_hmac and km_abr OR in km_isolate_req), and a leaf
  // that holds the KM in reset sees them high from time 0. So a KM-path edge
  // counts only while the domain's own isolate request is high, and the HMAC
  // ordered reset counts only when the KM bit rose under that request. A
  // static KM bit cannot show that the sequencer waited for it. The request
  // also excludes a warm reset: sep_reset_n forces the gated resets without
  // the sequencer, which leaves the request low.
  logic hmac_km_iso_by_req_q, abr_host_iso_by_req_q;
  wire hmac_req = (hmac_host_isolate_req_i === 1'b1);
  wire abr_req  = (abr_host_isolate_req_i === 1'b1);
  wire hmac_rst_fall   = !in_reset && hmac_rst_n_q && !hmac_gated_rst_n_i;
  wire hmac_km_iso_rise = !in_reset && hmac_req && !hmac_km_iso_q && hmac_km_isolated_i;
  // The release of an isolate this group saw raised, not any KM-path drop.
  wire hmac_km_iso_fall = !in_reset && hmac_km_iso_by_req_q && hmac_km_iso_q &&
      !hmac_km_isolated_i;
  wire hmac_rst_ordered = hmac_rst_fall && hmac_req && hmac_km_iso_by_req_q &&
      hmac_host_isolated_i && hmac_km_isolated_i;
  wire abr_rst_fall    = !in_reset && abr_rst_n_q && !abr_gated_rst_n_i;
  // ABR: every leaf that resets ABR holds the KM in reset, so km_abr is high
  // before the request and only the host term can be ordered. The bin needs
  // the host bit to have risen under the request.
  wire abr_host_iso_rise = !in_reset && abr_req && !abr_host_iso_q && abr_host_isolated_i;
  wire abr_rst_ordered = abr_rst_fall && abr_req && abr_host_iso_by_req_q &&
      abr_host_isolated_i && abr_km_isolated_i;

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      hmac_km_iso_by_req_q <= 1'b0;
      abr_host_iso_by_req_q <= 1'b0;
    end else begin
      if (hmac_km_iso_rise) hmac_km_iso_by_req_q <= 1'b1;
      else if (!hmac_km_isolated_i) hmac_km_iso_by_req_q <= 1'b0;
      if (abr_host_iso_rise) abr_host_iso_by_req_q <= 1'b1;
      else if (!abr_host_isolated_i) abr_host_iso_by_req_q <= 1'b0;
    end
  end

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
    // so it does not distinguish a SHA-384 transfer. The Phase 2 bin sha512
    // samples only in the window of its owner, sep_dma_transfer_matrix_rand_test.
    // verilog_format: off  // verible packs these bins onto one line.
    cp_hash_opcode: coverpoint dma_opcode_w iff (dma_hash_any_go &&
                                                 ((dma_opcode_w != DmaOpSha512) || own_dma_matrix)) {
      bins sha256 = {DmaOpSha256};
      bins sha384 = {DmaOpSha384};
      bins sha512 = {DmaOpSha512};
    }
    // verilog_format: on
  endgroup

  covergroup sep_dma_completion_route_cg with function sample (logic irq_route, logic handshake);
    option.per_instance = 1;
    option.name = "sep_dma_completion_route_cg";
    // The DMA reports completion two ways and the suite walks both:
    // sep_dma_basic_test polls STATUS.done, sep_dma_hash_test takes the DMA_DONE
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
    // The opcode byte of each frame on the pads.
    cp_opcode: coverpoint spi_opcode iff (spi_opcode_ev) {
      bins jedec_id = {8'h9F};
      bins wren = {8'h06};
      bins wrdi = {8'h04};
      bins rdsr = {8'h05};
      bins rdsr2 = {8'h35};
      bins page_program = {8'h02};
      bins read = {8'h03};
      bins fast_read = {8'h0B};
      bins sector_erase = {8'h20};
    }
  endgroup

  // Reads in flight on the SMN inbound port when a read is accepted.
  covergroup sep_smn_inbound_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_smn_inbound_cg";
    cp_rd_depth: coverpoint m_rd_depth iff (m_ar_hs) {
      bins d1 = {5'd1};
      bins d2 = {5'd2};
      bins d3 = {5'd3};
      bins d4 = {5'd4};
      bins deep = {[5'd5 : 5'd16]};
    }
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
    // sep_efuse_otp_program_seq and sep_lcc_demote_matrix_seq;
    // sep_warm_cold_reset_scratch_test cannot, because it passes
    // +skip_fuse_sense, which disqualifies the sense bin above.
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
    // The two illegal encodings are separate cells: they fail the
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
    // (cocotb/env/sep_lcc_golden.py), so it is recorded on its own rather than
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
    // A refused read is an error path that this group does not grade, so only
    // OKAY is a cell.
    cp_map_resp: coverpoint map_resp iff (map_hit) {
      bins okay = {AxiOkay};
    }
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

  // One edge of one SEP AXI mailbox interrupt, sep_internal_interrupts[ch].
  covergroup sep_mailbox_channel_cg with function sample (logic [2:0] ch, logic is_clear);
    option.per_instance = 1;
    option.name = "sep_mailbox_channel_cg";
    cp_ch: coverpoint ch {bins ch[] = {[0 : 7]};}
    cp_edge: coverpoint is_clear {bins raise = {1'b0}; bins clear = {1'b1};}
    x_ch_edge: cross cp_ch, cp_edge;
  endgroup

  // ------------------------------------------------------------------
  // Seed-dependent groups. Each records a value a RANDCFG leaf draws from
  // its seed, so a single regression can leave a cell empty. The names end
  // in _rand_cg so the report separates them from the deterministic groups.
  // ------------------------------------------------------------------
  // CONTROL.TX_WATERMARK. SepSpiHostCfg draws one value per bin on every seed.
  covergroup sep_spi_host_rand_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_spi_host_rand_cg";
    cp_tx_wm: coverpoint spi_tx_wm iff (spi_ctrl_wr) {
      bins low = {[8'd2 : 8'd4]}; bins high = {[8'd5 : 8'd8]};
    }
  endgroup

  // WIRQT, drawn from 1..MAILBOX_DEPTH-1 by SepMboxCfg, at the first push
  // after it is written.
  covergroup sep_mbox_rand_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_mbox_rand_cg";
    cp_wirqt: coverpoint mbox_wirqt_q iff (mbox_wirqt_used) {
      bins low = {[8'd1 : 8'(sep_pkg::MailboxDepth / 2 - 1)]};
      bins high = {[8'(sep_pkg::MailboxDepth / 2) : 8'(sep_pkg::MailboxDepth - 1)]};
    }
  endgroup

  // TOTAL_DATA_SIZE of the dma_basic copy, drawn from {16, 32}, at its COPY GO.
  // The Phase 2 bins b4 to b16384 sample only in the window of their owner,
  // sep_dma_transfer_matrix_rand_test. cp_irq_x_enable (Phase 2, owner
  // sep_dma_irq_error_lock_rand_test) is {latched INTR_ENABLE[2:0], event
  // (0 single_chunk_done, 1 multi_chunk_done, 2 error_zero_size)}, scored at
  // the INTR_STATE read that ends a trial when the PIC lines match the gate.
  covergroup sep_dma_rand_cg @(posedge clk_i);
    option.per_instance = 1;
    option.name = "sep_dma_rand_cg";
    cp_len: coverpoint dma_total_q iff (dma_copy_go && dma_total_valid_q &&
                                        ((dma_total_q inside {32'd16, 32'd32}) || own_dma_matrix)) {
      bins b16 = {32'd16};
      bins b32 = {32'd32};
      bins b4 = {32'd4};
      bins b64 = {32'd64};
      bins b256 = {32'd256};
      bins b1024 = {32'd1024};
      bins b4096 = {32'd4096};
      bins b16384 = {32'd16384};
    }
    cp_irq_x_enable: coverpoint dma_irq_cell_q iff (dma_irq_cell_ev_q) {
      bins en_event[] = {[5'd0 : 5'd31]}; wildcard ignore_bins no_event = {5'b???11};
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
  sep_smn_inbound_cg          u_sep_smn_inbound_cg          = new();
  sep_mailbox_channel_cg      u_sep_mailbox_channel_cg      = new();
  sep_spi_host_rand_cg        u_sep_spi_host_rand_cg        = new();
  sep_mbox_rand_cg            u_sep_mbox_rand_cg            = new();
  sep_dma_rand_cg             u_sep_dma_rand_cg             = new();

  // Event-sampled groups: sample only on the completing event, so a cell
  // records one completed operation rather than one clock of a held state.
  always_ff @(posedge clk_i) begin
    if (!in_reset) begin
      u_sep_cpu_boot_cg.sample(cpu_console, 1'b0, cpu_pc);
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
      if (feat_ctrl_sample) begin
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
      if (prog_pending_q && efuse_prog_done) begin
        u_sep_efuse_program_lock_cg.sample(prog_spare_q, prog_locked_q, efuse_prog_err);
      end
      for (int ch = 0; ch < 8; ch++) begin
        if (mbox_ch_raise[ch]) u_sep_mailbox_channel_cg.sample(3'(ch), 1'b0);
        if (mbox_ch_clear[ch]) u_sep_mailbox_channel_cg.sample(3'(ch), 1'b1);
      end
    end
  end

  // The PASS edge is sampled in the time step the mailbox model raises it,
  // not on a clock. The cocotb boot loop sees fw_done on the next rising edge
  // and ends the run there (sep_base_test.py), so a clock-sampled strobe races
  // the end of the simulation and is lost. fw_done and fw_pass update in the
  // same NBA step, so the block can wake on either one first; it samples once
  // both read 1, and re-arms when fw_done drops.
  always @(fw_done_i or fw_pass_i or rst_ni) begin
    if (in_reset || (fw_done_i !== 1'b1)) begin
      cpu_pass_seen = 1'b0;
    end else if ((fw_pass_i === 1'b1) && !cpu_pass_seen) begin
      cpu_pass_seen = 1'b1;
      u_sep_cpu_boot_cg.sample(1'b0, 1'b1, 1'b0);
    end
  end

  // =====================================================================
  // Phase 2: fabric and remap groups (docs/SEP_FCOV.adoc, fabric and remap
  // groups). VCS only, like the rest of this module.
  //
  // GATE. Every bin of this section samples only inside the graded window
  // of an owning test: `graded_owner` holds that test's code from
  // tb/sep_fcov_owner_codes.svh. The leaf writes the variable through the
  // handle u_sep_fcov; it is 0 outside a graded window. It drives nothing.
  //
  // PAIRING. Each tracker follows one transaction per channel of one
  // initiator, from the request handshake to its response. A sample is taken
  // only when exactly one transaction of that channel was in flight, so a
  // response is never paired with another request's address. A missed sample
  // is a missed hit, never a false one.
  //
  // MODELS. The filter verdict, the granule widening and the alias-region
  // hit that name a bin are written from hw/ip/axi_filter/doc/index.adoc
  // and the alias_remap and output_remap register descriptions. They read
  // only the programmed register fields (taps) and the request attributes.
  // =====================================================================
  `include "sep_fcov_crypto_reg_addrs.svh"

  wire own_rebase  = (graded_owner == FcovOwnSepFabricInboundRebaseTest);
  wire own_match   = (graded_owner == FcovOwnSepFabricFilterMatchPriorityRandTest);
  wire own_route   = (graded_owner == FcovOwnSepFabricOutboundRouteAttrTest);
  wire own_alias   = (graded_owner == FcovOwnSepFabricAliasRemapAttrRandTest);
  wire own_smc     = (graded_owner == FcovOwnSepFabricSmcRouteTest);
  wire own_ext     = (graded_owner == FcovOwnSepFabricExtensionPortWindowTest);
  wire own_row     = (graded_owner == FcovOwnSepFabricRowResponseMatrixTest);
  wire own_twin    = (graded_owner == FcovOwnSepCpuLsuAliasWindowTwinTest);
  wire own_dma     = (graded_owner == FcovOwnSepFabricDmaEndpointMatrixTest);
  wire own_tcm_dma = (graded_owner == FcovOwnSepTcmDmaApertureEccTest);

  localparam logic [1:0] FRespOkay = 2'b00;
  localparam logic [1:0] FRespSlverr = 2'b10;
  localparam logic [1:0] FRespDecerr = 2'b11;

  localparam logic [2:0] SelSmc = 3'(sep_pkg::SEP_EXT_TO_SMC);
  localparam logic [2:0] SelSmu = 3'(sep_pkg::SEP_EXT_TO_SMU);
  localparam logic [2:0] SelAp = 3'(sep_pkg::SEP_EXT_AP_REMAP);
  localparam logic [2:0] SelStee = 3'(sep_pkg::SEP_EXT_STEE_REMAP);
  localparam logic [2:0] SelLocal = 3'(sep_pkg::SEP_LOCAL);

  // Address classes (hw/sys/sep/regs/gen/adoc/memory_map.adoc;
  // hw/sys/sep/doc/memory_map.adoc).
  localparam logic [31:0] FSramBase = 32'(SEP_TOP_SEP_SRAM_BASE_ADDR);
  localparam logic [31:0] FSramEnd = 32'(SEP_TOP_SEP_SRAM_BASE_ADDR + SEP_TOP_SEP_SRAM_SIZE - 1);
  localparam logic [31:0] FRomBase = 32'(SEP_TOP_SEP_BOOT_ROM_BASE_ADDR);
  localparam logic [31:0] FRomEnd      = 32'(SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + SEP_TOP_SEP_BOOT_ROM_SIZE - 1);
  localparam logic [31:0] FApBase = 32'(SEP_TOP_AP_REGION_BASE_ADDR);
  localparam logic [31:0] FApEnd = 32'(SEP_TOP_AP_REGION_BASE_ADDR + SEP_TOP_AP_REGION_SIZE - 1);
  localparam logic [31:0] FSteeBase = 32'(SEP_TOP_STEE_REGION_BASE_ADDR);
  localparam logic [31:0] FSteeEnd     = 32'(SEP_TOP_STEE_REGION_BASE_ADDR + SEP_TOP_STEE_REGION_SIZE - 1);
  localparam logic [31:0] FExtBase = 32'(SEP_TOP_SEP_EXTERNAL_BASE_ADDR);
  localparam logic [31:0] FExtEnd      = 32'(SEP_TOP_SEP_EXTERNAL_BASE_ADDR + SEP_TOP_SEP_EXTERNAL_SIZE - 1);
  localparam logic [31:0] FShimLast    = 32'(SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR +
                                             SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_SIZE - 1);
  localparam logic [31:0] FExtFirst = FShimLast + 32'd1;
  localparam logic [31:0] FExtTopWord = FExtEnd - 32'd7;
  localparam logic [31:0] FDmaCsrBase = SECURE_DMA_REG_MAP_BASE_ADDR;
  localparam logic [31:0] FDmaCsrEnd = SECURE_DMA_REG_MAP_BASE_ADDR + SECURE_DMA_REG_MAP_SIZE - 1;
  localparam logic [31:0] FInfiltBase = INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] FOutfiltBase = OUTBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] FFiltStride  = INBOUND_FILTER_CTRL_1__REG_MAP_BASE_ADDR -
                                         INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;
  localparam logic [31:0] FFiltStart = INBOUND_FILTER_CTRL_0__START_ADDR_REG_OFFSET;
  localparam logic [31:0] FFiltEnd = INBOUND_FILTER_CTRL_0__END_ADDR_REG_OFFSET;

  function automatic bit in_rng(input logic [31:0] a, input logic [31:0] lo, input logic [31:0] hi);
    return (a >= lo) && (a <= hi);
  endfunction

  // ---------------------------------------------------------------------
  // Filter reference model (hw/ip/axi_filter/doc/index.adoc, "Match, Then
  // Permit" and "Address Range Granule"; smc-traffic-filters.svg: src_id
  // against AxUSER[3:0]).
  // ---------------------------------------------------------------------
  typedef struct packed {
    logic        en;
    logic        rd;
    logic        wr;
    logic        ns;
    logic        burst;
    logic [3:0]  src;
    logic [55:0] s;
    logic [55:0] e;
  } fent_t;

  typedef struct packed {
    logic       win;         // an entry matches
    logic [5:0] w;           // lowest matching entry
    logic       perm;        // its permission bit for the direction
    logic       hides_allow; // a higher matching entry would admit
    logic       low_valid;   // an entry covers the address
    logic [5:0] low;         // lowest covering entry
    logic [3:0] low_fail;    // {burst, src, ns, disabled} of that entry
    logic       ftr;         // the lowest covering entry failed and another matched
    logic       en_cov;      // an enabled entry covers the address
    logic       all_dis;     // every entry is disabled
    logic       armed;       // all disabled, and one covering entry would match
  } fres_t;

  fent_t in_f [32];
  fent_t out_f [32];
  always_comb begin
    for (int i = 0; i < 32; i++) begin
      in_f[i]  = '0;
      out_f[i] = '{en: out_f_en_i[i], rd: out_f_rd_i[i], wr: out_f_wr_i[i], ns: out_f_ns_i[i],
                   burst: out_f_burst_i[i], src: out_f_src_i[i], s: out_f_start_i[i],
                   e: out_f_end_i[i]};
    end
    for (int i = 0; i < 16; i++) begin
      in_f[i] = '{
          en: in_f_en_i[i],
          rd: in_f_rd_i[i],
          wr: in_f_wr_i[i],
          ns: in_f_ns_i[i],
          burst: in_f_burst_i[i],
          src: in_f_src_i[i],
          s: in_f_start_i[i],
          e: in_f_end_i[i]
      };
    end
  end

  function automatic logic [55:0] gran_lo(input logic [55:0] a, input logic burst);
    return burst ? {a[55:12], 12'h000} : {a[55:3], 3'h0};
  endfunction

  function automatic logic [55:0] gran_hi(input logic [55:0] a, input logic burst);
    return burst ? {a[55:12], 12'hFFF} : {a[55:3], 3'h7};
  endfunction

  function automatic bit f_cov(input fent_t f, input logic [55:0] a);
    return (gran_lo(a, f.burst) >= gran_lo(f.s, f.burst)) &&
        (gran_lo(a, f.burst) <= gran_lo(f.e, f.burst));
  endfunction

  function automatic fres_t f_eval(input fent_t f[32], input int n, input logic [55:0] a,
                                   input logic wr, input logic prot1, input logic [3:0] user,
                                   input logic [7:0] len);
    fres_t r;
    r = '0;
    r.all_dis = 1'b1;
    for (int i = 0; i < n; i++) begin
      logic [3:0] fl;
      bit c;
      c  = f_cov(f[i], a);
      fl = {(!f[i].burst && (len != 8'd0)), ((f[i].src != 4'd0) && (f[i].src != user)),
            (f[i].ns != prot1), !f[i].en};
      if (f[i].en) r.all_dis = 1'b0;
      if (c && f[i].en) r.en_cov = 1'b1;
      if (c && !f[i].en && f[i].rd && f[i].wr && (f[i].src == 4'd0) && (f[i].ns == prot1)) begin
        r.armed = 1'b1;
      end
      if (c && !r.low_valid) begin
        r.low_valid = 1'b1;
        r.low       = 6'(i);
        r.low_fail  = fl;
      end
      if (c && (fl == 4'd0)) begin
        if (!r.win) begin
          r.win  = 1'b1;
          r.w    = 6'(i);
          r.perm = wr ? f[i].wr : f[i].rd;
        end else if (!r.perm && (wr ? f[i].wr : f[i].rd)) begin
          r.hides_allow = 1'b1;
        end
      end
    end
    r.ftr = r.win && (r.low_fail != 4'd0);
    if (!r.all_dis) r.armed = 1'b0;
    return r;
  endfunction

  // Range-programmed state since reset, per instance: a START_ADDR or
  // END_ADDR write from the LSU. Reset state means no such write.
  // The START and END write data of every entry, for the granule shape.
  logic in_range_wr_q, out_range_wr_q;
  logic [55:0] in_sw_q [16];
  logic [55:0] in_ew_q [16];
  logic [55:0] out_sw_q [32];
  logic [55:0] out_ew_q [32];

  // ---------------------------------------------------------------------
  // Handshakes.
  // ---------------------------------------------------------------------
  wire si_aw_hs = !in_reset && (in_req_i.aw_valid === 1'b1) && (in_resp_i.aw_ready === 1'b1);
  wire si_ar_hs = !in_reset && (in_req_i.ar_valid === 1'b1) && (in_resp_i.ar_ready === 1'b1);
  wire si_b_hs  = !in_reset && (in_resp_i.b_valid === 1'b1) && (in_req_i.b_ready === 1'b1);
  wire si_r_end = !in_reset && (in_resp_i.r_valid === 1'b1) && (in_req_i.r_ready === 1'b1) &&
                  (in_resp_i.r.last === 1'b1);
  wire xb_aw_hs = !in_reset && (xbar_req_i.aw_valid === 1'b1) && (xbar_resp_i.aw_ready === 1'b1);
  wire xb_ar_hs = !in_reset && (xbar_req_i.ar_valid === 1'b1) && (xbar_resp_i.ar_ready === 1'b1);
  wire xb_b_hs  = !in_reset && (xbar_resp_i.b_valid === 1'b1) && (xbar_req_i.b_ready === 1'b1);
  wire xb_r_end = !in_reset && (xbar_resp_i.r_valid === 1'b1) && (xbar_req_i.r_ready === 1'b1) &&
                  (xbar_resp_i.r.last === 1'b1);
  wire csr_aw_hs = !in_reset && (sys_csr_awvalid_i === 1'b1) && (sys_csr_awready_i === 1'b1);
  wire csr_ar_hs = !in_reset && (sys_csr_arvalid_i === 1'b1) && (sys_csr_arready_i === 1'b1);
  wire lq_aw_hs = !in_reset && (lsu_req_i.aw_valid === 1'b1) && (lsu_resp_i.aw_ready === 1'b1);
  wire lq_ar_hs = !in_reset && (lsu_req_i.ar_valid === 1'b1) && (lsu_resp_i.ar_ready === 1'b1);
  wire lq_w_hs  = !in_reset && (lsu_req_i.w_valid === 1'b1) && (lsu_resp_i.w_ready === 1'b1);
  wire lq_b_hs  = !in_reset && (lsu_resp_i.b_valid === 1'b1) && (lsu_req_i.b_ready === 1'b1);
  wire lq_r_end = !in_reset && (lsu_resp_i.r_valid === 1'b1) && (lsu_req_i.r_ready === 1'b1) &&
                  (lsu_resp_i.r.last === 1'b1);
  wire al_aw_hs = !in_reset && (alias_in_req_i.aw_valid === 1'b1) &&
                  (alias_in_resp_i.aw_ready === 1'b1);
  wire al_ar_hs = !in_reset && (alias_in_req_i.ar_valid === 1'b1) &&
                  (alias_in_resp_i.ar_ready === 1'b1);
  wire rt_aw_hs = !in_reset && (route_req_i.aw_valid === 1'b1) && (route_resp_i.aw_ready === 1'b1);
  wire rt_ar_hs = !in_reset && (route_req_i.ar_valid === 1'b1) && (route_resp_i.ar_ready === 1'b1);
  wire rt_b_hs  = !in_reset && (route_resp_i.b_valid === 1'b1) && (route_req_i.b_ready === 1'b1);
  wire rt_r_end = !in_reset && (route_resp_i.r_valid === 1'b1) && (route_req_i.r_ready === 1'b1) &&
                  (route_resp_i.r.last === 1'b1);
  wire po_aw_hs = !in_reset && (pre_out_req_i.aw_valid === 1'b1) &&
                  (pre_out_resp_i.aw_ready === 1'b1);
  wire po_ar_hs = !in_reset && (pre_out_req_i.ar_valid === 1'b1) &&
                  (pre_out_resp_i.ar_ready === 1'b1);
  wire po_b_hs  = !in_reset && (pre_out_resp_i.b_valid === 1'b1) && (pre_out_req_i.b_ready === 1'b1);
  wire po_r_end = !in_reset && (pre_out_resp_i.r_valid === 1'b1) &&
                  (pre_out_req_i.r_ready === 1'b1) && (pre_out_resp_i.r.last === 1'b1);
  wire out_aw_hs = !in_reset && (out_req_i.aw_valid === 1'b1) && (out_resp_i.aw_ready === 1'b1);
  wire out_ar_hs = !in_reset && (out_req_i.ar_valid === 1'b1) && (out_resp_i.ar_ready === 1'b1);
  wire smc_aw_hs = !in_reset && (smc_req_i.aw_valid === 1'b1) && (smc_resp_i.aw_ready === 1'b1);
  wire smc_ar_hs = !in_reset && (smc_req_i.ar_valid === 1'b1) && (smc_resp_i.ar_ready === 1'b1);
  wire ext_aw_hs = !in_reset && (ext_req_i.aw_valid === 1'b1) && (ext_resp_i.aw_ready === 1'b1);
  wire ext_ar_hs = !in_reset && (ext_req_i.ar_valid === 1'b1) && (ext_resp_i.ar_ready === 1'b1);
  wire dq_aw_hs = !in_reset && (dma_req_i.aw_valid === 1'b1) && (dma_resp_i.aw_ready === 1'b1);
  wire [31:0] dq_req_a = dq_aw_hs ? dma_req_i.aw.addr : dma_req_i.ar.addr;
  wire dq_ar_hs = !in_reset && (dma_req_i.ar_valid === 1'b1) && (dma_resp_i.ar_ready === 1'b1);
  wire dq_b_hs  = !in_reset && (dma_resp_i.b_valid === 1'b1) && (dma_req_i.b_ready === 1'b1);
  wire dq_r_end = !in_reset && (dma_resp_i.r_valid === 1'b1) && (dma_req_i.r_ready === 1'b1) &&
                  (dma_resp_i.r.last === 1'b1);
  wire dcsr_hs  = !in_reset && (((dma_csr_req_i.aw_valid === 1'b1) &&
                                 (dma_csr_resp_i.aw_ready === 1'b1)) ||
                                ((dma_csr_req_i.ar_valid === 1'b1) &&
                                 (dma_csr_resp_i.ar_ready === 1'b1)));
  wire rom_hs   = !in_reset && (rom_req_i.req === 1'b1) && (rom_rsp_i.gnt === 1'b1);
  wire out_hs   = out_aw_hs || out_ar_hs;
  wire smc_hs   = smc_aw_hs || smc_ar_hs;
  wire ext_hs   = ext_aw_hs || ext_ar_hs;
  wire xb_hs    = xb_aw_hs || xb_ar_hs;
  wire csr_hs   = csr_aw_hs || csr_ar_hs;

  // probe_alive: the probed port shows at least one handshake since reset.
  logic alive_out_q, alive_smc_q, alive_ext_q, alive_xb_q, alive_rom_q, alive_dcsr_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      {alive_out_q, alive_smc_q, alive_ext_q, alive_xb_q, alive_rom_q, alive_dcsr_q} <= '0;
    end else begin
      alive_out_q  <= alive_out_q || out_hs;
      alive_smc_q  <= alive_smc_q || smc_hs;
      alive_ext_q  <= alive_ext_q || ext_hs;
      alive_xb_q   <= alive_xb_q || xb_hs;
      alive_rom_q  <= alive_rom_q || rom_hs;
      alive_dcsr_q <= alive_dcsr_q || dcsr_hs;
    end
  end

  // ---------------------------------------------------------------------
  // System Interface tracker: one read and one write.
  // ---------------------------------------------------------------------
  typedef struct packed {
    logic [55:0] addr;
    logic [7:0]  len;
    logic [2:0]  size;
    logic [2:0]  prot;
    logic [3:0]  user;
    logic        xb;
    logic [31:0] xb_addr;
    logic        csr;
    logic        ext;
  } si_txn_t;

  si_txn_t si_rd_q, si_wr_q;
  logic [3:0] si_rd_n_q, si_wr_n_q;

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      si_rd_q <= '0;
      si_wr_q <= '0;
      si_rd_n_q <= '0;
      si_wr_n_q <= '0;
    end else begin
      si_rd_n_q <= si_rd_n_q + 4'(si_ar_hs) - 4'(si_r_end);
      si_wr_n_q <= si_wr_n_q + 4'(si_aw_hs) - 4'(si_b_hs);
      if (si_ar_hs) begin
        si_rd_q <= '{
            addr: in_req_i.ar.addr,
            len: in_req_i.ar.len,
            size: in_req_i.ar.size,
            prot: in_req_i.ar.prot,
            user: in_req_i.ar.user[3:0],
            xb: xb_ar_hs,
            xb_addr: xbar_req_i.ar.addr,
            csr: csr_ar_hs,
            ext: ext_ar_hs
        };
      end else if (si_rd_n_q != 4'd0) begin
        if (xb_ar_hs && !si_rd_q.xb) begin
          si_rd_q.xb      <= 1'b1;
          si_rd_q.xb_addr <= xbar_req_i.ar.addr;
        end
        if (csr_ar_hs) si_rd_q.csr <= 1'b1;
        if (ext_ar_hs) si_rd_q.ext <= 1'b1;
      end
      if (si_aw_hs) begin
        si_wr_q <= '{
            addr: in_req_i.aw.addr,
            len: in_req_i.aw.len,
            size: in_req_i.aw.size,
            prot: in_req_i.aw.prot,
            user: in_req_i.aw.user[3:0],
            xb: xb_aw_hs,
            xb_addr: xbar_req_i.aw.addr,
            csr: csr_aw_hs,
            ext: ext_aw_hs
        };
      end else if (si_wr_n_q != 4'd0) begin
        if (xb_aw_hs && !si_wr_q.xb) begin
          si_wr_q.xb      <= 1'b1;
          si_wr_q.xb_addr <= xbar_req_i.aw.addr;
        end
        if (csr_aw_hs) si_wr_q.csr <= 1'b1;
        if (ext_aw_hs) si_wr_q.ext <= 1'b1;
      end
    end
  end

  wire si_rd_done = si_r_end && (si_rd_n_q == 4'd1) && !si_ar_hs;
  wire si_wr_done = si_b_hs && (si_wr_n_q == 4'd1) && !si_aw_hs;
  wire si_done    = si_rd_done || si_wr_done;
  wire si_dir_w   = si_wr_done;  // a cycle with both completions samples the write
  si_txn_t    si_c;
  logic [1:0]  si_resp;
  logic [63:0] si_rdata;
  always_comb begin
    si_c     = si_dir_w ? si_wr_q : si_rd_q;
    si_resp  = si_dir_w ? in_resp_i.b.resp : in_resp_i.r.resp;
    si_rdata = in_resp_i.r.data;
  end
  fres_t si_f;
  assign si_f = f_eval(in_f, 16, si_c.addr, si_dir_w, si_c.prot[1], si_c.user, si_c.len);

  // Inbound aperture: rebase of the SEP_REGION_SIZE window at
  // SEP_GLOBAL_BASE_ADDR to 0 (hw/sys/sep/doc/fabric.adoc, Fabric Topology).
  wire         si_in_win = (si_c.addr >= sep_base_i) && (si_c.addr < (sep_base_i + sep_size_i));
  wire  [55:0] si_local  = si_in_win ? (si_c.addr - sep_base_i) : si_c.addr;
  wire  [55:0] si_off    = si_c.addr - sep_base_i;

  // ---------------------------------------------------------------------
  // LSU tracker: one read and one write, with the port activity of the
  // window and the request at the route demux.
  // ---------------------------------------------------------------------
  typedef struct packed {
    logic [31:0] addr;
    logic [2:0]  size;
    logic [2:0]  prot;
    logic [3:0]  cache;
    logic [11:0] user;
    logic        out;
    logic        smc;
    logic        ext;
    logic        rt;
    logic [2:0]  sel;
    logic        po;
    logic [55:0] po_addr;
  } lsu_txn_t;

  lsu_txn_t lq_rd_q, lq_wr_q;
  logic [3:0] lq_rd_n_q, lq_wr_n_q;

  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      lq_rd_q <= '0;
      lq_wr_q <= '0;
      lq_rd_n_q <= '0;
      lq_wr_n_q <= '0;
    end else begin
      lq_rd_n_q <= lq_rd_n_q + 4'(lq_ar_hs) - 4'(lq_r_end);
      lq_wr_n_q <= lq_wr_n_q + 4'(lq_aw_hs) - 4'(lq_b_hs);
      if (lq_ar_hs) begin
        lq_rd_q <= '{
            addr: lsu_req_i.ar.addr,
            size: lsu_req_i.ar.size,
            prot: lsu_req_i.ar.prot,
            cache: lsu_req_i.ar.cache,
            user: lsu_req_i.ar.user,
            default: '0
        };
      end else if (lq_rd_n_q != 4'd0) begin
        if (out_ar_hs) lq_rd_q.out <= 1'b1;
        if (smc_ar_hs) lq_rd_q.smc <= 1'b1;
        if (ext_ar_hs) lq_rd_q.ext <= 1'b1;
        if (rt_ar_hs && !lq_rd_q.rt) begin
          lq_rd_q.rt  <= 1'b1;
          lq_rd_q.sel <= route_sel_ar_i;
        end
        if (po_ar_hs && !lq_rd_q.po) begin
          lq_rd_q.po      <= 1'b1;
          lq_rd_q.po_addr <= pre_out_req_i.ar.addr;
        end
      end
      if (lq_aw_hs) begin
        lq_wr_q <= '{
            addr: lsu_req_i.aw.addr,
            size: lsu_req_i.aw.size,
            prot: lsu_req_i.aw.prot,
            cache: lsu_req_i.aw.cache,
            user: lsu_req_i.aw.user,
            default: '0
        };
      end else if (lq_wr_n_q != 4'd0) begin
        if (out_aw_hs) lq_wr_q.out <= 1'b1;
        if (smc_aw_hs) lq_wr_q.smc <= 1'b1;
        if (ext_aw_hs) lq_wr_q.ext <= 1'b1;
        if (rt_aw_hs && !lq_wr_q.rt) begin
          lq_wr_q.rt  <= 1'b1;
          lq_wr_q.sel <= route_sel_aw_i;
        end
        if (po_aw_hs && !lq_wr_q.po) begin
          lq_wr_q.po      <= 1'b1;
          lq_wr_q.po_addr <= pre_out_req_i.aw.addr;
        end
      end
    end
  end

  wire lq_rd_done = lq_r_end && (lq_rd_n_q == 4'd1) && !lq_ar_hs;
  wire lq_wr_done = lq_b_hs && (lq_wr_n_q == 4'd1) && !lq_aw_hs;
  wire lq_done    = lq_rd_done || lq_wr_done;
  wire lq_dir_w   = lq_wr_done;
  lsu_txn_t    lq_c;
  logic [1:0]  lq_resp;
  logic [63:0] lq_rdata;
  always_comb begin
    lq_c     = lq_dir_w ? lq_wr_q : lq_rd_q;
    lq_resp  = lq_dir_w ? lsu_resp_i.b.resp : lsu_resp_i.r.resp;
    lq_rdata = lsu_resp_i.r.data;
  end

  // LSU write decode of the filter banks: the START and END write data of each
  // entry, and whether any range was written since reset. The data lane of a
  // 32-bit write follows its strobes on the 64-bit bus.
  logic [31:0] lq_aw_addr_q;
  logic        lq_aw_open_q;
  logic [31:0] lq_wd_a;
  logic        lq_wd_inb;
  logic        lq_wd_hit;
  logic        lq_wd_start;
  int          lq_wd_idx;
  logic [55:0] lq_wd_cur;
  always_comb begin
    logic [31:0] rel;
    logic [31:0] off;
    lq_wd_a     = lq_aw_hs ? lsu_req_i.aw.addr : lq_aw_addr_q;
    lq_wd_a     = {lq_wd_a[31:3], 3'b000};
    lq_wd_inb   = in_rng(lq_wd_a, FInfiltBase, FInfiltBase + 16 * FFiltStride - 1);
    rel         = lq_wd_a - (lq_wd_inb ? FInfiltBase : FOutfiltBase);
    lq_wd_idx   = int'(rel / FFiltStride);
    off         = rel % FFiltStride;
    lq_wd_start = (off == FFiltStart);
    lq_wd_hit   = (lq_wd_inb || in_rng(lq_wd_a, FOutfiltBase, FOutfiltBase + 32 * FFiltStride - 1)) &&
                  ((off == FFiltStart) || (off == FFiltEnd));
    lq_wd_cur   = '0;
    if (lq_wd_hit) begin
      if (lq_wd_inb) lq_wd_cur = lq_wd_start ? in_sw_q[lq_wd_idx] : in_ew_q[lq_wd_idx];
      else lq_wd_cur = lq_wd_start ? out_sw_q[lq_wd_idx] : out_ew_q[lq_wd_idx];
      if (|lsu_req_i.w.strb[3:0]) lq_wd_cur[31:0] = lsu_req_i.w.data[31:0];
      if (|lsu_req_i.w.strb[7:4]) lq_wd_cur[55:32] = lsu_req_i.w.data[55:32];
    end
  end
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      lq_aw_addr_q   <= '0;
      lq_aw_open_q   <= 1'b0;
      in_range_wr_q  <= 1'b0;
      out_range_wr_q <= 1'b0;
      for (int i = 0; i < 16; i++) begin
        in_sw_q[i] <= '0;
        in_ew_q[i] <= '0;
      end
      for (int i = 0; i < 32; i++) begin
        out_sw_q[i] <= '0;
        out_ew_q[i] <= '0;
      end
    end else begin
      if (lq_aw_hs) begin
        lq_aw_addr_q <= lsu_req_i.aw.addr;
        lq_aw_open_q <= 1'b1;
      end
      if (lq_w_hs && (lq_aw_open_q || lq_aw_hs)) begin
        if (lq_wd_hit) begin
          if (lq_wd_inb) begin
            in_range_wr_q <= 1'b1;
            if (lq_wd_start) in_sw_q[lq_wd_idx] <= lq_wd_cur;
            else in_ew_q[lq_wd_idx] <= lq_wd_cur;
          end else begin
            out_range_wr_q <= 1'b1;
            if (lq_wd_start) out_sw_q[lq_wd_idx] <= lq_wd_cur;
            else out_ew_q[lq_wd_idx] <= lq_wd_cur;
          end
        end
        if (lsu_req_i.w.last === 1'b1) lq_aw_open_q <= 1'b0;
      end
    end
  end

  // ---------------------------------------------------------------------
  // Outbound filter tracker (pre_out_filter): one read and one write, with
  // the PR-OUT activity of the window.
  // ---------------------------------------------------------------------
  typedef struct packed {
    logic [55:0] addr;
    logic [7:0]  len;
    logic [2:0]  prot;
    logic [3:0]  user;
    logic        out;
  } po_txn_t;

  po_txn_t po_rd_q, po_wr_q;
  logic [3:0] po_rd_n_q, po_wr_n_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      po_rd_q <= '0;
      po_wr_q <= '0;
      po_rd_n_q <= '0;
      po_wr_n_q <= '0;
    end else begin
      po_rd_n_q <= po_rd_n_q + 4'(po_ar_hs) - 4'(po_r_end);
      po_wr_n_q <= po_wr_n_q + 4'(po_aw_hs) - 4'(po_b_hs);
      if (po_ar_hs) begin
        po_rd_q <= '{
            addr: pre_out_req_i.ar.addr,
            len: pre_out_req_i.ar.len,
            prot: pre_out_req_i.ar.prot,
            user: pre_out_req_i.ar.user[3:0],
            out: out_ar_hs
        };
      end else if ((po_rd_n_q != 4'd0) && out_ar_hs) begin
        po_rd_q.out <= 1'b1;
      end
      if (po_aw_hs) begin
        po_wr_q <= '{
            addr: pre_out_req_i.aw.addr,
            len: pre_out_req_i.aw.len,
            prot: pre_out_req_i.aw.prot,
            user: pre_out_req_i.aw.user[3:0],
            out: out_aw_hs
        };
      end else if ((po_wr_n_q != 4'd0) && out_aw_hs) begin
        po_wr_q.out <= 1'b1;
      end
    end
  end
  wire po_rd_done = po_r_end && (po_rd_n_q == 4'd1) && !po_ar_hs;
  wire po_wr_done = po_b_hs && (po_wr_n_q == 4'd1) && !po_aw_hs;
  wire po_done    = po_rd_done || po_wr_done;
  wire po_dir_w   = po_wr_done;
  po_txn_t   po_c;
  logic [1:0] po_resp;
  always_comb begin
    po_c    = po_dir_w ? po_wr_q : po_rd_q;
    po_resp = po_dir_w ? pre_out_resp_i.b.resp : pre_out_resp_i.r.resp;
  end
  fres_t po_f;
  assign po_f = f_eval(out_f, 32, po_c.addr, po_dir_w, po_c.prot[1], po_c.user, po_c.len);

  // AR and AW winner of the last completion per instance, for cp_ar_aw_independent.
  logic [55:0] in_last_rd_addr_q, in_last_wr_addr_q, out_last_rd_addr_q, out_last_wr_addr_q;
  logic [6:0] in_last_rd_w_q, in_last_wr_w_q, out_last_rd_w_q, out_last_wr_w_q;
  wire  [6:0]  si_wcode = si_f.win ? {1'b1, si_f.w} : 7'd0;
  wire  [6:0]  po_wcode = po_f.win ? {1'b1, po_f.w} : 7'd0;
  always_ff @(posedge clk_i) begin
    if (in_reset || !own_match) begin
      in_last_rd_addr_q <= '1;
      in_last_wr_addr_q <= '1;
      out_last_rd_addr_q <= '1;
      out_last_wr_addr_q <= '1;
      in_last_rd_w_q <= '0;
      in_last_wr_w_q <= '0;
      out_last_rd_w_q <= '0;
      out_last_wr_w_q <= '0;
    end else begin
      if (si_done && si_dir_w) begin
        in_last_wr_addr_q <= si_c.addr;
        in_last_wr_w_q <= si_wcode;
      end
      if (si_done && !si_dir_w) begin
        in_last_rd_addr_q <= si_c.addr;
        in_last_rd_w_q <= si_wcode;
      end
      if (po_done && po_dir_w) begin
        out_last_wr_addr_q <= po_c.addr;
        out_last_wr_w_q <= po_wcode;
      end
      if (po_done && !po_dir_w) begin
        out_last_rd_addr_q <= po_c.addr;
        out_last_rd_w_q <= po_wcode;
      end
    end
  end
  wire si_ar_aw_div = si_done &&
      (si_dir_w ? ((in_last_rd_addr_q == si_c.addr) && (in_last_rd_w_q != si_wcode))
                : ((in_last_wr_addr_q == si_c.addr) && (in_last_wr_w_q != si_wcode)));
  wire po_ar_aw_div = po_done &&
      (po_dir_w ? ((out_last_rd_addr_q == po_c.addr) && (out_last_rd_w_q != po_wcode))
                : ((out_last_wr_addr_q == po_c.addr) && (out_last_wr_w_q != po_wcode)));

  // ---------------------------------------------------------------------
  // Initiator rule (docs/SEP_FCOV.adoc, collection rule 5): a beat on a
  // shared port belongs to the initiator whose own request tap holds an
  // accepted, unanswered request with the same address. The initiator taps
  // are lsu_req, dma_req and xbar_ext_req.
  // ---------------------------------------------------------------------
  typedef enum logic [1:0] {
    INIT_NONE,
    INIT_LSU,
    INIT_DMA,
    INIT_SI
  } init_e;
  logic lp_rd_v_q, lp_wr_v_q, dp_rd_v_q, dp_wr_v_q, xp_rd_v_q, xp_wr_v_q;
  logic [31:0] lp_rd_a_q, lp_wr_a_q, dp_rd_a_q, dp_wr_a_q, xp_rd_a_q, xp_wr_a_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      {lp_rd_v_q, lp_wr_v_q, dp_rd_v_q, dp_wr_v_q, xp_rd_v_q, xp_wr_v_q} <= '0;
      {lp_rd_a_q, lp_wr_a_q, dp_rd_a_q, dp_wr_a_q, xp_rd_a_q, xp_wr_a_q} <= '0;
    end else begin
      if (lq_ar_hs) begin
        lp_rd_v_q <= 1'b1;
        lp_rd_a_q <= lsu_req_i.ar.addr;
      end else if (lq_r_end) lp_rd_v_q <= 1'b0;
      if (lq_aw_hs) begin
        lp_wr_v_q <= 1'b1;
        lp_wr_a_q <= lsu_req_i.aw.addr;
      end else if (lq_b_hs) lp_wr_v_q <= 1'b0;
      if (dq_ar_hs) begin
        dp_rd_v_q <= 1'b1;
        dp_rd_a_q <= dma_req_i.ar.addr;
      end else if (dq_r_end) dp_rd_v_q <= 1'b0;
      if (dq_aw_hs) begin
        dp_wr_v_q <= 1'b1;
        dp_wr_a_q <= dma_req_i.aw.addr;
      end else if (dq_b_hs) dp_wr_v_q <= 1'b0;
      if (xb_ar_hs) begin
        xp_rd_v_q <= 1'b1;
        xp_rd_a_q <= xbar_req_i.ar.addr;
      end else if (xb_r_end) xp_rd_v_q <= 1'b0;
      if (xb_aw_hs) begin
        xp_wr_v_q <= 1'b1;
        xp_wr_a_q <= xbar_req_i.aw.addr;
      end else if (xb_b_hs) xp_wr_v_q <= 1'b0;
    end
  end

  function automatic init_e who(input logic wr, input logic [31:0] a, input bit lsu_ok,
                                input bit dma_ok, input bit si_ok);
    bit l, d, x;
    l = lsu_ok && (wr ? (lp_wr_v_q && (lp_wr_a_q == a)) : (lp_rd_v_q && (lp_rd_a_q == a)));
    d = dma_ok && (wr ? (dp_wr_v_q && (dp_wr_a_q == a)) : (dp_rd_v_q && (dp_rd_a_q == a)));
    x = si_ok && (wr ? (xp_wr_v_q && (xp_wr_a_q == a)) : (xp_rd_v_q && (xp_rd_a_q == a)));
    if (l && !d && !x) return INIT_LSU;
    if (d && !l && !x) return INIT_DMA;
    if (x && !l && !d) return INIT_SI;
    return INIT_NONE;
  endfunction

  // Route tracker: the request at the alias remap input names the initiator;
  // the route demux input names the select and the remapped address. One
  // transaction per channel through the cut between them.
  typedef struct packed {
    logic        v;
    init_e       init;
    logic [2:0]  prot;
    logic [11:0] user;
    logic        rt;
    logic [2:0]  sel;
    logic [55:0] addr;
  } rt_txn_t;
  rt_txn_t rt_rd_q, rt_wr_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      rt_rd_q <= '0;
      rt_wr_q <= '0;
    end else begin
      if (al_ar_hs) begin
        rt_rd_q <= '{
            v: 1'b1,
            init: who(1'b0, alias_in_req_i.ar.addr[31:0], 1, 1, 0),
            prot: alias_in_req_i.ar.prot,
            user: alias_in_req_i.ar.user,
            default: '0
        };
      end else if (rt_ar_hs && rt_rd_q.v && !rt_rd_q.rt) begin
        rt_rd_q.rt   <= 1'b1;
        rt_rd_q.sel  <= route_sel_ar_i;
        rt_rd_q.addr <= route_req_i.ar.addr;
      end else if (rt_r_end) begin
        rt_rd_q <= '0;
      end
      if (al_aw_hs) begin
        rt_wr_q <= '{
            v: 1'b1,
            init: who(1'b1, alias_in_req_i.aw.addr[31:0], 1, 1, 0),
            prot: alias_in_req_i.aw.prot,
            user: alias_in_req_i.aw.user,
            default: '0
        };
      end else if (rt_aw_hs && rt_wr_q.v && !rt_wr_q.rt) begin
        rt_wr_q.rt   <= 1'b1;
        rt_wr_q.sel  <= route_sel_aw_i;
        rt_wr_q.addr <= route_req_i.aw.addr;
      end else if (rt_b_hs) begin
        rt_wr_q <= '0;
      end
    end
  end

  // Outbound port and SMC port samples, attributed through the route tracker.
  function automatic bit in_smu_ap(input logic [55:0] a);
    return (a >= smu_base_i) && (a < (smu_base_i + smu_size_i));
  endfunction
  function automatic bit in_smc_ap(input logic [55:0] a);
    return (a >= smc_base_i) && (a < (smc_base_i + smc_size_i));
  endfunction

  // Route class of a captured request: 0 none, 1 smu_aperture, 2 ge_4g,
  // 3 ap_region, 4 stee_region, 5 smc_aperture.
  function automatic logic [2:0] route_class(input rt_txn_t t, input bit smc_port);
    if (!t.v || !t.rt) return 3'd0;
    if (smc_port) return (t.sel == SelSmc) ? 3'd5 : 3'd0;
    if (t.sel == SelSmu) begin
      if (in_smu_ap(t.addr)) return 3'd1;
      if (t.addr >= 56'h1_0000_0000) return 3'd2;
      return 3'd0;
    end
    if (t.sel == SelAp) return 3'd3;
    if (t.sel == SelStee) return 3'd4;
    return 3'd0;
  endfunction

  wire [2:0] out_rd_cls = out_ar_hs ? route_class(rt_rd_q, 1'b0) : 3'd0;
  wire [2:0] out_wr_cls = out_aw_hs ? route_class(rt_wr_q, 1'b0) : 3'd0;
  wire [2:0] smc_rd_cls = smc_ar_hs ? route_class(rt_rd_q, 1'b1) : 3'd0;
  wire [2:0] smc_wr_cls = smc_aw_hs ? route_class(rt_wr_q, 1'b1) : 3'd0;

  // ---------------------------------------------------------------------
  // sep_fabric_inbound_aperture_cg
  // ---------------------------------------------------------------------
  // cp_in_ap_class codes: 1 target_sram, 2 target_scratch, 3 bottom_word,
  // 4 top_word, 5 last_byte. cp_out_ap_class: 1 one_byte_above_top,
  // 2 below_base. cp_translation: 1 in_window_rebased, 2
  // outside_window_unchanged. cp_rebased_limit: 1 forwarded_below_0x4000_0000,
  // 2 decerr_at_or_above_0x4000_0000.
  logic [2:0] ap_in_cls, ap_out_cls, ap_tr_cls, ap_lim_cls;
  // cp_dest_class_verdict code {class[1:0], dir, verdict[1:0]}: class 0
  // mailbox, 1 system_csr, 2 loopback, 3 unreachable_unit; verdict 1 blocked,
  // 2 admitted, 3 refused_with_entry.
  logic [4:0] ap_dest;
  // cp_burst_region code {kind, dir}: kind 0 in_extent_reg, 1 hole.
  logic [1:0] ap_burst;
  logic ap_burst_hit, ap_burst_bad;
  always_comb begin
    logic [31:0] l;
    logic [1:0]  cls;
    logic [1:0]  vd;
    ap_in_cls  = 3'd0;
    ap_out_cls = 3'd0;
    ap_tr_cls  = 3'd0;
    ap_lim_cls = 3'd0;
    ap_dest    = 5'd0;
    ap_burst   = 2'd0;
    ap_burst_hit = 1'b0;
    ap_burst_bad = 1'b0;
    l = si_local[31:0];
    if (si_in_win) begin
      if (si_off == 56'd0) ap_in_cls = 3'd3;
      else if (si_off == (sep_size_i - 56'd8)) ap_in_cls = 3'd4;
      else if (si_off == (sep_size_i - 56'd1)) ap_in_cls = 3'd5;
      else if ((si_resp == FRespOkay) && si_c.xb && in_rng(l, FSramBase, FSramEnd))
        ap_in_cls = 3'd1;
      else if ((si_resp == FRespOkay) && si_c.csr && in_rng(l, 32'h1080_2000, 32'h1080_20FF))
        ap_in_cls = 3'd2;
    end
    if ((si_c.addr == (sep_base_i + sep_size_i)) && (si_resp == FRespDecerr)) ap_out_cls = 3'd1;
    if ((si_c.addr == (sep_base_i - 56'd1)) && (si_resp == FRespDecerr)) ap_out_cls = 3'd2;
    if (si_c.xb) begin
      if (si_in_win && (si_c.xb_addr == 32'(si_c.addr - sep_base_i))) ap_tr_cls = 3'd1;
      if (!si_in_win && (si_c.xb_addr == si_c.addr[31:0])) ap_tr_cls = 3'd2;
    end
    if ((si_local < 56'h4000_0000) && si_c.xb) ap_lim_cls = 3'd1;
    if ((si_local >= 56'h4000_0000) && (si_resp == FRespDecerr) && !si_c.xb) ap_lim_cls = 3'd2;
    // Destination class by the local address (memory_map.adoc).
    if (si_local < 56'h4000_0000) begin
      if (in_rng(l, 32'h10A0_0000, 32'h10A0_FFFF)) cls = 2'd0;
      else if (in_rng(l, 32'h10A1_0000, 32'h10A4_FFFF) || in_rng(l, 32'h1080_2000, 32'h1080_20FF))
        cls = 2'd1;
      else if (in_rng(
              l, FRomBase, FRomEnd
          ) || in_rng(
              l, 32'h1080_3000, 32'h1080_3FFF
          ) || in_rng(
              l, FApBase, FApEnd
          ) || in_rng(
              l, FSteeBase, FSteeEnd
          ))
        cls = 2'd3;
      else cls = 2'd2;
      vd = 2'd0;
      if ((si_resp == FRespDecerr) && !si_f.en_cov) vd = 2'd1;
      if ((si_resp == FRespOkay) && si_c.xb) vd = 2'd2;
      if ((si_resp == FRespDecerr) && si_f.en_cov) vd = 2'd3;
      if (vd != 2'd0) ap_dest = {cls, si_dir_w, vd};
    end
    // Crypto-region burst (crypto.adoc, Single-Beat Access Only).
    if ((si_c.len != 8'd0) && in_rng(
            si_c.addr[31:0], 32'h1090_0000, 32'h1094_FFFF
        ) && (si_c.addr[55:32] == '0) && si_f.win && si_f.perm) begin
      ap_burst_hit = (si_resp == FRespDecerr);
      ap_burst_bad = (si_resp != FRespDecerr);
      ap_burst     = {!fcov_crypto_reg_addr({si_c.addr[31:2], 2'b00}), si_dir_w};
    end
  end

  covergroup sep_fabric_inbound_aperture_cg with function sample (
      logic [2:0] in_cls,
      logic [2:0] out_cls,
      logic [2:0] tr_cls,
      logic [2:0] lim_cls,
      logic own_rb,
      logic [4:0] dest,
      logic own_dest,
      logic [1:0] burst,
      logic burst_hit,
      logic burst_bad,
      logic own_bu
  );
    option.per_instance = 1;
    option.name = "sep_fabric_inbound_aperture_cg";
    cp_in_ap_class: coverpoint in_cls iff (own_rb) {
      bins target_sram = {3'd1};
      bins target_scratch = {3'd2};
      bins bottom_word = {3'd3};
      bins top_word = {3'd4};
      bins last_byte = {3'd5};
    }
    cp_out_ap_class: coverpoint out_cls iff (own_rb) {
      bins one_byte_above_top = {3'd1}; bins below_base = {3'd2};
    }
    cp_translation: coverpoint tr_cls iff (own_rb) {
      bins in_window_rebased = {3'd1}; bins outside_window_unchanged = {3'd2};
    }
    cp_rebased_limit: coverpoint lim_cls iff (own_rb) {
      bins forwarded_below_0x4000_0000 = {3'd1}; bins decerr_at_or_above_0x4000_0000 = {3'd2};
    }
    cp_dest_class_verdict: coverpoint dest iff (own_dest) {
      bins mailbox_r_blocked = {5'b00_0_01};
      bins mailbox_w_blocked = {5'b00_1_01};
      bins system_csr_r_blocked = {5'b01_0_01};
      bins system_csr_w_blocked = {5'b01_1_01};
      bins loopback_r_blocked = {5'b10_0_01};
      bins loopback_w_blocked = {5'b10_1_01};
      bins loopback_r_admitted = {5'b10_0_10};
      bins loopback_w_admitted = {5'b10_1_10};
      bins unreachable_r_refused_with_entry = {5'b11_0_11};
      bins unreachable_w_refused_with_entry = {5'b11_1_11};
    }
    cp_burst_region: coverpoint burst iff (own_bu && burst_hit) {
      bins in_extent_reg_r = {2'b00};
      bins in_extent_reg_w = {2'b01};
      bins hole_r = {2'b10};
      bins hole_w = {2'b11};
    }
    // Check only: a crypto-region burst that is not refused is illegal. The
    // point carries no bin of its own, so it adds nothing to the group score.
    cp_burst_region_bad: coverpoint burst_bad iff (own_bu) {
      option.weight = 0; type_option.weight = 0; illegal_bins not_decerr = {1'b1};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_fabric_outbound_route_cg
  // ---------------------------------------------------------------------
  // cp_route_class_dir code {class, dir}. cp_out_attr codes: 1..6 route
  // {smu, ap, stee} x prot[1] {0, 1} with AxPROT as issued; 7 ap and 8 stee
  // with AxUSER 0 while the LSU drove non-zero; 9 smu with the issued
  // non-zero AxUSER; 10 DMA on smu with AxUSER 0.
  covergroup sep_fabric_outbound_route_cg with function sample (
      logic [3:0] cls_dir,
      logic own_cls,
      logic [1:0] smu_cfg,
      logic own_smu,
      logic [3:0] smc_cfg,
      logic own_smc_cfg,
      logic smc_ready,
      logic [3:0] attr,
      logic own_attr
  );
    option.per_instance = 1;
    option.name = "sep_fabric_outbound_route_cg";
    cp_route_class_dir: coverpoint cls_dir iff (own_cls) {
      bins smu_aperture_r = {4'b0010};
      bins smu_aperture_w = {4'b0011};
      bins ge_4g_r = {4'b0100};
      bins ge_4g_w = {4'b0101};
      bins ap_region_r = {4'b0110};
      bins ap_region_w = {4'b0111};
      bins stee_region_r = {4'b1000};
      bins stee_region_w = {4'b1001};
      bins smc_aperture_r = {4'b1010};
      bins smc_aperture_w = {4'b1011};
    }
    cp_smu_aperture_cfg: coverpoint smu_cfg iff (own_smu) {
      bins reset_first_word = {2'd1}; bins reset_last_word = {2'd2};
    }
    // {cfg (0 A, 1 B), class (0 first_word, 1 last_word), dir} + 1.
    cp_smc_cfg_class_dir: coverpoint smc_cfg iff (own_smc_cfg) {
      bins a_first_r = {4'd1};
      bins a_first_w = {4'd2};
      bins a_last_r = {4'd3};
      bins a_last_w = {4'd4};
      bins b_first_r = {4'd5};
      bins b_first_w = {4'd6};
      bins b_last_r = {4'd7};
      bins b_last_w = {4'd8};
    }
    cp_smc_readiness: coverpoint smc_ready iff (own_smc_cfg) {
      bins request_after_fuse_sense_done = {1'b1};
    }
    cp_out_attr: coverpoint attr iff (own_attr) {
      bins smu_prot1_0 = {4'd1};
      bins smu_prot1_1 = {4'd2};
      bins ap_prot1_0 = {4'd3};
      bins ap_prot1_1 = {4'd4};
      bins stee_prot1_0 = {4'd5};
      bins stee_prot1_1 = {4'd6};
      bins ap_user_others = {4'd7};
      bins stee_user_others = {4'd8};
      bins smu_user_kept = {4'd9};
      bins dma_smu_user_zero = {4'd10};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_remap_output_offset_cg
  // ---------------------------------------------------------------------
  covergroup sep_remap_output_offset_cg with function sample (logic [1:0] inst_dir, logic own);
    option.per_instance = 1;
    option.name = "sep_remap_output_offset_cg";
    cp_instance_dir: coverpoint inst_dir iff (own) {
      bins ap_r = {2'b00}; bins ap_w = {2'b01}; bins stee_r = {2'b10}; bins stee_w = {2'b11};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_remap_alias_cg
  // ---------------------------------------------------------------------
  covergroup sep_remap_alias_cg with function sample (
      logic [3:0] boundary,
      logic [2:0] cache_ovr,
      logic [1:0] vgate,
      logic [2:0] offx,
      logic own_al,
      logic [4:0] twin,
      logic own_twin_s
  );
    option.per_instance = 1;
    option.name = "sep_remap_alias_cg";
    // {class 1..6, dir}: below, start, mid, end_minus_1, end, above.
    cp_boundary_dir: coverpoint boundary iff (own_al) {
      bins below_r = {4'b0010};
      bins below_w = {4'b0011};
      bins start_r = {4'b0100};
      bins start_w = {4'b0101};
      bins mid_r = {4'b0110};
      bins mid_w = {4'b0111};
      bins end_minus_1_r = {4'b1000};
      bins end_minus_1_w = {4'b1001};
      bins end_r = {4'b1010};
      bins end_w = {4'b1011};
      bins above_r = {4'b1100};
      bins above_w = {4'b1101};
    }
    // {kind 1 hit F over 0, 2 hit 0 over F, 3 miss kept, dir}.
    cp_cacheable_override_dir: coverpoint cache_ovr iff (own_al) {
      bins hit_f_over_0_r = {3'b010};
      bins hit_f_over_0_w = {3'b011};
      bins hit_0_over_f_r = {3'b100};
      bins hit_0_over_f_w = {3'b101};
      bins miss_kept_r = {3'b110};
      bins miss_kept_w = {3'b111};
    }
    cp_valid_gate: coverpoint vgate iff (own_al) {
      bins valid0_r = {2'd1}; bins valid0_w = {2'd2}; bins valid0_cacheable_nonzero = {2'd3};
    }
    // {validity (0 valid, 1 invalid), dir} + 1.
    cp_offset_expansion: coverpoint offx iff (own_al) {
      bins valid_r = {3'd1};
      bins valid_w = {3'd2};
      bins invalid_r = {3'd3};
      bins invalid_w = {3'd4};
    }
    // {class, form}: class 1 scratch, 2 aes_word, 3 sys_csr, 4 spi_word,
    // 5 esrc_word, 6 sram_start, 7 sram_end, 8 ext_top (DMA); form 0
    // direct, 1 alias.
    cp_local_alias_twin: coverpoint twin iff (own_twin_s) {
      bins scratch_direct = {5'b0001_0};
      bins scratch_alias = {5'b0001_1};
      bins aes_word_direct = {5'b0010_0};
      bins aes_word_alias = {5'b0010_1};
      bins sys_csr_direct = {5'b0011_0};
      bins sys_csr_alias = {5'b0011_1};
      bins spi_word_direct = {5'b0100_0};
      bins spi_word_alias = {5'b0100_1};
      bins esrc_word_direct = {5'b0101_0};
      bins esrc_word_alias = {5'b0101_1};
      bins sram_start_direct = {5'b0110_0};
      bins sram_start_alias = {5'b0110_1};
      bins sram_end_direct = {5'b0111_0};
      bins sram_end_alias = {5'b0111_1};
      bins dma_ext_top_alias = {5'b1000_1};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_filter_match_cg
  // ---------------------------------------------------------------------
  covergroup sep_filter_match_cg with function sample (
      logic inst_out,
      logic dir_w,
      logic [2:0] fail_cond,
      logic [1:0] src_cls,
      logic ar_aw_div,
      logic [2:0] winner,
      logic own_m,
      logic own_ftr_out
  );
    option.per_instance = 1;
    option.name = "sep_filter_match_cg";
    // Cross axes only: weight 0, gated like the crosses.
    cp_inst: coverpoint inst_out iff (own_m || own_ftr_out) {
      option.weight = 0; bins in = {1'b0}; bins out = {1'b1};
    }
    cp_dir: coverpoint dir_w iff (own_m || own_ftr_out) {
      option.weight = 0; bins r = {1'b0}; bins w = {1'b1};
    }
    // 1 entry_disabled, 2 ns_mismatch, 3 src_mismatch, 4 burst_mismatch.
    cp_fail: coverpoint fail_cond iff (own_m || own_ftr_out) {
      option.weight = 0;
      bins entry_disabled = {3'd1};
      bins ns_mismatch = {3'd2};
      bins src_mismatch = {3'd3};
      bins burst_mismatch = {3'd4};
    }
    cp_fail_cond_fallthrough: cross cp_inst, cp_dir, cp_fail iff (
        (own_m && !(inst_out && (fail_cond == 3'd3))) ||
        (own_ftr_out && inst_out && (fail_cond == 3'd3))) {
      ignore_bins out_burst = binsof (cp_inst.out) && binsof (cp_fail.burst_mismatch);
    }
    // 1 wildcard, 2 exact, 3 mismatch.
    cp_src: coverpoint src_cls iff (own_m) {
      option.weight = 0; bins wildcard_src = {2'd1}; bins exact = {2'd2}; bins mismatch = {2'd3};
    }
    cp_src_id_class: cross cp_inst, cp_src iff (own_m);
    cp_ar_aw: coverpoint ar_aw_div iff (own_m) {option.weight = 0; bins winner_differs = {1'b1};}
    cp_ar_aw_independent: cross cp_inst, cp_ar_aw iff (own_m);
    // 1 lowest_allow, 2 perm_block, 3 perm_block_hides_allow,
    // 4 fallthrough_allow, 5 no_match.
    cp_win: coverpoint winner iff (own_m) {
      option.weight = 0;
      bins lowest_allow = {3'd1};
      bins perm_block = {3'd2};
      bins perm_block_hides_allow = {3'd3};
      bins fallthrough_allow = {3'd4};
      bins no_match = {3'd5};
    }
    cp_winner_class: cross cp_inst, cp_win iff (own_m) {
      ignore_bins in_perm_block = binsof (cp_inst.in) && binsof (cp_win.perm_block);
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_filter_range_granule_cg
  // ---------------------------------------------------------------------
  covergroup sep_filter_range_granule_cg with function sample (
      logic inst_out,
      logic gran_4k,
      logic [1:0] shape,
      logic [2:0] point,
      logic [1:0] subg,
      logic own
  );
    option.per_instance = 1;
    option.name = "sep_filter_range_granule_cg";
    // Cross axes only: weight 0, gated like the crosses.
    cp_inst: coverpoint inst_out iff (own) {
      option.weight = 0; bins in = {1'b0}; bins out = {1'b1};
    }
    cp_gran: coverpoint gran_4k iff (own) {option.weight = 0; bins g8b = {1'b0}; bins g4k = {1'b1};}
    // 1 one, 2 equal, 3 straddle.
    cp_shape: coverpoint shape iff (own) {
      option.weight = 0; bins one = {2'd1}; bins equal = {2'd2}; bins straddle = {2'd3};
    }
    cp_granule_shape_inst: cross cp_gran, cp_shape, cp_inst iff (own) {
      ignore_bins g8b_one_equal = binsof (cp_gran.g8b) && binsof (cp_shape) intersect {2'd1, 2'd2};
      ignore_bins in_4k_one = binsof (cp_gran.g4k) && binsof (cp_shape.one) && binsof (cp_inst.in);
    }
    // 1 below_widened_base, 2 at_widened_base, 3 at_widened_top_word,
    // 4 above_widened_top.
    cp_point: coverpoint point iff (own) {
      option.weight = 0;
      bins below_widened_base = {3'd1};
      bins at_widened_base = {3'd2};
      bins at_widened_top_word = {3'd3};
      bins above_widened_top = {3'd4};
    }
    cp_probe_point_verdict: cross cp_point, cp_inst iff (own);
    cp_subgranule_off: coverpoint subg iff (own) {
      bins first_word = {2'd1}; bins second_word = {2'd2}; bins last_word_4k = {2'd3};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_filter_default_policy_cg
  // ---------------------------------------------------------------------
  covergroup sep_filter_default_policy_cg with function sample (
      logic inst_out,
      logic [1:0] basis,
      logic [2:0] active_blk,
      logic [1:0] bypass,
      logic own_m,
      logic own_r
  );
    option.per_instance = 1;
    option.name = "sep_filter_default_policy_cg";
    // Cross axes only: weight 0, gated like the cross.
    cp_inst: coverpoint inst_out iff (own_m) {
      option.weight = 0; bins in = {1'b0}; bins out = {1'b1};
    }
    // 1 reset_state, 2 armed_disabled.
    cp_basis: coverpoint basis iff (own_m) {
      option.weight = 0; bins reset_state = {2'd1}; bins armed_disabled = {2'd2};
    }
    cp_deny_basis: cross cp_basis, cp_inst iff (own_m) {
      ignore_bins reset_in = binsof (cp_basis.reset_state) && binsof (cp_inst.in);
    }
    // {kind (0 unmatched, 1 perm_clear_on_match), dir} + 1, with sep_debug 0.
    cp_filter_active_block: coverpoint active_blk iff (own_m) {
      bins unmatched_r = {3'd1};
      bins unmatched_w = {3'd2};
      bins perm_clear_on_match_r = {3'd3};
      bins perm_clear_on_match_w = {3'd4};
    }
    // sep_debug 1: 1 outbound_entry_disabled_blocked, 2
    // outbound_entry_enabled_admitted.
    cp_dbg_bypass: coverpoint bypass iff (own_r) {
      bins outbound_entry_disabled_blocked = {2'd1}; bins outbound_entry_enabled_admitted = {2'd2};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_fabric_dedicated_port_cg (fabric coverpoints and the DMA TCM cells)
  // ---------------------------------------------------------------------
  covergroup sep_fabric_dedicated_port_cg with function sample (
      logic [2:0] ext_init_dir,
      logic own_ext_s,
      logic own_dma_s,
      logic [1:0] ext_cls,
      logic [1:0] ext_burst,
      logic [1:0] tcm_cell,
      logic own_tcm
  );
    option.per_instance = 1;
    option.name = "sep_fabric_dedicated_port_cg";
    // {init (1 LSU, 2 SI, 3 DMA), dir}.
    cp_ext_init_dir_ls: coverpoint ext_init_dir iff (own_ext_s) {
      bins lsu_r = {3'b010}; bins lsu_w = {3'b011}; bins si_r = {3'b100}; bins si_w = {3'b101};
    }
    cp_ext_init_dir_dma: coverpoint ext_init_dir iff (own_dma_s) {
      bins dma_r = {3'b110}; bins dma_w = {3'b111};
    }
    cp_ext_addr_class: coverpoint ext_cls iff (own_ext_s) {
      bins first_word_above_shim = {2'd1}; bins mid = {2'd2}; bins top_word = {2'd3};
    }
    cp_ext_burst: coverpoint ext_burst iff (own_ext_s) {
      bins si_incr_write_len3 = {2'd1}; bins si_incr_read_len7 = {2'd2};
    }
    // {dir, range (0 ICCM, 1 DCCM)}.
    cp_tcm_dma_dir_range: coverpoint tcm_cell iff (own_tcm) {
      bins r_iccm = {2'b00}; bins r_dccm = {2'b01}; bins w_iccm = {2'b10}; bins w_dccm = {2'b11};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_dma_endpoint_cg: the fabric endpoint cells (cp_dma_pair,
  // cp_dma_addr_form, cp_dma_smc_beat) and the DMA area cells
  // (cp_beats_per_txn, cp_src_x_dst_endpoint, sampled in the SPI and DMA
  // section with their own owner gates).
  // ---------------------------------------------------------------------
  covergroup sep_dma_endpoint_cg with function sample (
      logic [3:0] pair,
      logic [2:0] form,
      logic [1:0] smc_beat,
      logic own,
      logic [2:0] bpt,
      logic bpt_v,
      logic [1:0] ep,
      logic ep_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_endpoint_cg";
    // DMA pair by the class of the read and of the write address.
    cp_dma_pair: coverpoint pair iff (own) {
      bins sram_to_register = {4'd1};
      bins register_to_sram = {4'd2};
      bins reset_ctrl_to_sram = {4'd3};
      bins sram_to_smc = {4'd4};
      bins smc_to_sram = {4'd5};
      bins sram_to_ap = {4'd6};
      bins sram_to_smu = {4'd7};
      bins sram_to_ext = {4'd8};
      bins sram_to_sys_csr = {4'd9};
      bins sys_csr_to_sram = {4'd10};
    }
    // {form (0 direct, 1 alias), side (1 sram source, 2 sram destination,
    // 3 ext destination)}.
    cp_dma_addr_form: coverpoint form iff (own) {
      bins direct_sram_src = {3'b0_01};
      bins direct_sram_dst = {3'b0_10};
      bins direct_ext_dst = {3'b0_11};
      bins alias_sram_src = {3'b1_01};
      bins alias_sram_dst = {3'b1_10};
      bins alias_ext_dst = {3'b1_11};
    }
    cp_dma_smc_beat: coverpoint smc_beat iff (own) {
      bins user0_len0_r = {2'd1}; bins user0_len0_w = {2'd2};
    }
    // {write, latched TRANSFER_WIDTH} of each DMA AR and AW handshake with
    // AxLEN = 0.
    cp_beats_per_txn: coverpoint bpt iff (bpt_v) {
      bins read_enc0 = {3'b0_00};
      bins read_enc1 = {3'b0_01};
      bins read_enc2 = {3'b0_10};
      bins write_enc0 = {3'b1_00};
      bins write_enc1 = {3'b1_01};
      bins write_enc2 = {3'b1_10};
    }
    // Class of the latched source and destination at GO.
    cp_src_x_dst_endpoint: coverpoint ep iff (ep_v) {
      bins sram_to_sram = {2'd1}; bins spi_to_sram = {2'd2};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_aperture_reserved_access_cg: the address-map row cells. The memory
  // coverage area extends this group with its own coverpoints.
  //
  // Rows and cells are the generated table
  // (hw/sys/sep/regs/gen/adoc/memory_map.adoc): {base, end, decoded extent}.
  // ---------------------------------------------------------------------
  localparam int unsigned NRows = 21;
  localparam logic [31:0] RowBase[NRows] = '{
      32'h1080_0000,
      32'h1080_1000,
      32'h1080_3000,
      32'h1090_0000,
      32'h1091_0000,
      32'h1091_1000,
      32'h1091_3000,
      32'h1091_5000,
      32'h1091_5800,
      32'h1091_6000,
      32'h1091_8000,
      32'h1092_0000,
      32'h1094_0000,
      32'h1005_0000,
      32'h1080_4000,
      32'h1091_4000,
      32'h1092_1000,
      32'h1093_0600,
      32'h1096_0000,
      32'h10C0_0000,
      32'h1200_0000
  };
  localparam logic [31:0] RowEnd[NRows] = '{
      32'h1080_0FFF,
      32'h1080_1FFF,
      32'h1080_3FFF,
      32'h1090_FFFF,
      32'h1091_0FFF,
      32'h1091_2FFF,
      32'h1091_3FFF,
      32'h1091_57FF,
      32'h1091_5FFF,
      32'h1091_6FFF,
      32'h1091_FFFF,
      32'h1092_0FFF,
      32'h1094_FFFF,
      32'h107F_FFFF,
      32'h108F_FFFF,
      32'h1091_4FFF,
      32'h1092_FFFF,
      32'h1093_FFFF,
      32'h109F_FFFF,
      32'h10FF_FFFF,
      32'h1FFF_FFFF
  };
  localparam logic [31:0] RowExt[NRows] = '{
      32'h150,
      32'h38,
      32'h8,
      32'hC000,
      32'h8C,
      32'h2000,
      32'h1000,
      32'h60,
      32'h48,
      32'h17C,
      32'h18,
      32'h1C,
      32'hC018,
      32'h0,
      32'h0,
      32'h0,
      32'h0,
      32'h0,
      32'h0,
      32'h0,
      32'h0
  };
  // Row ids: 0 DMA, 1 WDT, 2 reset control, 3 OTBN, 4 AES, 5 HMAC, 6 KMAC,
  // 7 CSRNG, 8 EDN, 9 entropy source, 10 LC, 11 KM mailbox, 12 ABR,
  // 13..20 the Reserved rows.
  function automatic int row_of(input logic [31:0] a);
    for (int r = 0; r < NRows; r++) if (in_rng(a, RowBase[r], RowEnd[r])) return r;
    return -1;
  endfunction

  // cp_row_cell code {row[4:0], kind[1:0]}: kind 0 reserved, 1 hole, 2 past,
  // 3 live. The response and the 32-bit data lane equal the cell.
  function automatic logic [7:0] row_cell(input logic [31:0] a, input logic wr,
                                          input logic [1:0] resp, input logic [31:0] lane);
    int r;
    bit is_reg;
    r = row_of(a);
    if (r < 0) return 8'hFF;
    if (r >= 13) begin
      if ((resp == FRespDecerr) && (wr || (lane == 32'hBADC_AB1E))) return 8'({5'(r), 2'd0});
      return 8'hFF;
    end
    if (a >= RowBase[r] + RowExt[r]) begin
      if ((resp == FRespDecerr) && (wr || (lane == 32'hBADC_AB1E))) return 8'({5'(r), 2'd2});
      return 8'hFF;
    end
    is_reg = (r inside {3, 5, 6, 9, 12}) ? fcov_crypto_reg_addr({a[31:2], 2'b00}) : 1'b1;
    if (is_reg) return (!wr && (resp == FRespOkay)) ? 8'({5'(r), 2'd3}) : 8'hFF;
    if (r inside {3, 5, 6}) begin
      if ((resp == FRespSlverr) && (wr || (lane == 32'hFFFF_FFFF))) return 8'({5'(r), 2'd1});
    end else if (r inside {9, 12}) begin
      if ((resp == FRespOkay) && (wr || (lane == 32'h0))) return 8'({5'(r), 2'd1});
    end
    return 8'hFF;
  endfunction

  covergroup sep_aperture_reserved_access_cg with function sample (
      logic [7:0] row_c, logic [1:0] init_dir, logic [2:0] rst_off, logic [1:0] noalias, logic own
  );
    option.per_instance = 1;
    option.name = "sep_aperture_reserved_access_cg";
    cp_row_cell: coverpoint row_c iff (own) {
      bins rsvd_10050000 = {8'd52};
      bins rsvd_10804000 = {8'd56};
      bins rsvd_10914000 = {8'd60};
      bins rsvd_10921000 = {8'd64};
      bins rsvd_10930600 = {8'd68};
      bins rsvd_10960000 = {8'd72};
      bins rsvd_10c00000 = {8'd76};
      bins rsvd_12000000 = {8'd80};
      bins hole_otbn = {8'd13};
      bins hole_hmac = {8'd21};
      bins hole_kmac = {8'd25};
      bins hole_esrc = {8'd37};
      bins hole_abr = {8'd49};
      bins past_dma = {8'd2};
      bins past_wdt = {8'd6};
      bins past_reset_ctrl = {8'd10};
      bins past_otbn = {8'd14};
      bins past_aes = {8'd18};
      bins past_csrng = {8'd30};
      bins past_edn = {8'd34};
      bins past_esrc = {8'd38};
      bins past_lc = {8'd42};
      bins past_km_mbox = {8'd46};
      bins live_dma = {8'd3};
      bins live_wdt = {8'd7};
      bins live_reset_ctrl = {8'd11};
      bins live_otbn = {8'd15};
      bins live_aes = {8'd19};
      bins live_hmac = {8'd23};
      bins live_kmac = {8'd27};
      bins live_csrng = {8'd31};
      bins live_edn = {8'd35};
      bins live_esrc = {8'd39};
      bins live_lc = {8'd43};
      bins live_km_mbox = {8'd47};
      bins live_abr = {8'd51};
    }
    // {init (0 LSU, 1 SI), dir}.
    cp_row_init_dir: coverpoint init_dir iff (own) {
      bins lsu_r = {2'b00}; bins lsu_w = {2'b01}; bins si_r = {2'b10}; bins si_w = {2'b11};
    }
    // The LSU crosses only the reset-control and live-word cells; a
    // live-word cell is a read; reset control is graded from the LSU only.
    x_row_cell_init: cross cp_row_cell, cp_row_init_dir iff (own) {
      ignore_bins live_write = binsof(cp_row_cell) intersect {8'd3, 8'd7, 8'd11, 8'd15, 8'd19, 8'd23, 8'd27, 8'd31, 8'd35, 8'd39, 8'd43, 8'd47, 8'd51} &&
                               binsof(cp_row_init_dir) intersect {
        2'b01, 2'b11
      };
      ignore_bins si_reset_ctrl = binsof(cp_row_cell) intersect {8'd10, 8'd11} &&
                                  binsof(cp_row_init_dir) intersect {
        2'b10, 2'b11
      };
      ignore_bins lsu_other = !binsof(cp_row_cell) intersect {8'd10, 8'd3, 8'd7, 8'd11, 8'd15, 8'd19, 8'd23, 8'd27, 8'd31, 8'd35, 8'd39, 8'd43, 8'd47, 8'd51} &&
                              binsof(cp_row_init_dir) intersect {
        2'b00, 2'b01
      };
    }
    // {class 1 in_extent, 2 immediately_above, 3 far_inside_reserved, dir}.
    cp_aperture_offset_dir: coverpoint rst_off iff (own) {
      bins in_extent_r = {3'b010};
      bins in_extent_w = {3'b011};
      bins immediately_above_r = {3'b100};
      bins immediately_above_w = {3'b101};
      bins far_inside_reserved_r = {3'b110};
      bins far_inside_reserved_w = {3'b111};
    }
    cp_non_aliasing: coverpoint noalias iff (own) {
      bins reset_ctrl = {2'd1}; bins hmac = {2'd2}; bins kmac = {2'd3};
    }
  endgroup

  // ---------------------------------------------------------------------
  // sep_crypto_bus_access_cg: the OTBN register cache cells. The crypto
  // coverage area extends this group with its own coverpoints.
  // ---------------------------------------------------------------------
  covergroup sep_crypto_bus_access_cg with function sample (logic [1:0] cache_dir, logic own);
    option.per_instance = 1;
    option.name = "sep_crypto_bus_access_cg";
    // {AxCACHE[1], dir}.
    cp_otbn_cache_reg: coverpoint cache_dir iff (own) {
      bins nonmod_r = {2'b00}; bins nonmod_w = {2'b01}; bins mod_r = {2'b10}; bins mod_w = {2'b11};
    }
  endgroup

  sep_fabric_inbound_aperture_cg  u_sep_fabric_inbound_aperture_cg  = new();
  sep_fabric_outbound_route_cg    u_sep_fabric_outbound_route_cg    = new();
  sep_remap_output_offset_cg      u_sep_remap_output_offset_cg      = new();
  sep_remap_alias_cg              u_sep_remap_alias_cg              = new();
  sep_filter_match_cg             u_sep_filter_match_cg             = new();
  sep_filter_range_granule_cg     u_sep_filter_range_granule_cg     = new();
  sep_filter_default_policy_cg    u_sep_filter_default_policy_cg    = new();
  sep_fabric_dedicated_port_cg    u_sep_fabric_dedicated_port_cg    = new();
  sep_dma_endpoint_cg             u_sep_dma_endpoint_cg             = new();
  sep_aperture_reserved_access_cg u_sep_aperture_reserved_access_cg = new();
  sep_crypto_bus_access_cg        u_sep_crypto_bus_access_cg        = new();

  // ---------------------------------------------------------------------
  // Sample computation.
  // ---------------------------------------------------------------------
  // Filter-match and default-policy samples of one completion.
  function automatic logic [2:0] fail_code(input logic [3:0] fl);
    unique case (fl)
      4'b0001: return 3'd1;
      4'b0010: return 3'd2;
      4'b0100: return 3'd3;
      4'b1000: return 3'd4;
      default: return 3'd0;
    endcase
  endfunction

  function automatic logic [2:0] winner_code(input fres_t f, input logic [1:0] resp);
    if (!f.win) return (resp == FRespDecerr) ? 3'd5 : 3'd0;
    if (f.perm) begin
      if (resp != FRespOkay) return 3'd0;
      return f.ftr ? 3'd4 : 3'd1;
    end
    if (resp != FRespDecerr) return 3'd0;
    return f.hides_allow ? 3'd3 : 3'd2;
  endfunction

  function automatic logic [1:0] src_code(input fent_t f[32], input fres_t r,
                                          input logic [3:0] user);
    if (!r.low_valid || !f[r.low].en) return 2'd0;
    if (f[r.low].src == 4'd0) return 2'd1;
    return (f[r.low].src == user) ? 2'd2 : 2'd3;
  endfunction

  // Granule leg: shape of the winner's programmed START and END, the probe
  // point against its widened range, and the in-granule offset.
  function automatic logic [1:0] shape_code(input logic [55:0] sw, input logic [55:0] ew,
                                            input logic burst);
    logic [55:0] gs, ge, g;
    g  = burst ? 56'h1000 : 56'h8;
    gs = gran_lo(sw, burst);
    ge = gran_lo(ew, burst);
    if (sw == ew) return 2'd2;
    if (gs == ge) return 2'd1;
    if (ge == gs + g) return 2'd3;
    return 2'd0;
  endfunction

  function automatic logic [2:0] point_code(input logic [55:0] a, input logic [55:0] sw,
                                            input logic [55:0] ew, input logic burst,
                                            input logic [1:0] resp);
    logic [55:0] wb, wt;
    wb = gran_lo(sw, burst);
    wt = gran_hi(ew, burst);
    if ((a == wb - 56'd4) && (resp == FRespDecerr)) return 3'd1;
    if ((a == wb) && (resp == FRespOkay)) return 3'd2;
    if ((a == wt - 56'd3) && (resp == FRespOkay)) return 3'd3;
    if ((a == wt + 56'd1) && (resp == FRespDecerr)) return 3'd4;
    return 3'd0;
  endfunction

  function automatic logic [1:0] subg_code(input logic [55:0] a, input logic burst);
    logic [55:0] off;
    off = a - gran_lo(a, burst);
    if (off == 56'd0) return 2'd1;
    if (off == 56'd4) return 2'd2;
    if (burst && (off == 56'hFFC)) return 2'd3;
    return 2'd0;
  endfunction

  // Lowest enabled entry of an instance, for the single-entry granule leg.
  function automatic int low_en(input fent_t f[32], input int n);
    for (int i = 0; i < n; i++) if (f[i].en) return i;
    return -1;
  endfunction

  // Alias region evaluation of one request at the alias remap input.
  typedef struct packed {
    logic [3:0] boundary;
    logic [2:0] cache_ovr;
    logic [1:0] vgate;
    logic [2:0] offx;
  } al_res_t;

  function automatic al_res_t al_eval(input logic [55:0] a, input logic [3:0] ci,
                                      input logic [55:0] b, input logic [3:0] co, input logic wr);
    al_res_t     r;
    logic [43:0] pg;
    bit          hit;
    int          hk;
    r   = '0;
    pg  = a[55:12];
    hit = 1'b0;
    hk  = -1;
    for (int k = 0; k < 16; k++) begin
      if (al_valid_i[k] && (pg >= al_start_i[k]) && (pg < al_end_i[k]) && !hit) begin
        hit = 1'b1;
        hk  = k;
      end
    end
    // Byte classes S-1, S, E-1 and E; the middle class is any other byte of
    // a page inside the region, so a two-page region still has one.
    for (int k = 0; k < 16; k++) begin
      if (al_valid_i[k] && (r.boundary == 4'd0)) begin
        logic [55:0] sb, eb;
        sb = {al_start_i[k], 12'h000};
        eb = {al_end_i[k], 12'h000};
        if (a == sb - 56'd1) r.boundary = {3'd1, wr};
        else if (a == sb) r.boundary = {3'd2, wr};
        else if (a == eb - 56'd1) r.boundary = {3'd4, wr};
        else if (a == eb) r.boundary = {3'd5, wr};
        else if ((pg > al_start_i[k]) && (pg < al_end_i[k])) r.boundary = {3'd3, wr};
        else if (pg == al_end_i[k] + 44'd1) r.boundary = {3'd6, wr};
      end
    end
    if (hit) begin
      if ((al_cache_i[hk] == 4'hF) && (ci == 4'h0) && (co == 4'hF)) r.cache_ovr = {2'd1, wr};
      if ((al_cache_i[hk] == 4'h0) && (ci == 4'hF) && (co == 4'h0)) r.cache_ovr = {2'd2, wr};
      if (((pg + al_offset_i[hk]) >> 20) & 44'd1 && !a[32] && b[32] &&
          (b[55:12] == pg + al_offset_i[hk])) begin
        r.offx = {2'd0, wr} + 3'd1;
      end
    end else begin
      if (co == ci) r.cache_ovr = {2'd3, wr};
      for (int k = 0; k < 16; k++) begin
        if (!al_valid_i[k] && (pg >= al_start_i[k]) && (pg < al_end_i[k]) && (b == a) && (co == ci)) begin
          r.vgate = wr ? 2'd2 : 2'd1;
          if (((pg + al_offset_i[k]) >> 20) & 44'd1 && !a[32]) begin
            r.offx = {2'd1, wr} + 3'd1;
          end
        end
      end
    end
    return r;
  endfunction

  // Valid-clear with cacheable non-zero: a separate bin of cp_valid_gate.
  function automatic bit al_vgate_cache(input logic [55:0] a, input logic [3:0] ci,
                                        input logic [55:0] b, input logic [3:0] co);
    for (int k = 0; k < 16; k++) begin
      if (!al_valid_i[k] && (al_cache_i[k] != 4'h0) && (a[55:12] >= al_start_i[k]) &&
          (a[55:12] < al_end_i[k]) && (b == a) && (co == ci))
        return 1'b1;
    end
    return 1'b0;
  endfunction

  // Local alias twin: class of a local address and the form of the request.
  function automatic logic [3:0] twin_class(input logic [31:0] a);
    if (in_rng(
            a,
            32'(SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR),
            32'(SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR + SEP_TOP_SEP_SCRATCH_COLD_SIZE - 1)
        ))
      return 4'd1;
    if ({a[31:2], 2'b00} == AES_CTRL_SHADOWED_REG_ADDR) return 4'd2;
    if ({a[31:2], 2'b00} == SEP_CPU_CTRL_SEP_VERSION_ID_REG_ADDR) return 4'd3;
    if ({a[31:2], 2'b00} == SPI_CONTROLLER_CSID_REG_ADDR) return 4'd4;
    if ({a[31:2], 2'b00} == ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR) return 4'd5;
    if ({a[31:3], 3'b000} == FSramBase) return 4'd6;
    if ({a[31:3], 3'b000} == {FSramEnd[31:3], 3'b000}) return 4'd7;
    return 4'd0;
  endfunction

  // A request's form: 0 direct (raw equals translated), 1 alias (raw in the
  // local alias window and translated = SRAM base + offset), 2 neither.
  function automatic logic [1:0] alias_form(input logic [31:0] raw, input logic [31:0] xl);
    if (raw == xl) return 2'd0;
    if ((raw >= 32'hD000_0000) && (xl == FSramBase + (raw - local_base_i[31:0]))) return 2'd1;
    return 2'd2;
  endfunction

  // DMA endpoint class by DMA master address: 1 sram, 2 register, 3
  // reset_ctrl, 4 smc, 5 ap, 6 smu, 7 ext, 8 sys_csr, 0 other.
  function automatic logic [3:0] dma_cls(input logic [31:0] a);
    if (in_rng(a, FSramBase, FSramEnd)) return 4'd1;
    if (in_rng(a, 32'h1080_3000, 32'h1080_3FFF)) return 4'd3;
    if ((smc_size_i != '0) && in_smc_ap({24'd0, a})) return 4'd4;
    if (in_rng(a, FApBase, FApEnd)) return 4'd5;
    if (in_smu_ap({24'd0, a})) return 4'd6;
    if (in_rng(a, FExtBase, FExtEnd)) return 4'd7;
    if (in_rng(a, 32'h10A1_0000, 32'h10A4_FFFF)) return 4'd8;
    if (in_rng(a, 32'h1080_0000, 32'h10FF_FFFF)) return 4'd2;
    return 4'd0;
  endfunction

  function automatic logic [3:0] dma_pair(input logic [3:0] s, input logic [3:0] d);
    if ((s == 4'd1) && (d == 4'd2)) return 4'd1;
    if ((s == 4'd2) && (d == 4'd1)) return 4'd2;
    if ((s == 4'd3) && (d == 4'd1)) return 4'd3;
    if ((s == 4'd1) && (d == 4'd4)) return 4'd4;
    if ((s == 4'd4) && (d == 4'd1)) return 4'd5;
    if ((s == 4'd1) && (d == 4'd5)) return 4'd6;
    if ((s == 4'd1) && (d == 4'd6)) return 4'd7;
    if ((s == 4'd1) && (d == 4'd7)) return 4'd8;
    if ((s == 4'd1) && (d == 4'd8)) return 4'd9;
    if ((s == 4'd8) && (d == 4'd1)) return 4'd10;
    return 4'd0;
  endfunction

  // DMA run tracker: the class of the first read and of the first write of a
  // run; a run ends at the done or error interrupt.
  logic irq_dma_done_q2, irq_dma_err_q2;
  wire        dma_run_end = !in_reset && (((irq_dma_done_i === 1'b1) && !irq_dma_done_q2) ||
                                          ((irq_dma_error_i === 1'b1) && !irq_dma_err_q2));
  logic [3:0] dma_src_cls_q, dma_dst_cls_q;
  logic dma_src_v_q, dma_dst_v_q;
  // Not-connected windows: a DMA request to the boot ROM base or a DMA CSR
  // word, open until the run ends; the probe saw a handshake in the window.
  logic nc_rom_q, nc_rom_seen_q, nc_csr_q, nc_csr_seen_q;
  // DMA TCM cell: a DMA request into ICCM or DCCM, confirmed by tcm activity.
  logic       tcm_pend_q;
  logic [1:0] tcm_cell_q;
  always_ff @(posedge clk_i) begin
    if (in_reset) begin
      irq_dma_done_q2 <= 1'b0;
      irq_dma_err_q2 <= 1'b0;
      dma_src_cls_q <= '0;
      dma_dst_cls_q <= '0;
      dma_src_v_q <= 1'b0;
      dma_dst_v_q <= 1'b0;
      nc_rom_q <= 1'b0;
      nc_rom_seen_q <= 1'b0;
      nc_csr_q <= 1'b0;
      nc_csr_seen_q <= 1'b0;
      tcm_pend_q <= 1'b0;
      tcm_cell_q <= '0;
    end else begin
      irq_dma_done_q2 <= (irq_dma_done_i === 1'b1);
      irq_dma_err_q2  <= (irq_dma_error_i === 1'b1);
      if (dma_run_end) begin
        dma_src_v_q <= 1'b0;
        dma_dst_v_q <= 1'b0;
        nc_rom_q <= 1'b0;
        nc_csr_q <= 1'b0;
      end else begin
        if (dq_ar_hs && !dma_src_v_q) begin
          dma_src_v_q <= 1'b1;
          dma_src_cls_q <= dma_cls(dma_req_i.ar.addr);
        end
        if (dq_aw_hs && !dma_dst_v_q) begin
          dma_dst_v_q <= 1'b1;
          dma_dst_cls_q <= dma_cls(dma_req_i.aw.addr);
        end
        if ((dq_ar_hs && (dma_req_i.ar.addr == FRomBase)) || (dq_aw_hs && (dma_req_i.aw.addr == FRomBase))) begin
          nc_rom_q <= 1'b1;
          nc_rom_seen_q <= 1'b0;
        end else if (nc_rom_q && rom_hs) begin
          nc_rom_seen_q <= 1'b1;
        end
        if (dq_ar_hs && in_rng(dma_req_i.ar.addr, FDmaCsrBase, FDmaCsrEnd)) begin
          nc_csr_q <= 1'b1;
          nc_csr_seen_q <= 1'b0;
        end else if (nc_csr_q && dcsr_hs) begin
          nc_csr_seen_q <= 1'b1;
        end
      end
      if (dq_ar_hs || dq_aw_hs) begin
        if (in_rng(dq_req_a, 32'hC000_0000, 32'hC003_FFFF)) begin
          tcm_pend_q <= 1'b1;
          tcm_cell_q <= {dq_aw_hs, 1'b0};
        end
        if (in_rng(dq_req_a, 32'hC004_0000, 32'hC005_FFFF)) begin
          tcm_pend_q <= 1'b1;
          tcm_cell_q <= {dq_aw_hs, 1'b1};
        end
      end else if (tcm_pend_q && (tcm_clken_i === 1'b1) && ((tcm_wren_i === 1'b1) == tcm_cell_q[1])) begin
        tcm_pend_q <= 1'b0;
      end else if (dq_b_hs || dq_r_end) begin
        tcm_pend_q <= 1'b0;
      end
    end
  end
  wire tcm_hit = tcm_pend_q && (tcm_clken_i === 1'b1) && ((tcm_wren_i === 1'b1) == tcm_cell_q[1]) &&
                 !(dq_ar_hs || dq_aw_hs);

  // Non-aliasing: a gap, tail or hole write of {reset control, HMAC, KMAC}
  // that the decode refused, then an OKAY LSU read of the live reference.
  logic [3:1] na_wr_q;
  function automatic logic [1:0] na_unit(input logic [31:0] a);
    if (in_rng(a, 32'h1080_3008, 32'h1080_3FFF)) return 2'd1;
    if (in_rng(a, 32'h1091_1000, 32'h1091_2FFF) && !fcov_crypto_reg_addr({a[31:2], 2'b00}))
      return 2'd2;
    if (in_rng(a, 32'h1091_3000, 32'h1091_3FFF) && !fcov_crypto_reg_addr({a[31:2], 2'b00}))
      return 2'd3;
    return 2'd0;
  endfunction
  function automatic logic [1:0] na_ref(input logic [31:0] a);
    if ({a[31:2], 2'b00} == 32'(SEP_TOP_SEP_RESET_CTRL_BASE_ADDR)) return 2'd1;
    if ({a[31:2], 2'b00} == HMAC_CFG_REG_ADDR) return 2'd2;
    if (({a[31:2], 2'b00} >= KMAC_PREFIX_0__REG_ADDR) && ({a[31:2], 2'b00} <= KMAC_PREFIX_10__REG_ADDR))
      return 2'd3;
    return 2'd0;
  endfunction
  logic [1:0] na_sample;
  always_comb begin
    na_sample = 2'd0;
    if (lq_rd_done && (lq_resp == FRespOkay) && (na_ref(
            lq_c.addr
        ) != 2'd0) && na_wr_q[na_ref(
            lq_c.addr
        )])
      na_sample = na_ref(lq_c.addr);
  end
  always_ff @(posedge clk_i) begin
    if (in_reset || !own_row) begin
      na_wr_q <= '0;
    end else begin
      if (lq_wr_done && (lq_resp != FRespOkay) && (na_unit(lq_c.addr) != 2'd0))
        na_wr_q[na_unit(lq_c.addr)] <= 1'b1;
      if (si_wr_done && (si_resp != FRespOkay) && (na_unit(si_c.addr[31:0]) != 2'd0))
        na_wr_q[na_unit(si_c.addr[31:0])] <= 1'b1;
      if (na_sample != 2'd0) na_wr_q[na_sample] <= 1'b0;
    end
  end

  // Silence events (sep_fabric_port_silence_cp): a completed request with
  // no handshake on the probe in its window, and the probe alive.
  wire [31:0] lq_a = lq_c.addr;
  wire sil_out_local = lq_done && own_route && alive_out_q && (lq_resp == FRespOkay) && !lq_c.out &&
                       lq_c.rt && (lq_c.sel == SelLocal) &&
                       (in_rng(lq_a, 32'h1080_2000, 32'h1080_20FF) || in_rng(lq_a, 32'h10A1_0000, 32'h10A4_FFFF));
  fres_t lq_of;
  assign lq_of = f_eval(out_f, 32, lq_c.po_addr, lq_dir_w, lq_c.prot[1], 4'd0, 8'd0);
  wire sil_out_deny  = lq_done && own_route && alive_out_q && (lq_resp == FRespDecerr) && !lq_c.out &&
                       lq_c.po && lq_of.low_valid && !lq_of.en_cov;
  wire sil_smc_above = lq_done && own_smc && alive_smc_q && !lq_c.smc && (smc_size_i != '0) &&
                       ({24'd0, lq_a} == smc_base_i + smc_size_i);
  wire sil_smc_smu   = lq_done && own_smc && alive_smc_q && !lq_c.smc && in_smu_ap({24'd0, lq_a}) &&
                       !in_smc_ap({24'd0, lq_a});
  // Written out, not through in_smu_ap(): a continuous assignment re-evaluates
  // only on its own operands, and the function reads the SMU inputs in its body.
  wire smc_in_smu    = (smc_size_i != '0) && (smc_base_i >= smu_base_i) &&
                       (smc_base_i + smc_size_i <= smu_base_i + smu_size_i);
  wire sil_on_smc    = lq_done && own_smc && alive_out_q && lq_c.smc && !lq_c.out;
  wire sil_on_smc_only = sil_on_smc && !smc_in_smu;
  wire sil_on_smc_ovl  = sil_on_smc && smc_in_smu;
  wire sil_shim_first = own_ext && alive_ext_q &&
                        ((lq_done && !lq_c.ext && (lq_a == FExtBase)) ||
                         (si_done && !si_c.ext && (si_c.addr == {24'd0, FExtBase})));
  wire sil_shim_last  = own_ext && alive_ext_q &&
                        ((lq_done && !lq_c.ext && (lq_a == FShimLast)) ||
                         (si_done && !si_c.ext && (si_c.addr == {24'd0, FShimLast})));
  wire sil_ext_deny   = si_done && own_ext && alive_xb_q && (si_c.len != 8'd0) &&
                        (si_resp == FRespDecerr) && !si_c.xb && !si_f.en_cov;
  wire sil_in_filter  = si_done && own_match && alive_xb_q && (si_resp == FRespDecerr) && !si_c.xb &&
                        !si_c.csr && !(si_f.win && si_f.perm);
  wire sil_in_rebase  = si_done && own_rebase && alive_xb_q && (si_resp == FRespDecerr) && !si_c.xb &&
                        !si_c.csr && si_f.win && si_f.perm && (si_local >= 56'h4000_0000);
  wire sil_dma_rom    = dma_run_end && own_dma && alive_rom_q && nc_rom_q && !nc_rom_seen_q;
  wire sil_dma_csr    = dma_run_end && own_dma && alive_dcsr_q && nc_csr_q && !nc_csr_seen_q;

  // sep_fabric_port_silence_cp: one coverpoint per silence property and one
  // bin per cause. A covergroup, not a cover property, so the points land in
  // the functional report with the other fabric groups.
  covergroup sep_fabric_port_silence_cp with function sample (logic [12:0] sil);
    option.per_instance = 1;
    option.name = "sep_fabric_port_silence_cp";
    sil_out_local_target: coverpoint sil[0] {bins target_scratch_or_csr = {1'b1};}
    sil_out_filter_deny: coverpoint sil[1] {bins disabled = {1'b1};}
    sil_smc_outside_aperture: coverpoint sil[3:2] {
      wildcard bins above_top = {2'b?1}; wildcard bins smu_window = {2'b1?};
    }
    sil_out_on_smc_route: coverpoint sil[5:4] {
      wildcard bins smc_only = {2'b?1}; wildcard bins smu_overlap = {2'b1?};
    }
    sil_ext_shim_window: coverpoint sil[7:6] {
      wildcard bins first = {2'b?1}; wildcard bins last = {2'b1?};
    }
    sil_ext_filter_deny: coverpoint sil[8] {bins burst = {1'b1};}
    sil_inbound_refused: coverpoint sil[10:9] {
      wildcard bins filter_deny = {2'b?1}; wildcard bins rebase_ge_0x4000_0000 = {2'b1?};
    }
    sil_dma_not_connected: coverpoint sil[12:11] {
      wildcard bins boot_rom = {2'b?1}; wildcard bins dma_csr = {2'b1?};
    }
  endgroup

  sep_fabric_port_silence_cp u_sep_fabric_port_silence_cp = new();

  wire [12:0] sil_vec = {sil_dma_csr, sil_dma_rom, sil_in_rebase, sil_in_filter, sil_ext_deny,
                         sil_shim_last, sil_shim_first, sil_on_smc_ovl, sil_on_smc_only,
                         sil_smc_smu, sil_smc_above, sil_out_deny, sil_out_local};

  always_ff @(posedge clk_i) begin
    if (|sil_vec) u_sep_fabric_port_silence_cp.sample(sil_vec);
  end

  // Sampling of the fabric and remap covergroups. The block holds no state:
  // it computes each sample argument in procedural locals and calls sample().
  always @(posedge clk_i) begin
    if (!in_reset) begin
      // Inbound completions.
      if (si_done) begin
        logic [2:0] fc;
        int         le;
        u_sep_fabric_inbound_aperture_cg.sample(ap_in_cls, ap_out_cls, ap_tr_cls, ap_lim_cls,
                                                own_rebase, ap_dest, own_rebase || own_match,
                                                ap_burst, ap_burst_hit, ap_burst_bad, own_row);
        fc = (si_f.ftr && si_f.perm && (si_resp == FRespOkay) && ($countones(si_f.low_fail) == 1)) ?
            fail_code(si_f.low_fail) : 3'd0;
        u_sep_filter_match_cg.sample(1'b0, si_dir_w, fc, src_code(in_f, si_f, si_c.user),
                                     si_ar_aw_div, winner_code(si_f, si_resp), own_match, 1'b0);
        le = low_en(in_f, 16);
        if (le >= 0) begin
          u_sep_filter_range_granule_cg.sample(
              1'b0, in_f[le].burst, (si_f.win && (si_f.w == 6'(le))) ? shape_code(
              in_sw_q[le], in_ew_q[le], in_f[le].burst) : 2'd0, point_code(
              si_c.addr, in_sw_q[le], in_ew_q[le], in_f[le].burst, si_resp),
              (si_f.win && si_f.perm && (si_resp == FRespOkay) && (si_c.size == 3'd2)) ? subg_code(
              si_c.addr, in_f[le].burst) : 2'd0, own_match);
        end
        u_sep_filter_default_policy_cg.sample(1'b0,
                                              (si_resp != FRespDecerr || !si_f.all_dis) ? 2'd0 : (!in_range_wr_q ? 2'd1 : (si_f.armed ? 2'd2 : 2'd0)),
                                              ((sep_debug_i === 1'b0) && (si_resp == FRespDecerr))
              ? (!si_f.win ? {2'd0, si_dir_w} + 3'd1 : (!si_f.perm ? {2'd1, si_dir_w} + 3'd1 : 3'd0)) : 3'd0,
                                              2'd0, own_match, 1'b0);
        if (si_c.size == 3'd2) begin
          u_sep_aperture_reserved_access_cg.sample(
              row_cell(
              si_c.addr[31:0], si_dir_w, si_resp, si_c.addr[2] ? si_rdata[63:32] : si_rdata[31:0]),
              {1'b1, si_dir_w}, 3'd0, 2'd0, own_row && (si_c.addr[55:32] == '0));
        end
      end
      // Outbound filter completions.
      if (po_done) begin
        logic [2:0] fc;
        int         le;
        fc = (po_f.ftr && po_f.perm && (po_resp == FRespOkay) && ($countones(po_f.low_fail) == 1)) ?
            fail_code(po_f.low_fail) : 3'd0;
        u_sep_filter_match_cg.sample(1'b1, po_dir_w, fc, src_code(out_f, po_f, po_c.user),
                                     po_ar_aw_div, winner_code(po_f, po_resp), own_match,
                                     own_route);
        le = low_en(out_f, 32);
        if (le >= 0) begin
          u_sep_filter_range_granule_cg.sample(
              1'b1, out_f[le].burst, (po_f.win && (po_f.w == 6'(le))) ? shape_code(
              out_sw_q[le], out_ew_q[le], out_f[le].burst) : 2'd0, point_code(
              po_c.addr, out_sw_q[le], out_ew_q[le], out_f[le].burst, po_resp),
              (po_f.win && po_f.perm && (po_resp == FRespOkay)) ? subg_code(
              po_c.addr, out_f[le].burst) : 2'd0, own_match);
        end
        u_sep_filter_default_policy_cg.sample(1'b1,
                                              (po_resp != FRespDecerr || !po_f.all_dis) ? 2'd0 : (!out_range_wr_q ? 2'd1 : (po_f.armed ? 2'd2 : 2'd0)),
                                              3'd0,
                                              (sep_debug_i !== 1'b1) ? 2'd0 :
              ((po_resp == FRespDecerr) && po_f.low_valid && !po_f.en_cov) ? 2'd1 :
              ((po_resp == FRespOkay) && po_f.win && po_f.perm && po_c.out) ? 2'd2 : 2'd0,
                                              own_match, own_route);
      end
      // LSU completions: row cells of the LSU initiator, the reset-control
      // offset classes, the OTBN cache cells and the non-aliasing compare.
      if (lq_done) begin
        logic [2:0] ro;
        ro = 3'd0;
        if (in_rng(lq_a, 32'h1080_3000, 32'h1080_3007)) ro = {2'd1, lq_dir_w};
        else if (in_rng(lq_a, 32'h1080_3008, 32'h1080_300F)) ro = {2'd2, lq_dir_w};
        else if (in_rng(lq_a, 32'h1080_3010, 32'h1080_3FFF)) ro = {2'd3, lq_dir_w};
        u_sep_aperture_reserved_access_cg.sample(
            ((lq_c.size == 3'd2) && ((row_of(lq_a) == 2) || !lq_dir_w)) ? row_cell(
            lq_a, lq_dir_w, lq_resp, lq_a[2] ? lq_rdata[63:32] : lq_rdata[31:0]) : 8'hFF, {
            1'b0, lq_dir_w}, ro, na_sample, own_row);
        if (in_rng(
                lq_a, 32'h1090_0000, 32'h1090_3FFF
            ) && fcov_crypto_reg_addr(
                {lq_a[31:2], 2'b00}
            ) && (lq_resp == FRespOkay)) begin
          u_sep_crypto_bus_access_cg.sample({lq_c.cache[1], lq_dir_w}, own_row);
        end
      end
      // Outbound port captures.
      if (out_ar_hs || out_aw_hs) begin
        rt_txn_t    t;
        logic [2:0] c;
        logic       w;
        logic [2:0] op;
        logic [11:0] ou;
        logic [55:0] oa;
        w  = out_aw_hs;
        t  = w ? rt_wr_q : rt_rd_q;
        c  = w ? out_wr_cls : out_rd_cls;
        op = w ? out_req_i.aw.prot : out_req_i.ar.prot;
        ou = w ? out_req_i.aw.user : out_req_i.ar.user;
        oa = w ? out_req_i.aw.addr : out_req_i.ar.addr;
        if (c != 3'd0) begin
          logic [3:0] at;
          logic       own_c;
          own_c = (c == 3'd2) ? own_alias : own_route;
          u_sep_fabric_outbound_route_cg.sample({c, w}, own_c,
                                                ((c == 3'd1) && (smu_base_i == 56'h8000_0000) && (smu_size_i == 56'h4000_0000))
                ? ((oa[55:3] == smu_base_i[55:3]) ? 2'd1 :
                   (oa[55:3] == (smu_base_i + smu_size_i - 56'd1) >> 3) ? 2'd2 : 2'd0) : 2'd0,
                                                own_route, 4'd0, 1'b0, 1'b0, 4'd0, 1'b0);
          at = 4'd0;
          if ((c inside {3'd1, 3'd3, 3'd4}) && (op == t.prot) && (t.init == INIT_LSU)) begin
            at = (c == 3'd1) ? 4'd1 : (c == 3'd3) ? 4'd3 : 4'd5;
            at = at + 4'(op[1]);
            u_sep_fabric_outbound_route_cg.sample(4'd0, 1'b0, 2'd0, 1'b0, 4'd0, 1'b0, 1'b0, at,
                                                  own_route);
          end
          if ((c inside {3'd3, 3'd4}) && (t.init == INIT_LSU) && (t.user[3:0] != 4'd0) && (ou == 12'd0)) begin
            u_sep_fabric_outbound_route_cg.sample(4'd0, 1'b0, 2'd0, 1'b0, 4'd0, 1'b0, 1'b0,
                                                  (c == 3'd3) ? 4'd7 : 4'd8, own_route);
          end
          if ((c == 3'd1) && (t.init == INIT_LSU) && (t.user != 12'd0) && (ou == t.user)) begin
            u_sep_fabric_outbound_route_cg.sample(4'd0, 1'b0, 2'd0, 1'b0, 4'd0, 1'b0, 1'b0, 4'd9,
                                                  own_route);
          end
          if ((c == 3'd1) && (t.init == INIT_DMA) && (ou == 12'd0)) begin
            u_sep_fabric_outbound_route_cg.sample(4'd0, 1'b0, 2'd0, 1'b0, 4'd0, 1'b0, 1'b0, 4'd10,
                                                  own_dma);
          end
          if (c inside {3'd3, 3'd4}) begin
            logic [3:0] rg;
            logic       vld;
            rg  = 4'(t.addr[31:0] >> 19);
            vld = (c == 3'd3) ? ap_valid_i[rg] : stee_valid_i[rg];
            if (vld) u_sep_remap_output_offset_cg.sample({(c == 3'd4), w}, own_route || own_dma);
          end
        end
      end
      // SMC port captures.
      if (smc_ar_hs || smc_aw_hs) begin
        rt_txn_t     t;
        logic        w;
        logic [55:0] sa;
        logic [3:0]  sc;
        w  = smc_aw_hs;
        t  = w ? rt_wr_q : rt_rd_q;
        sa = w ? smc_req_i.aw.addr : smc_req_i.ar.addr;
        sc = 4'd0;
        if (smc_size_i == 56'h0100_0000) begin
          logic cfg_b;
          logic last;
          cfg_b = (smc_base_i == 56'h9000_0000);
          if ((smc_base_i == 56'h4000_0000) || cfg_b) begin
            if (sa[55:3] == smc_base_i[55:3]) sc = {cfg_b, 1'b0, w} + 4'd1;
            else if (sa[55:3] == (smc_base_i + smc_size_i - 56'd1) >> 3)
              sc = {cfg_b, 1'b1, w} + 4'd1;
          end
        end
        u_sep_fabric_outbound_route_cg.sample(
            (smc_wr_cls == 3'd5 || smc_rd_cls == 3'd5) ? {3'd5, w} : 4'd0, own_smc, 2'd0, 1'b0, sc,
            own_smc, (smc_fuse_done_i === 1'b1), 4'd0, 1'b0);
        if (t.init == INIT_DMA) begin
          logic [11:0] su;
          logic [7:0]  sl;
          su = w ? smc_req_i.aw.user : smc_req_i.ar.user;
          sl = w ? smc_req_i.aw.len : smc_req_i.ar.len;
          if ((su == 12'd0) && (sl == 8'd0))
            u_sep_dma_endpoint_cg.sample(4'd0, 3'd0, w ? 2'd2 : 2'd1, own_dma, 3'd0, 1'b0, 2'd0,
                                         1'b0);
        end
      end
      // Extension port captures.
      if (ext_ar_hs || ext_aw_hs) begin
        logic        w;
        logic [31:0] ea;
        logic [2:0]  es;
        logic [7:0]  el;
        logic [1:0]  eb;
        init_e       ei;
        logic [1:0]  ecls;
        logic [1:0]  ebu;
        w  = ext_aw_hs;
        ea = w ? ext_req_i.aw.addr : ext_req_i.ar.addr;
        es = w ? ext_req_i.aw.size : ext_req_i.ar.size;
        el = w ? ext_req_i.aw.len : ext_req_i.ar.len;
        eb = w ? ext_req_i.aw.burst : ext_req_i.ar.burst;
        ei = who(w, ea, 1, 1, 1);
        ecls = 2'd0;
        if ((ea == FExtFirst) && (es <= 3'd2)) ecls = 2'd1;
        else if ({ea[31:3], 3'b000} == FExtTopWord) ecls = 2'd3;
        else if (in_rng(ea, FExtFirst, FExtEnd)) ecls = 2'd2;
        ebu = 2'd0;
        if ((ei == INIT_SI) && (eb == axi_pkg::BURST_INCR) && w && (el == 8'd3)) ebu = 2'd1;
        if ((ei == INIT_SI) && (eb == axi_pkg::BURST_INCR) && !w && (el == 8'd7)) ebu = 2'd2;
        u_sep_fabric_dedicated_port_cg.sample(
            (ei == INIT_LSU) ? {2'd1, w} : (ei == INIT_SI) ? {2'd2, w} : (ei == INIT_DMA) ? {2'd3, w} : 3'd0,
            own_ext, own_dma, ecls, ebu, 2'd0, 1'b0);
      end
      if (tcm_hit)
        u_sep_fabric_dedicated_port_cg.sample(3'd0, 1'b0, 1'b0, 2'd0, 2'd0, tcm_cell_q,
                                              own_tcm_dma);
      // Alias remap input.
      if (al_ar_hs || al_aw_hs) begin
        logic    w;
        al_res_t ar;
        logic [55:0] ia, oa;
        logic [3:0] ic, oc;
        w  = al_aw_hs;
        ia = w ? alias_in_req_i.aw.addr : alias_in_req_i.ar.addr;
        oa = w ? alias_out_req_i.aw.addr : alias_out_req_i.ar.addr;
        ic = w ? alias_in_req_i.aw.cache : alias_in_req_i.ar.cache;
        oc = w ? alias_out_req_i.aw.cache : alias_out_req_i.ar.cache;
        ar = al_eval(ia, ic, oa, oc, w);
        u_sep_remap_alias_cg.sample(ar.boundary, ar.cache_ovr, ar.vgate, ar.offx, own_alias, 5'd0,
                                    1'b0);
        if (al_vgate_cache(ia, ic, oa, oc)) begin
          u_sep_remap_alias_cg.sample(4'd0, 3'd0, 2'd3, 3'd0, own_alias, 5'd0, 1'b0);
        end
      end
      // CPU LSU alias twin (real CPU only): the raw and translated request.
      if (lsu_raw_live_i === 1'b1) begin
        if (lq_ar_hs || lq_aw_hs) begin
          logic w;
          logic [31:0] ra, xa;
          logic [3:0]  tc;
          logic [1:0]  fm;
          w  = lq_aw_hs;
          ra = w ? lsu_raw_req_i.aw.addr : lsu_raw_req_i.ar.addr;
          xa = w ? lsu_req_i.aw.addr : lsu_req_i.ar.addr;
          tc = twin_class(xa);
          fm = alias_form(ra, xa);
          if ((tc != 4'd0) && (fm != 2'd2)) begin
            u_sep_remap_alias_cg.sample(4'd0, 3'd0, 2'd0, 3'd0, 1'b0, {tc, fm[0]}, own_twin);
          end
        end
      end
      // DMA requests: address form, the ext_top alias twin, and the pair at
      // the end of a run.
      if (dq_ar_hs || dq_aw_hs) begin
        logic w;
        logic [31:0] ra, xa;
        logic [1:0]  fm;
        logic [1:0]  side;
        w  = dq_aw_hs;
        ra = w ? dma_raw_req_i.aw.addr : dma_raw_req_i.ar.addr;
        xa = w ? dma_req_i.aw.addr : dma_req_i.ar.addr;
        fm = alias_form(ra, xa);
        side = 2'd0;
        if (!w && in_rng(xa, FSramBase, FSramEnd)) side = 2'd1;
        if (w && in_rng(xa, FSramBase, FSramEnd)) side = 2'd2;
        if (w && in_rng(xa, FExtBase, FExtEnd)) side = 2'd3;
        if ((side != 2'd0) && (fm != 2'd2))
          u_sep_dma_endpoint_cg.sample(4'd0, {fm[0], side}, 2'd0, own_dma, 3'd0, 1'b0, 2'd0, 1'b0);
        if (w && (fm == 2'd1) && ({xa[31:3], 3'b000} == FExtTopWord)) begin
          u_sep_remap_alias_cg.sample(4'd0, 3'd0, 2'd0, 3'd0, 1'b0, {4'd8, 1'b1}, own_dma);
        end
      end
      if (dma_run_end && dma_src_v_q && dma_dst_v_q) begin
        u_sep_dma_endpoint_cg.sample(dma_pair(dma_src_cls_q, dma_dst_cls_q), 3'd0, 2'd0, own_dma,
                                     3'd0, 1'b0, 2'd0, 1'b0);
      end
    end
  end

  // =====================================================================
  // Phase 2: SPI and DMA groups (docs/SEP_FCOV.adoc, SPI and DMA groups).
  // VCS only. The decode and the owner gate are in the SPI and DMA decode
  // section above. Each `*_v` argument is the gated sample strobe of one
  // coverpoint: the event of the coverpoint AND an owning test's window.
  // The encodings of the packed arguments are in the comment of each
  // coverpoint.
  // =====================================================================

  // --- SPI groups --------------------------------------------------------
  covergroup sep_spi_command_segment_cg with function sample (
      logic [3:0] sd, logic sd_v, logic [1:0] chg, logic chg_v, logic [3:0] fe, logic fe_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_command_segment_cg";
    // {SPEED, DIRECTION} of each segment of a frame that passes the frame
    // gate (leading sck edges equal the sum of the segment cycles).
    cp_speed_dir_legal: coverpoint sd iff (sd_v) {
      bins s0_dummy = {4'b00_00};
      bins s0_rx = {4'b00_01};
      bins s0_tx = {4'b00_10};
      bins s0_bidir = {4'b00_11};
      bins s1_dummy = {4'b01_00};
      bins s1_rx = {4'b01_01};
      bins s1_tx = {4'b01_10};
      bins s2_dummy = {4'b10_00};
      bins s2_rx = {4'b10_01};
      bins s2_tx = {4'b10_10};
    }
    // {SPEED changed, DIRECTION changed} against the previous segment, at a
    // COMMAND write while that segment had CSAAT = 1 and chip select is low.
    cp_chain_change: coverpoint chg iff (chg_v) {
      wildcard bins speed_changed = {2'b1?}; wildcard bins direction_changed = {2'b?1};
    }
    // {DIRECTION, RXQD rose, TXQD fell} from the COMMAND write to the fall
    // of ACTIVE.
    cp_fifo_effect: coverpoint fe iff (fe_v) {
      bins neither = {4'b00_0_0};
      bins rx_pushed = {4'b01_1_0};
      bins tx_popped = {4'b10_0_1};
      bins both = {4'b11_1_1};
    }
  endgroup

  covergroup sep_spi_seg_rand_cg with function sample (
      logic [3:0] lk, logic lk_v, logic [2:0] cd, logic cd_v, logic [3:0] cs, logic cs_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_seg_rand_cg";
    // {LEN class, dummy}: class 0 len0, 1 sub_word, 2 max, 3 word_multiple,
    // 4 non_multiple. A 1 MiB data segment is not driven.
    cp_len_x_kind: coverpoint lk iff (lk_v) {
      bins len0_data = {4'b000_0};
      bins len0_dummy = {4'b000_1};
      bins sub_word_data = {4'b001_0};
      bins sub_word_dummy = {4'b001_1};
      bins max_dummy = {4'b010_1};
      bins word_multiple_data = {4'b011_0};
      bins word_multiple_dummy = {4'b011_1};
      bins non_multiple_data = {4'b100_0};
      bins non_multiple_dummy = {4'b100_1};
      ignore_bins max_data = {4'b010_0};
    }
    // {CSAAT, DIRECTION}.
    cp_csaat_x_dir: coverpoint cd iff (cd_v) {
      bins csaat_dir[] = {[3'd0 : 3'd7]};
    }
    // {CLKDIV class (0 zero, 1 small, 2 mid), SPEED}.
    cp_clkdiv_x_speed: coverpoint cs iff (cs_v) {
      bins clk_speed[] = {[4'd0 : 4'd15]};
      wildcard ignore_bins speed3 = {4'b??11};
      wildcard ignore_bins clk_other = {4'b11??};
    }
  endgroup

  covergroup sep_spi_illegal_access_cg with function sample (
      logic [3:0] ill, logic ill_v, logic cbz, logic cbz_v, logic sz_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_illegal_access_cg";
    // {SPEED, DIRECTION} of an illegal COMMAND whose next ERROR_STATUS read
    // shows CMDINVAL.
    cp_illegal_speed_dir: coverpoint ill iff (ill_v) {
      bins s3_dummy = {4'b11_00};
      bins s3_rx = {4'b11_01};
      bins s3_bidir = {4'b11_11};
      bins s1_bidir = {4'b01_11};
      bins s2_bidir = {4'b10_11};
    }
    // ACTIVE at a COMMAND write with READY = 0, scored at the CMDBUSY rise.
    cp_cmdbusy_cell: coverpoint cbz iff (cbz_v) {
      bins ready0_active0 = {1'b0}; bins ready0_active1 = {1'b1};
    }
    cp_spien0_cmd_write: coverpoint sz_v {bins cmd_write_while_spien0 = {1'b1};}
  endgroup

  covergroup sep_spi_pad_interface_cg with function sample (
      logic [1:0] pt, logic pt_v, logic hr, logic hr_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_pad_interface_cg";
    // Core-clock pad timing against the latched CONFIGOPTS.
    cp_pad_timing_ok: coverpoint pt iff (pt_v) {
      bins period_ok = {2'd0};
      bins lead_ok = {2'd1};
      bins trail_ok = {2'd2};
      bins idle_gap_ok = {2'd3};
    }
    cp_spien_hold_run: coverpoint hr iff (hr_v) {bins hold = {1'b0}; bins run = {1'b1};}
  endgroup

  covergroup sep_spi_pad_rand_cg with function sample (
      logic [2:0] m8,
      logic m8_v,
      logic [4:0] md,
      logic md_v,
      logic [1:0] ck,
      logic ck_v,
      logic [5:0] csn,
      logic csn_v,
      logic [1:0] il,
      logic il_v,
      logic cp,
      logic cp_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_pad_rand_cg";
    // {CPOL, CPHA, FULLCYC}.
    cp_mode8: coverpoint m8 iff (m8_v) {
      bins mode[] = {[3'd0 : 3'd7]};
    }
    // {CPOL, CPHA, FULLCYC, DIRECTION}; the bidirectional cells of the
    // modes other than 000 are not driven.
    cp_mode_x_dir: coverpoint md iff (md_v) {
      bins mode_dir[] = {[5'd0 : 5'd31]};
      wildcard ignore_bins dummy = {5'b???00};
      ignore_bins bidir_not_mode0 = {5'd7, 5'd11, 5'd15, 5'd19, 5'd23, 5'd27, 5'd31};
    }
    cp_clkdiv_class: coverpoint ck iff (ck_v) {
      bins zero = {2'd0}; bins small_1to3 = {2'd1}; bins mid_4to15 = {2'd2};
    }
    // {CSNLEAD class, CSNTRAIL class, CSNIDLE class}: 0 zero, 1 mid, 2 max.
    cp_csn_class: coverpoint csn iff (csn_v) {
      wildcard bins lead_zero = {6'b00_??_??};
      wildcard bins lead_mid = {6'b01_??_??};
      wildcard bins lead_max = {6'b10_??_??};
      wildcard bins trail_zero = {6'b??_00_??};
      wildcard bins trail_mid = {6'b??_01_??};
      wildcard bins trail_max = {6'b??_10_??};
      wildcard bins idle_mid = {6'b??_??_01};
      wildcard bins idle_max = {6'b??_??_10};
    }
    // {latched CPOL, sck} with chip select high.
    cp_idle_level: coverpoint il iff (il_v) {
      bins low_with_cpol0 = {2'b00}; bins high_with_cpol1 = {2'b11};
    }
    cp_cpha_edge: coverpoint cp iff (cp_v) {
      bins cpha0_change_after_trailing_edge = {1'b0}; bins cpha1_change_after_leading_edge = {1'b1};
    }
  endgroup

  covergroup sep_spi_fifo_status_cg with function sample (
      logic [2:0] fl,
      logic fl_v,
      logic [1:0] st,
      logic st_v,
      logic [1:0] ra,
      logic ra_v,
      logic ca,
      logic ca_v,
      logic tw,
      logic tw_v,
      logic [2:0] rr,
      logic rr_v,
      logic [4:0] dc,
      logic dc_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_fifo_status_cg";
    // {flag (0 TXFULL, 1 TXEMPTY, 2 RXFULL, 3 RXEMPTY), new level}.
    cp_flag: coverpoint fl iff (fl_v) {
      bins txfull_0 = {3'b00_0};
      bins txfull_1 = {3'b00_1};
      bins txempty_0 = {3'b01_0};
      bins txempty_1 = {3'b01_1};
      bins rxfull_0 = {3'b10_0};
      bins rxfull_1 = {3'b10_1};
      bins rxempty_0 = {3'b11_0};
      bins rxempty_1 = {3'b11_1};
    }
    cp_stall: coverpoint st iff (st_v) {
      bins tx_stall_entered = {2'd0};
      bins tx_stall_relieved = {2'd1};
      bins rx_stall_entered = {2'd2};
      bins rx_stall_relieved = {2'd3};
    }
    // {READY, ACTIVE}.
    cp_ready_x_active: coverpoint ra iff (ra_v) {
      bins ready_idle = {2'b10};
      bins ready_active = {2'b11};
      bins notready_active = {2'b01};
      bins notready_idle = {2'b00};
    }
    cp_cmd_accept: coverpoint ca iff (ca_v) {
      bins accept_at_active0 = {1'b0}; bins accept_at_active1 = {1'b1};
    }
    cp_tx_write_space: coverpoint tw iff (tw_v) {
      bins tx_write_when_empty = {1'b0}; bins tx_write_when_partial = {1'b1};
    }
    // {while ACTIVE, occupancy (1 one, 2 partial, 3 full)} at an RXDATA read.
    cp_rx_read: coverpoint rr iff (rr_v) {
      bins single_after_poll_one = {3'b0_01};
      bins single_after_poll_partial = {3'b0_10};
      bins single_after_poll_full = {3'b0_11};
      bins while_active_one = {3'b1_01};
      bins while_active_partial = {3'b1_10};
      bins while_active_full = {3'b1_11};
    }
    // {counter (0 CMDQD, 1 TXQD, 2 RXQD), ACTIVE, occupancy (0 zero, 1 one,
    // 2 mid, 3 max)}; TXQD and RXQD with ACTIVE = 1 at one and mid are not
    // graded.
    cp_depth_counter: coverpoint dc iff (dc_v) {
      bins ctr_act_occ[] = {[5'd0 : 5'd23]};
      ignore_bins qd_active_one_mid = {5'b01_1_01, 5'b01_1_10, 5'b10_1_01, 5'b10_1_10};
    }
  endgroup

  covergroup sep_spi_fifo_rand_cg with function sample (
      logic tw_v, logic [2:0] rw, logic rw_v, logic [2:0] ss, logic ss_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_fifo_rand_cg";
    cp_txwm: coverpoint tw_v {bins above_depth = {1'b1};}
    // {RX_WATERMARK class (0 zero, 1 one, 2 mid), out}.
    cp_rxwm: coverpoint rw iff (rw_v) {
      bins zero_into = {3'b00_0};
      bins one_into = {3'b01_0};
      bins one_out = {3'b01_1};
      bins mid_into = {3'b10_0};
      bins mid_out = {3'b10_1};
    }
    // {stall (0 TX, 1 RX), SPEED}.
    cp_stall_x_speed: coverpoint ss iff (ss_v) {
      bins tx_stall_s0 = {3'b0_00};
      bins tx_stall_s1 = {3'b0_01};
      bins tx_stall_s2 = {3'b0_10};
      bins rx_stall_s0 = {3'b1_00};
      bins rx_stall_s1 = {3'b1_01};
      bins rx_stall_s2 = {3'b1_10};
    }
  endgroup

  covergroup sep_spi_interrupt_cg with function sample (
      logic [2:0] ea, logic ea_v, logic it, logic it_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_interrupt_cg";
    cp_event_aggregation: coverpoint ea iff (ea_v) {
      bins single_source_asserts = {3'd0};
      bins several_assert = {3'd1};
      bins enable0_no_assert = {3'd2};
      bins held_while_condition = {3'd3};
      bins deasserted_condition_removed = {3'd4};
      bins deasserted_source_masked = {3'd5};
    }
    cp_intr_test: coverpoint it iff (it_v) {bins error_force = {1'b0}; bins error_release = {1'b1};}
  endgroup

  covergroup sep_spi_misc_rand_cg with function sample (
      logic [4:0] sec,
      logic sec_v,
      logic [3:0] ies,
      logic ies_v,
      logic [4:0] cf,
      logic cf_v,
      logic sw_v,
      logic [2:0] re,
      logic re_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_misc_rand_cg";
    // {source (0 IDLE, 1 READY, 2 TXWM, 3 RXWM, 4 TXEMPTY, 5 RXFULL),
    // EVENT_ENABLE bit, level}.
    cp_event_src_x_en_x_cond: coverpoint sec iff (sec_v) {
      bins src_en_lvl[] = {[5'd0 : 5'd23]};
    }
    // {INTR_ENABLE[1:0], INTR_STATE (0 none, 1 error, 2 event, 3 both)}
    // where PIC source 14 equals (INTR_STATE AND INTR_ENABLE) != 0. The five
    // cells the open test grades are not bins.
    cp_intr_en_x_state: coverpoint ies iff (ies_v) {
      bins en_state[] = {[4'd0 : 4'd15]};
      ignore_bins open_test_cells = {4'b00_00, 4'b01_00, 4'b10_00, 4'b00_01, 4'b01_01};
    }
    // {class (0 CSIDINVAL, 1 CMDINVAL, 2 UNDERFLOW, 3 OVERFLOW, 4 CMDBUSY,
    // 5 ACCESSINVAL), form (0 w1_on_set, 1 w0_on_set, 2 w1_on_clear,
    // 3 w0_on_clear)} at an ERROR_STATUS write.
    cp_clear_form: coverpoint cf iff (cf_v) {
      bins csidinval_w1_on_set = {5'b000_00};
      bins csidinval_w0_on_set = {5'b000_01};
      bins csidinval_w1_on_clear = {5'b000_10};
      bins cmdinval_w1_on_set = {5'b001_00};
      bins cmdinval_w0_on_set = {5'b001_01};
      bins cmdinval_w1_on_clear = {5'b001_10};
      bins underflow_w1_on_set = {5'b010_00};
      bins underflow_w0_on_set = {5'b010_01};
      bins underflow_w1_on_clear = {5'b010_10};
      bins overflow_w1_on_set = {5'b011_00};
      bins overflow_w0_on_set = {5'b011_01};
      bins overflow_w1_on_clear = {5'b011_10};
      bins cmdbusy_w1_on_set = {5'b100_00};
      bins cmdbusy_w0_on_set = {5'b100_01};
      bins cmdbusy_w1_on_clear = {5'b100_10};
      bins accessinval_w1_on_clear = {5'b101_10};
      bins accessinval_w0_on_clear = {5'b101_11};
    }
    cp_swrst_midseg: coverpoint sw_v {bins sw_rst_written_inside_segment = {1'b1};}
    cp_rst_entry_midseg: coverpoint re iff (re_v) {
      bins intr_state = {3'd0};
      bins intr_enable = {3'd1};
      bins control = {3'd2};
      bins configopts = {3'd3};
      bins csid = {3'd4};
      bins error_enable = {3'd5};
      bins error_status = {3'd6};
      bins event_enable = {3'd7};
    }
  endgroup

  covergroup sep_spi_error_status_cg with function sample (
      logic [3:0] rc,
      logic rc_v,
      logic il,
      logic il_v,
      logic uf_v,
      logic of_v,
      logic [3:0] zs,
      logic zs_v,
      logic [31:0] cv,
      logic cv_v
  );
    option.per_instance = 1;
    option.name = "sep_spi_error_status_cg";
    // {class (0 CSIDINVAL, 1 CMDINVAL, 2 UNDERFLOW, 3 OVERFLOW, 4 CMDBUSY),
    // cleared}.
    cp_error_raised_cleared: coverpoint rc iff (rc_v) {
      bins csidinval_raised = {4'b000_0};
      bins csidinval_cleared = {4'b000_1};
      bins cmdinval_raised = {4'b001_0};
      bins cmdinval_cleared = {4'b001_1};
      bins underflow_raised = {4'b010_0};
      bins underflow_cleared = {4'b010_1};
      bins overflow_raised = {4'b011_0};
      bins overflow_cleared = {4'b011_1};
      bins cmdbusy_raised = {4'b100_0};
      bins cmdbusy_cleared = {4'b100_1};
    }
    cp_intr_error_latch: coverpoint il iff (il_v) {
      bins held_after_status_cleared = {1'b0}; bins cleared_by_intr_state_w1c = {1'b1};
    }
    cp_underflow_cell: coverpoint uf_v {bins single_read_enable1 = {1'b1};}
    cp_overflow_cell: coverpoint of_v {bins write_full_enable1 = {1'b1};}
    // {pair (0 0x00, 1 0x18, 2 0x28, 3 0x30), strobe (0 low, 1 high, 2 both)}.
    cp_zero_strobe_cell: coverpoint zs iff (zs_v) {
      bins p00_low = {4'b00_00};
      bins p00_high = {4'b00_01};
      bins p00_both = {4'b00_10};
      bins p18_low = {4'b01_00};
      bins p18_high = {4'b01_01};
      bins p18_both = {4'b01_10};
      bins p28_low = {4'b10_00};
      bins p28_high = {4'b10_01};
      bins p28_both = {4'b10_10};
      bins p30_low = {4'b11_00};
      bins p30_high = {4'b11_01};
      bins p30_both = {4'b11_10};
    }
    cp_csid_out_of_range: coverpoint cv iff (cv_v) {bins csid_mid = {[32'd2 : 32'hFFFF_FFFE]};}
  endgroup

  // The DMA reset-retention coverpoints of the memory, boot and reset area
  // extend this group with their own coverpoints.
  covergroup sep_periph_reset_state_cg with function sample (
      logic [1:0] dom, logic dom_v, logic hold, logic hold_v
  );
    option.per_instance = 1;
    option.name = "sep_periph_reset_state_cg";
    cp_sw_rst_domain: coverpoint dom iff (dom_v) {
      bins tx_fifo_fifos_drained = {2'd0};
      bins rx_fifo_fifos_drained = {2'd1};
      bins core_state_fifos_drained = {2'd2};
    }
    cp_sw_rst_hold: coverpoint hold iff (hold_v) {
      bins reads_back_1_while_held = {1'b0}; bins cleared_by_fw_write = {1'b1};
    }
  endgroup

  // --- DMA groups --------------------------------------------------------
  covergroup sep_spi_dma_use_case_cg with function sample (logic [4:0] uc, logic uc_v);
    option.per_instance = 1;
    option.name = "sep_spi_dma_use_case_cg";
    // {destination SRAM direct, hash off, handshake on, SPEED} of the first
    // Rx COMMAND after a GO with the source in the SPI window.
    cp_use_case_matrix: coverpoint uc iff (uc_v) {
      bins sram_direct_hash_off_handshake_spi_x1 = {5'b1_1_1_00};
    }
  endgroup

  covergroup sep_dma_transfer_cg with function sample (
      logic [3:0] mode, logic mode_v, logic [1:0] al, logic al_v, logic mh, logic mh_v, logic ps_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_transfer_cg";
    // {SRC INCREMENT, SRC WRAP, DST INCREMENT, DST WRAP} at GO.
    cp_src_x_dst_mode: coverpoint mode iff (mode_v) {
      bins mode[] = {[4'd0 : 4'd15]};
    }
    cp_alignment_baseline: coverpoint al iff (al_v) {
      bins enc0 = {2'd0}; bins enc1 = {2'd1}; bins enc2 = {2'd2};
    }
    // mem_to_mem x hash off x {single_chunk, multi_chunk}.
    cp_mode_hash_chunk: coverpoint mh iff (mh_v) {
      bins mem_to_mem_hash_off_single_chunk = {1'b0}; bins mem_to_mem_hash_off_multi_chunk = {1'b1};
    }
    cp_peripheral_stream: coverpoint ps_v {bins fixed_source_incr_dest_multi_chunk = {1'b1};}
  endgroup

  covergroup sep_dma_xfer_rand_cg with function sample (
      logic [5:0] mw,
      logic mw_v,
      logic [4:0] mc,
      logic mc_v,
      logic [1:0] wi,
      logic wi_v,
      logic [1:0] ab,
      logic ab_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_xfer_rand_cg";
    // {address mode (4 bits as cp_src_x_dst_mode), width encoding}.
    cp_mode_x_width: coverpoint mw iff (mw_v) {
      bins mode_width[] = {[6'd0 : 6'd63]}; wildcard ignore_bins enc3 = {6'b????11};
    }
    // {address mode, n > 1}; n > 1 on a side with INCREMENT = 0 and
    // WRAP = 0 is not graded.
    cp_mode_x_chunkcount: coverpoint mc iff (mc_v) {
      bins mode_multi[] = {[5'd0 : 5'd31]};
      wildcard ignore_bins src_fixed_multi = {5'b00??1};
      wildcard ignore_bins dst_fixed_multi = {5'b??001};
    }
    cp_wrap_independence: coverpoint wi iff (wi_v) {
      bins enc0 = {2'd0}; bins enc1 = {2'd1}; bins enc2 = {2'd2};
    }
    // Phase class of the ABORT write; both regions are SEP SRAM.
    cp_abort_phase: coverpoint ab iff (ab_v) {
      bins first_txn_internal_only = {2'd0};
      bins mid_chunk_internal_only = {2'd1};
      bins chunk_boundary_internal_only = {2'd2};
      bins final_txn_internal_only = {2'd3};
    }
  endgroup

  covergroup sep_dma_completion_cg with function sample (
      logic [2:0] gl,
      logic gl_v,
      logic [1:0] bp,
      logic bp_v,
      logic ds,
      logic ds_v,
      logic dcp_v,
      logic [1:0] cc,
      logic cc_v,
      logic cdc_v,
      logic [1:0] cd,
      logic cd_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_completion_cg";
    cp_go_lifecycle: coverpoint gl iff (gl_v) {
      bins normal_set = {3'd0};
      bins normal_autoclear = {3'd1};
      bins handshake_set = {3'd2};
      bins handshake_not_autoclear = {3'd3};
      bins handshake_fw_clear = {3'd4};
    }
    cp_busy_phase: coverpoint bp iff (bp_v) {
      bins idle = {2'd0}; bins in_progress = {2'd1}; bins between_chunks = {2'd2};
    }
    cp_done_set: coverpoint ds iff (ds_v) {
      bins normal_single = {1'b0}; bins final_chunk_of_multi = {1'b1};
    }
    cp_done_clear_path: coverpoint dcp_v {bins hw_autoclear_on_new_transfer = {1'b1};}
    cp_chunk_done_class: coverpoint cc iff (cc_v) {
      bins single_chunk_not_raised = {2'd0};
      bins multi_chunk_raised = {2'd1};
      bins handshake_not_raised = {2'd2};
    }
    cp_chunk_done_clear: coverpoint cdc_v {bins hw_clear_at_next_chunk_start = {1'b1};}
    // {multi_exact, WRAP} in normal mode.
    cp_chunk_decomp: coverpoint cd iff (cd_v) {
      bins single_chunk_wrap0 = {2'b00};
      bins single_chunk_wrap1 = {2'b01};
      bins multi_exact_wrap0 = {2'b10};
      bins multi_exact_wrap1 = {2'b11};
    }
  endgroup

  // RANGE_REGWEN value bin (cp_regwen_value) is parked: it needs the write
  // that applies the range lock, which the register description does not
  // name. It is not in the group.
  covergroup sep_dma_range_config_cg with function sample (
      logic rv_v, logic bl_v, logic [2:0] ip, logic ip_v, logic [1:0] uw, logic uw_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_range_config_cg";
    cp_range_valid_at_go: coverpoint rv_v {bins valid1 = {1'b1};}
    cp_base_limit_rel: coverpoint bl_v {bins limit_gt_base = {1'b1};}
    // {side (0 source, 1 destination), position (0 at BASE, 1 interior,
    // 2 at LIMIT)} of a transfer that ends with DONE and no error.
    cp_inrange_pos_x_side: coverpoint ip iff (ip_v) {
      bins src_at_base = {3'b0_00};
      bins src_interior = {3'b0_01};
      bins src_at_limit = {3'b0_10};
      bins dst_at_base = {3'b1_00};
      bins dst_interior = {3'b1_01};
      bins dst_at_limit = {3'b1_10};
    }
    cp_unlocked_write: coverpoint uw iff (uw_v) {
      bins base = {2'd0}; bins limit = {2'd1}; bins valid = {2'd2};
    }
  endgroup

  covergroup sep_dma_hash_cg with function sample (
      logic it,
      logic it_v,
      logic dv,
      logic dv_v,
      logic [2:0] sw,
      logic sw_v,
      logic [31:0] ml,
      logic ml_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_hash_cg";
    cp_initial_transfer_ctx: coverpoint it iff (it_v) {
      bins continuation_hash = {1'b0}; bins initial_hash = {1'b1};
    }
    cp_digest_valid_lifecycle: coverpoint dv iff (dv_v) {
      bins cleared_at_initial = {1'b0}; bins set_when_digest_written = {1'b1};
    }
    // {DIGEST_SWAP, word (0 first, 1 middle, 2 last_valid)}.
    cp_digest_swap_x_word: coverpoint sw iff (sw_v) {
      bins swap0_first = {3'b0_00};
      bins swap0_middle = {3'b0_01};
      bins swap0_last_valid = {3'b0_10};
      bins swap1_first = {3'b1_00};
      bins swap1_middle = {3'b1_01};
      bins swap1_last_valid = {3'b1_10};
    }
    cp_msg_len_class: coverpoint ml iff (ml_v) {
      bins l52 = {32'd52};
      bins l56 = {32'd56};
      bins l60 = {32'd60};
      bins l64 = {32'd64};
      bins l108 = {32'd108};
      bins l112 = {32'd112};
      bins l116 = {32'd116};
      bins l124 = {32'd124};
      bins l128 = {32'd128};
      bins l132 = {32'd132};
    }
  endgroup

  covergroup sep_dma_config_fault_cg with function sample (
      logic [1:0] sz, logic sz_v, logic hw, logic hw_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_config_fault_cg";
    // Scored at the ERROR_CODE.SIZE_ERROR rise after the faulty GO.
    cp_size_zero_kind: coverpoint sz iff (sz_v) {
      bins total_zero = {2'd0}; bins chunk_zero = {2'd1}; bins both_zero = {2'd2};
    }
    cp_hash_width_fault: coverpoint hw iff (hw_v) {bins enc0 = {1'b0}; bins enc1 = {1'b1};}
  endgroup

  covergroup sep_dma_error_terminal_cg with function sample (logic ea_v, logic ao_v, logic aq_v);
    option.per_instance = 1;
    option.name = "sep_dma_error_terminal_cg";
    cp_error_x_aggregate: coverpoint ea_v {bins size_error_status_and_intr_state = {1'b1};}
    cp_abort_outcome: coverpoint ao_v {bins aborted_set = {1'b1};}
    cp_abort_quiet: coverpoint aq_v {bins no_beat_after_aborted = {1'b1};}
  endgroup

  // sep_dma_containment_cg is not defined here. Its four range-lock
  // coverpoints (cp_locked_write_refused, cp_regwen_invalid_value,
  // cp_lock_recovery, cp_lock_ctx) are parked: each needs the write that
  // applies the range lock, which the register description does not name
  // (secure_dma.adoc, RANGE_REGWEN). The group's executable coverpoint,
  // cp_dma_lock_recovery, belongs to the memory, boot and reset area.

  sep_spi_command_segment_cg u_sep_spi_command_segment_cg = new();
  sep_spi_seg_rand_cg        u_sep_spi_seg_rand_cg        = new();
  sep_spi_illegal_access_cg  u_sep_spi_illegal_access_cg  = new();
  sep_spi_pad_interface_cg   u_sep_spi_pad_interface_cg   = new();
  sep_spi_pad_rand_cg        u_sep_spi_pad_rand_cg        = new();
  sep_spi_fifo_status_cg     u_sep_spi_fifo_status_cg     = new();
  sep_spi_fifo_rand_cg       u_sep_spi_fifo_rand_cg       = new();
  sep_spi_interrupt_cg       u_sep_spi_interrupt_cg       = new();
  sep_spi_misc_rand_cg       u_sep_spi_misc_rand_cg       = new();
  sep_spi_error_status_cg    u_sep_spi_error_status_cg    = new();
  sep_periph_reset_state_cg  u_sep_periph_reset_state_cg  = new();
  sep_spi_dma_use_case_cg    u_sep_spi_dma_use_case_cg    = new();
  sep_dma_transfer_cg        u_sep_dma_transfer_cg        = new();
  sep_dma_xfer_rand_cg       u_sep_dma_xfer_rand_cg       = new();
  sep_dma_completion_cg      u_sep_dma_completion_cg      = new();
  sep_dma_range_config_cg    u_sep_dma_range_config_cg    = new();
  sep_dma_hash_cg            u_sep_dma_hash_cg            = new();
  sep_dma_config_fault_cg    u_sep_dma_config_fault_cg    = new();
  sep_dma_error_terminal_cg  u_sep_dma_error_terminal_cg  = new();

  // --- SPI and DMA sampling ----------------------------------------------
  // LEN class of a segment: 0 len0, 1 sub_word, 2 max, 3 word_multiple,
  // 4 non_multiple.
  function automatic logic [2:0] len_cls(input logic [19:0] len);
    if (len == 20'd0) return 3'd0;
    if (len <= 20'd2) return 3'd1;
    if (len == 20'hFFFFF) return 3'd2;
    if (((len + 20'd1) & 20'd3) == 20'd0) return 3'd3;
    return 3'd4;
  endfunction
  // Occupancy class: 0 zero, 1 one, 2 mid, 3 max (full flag).
  function automatic logic [1:0] occ_cls(input logic [7:0] qd, input logic full);
    if (full) return 2'd3;
    if (qd == 8'd0) return 2'd0;
    if (qd == 8'd1) return 2'd1;
    return 2'd2;
  endfunction
  // RX_WATERMARK class: 0 zero, 1 one, 2 mid (2..126), 3 other.
  function automatic logic [1:0] rxwm_cls(input logic [7:0] wm);
    if (wm == 8'd0) return 2'd0;
    if (wm == 8'd1) return 2'd1;
    if (wm <= 8'd126) return 2'd2;
    return 2'd3;
  endfunction
  // 8-byte SPI pair of a zero-strobe write: 0 0x00, 1 0x18, 2 0x28, 3 0x30, 4 other.
  function automatic logic [2:0] zs_pair(input logic [31:0] a);
    if (a == SpiBase) return 3'd0;
    if (a == SpiBase + 32'h18) return 3'd1;
    if (a == SpiBase + 32'h28) return 3'd2;
    if (a == SpiBase + 32'h30) return 3'd3;
    return 3'd4;
  endfunction

  always @(posedge clk_i) begin
    // ---- SPI command segments, frames and pads ----
    if (fr_end && fr_gate) begin
      for (int i = 0; i < SpiQ; i++) begin
        if (5'(i) < fr_k) begin
          u_sep_spi_command_segment_cg.sample(
              {sq_speed_q[i], sq_dir_q[i]}, sq_own_q[i] && own_spi_matrix, 2'd0, 1'b0, 4'd0, 1'b0);
          u_sep_spi_seg_rand_cg.sample({len_cls(sq_len_q[i]), sq_dir_q[i] == SpiDirDummy},
                                       sq_own_q[i] && own_spi_matrix, 3'd0, 1'b0, 4'd0, 1'b0);
        end
      end
    end
    if (sc_accept) begin
      u_sep_spi_command_segment_cg.sample(4'd0, 1'b0, {sc_speed != sp_speed_q, sc_dir != sp_dir_q},
                                          own_spi_matrix && sp_v_q && sp_csaat_q && si_cslow_q,
                                          4'd0, 1'b0);
      u_sep_spi_seg_rand_cg.sample(4'd0, 1'b0, {sc_csaat, sc_dir}, own_spi_matrix, {
                                   clk_cls, sc_speed}, own_spi_matrix);
      u_sep_spi_pad_rand_cg.sample(cfg_mode, own_spi_timing && cfg_new_q, {cfg_mode, sc_dir},
                                   (own_spi_timing || own_spi_matrix) && (sc_dir != SpiDirDummy),
                                   clk_cls, own_spi_timing || own_spi_matrix || own_spi_fifo, {
                                   csn_cls(cfg_lead), csn_cls(cfg_trail), csn_cls(cfg_idle)},
                                   own_spi_timing, 2'd0, 1'b0, 1'b0, 1'b0);
      u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, si_act_q,
                                      own_spi_fifo || own_spi_matrix, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0,
                                      1'b0);
    end
    if (fe_close)
      u_sep_spi_command_segment_cg.sample(
          4'd0, 1'b0, 2'd0, 1'b0, {
          fe_dir_q, fe_rx_q || (s_rxqd > rxqd_q), fe_tx_q || (s_txqd < txqd_q)},
          fe_own_q && own_spi_matrix);
    if (sr_errst && il_v_q && ((sr_errst_d & SPI_CONTROLLER_ERROR_STATUS_CMDINVAL_MASK) != 32'h0))
      u_sep_spi_illegal_access_cg.sample(il_cell_q, il_own_q && own_spi_matrix, 1'b0, 1'b0, 1'b0);
    if (cbz_v_q && s_es[4] && !es_q[4])
      u_sep_spi_illegal_access_cg.sample(4'd0, 1'b0, cbz_act_q, own_spi_csr, 1'b0);
    if (sz_v_q && sw_ctrl && new_spien && !sz_spoil_q && cs_high && (sck_v == sck_q)) begin
      u_sep_spi_illegal_access_cg.sample(4'd0, 1'b0, 1'b0, 1'b0, own_spi_csr);
      u_sep_spi_pad_interface_cg.sample(2'd0, 1'b0, 1'b0, own_spi_csr);
    end
    if (run_arm_q && fr_start) u_sep_spi_pad_interface_cg.sample(2'd0, 1'b0, 1'b1, own_spi_csr);
    if (pt_period) u_sep_spi_pad_interface_cg.sample(2'd0, own_spi_timing, 1'b0, 1'b0);
    if (pt_lead) u_sep_spi_pad_interface_cg.sample(2'd1, own_spi_timing, 1'b0, 1'b0);
    if (pt_trail) u_sep_spi_pad_interface_cg.sample(2'd2, own_spi_timing, 1'b0, 1'b0);
    if (pt_gap) u_sep_spi_pad_interface_cg.sample(2'd3, own_spi_timing, 1'b0, 1'b0);
    if (spi_on && cs_high && !fr_on_q)
      u_sep_spi_pad_rand_cg.sample(3'd0, 1'b0, 5'd0, 1'b0, 2'd0, 1'b0, 6'd0, 1'b0, {cfg_cpol, sck_v
                                   }, own_spi_timing, 1'b0, 1'b0);
    if (cph0 || cph1)
      u_sep_spi_pad_rand_cg.sample(3'd0, 1'b0, 5'd0, 1'b0, 2'd0, 1'b0, 6'd0, 1'b0, 2'd0, 1'b0, cph1,
                                   own_spi_timing);

    // ---- SPI FIFO and status ----
    if (spi_on && sep_on_q) begin
      if (s_txf != txf_q)
        u_sep_spi_fifo_status_cg.sample({2'd0, s_txf}, own_spi_fifo, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if (s_txe != txe_q)
        u_sep_spi_fifo_status_cg.sample({2'd1, s_txe}, own_spi_fifo, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if (s_rxf != rxf_q)
        u_sep_spi_fifo_status_cg.sample({2'd2, s_rxf}, own_spi_fifo, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if (s_rxe != rxe_q)
        u_sep_spi_fifo_status_cg.sample({2'd3, s_rxe}, own_spi_fifo, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if (s_txst != txst_q)
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, {1'b0, !s_txst}, own_spi_fifo, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if (s_rxst != rxst_q)
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, {1'b1, !s_rxst}, own_spi_fifo, 2'd0, 1'b0, 1'b0,
                                        1'b0, 1'b0, 1'b0, 3'd0, 1'b0, 5'd0, 1'b0);
      if ((s_cb != cb_q) || (s_act != act_q))
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, {!s_cb, s_act},
                                        own_spi_fifo || own_spi_csr, 1'b0, 1'b0, 1'b0, 1'b0, 3'd0,
                                        1'b0, 5'd0, 1'b0);
      if ((s_cmdqd != cmdqd_q) || (s_cb != cb_q))
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                                        3'd0, 1'b0, {2'd0, s_act, occ_cls(8'(s_cmdqd), s_cb)},
                                        own_spi_fifo || own_spi_csr);
      if ((s_txqd != txqd_q) || (s_txf != txf_q))
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                                        3'd0, 1'b0, {2'd1, s_act, occ_cls(s_txqd, s_txf)},
                                        own_spi_fifo || own_spi_csr);
      if ((s_rxqd != rxqd_q) || (s_rxf != rxf_q))
        u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0,
                                        3'd0, 1'b0, {2'd2, s_act, occ_cls(s_rxqd, s_rxf)},
                                        own_spi_fifo || own_spi_csr);
      // Watermarks and stalls.
      if (s_txf && !txf_q && (s_txwm_cfg > s_txqd) && s_txwm && !txwm_fell_q)
        u_sep_spi_fifo_rand_cg.sample(own_spi_fifo, 3'd0, 1'b0, 3'd0, 1'b0);
      if (s_rxwm && !rxwm_q)
        u_sep_spi_fifo_rand_cg.sample(1'b0, {rxwm_cls(s_rxwm_cfg), 1'b0}, own_spi_fifo, 3'd0, 1'b0);
      if (!s_rxwm && rxwm_q && (rxpop_q != 5'd0))
        u_sep_spi_fifo_rand_cg.sample(1'b0, {rxwm_cls(s_rxwm_cfg), 1'b1}, own_spi_fifo, 3'd0, 1'b0);
      if (s_txst && !txst_q)
        u_sep_spi_fifo_rand_cg.sample(1'b0, 3'd0, 1'b0, {1'b0, sp_speed_q}, own_spi_fifo);
      if (s_rxst && !rxst_q)
        u_sep_spi_fifo_rand_cg.sample(1'b0, 3'd0, 1'b0, {1'b1, sp_speed_q}, own_spi_fifo);
      // Event sources against their enables.
      for (int i = 0; i < 6; i++) begin
        if (s_src[i] != src_q1[i])
          u_sep_spi_misc_rand_cg.sample({3'(i), s_evten[i], s_src[i]}, own_spi_csr, 4'd0, 1'b0,
                                        5'd0, 1'b0, 1'b0, 3'd0, 1'b0);
      end
      // Error status raise and clear.
      for (int c = 0; c < 5; c++) begin
        if (s_es[c] && !es_q[c])
          u_sep_spi_error_status_cg.sample({3'(c), 1'b0}, own_spi_csr, 1'b0, 1'b0, 1'b0, 1'b0, 4'd0,
                                           1'b0, 32'd0, 1'b0);
        if (!s_es[c] && es_q[c] && es_arm_q[c])
          u_sep_spi_error_status_cg.sample({3'(c), 1'b1}, own_spi_csr, 1'b0, 1'b0, 1'b0, 1'b0, 4'd0,
                                           1'b0, 32'd0, 1'b0);
      end
    end
    if (sw_txdata)
      u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, !si_txe_q,
                                      own_spi_fifo && (si_txe_q || !si_txf_q), 3'd0, 1'b0, 5'd0,
                                      1'b0);
    if (sr_rxdata) begin
      logic [1:0] oc;
      oc = ra_rxf_q ? 2'd3 : ((ra_rxqd_q == 8'd1) ? 2'd1 : ((ra_rxqd_q > 8'd1) ? 2'd2 : 2'd0));
      u_sep_spi_fifo_status_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, {
                                      ra_act_q, oc}, own_spi_fifo && (ra_act_q || ra_prev_status_q),
                                      5'd0, 1'b0);
    end

    // ---- SPI interrupts ----
    if (ev_rise && (sel_prev != 6'd0))
      u_sep_spi_interrupt_cg.sample(($countones(sel_prev) == 1) ? 3'd0 : 3'd1, own_spi_csr, 1'b0,
                                    1'b0);
    if (ev_fall) begin
      if ((src_q1 & evten_q2) != 6'd0) u_sep_spi_interrupt_cg.sample(3'd5, own_spi_csr, 1'b0, 1'b0);
      else if ((src_q2 & evten_q2) != 6'd0)
        u_sep_spi_interrupt_cg.sample(3'd4, own_spi_csr, 1'b0, 1'b0);
    end
    if (sr_ist) begin
      if ((s_src != 6'd0) && ((s_src & s_evten) == 6'd0) &&
          ((sr_ist_d & SPI_CONTROLLER_INTR_STATE_SPI_EVENT_MASK) == 32'h0))
        u_sep_spi_interrupt_cg.sample(3'd2, own_spi_csr, 1'b0, 1'b0);
      if (((sr_ist_d & SPI_CONTROLLER_INTR_STATE_SPI_EVENT_MASK) != 32'h0) && (held_q != 6'd0))
        u_sep_spi_interrupt_cg.sample(3'd3, own_spi_csr, 1'b0, 1'b0);
    end
    if (sw_itest && ((word4(w_data_q, SpiIntrTest) & SPI_CONTROLLER_INTR_TEST_ERROR_MASK) != 0))
      u_sep_spi_interrupt_cg.sample(3'd0, 1'b0, 1'b0, own_spi_csr);
    if (sw_ist && force_seen_q && ((word4(
            w_data_q, SpiIntrState
        ) & SPI_CONTROLLER_INTR_STATE_ERROR_MASK) != 0))
      u_sep_spi_interrupt_cg.sample(3'd0, 1'b0, 1'b1, own_spi_csr);

    // ---- SPI interrupt line, clear forms, SW_RST, first reads ----
    if (spi_on && (ies_settle_q == 2'd1)) begin
      logic [1:0] en, st;
      en = {s_ien_evt, s_ien_err};
      st = {s_ist_evt, s_ist_err};
      u_sep_spi_misc_rand_cg.sample(5'd0, 1'b0, {en, st},
                                    own_spi_csr && (irq_spi == ((en & st) != 2'b00)), 5'd0, 1'b0,
                                    1'b0, 3'd0, 1'b0);
    end
    if (sw_errst) begin
      for (int c = 0; c < 6; c++) begin
        logic o, w;
        o = si_es_q[c];
        w = sw_errst_d[es_shift(c)];
        u_sep_spi_misc_rand_cg.sample(5'd0, 1'b0, 4'd0, 1'b0, {
                                      3'(c), o ? (w ? 2'd0 : 2'd1) : (w ? 2'd2 : 2'd3)},
                                      own_spi_csr, 1'b0, 3'd0, 1'b0);
      end
    end
    if (sw_ctrl && new_swrst && !ctl_swrst && si_cslow_q)
      u_sep_spi_misc_rand_cg.sample(5'd0, 1'b0, 4'd0, 1'b0, 5'd0, 1'b0, own_spi_csr, 3'd0, 1'b0);
    if (re_hit)
      u_sep_spi_misc_rand_cg.sample(5'd0, 1'b0, 4'd0, 1'b0, 5'd0, 1'b0, 1'b0, re_idx[2:0],
                                    own_spi_coldrst);

    // ---- SPI error status cells ----
    if (esz_v_q && (esz_cnt_q == 2'd0) && s_ist_err && (s_es == 6'd0))
      u_sep_spi_error_status_cg.sample(4'd0, 1'b0, 1'b0, own_spi_csr, 1'b0, 1'b0, 4'd0, 1'b0, 32'd0,
                                       1'b0);
    if (err_q && !s_ist_err && ist_arm_q && (s_es == 6'd0))
      u_sep_spi_error_status_cg.sample(4'd0, 1'b0, 1'b1, own_spi_csr, 1'b0, 1'b0, 4'd0, 1'b0, 32'd0,
                                       1'b0);
    if (sr_rxdata && ra_rxe_q && ra_unf_en_q && !ra_unf_q && s_es[2])
      u_sep_spi_error_status_cg.sample(4'd0, 1'b0, 1'b0, 1'b0, own_spi_csr, 1'b0, 4'd0, 1'b0, 32'd0,
                                       1'b0);
    if (sw_txdata && si_txf_q && si_ovf_en_q && !si_ovf_q && s_es[3])
      u_sep_spi_error_status_cg.sample(4'd0, 1'b0, 1'b0, 1'b0, 1'b0, own_spi_csr, 4'd0, 1'b0, 32'd0,
                                       1'b0);
    if (wr_ev && (zs_pair(aw_addr_q) != 3'd4) && (w_strb_q inside {8'h0F, 8'hF0, 8'hFF})) begin
      logic [2:0] zp;
      zp = zs_pair(aw_addr_q);
      u_sep_spi_error_status_cg.sample(
          4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, {
          zp[1:0], (w_strb_q == 8'h0F) ? 2'd0 : ((w_strb_q == 8'hF0) ? 2'd1 : 2'd2)}, own_spi_csr,
          32'd0, 1'b0);
    end
    if (sr_errst && csr_v_q && (sr_errst_d == 32'h10))
      u_sep_spi_error_status_cg.sample(4'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, csr_val_q,
                                       own_spi_csr);

    // ---- SPI SW_RST domains and hold ----
    if (sw_ctrl && ctl_swrst && !new_swrst && (s_txqd == 8'd0) && s_txe && (s_rxqd == 8'd0) &&
        s_rxe && !s_act) begin
      for (int d = 0; d < 3; d++)
      u_sep_periph_reset_state_cg.sample(2'(d), own_spi_csr, 1'b0, 1'b0);
    end
    if (sr_ctrl && ctl_swrst && ((sr_ctrl_d & SPI_CONTROLLER_CONTROL_SW_RST_MASK) != 32'h0))
      u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, own_spi_csr);
    if (sr_ctrl && swr_clr_q && !ctl_swrst &&
        ((sr_ctrl_d & SPI_CONTROLLER_CONTROL_SW_RST_MASK) == 32'h0))
      u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b1, own_spi_csr);

    // ---- DMA use case and transfer configuration at GO ----
    if (uc_v_q && sw_cmd && (sc_dir == SpiDirRx) && d_cgo_q)
      u_sep_spi_dma_use_case_cg.sample({uc_q, sc_speed}, own_spi_dma_hs);
    if (d_go) begin
      u_sep_dma_transfer_cg.sample(d_mode, own_dma_matrix, d_width_q,
                                   own_dma_matrix && (d_src_q[1:0] == 2'd0) && (d_dst_q[1:0] == 2'd0) && (d_width_q != 2'd3),
                                   d_multi,
                                   own_dma_matrix && (dg_op == DmaOpCopy) && !d_src_spi && !d_dst_spi &&
              (d_single || d_multi),
                                   own_spi_dma_hs && (d_src_q == SpiRxdata) && (d_mode == 4'b01_10) && d_multi);
      u_sep_dma_xfer_rand_cg.sample({d_mode, d_width_q}, own_dma_matrix, {d_mode, d_multi},
                                    own_dma_matrix && (d_single || d_multi), 2'd0, 1'b0, 2'd0,
                                    1'b0);
      u_sep_dma_endpoint_cg.sample(
          4'd0, 3'd0, 2'd0, 1'b0, 3'd0, 1'b0,
          (d_src_sram && d_dst_sram) ? 2'd1 : ((d_src_spi && d_dst_sram) ? 2'd2 : 2'd0),
          own_dma_matrix || own_dma_irq || own_dma_abort || own_spi_dma_hs);
      u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0, 1'b0, 1'b0, {
                                     d_multi_exact, d_swrap_q || d_dwrap_q},
                                     own_dma_matrix && !dg_hs && (d_single || d_multi_exact));
      u_sep_dma_range_config_cg.sample(
          d_rvalid_q && (own_dma_matrix || own_dma_irq || own_dma_abort),
          own_dma_matrix && (d_limit_q > d_base_q), 3'd0, 1'b0, 2'd0, 1'b0);
      u_sep_dma_hash_cg.sample(
          dg_init,
          own_dma_matrix && !dg_hs && (dg_op inside {DmaOpSha256, DmaOpSha384, DmaOpSha512}), 1'b0,
          1'b0, 3'd0, 1'b0, d_total_q,
          own_dma_matrix && dg_init && (dg_op inside {DmaOpSha256, DmaOpSha384, DmaOpSha512}));
    end

    // ---- DMA beats ----
    if (dm_ar && (dma_req_i.ar.len == 8'd0))
      u_sep_dma_endpoint_cg.sample(4'd0, 3'd0, 2'd0, 1'b0, {1'b0, d_width_q},
                                   own_dma_matrix && (d_width_q != 2'd3), 2'd0, 1'b0);
    if (dm_aw && (dma_req_i.aw.len == 8'd0))
      u_sep_dma_endpoint_cg.sample(4'd0, 3'd0, 2'd0, 1'b0, {1'b1, d_width_q},
                                   own_dma_matrix && (d_width_q != 2'd3), 2'd0, 1'b0);

    // ---- DMA completion ----
    if (spi_on && sep_on_q) begin
      logic hs_now;
      hs_now = dci_v_q ? dci_hs_q : d_hs_q;
      if (d_go_q && !go_q)
        u_sep_dma_completion_cg.sample(hs_now ? 3'd2 : 3'd0,
                                       hs_now ? own_spi_dma_hs : own_dma_matrix, 2'd0, 1'b0, 1'b0,
                                       1'b0, 1'b0, 2'd0, 1'b0, 1'b0, 2'd0, 1'b0);
      if (!d_go_q && go_q && !d_hs_q && !dci_v_q)
        u_sep_dma_completion_cg.sample(3'd1, own_dma_matrix, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      if (!d_go_q && go_q && d_hs_q && dci_v_q && !dci_go_q)
        u_sep_dma_completion_cg.sample(3'd4, own_spi_dma_hs, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      if (((busy_q && !d_busy) || (go_q && !d_go_q)) && !d_busy && !d_go_q)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, own_dma_matrix, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      if (d_busy && !busy_q && !d_hs_q)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd1, own_dma_matrix, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      if (d_chunk && !chunk_q && !d_done)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd2, own_dma_matrix, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      if (d_done && !done_q && !d_hs_q) begin
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, d_multi,
                                       own_dma_matrix && (d_single || d_multi), 1'b0,
                                       d_multi ? 2'd1 : 2'd0,
                                       own_dma_matrix && x_on_q &&
                                           ((d_single && !cc_rose_q && !(d_chunk && !chunk_q)) ||
                                            (d_multi && (cc_rose_q || (d_chunk && !chunk_q)))),
                                       1'b0, 2'd0, 1'b0);
        u_sep_dma_xfer_rand_cg.sample(6'd0, 1'b0, 5'd0, 1'b0, x_width_q,
                                      own_dma_matrix && x_on_q && (x_total_q > x_chunk_q) &&
                                          (x_swrap_q || x_dwrap_q) && wi_ok_q &&
                                          (wi_n_q != 8'd0) && (x_width_q != 2'd3),
                                      2'd0, 1'b0);
      end
      if (done_q && !d_done)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0,
                                       own_dma_matrix && dc_go_q && !dc_w1_q, 2'd0, 1'b0, 1'b0,
                                       2'd0, 1'b0);
      if (chunk_q && !d_chunk && !d_done)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0, 1'b0,
                                       own_dma_matrix && !cdc_wr_q, 2'd0, 1'b0);
      if (dr_ctrl && d_hs_q && d_go_q && (d_total_q != 32'h0) &&
          (hs_aw_q >= (d_total_q >> d_width_q)))
        u_sep_dma_completion_cg.sample(3'd3, own_spi_dma_hs, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd2,
                                       own_spi_dma_hs && !hs_chunk_rose_q, 1'b0, 2'd0, 1'b0);

      // ---- DMA range ----
      if (d_done && !done_q && ir_v_q && d_no_err && !d_err) begin
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, {1'b0, ir_src_q},
                                         own_dma_matrix && (ir_src_q != 2'd3), 2'd0, 1'b0);
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, {1'b1, ir_dst_q},
                                         own_dma_matrix && (ir_dst_q != 2'd3), 2'd0, 1'b0);
      end

      // ---- DMA hash ----
      if (dv_arm_q && ((dvalid_q && !d_dvalid) ||
                       (dr_status && ((dr_status_d & SECURE_DMA_STATUS_BUSY_MASK) != 0) &&
                        ((dr_status_d & SECURE_DMA_STATUS_SHA2_DIGEST_VALID_MASK) == 0))))
        u_sep_dma_hash_cg.sample(1'b0, 1'b0, 1'b0, own_dma_matrix, 3'd0, 1'b0, 32'd0, 1'b0);
      if (d_dvalid && !dvalid_q && dv_hash_q)
        u_sep_dma_hash_cg.sample(1'b0, 1'b0, 1'b1, own_dma_matrix, 3'd0, 1'b0, 32'd0, 1'b0);
      if (rd_ev && in_win(ar_addr_q, DmaDigest0, DmaDigestEnd) && d_dvalid) begin
        for (int k = 0; k < 2; k++) begin
          logic [4:0] idx, last;
          idx = 5'((ar_addr_q - DmaDigest0) >> 2) + 5'(k);
          last = dg_last(d_op_q);
          if ((k == 0) || ((ar_size_q == 3'd3) && (ar_addr_q[2] == 1'b0))) begin
            if (idx <= last)
              u_sep_dma_hash_cg.sample(
                  1'b0, 1'b0, 1'b0, 1'b0, {
                  d_gswap_q, (idx == 5'd0) ? 2'd0 : ((idx == last) ? 2'd2 : 2'd1)}, own_dma_matrix,
                  32'd0, 1'b0);
          end
        end
      end

      // ---- DMA faults, errors and abort ----
      if (d_size_err && !size_err_q)
        u_sep_dma_config_fault_cg.sample(szk_q, own_dma_irq && szk_v_q, hwf_q,
                                         own_dma_irq && hwf_v_q);
      if (ea_v_q && d_err && d_ist_err) u_sep_dma_error_terminal_cg.sample(own_dma_irq, 1'b0, 1'b0);
      if (d_aborted && !aborted_q) u_sep_dma_error_terminal_cg.sample(1'b0, own_dma_abort, 1'b0);
      if (ab_on_q && aborted_q && !d_aborted && !ab_after_q && !dm_ar && !dm_aw)
        u_sep_dma_error_terminal_cg.sample(1'b0, 1'b0, own_dma_abort);
      if (d_abort && !abort_q)
        u_sep_dma_xfer_rand_cg.sample(6'd0, 1'b0, 5'd0, 1'b0, 2'd0, 1'b0, abort_cls(
                                      x_ar_q, x_total_q, x_chunk_q, x_width_q),
                                      own_dma_abort && x_on_q && in_win(x_src_q, SramBase, SramEnd
                                      ) && in_win(x_dst_q, SramBase, SramEnd));
    end
    // Range writes while RANGE_REGWEN is 0x6 that change the value.
    if (wr_ev && (rv_old_q == 4'h6)) begin
      if (hit4(aw_addr_q, w_strb_q, DmaBase) && (d_base_now != rb_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd0,
                                         own_dma_matrix || own_dma_irq);
      if (hit4(aw_addr_q, w_strb_q, DmaLimit) && (d_limit_now != rl_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd1,
                                         own_dma_matrix || own_dma_irq);
      if (hit4(aw_addr_q, w_strb_q, DmaRangeValid) && (d_valid_now != rvv_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd2,
                                         own_dma_matrix || own_dma_irq);
    end
  end

endmodule : sep_fcov

`endif

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

`timescale 1ps / 1fs

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
  input wire [2:0]  lsu_aw_size_i,
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
  // Fabric and remap taps (docs/SEP_FCOV.adoc, fabric and remap groups,
  // Sampler taps). Read-only copies of DUT nets.
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
  // port enables of the ICCM and the DCCM, apart (the DMA TCM cells only).
  input sep_pkg::sep_sram_req_t rom_req_i,
  input sep_pkg::sep_sram_rsp_t rom_rsp_i,
  input wire        iccm_clken_i,
  input wire        iccm_wren_i,
  input wire        dccm_clken_i,
  input wire        dccm_wren_i,
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
  input wire        irq_spi_i,

  // ---------------------------------------------------------------------
  // Mailbox, IRQ and PIC taps (docs/SEP_FCOV.adoc, mailbox, IRQ and PIC
  // groups, Signal aliases). Read-only copies of DUT nets and probe
  // ports. The PIC, CLAIM and TLU taps are 0 on the CPU stub build.
  // ---------------------------------------------------------------------
  // VEC: sep_internal_interrupts_probe_o. SMC: smc_mailbox_interrupt_o.
  input wire [42:0]          vec_i,
  input wire [7:0]           smc_irq_i,
  // PIC: veer.pic_ctrl_inst. Index N is PIC source N.
  input wire [255:0][3:0]    pic_prio_i,      // intpriority_reg
  input wire [255:0]         pic_en_i,        // intenable_reg
  input wire [255:0][1:0]    pic_gw_cfg_i,    // gw_config_reg {type, polarity}
  input wire                 pic_cfg_i,       // config_reg (mpiccfg.priord)
  input wire [255:0]         pic_gw_clr_i,    // gw_clear_reg_we
  input wire [255:0]         pic_req_i,       // extintsrc_req (raw input)
  input wire [255:0]         pic_req_gw_i,    // extintsrc_req_gw (gateway output)
  input wire                 pic_wren_i,      // picm_wren_ff
  input wire [14:0]          pic_waddr_i,     // picm_waddr_ff[14:0]
  input wire [31:0]          pic_wdata_i,     // store data of the write, before the PIC field mask
  // PICRD: pic_rd_data_probe_o {picm_rden_ff, picm_raddr_ff[14:0], picm_rd_data}.
  input wire [47:0]          pic_rd_i,
  // CLAIM: veer.pic_claimid. TLU: veer.dec.tlu.
  input wire [7:0]           pic_claim_i,
  input wire                 tlu_mstatus_mie_i,  // mstatus[0]
  input wire [5:0]           tlu_mie_i,
  input wire [5:0]           tlu_mip_i,
  input wire                 tlu_take_ext_i,
  input wire                 tlu_take_nmi_i,
  input wire                 tlu_take_timer_i,
  input wire                 tlu_take_soft_i,
  // MB[m]: gen_mailbox[m].u_axi_lite_mailbox. Port index 0 is i_slv_port_0
  // (outbound aperture), 1 is i_slv_port_1 (inbound aperture). FIFO index 0
  // is i_mbox_0_to_1 (FIFO A), 1 is i_mbox_1_to_0 (FIFO B).
  input wire [7:0][1:0][3:0] mb_status_i,     // status_q
  input wire [7:0][1:0][2:0] mb_irqs_i,       // irqs_q
  input wire [7:0][1:0][2:0] mb_irqen_i,      // irqen_q
  input wire [7:0][1:0][1:0] mb_error_i,      // error_q
  input wire [7:0][1:0][7:0] mb_wirqt_i,      // wirqt_q[7:0]
  input wire [7:0][1:0][7:0] mb_rirqt_i,      // rirqt_q[7:0]
  input wire [7:0][1:0]      mb_irq_i,        // irq_o
  input wire [7:0][1:0][2:0] mf_usage_i,      // usage_o
  input wire [7:0][1:0]      mf_full_i,       // full_o
  input wire [7:0][1:0]      mf_push_i,       // push_i
  input wire [7:0][1:0]      mf_pop_i,        // pop_i
  input wire [7:0][1:0]      mf_flush_i,      // flush_i
  // The AXI-Lite request and response of the mailbox unit (u_sep_axil_mailbox).
  input sep_pkg::sep_system_peripherals_mailbox_axi_lite_req_t  mbx_req_i,
  input sep_pkg::sep_system_peripherals_mailbox_axi_lite_resp_t mbx_resp_i,
  // FILT: u_inbound_filter.
  input wire                 filt_iso_w_i,    // isolate_write
  input wire                 filt_iso_r_i,    // isolate_read
  input wire                 filt_nwm_i,      // no_write_filter_matches
  input wire                 filt_nrm_i,      // no_read_filter_matches
  input wire [3:0]           filt_hit_i,      // write_filter_hit_idx
  input wire                 filt_awvalid_i,  // axi_in_req_i.aw_valid
  input wire                 filt_arvalid_i,  // axi_in_req_i.ar_valid
  input wire [15:0]          filt_locked_i,   // filters[f].locked
  // ALERTP, ERRP, EXT and the RESP inject of tb_top.
  input wire [10:0]          alert_pulse_i,   // crypto_alert_pulse_probe_o
  input wire [17:0]          err_pulse_i,     // sep_cpu_ctrl_err_pulse_probe_o
  input wire [sep_pkg::NUM_EXTERNAL_IRQS-1:0] ext_irq_i,  // sep_ext_interrupts_i
  input wire                 out_resp_hold_i, // smn_outbound_resp_hold_i
  input wire                 out_rd_slverr_i, // smn_outbound_rd_slverr_i
  // The irq field of the DUT port sep_io_spi_req_o.
  input wire                 spi_irq_field_i,

  // Memory, boot, reset, WDT and clock taps (docs/SEP_FCOV.adoc, memory,
  // boot, reset groups, Sampled signal paths): read-only, no force.
  input wire                 clk_wdt_i,
  input wire                 clk_ref_i,
  input wire                 wdt_rst_n_i,       // wdt_rst_ni
  input wire                 dbg_rstb_i,
  input wire                 scan_rst_n_i,      // scan_rst_ni as sep receives it
  input wire                 test_en_i,         // test_en_i as sep receives it
  input wire                 jtag_tck_i,        // core TAP pins after the bench select
  input wire                 jtag_tms_i,
  input wire                 jtag_tdi_i,
  input wire                 jtag_trst_n_i,
  input wire                 jtag_tdo_i,
  input wire                 ext_boot_done_i,   // ext_boot_seq_done_i
  input wire                 mpc_run_req_i,     // mpc_reset_run_req_i
  input wire                 mpc_run_sync_i,    // u_sep_cpu.mpc_reset_run_req_sync
  input wire                 strap_i,           // secure_tm_req_i
  input wire                 wdt_rst_req_i,     // wdt_timer_rst_req_o
  input wire [6:0]           ip_rst_n_i,        // sep_crypto_gated_rst_n, SW_RESET_N order
  input wire [13:0]          iso_req_i,         // sep_crypto_isolate_req, bench index
  input wire [13:0]          iso_ack_i,         // sep_crypto_isolated, bench index
  input wire                 aon_rst_n_i,       // u_sep_wdt_wrap.rst_wdt_n
  input wire [1:0]           km_cond_rst_n_i,   // {rst_cold_aasd_n, rst_warm_sync_n}
  input sep_pkg::jtag_sep_reset_ctrl_t jtag_rst_ctrl_i,  // after the pin-or-TDR mux
  input wire [30:0]          dmi_rst_vec_i,     // reset-vector TDR, bits 31:1
  // u_sep_wdt_wrap adapter stages.
  input sep_pkg::sep_32_32_6_12_axi_req_t  wdt_axi_req_i,
  input sep_pkg::sep_32_32_6_12_axi_req_t  wdt_axi_off_req_i,
  input sep_pkg::sep_32_32_6_12_axi_resp_t wdt_axi_resp_i,
  input sep_pkg::sep_32_32_axil_req_t      wdt_axil_req_i,
  input sep_pkg::sep_32_32_axil_resp_t     wdt_axil_resp_i,
  input tlul_pkg::tl_h2d_t                 wdt_tl_h2d_i,
  input tlul_pkg::tl_d2h_t                 wdt_tl_d2h_i,
  // test_en_i consumer pins, bit 0 the clock gater, bit 1 the AXI cells:
  // every pin of the class at 1, every pin of the class at 0.
  input wire [1:0]           te_pins_one_i,
  input wire [1:0]           te_pins_zero_i,

  // Memory, boot, reset taps of the CPU path, the memory macros and the
  // debug interface (docs/SEP_FCOV.adoc, memory, boot, reset groups,
  // Sampled signal paths): read-only, no force. The trap unit, LSU and DTM
  // taps are 0 on the CPU stub build.
  input wire [31:0]          cpu_trace_insn_i,
  input wire [4:0]           cpu_trace_ecause_i,
  input wire [31:0]          cpu_trace_tval_i,
  input wire [3:0]           ecc_dbg_i,         // ext_debug_bus_o[367:364]
  input sep_pkg::sep_sram_req_t sram_req_i,     // u_dut.sep_sram_req
  input sep_pkg::sep_sram_rsp_t sram_rsp_i,     // u_dut.sep_sram_rsp
  // cpu_tcm_axi_req / resp: the crossbar backdoor into the core DMA port.
  input sep_pkg::sep_32_64_6_12_axi_req_t  tcm_axi_req_i,
  input sep_pkg::sep_32_64_6_12_axi_resp_t tcm_axi_resp_i,
  // The TCM macro request and response (u_dut.sep_cpu_tcm_req, _rsp), bank
  // 0 in the low bits: ICCM 4 banks, DCCM 2 banks, 14-bit rows, 32-bit
  // data and 7-bit ECC per bank.
  input wire [3:0]           tcm_i_clken_i,
  input wire [3:0]           tcm_i_wren_i,
  input wire [55:0]          tcm_i_addr_i,
  input wire [127:0]         tcm_i_wdata_i,
  input wire [27:0]          tcm_i_wecc_i,
  input wire [127:0]         tcm_i_rdata_i,
  input wire [27:0]          tcm_i_recc_i,
  input wire [1:0]           tcm_d_clken_i,
  input wire [1:0]           tcm_d_wren_i,
  input wire [27:0]          tcm_d_addr_i,
  input wire [63:0]          tcm_d_wdata_i,
  input wire [13:0]          tcm_d_wecc_i,
  input wire [63:0]          tcm_d_rdata_i,
  input wire [13:0]          tcm_d_recc_i,
  // u_sep_cpu.ifu_axi_req / resp before the IFU demux (PR-IFU).
  input wire                 ifu_arvalid_i,
  input wire                 ifu_arready_i,
  input wire [31:0]          ifu_araddr_i,
  input wire [2:0]           ifu_arid_i,
  input wire                 ifu_rvalid_i,
  input wire                 ifu_rready_i,
  input wire [1:0]           ifu_rresp_i,
  input wire [2:0]           ifu_rid_i,
  input wire                 ifu_rlast_i,
  // Post-demux CPU master ports of sep.sv.
  input sep_pkg::sep_32_64_3_12_axi_req_t  ifu_rom_req_i,
  input sep_pkg::sep_32_64_3_12_axi_req_t  ifu_sram_req_i,
  input sep_pkg::sep_32_64_3_12_axi_req_t  lsu_rom_req_i,
  input sep_pkg::sep_32_64_3_12_axi_resp_t lsu_rom_resp_i,
  input sep_pkg::sep_32_64_3_12_axi_req_t  lsu_xbar_req_i,
  input sep_pkg::sep_32_64_3_12_axi_resp_t lsu_xbar_resp_i,
  // The ROM macro request after the ROM interface shim (word index).
  input wire                 rom_macro_req_i,
  input wire [12:0]          rom_macro_addr_i,
  // veer.dec.tlu: trap cause, ECC counters and their requests, the counter
  // write strobes and the threshold field of the CSR write data.
  input wire [31:0]          tlu_mcause_i,
  input wire [3:0]           tlu_mscause_i,
  input wire [31:0]          tlu_mdccmect_i,
  input wire [31:0]          tlu_miccmect_i,
  input wire                 tlu_dccm_ce_req_i,  // mdccme_ce_req
  input wire                 tlu_iccm_ce_req_i,  // miccme_ce_req
  input wire                 tlu_ce_int_i,
  input wire                 tlu_wr_dccmect_i,   // wr_mdccmect_r
  input wire                 tlu_wr_iccmect_i,   // wr_miccmect_r
  input wire [4:0]           tlu_csr_wt_i,       // dec_csr_wrdata_r[31:27]
  // veer.lsu: the M-stage packet and address.
  input wire                 lsu_m_valid_i,
  input wire                 lsu_m_load_i,
  input wire                 lsu_m_store_i,
  input wire                 lsu_m_dma_i,
  input wire [31:0]          lsu_m_addr_i,
  input wire [30:0]          nmi_vec_i,          // SEP_CORE.nmi_vec, bits 31:1
  // DTM output before the core and uncore mux, the DMI enables and the
  // uncore DMI outputs.
  input wire                 dmi_en_i,
  input wire [6:0]           dmi_addr_i,
  input wire                 dmi_wr_en_i,
  input wire                 dmi_core_en_i,      // dmi_core_enable_i
  input wire                 dmi_uncore_cfg_i,   // dmi_uncore_enable_i
  input wire                 dmi_uncore_en_i,    // dmi_uncore_en_o
  input wire                 dmi_uncore_wr_en_i  // dmi_uncore_wr_en_o
);

  import sep_top_addrmap_pkg::*;
  `include "sep_reg.svh"
  `include "sep_fcov_owner_codes.svh"

  // Graded-window gate of the Phase 2 groups (docs/SEP_FCOV.adoc, graded
  // window): the code of the owning test whose window is open, 0 when none
  // is. A leaf writes it through the u_sep_fcov handle. It drives nothing.
  int unsigned graded_owner = FcovOwnNone;

  // Quiet-window gate of the mailbox groups (docs/SEP_FCOV.adoc, mailbox, IRQ
  // and PIC sampling rules): 1 while the owning leaf holds a quiet window
  // after the settle wait of a check cycle. A leaf writes it through the
  // u_sep_fcov handle under the rules of graded_owner. It gates a sample, it
  // is never a bin value, and it drives nothing.
  bit quiet_win = 1'b0;

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
  localparam logic [3:0] DmaOpZero = 4'h4;

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
  logic [2:0] ar_size_q, aw_size_q;
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
      if (aw_hs) begin
        aw_addr_q <= lsu_aw_addr_i;
        aw_size_q <= lsu_aw_size_i;
      end
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
  wire dma_hash_any_go = dma_go && (dma_opcode_w inside {DmaOpSha256, DmaOpSha384, DmaOpSha512});
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
  // the wrong one. Every GO sets the label from its own opcode, and a rise of
  // STATUS.ERROR or STATUS.ABORTED clears it, so a failed COPY or SHA-256
  // does not label a later transfer of another opcode.
  logic dma_err_q, dma_abt_q;
  always_ff @(posedge clk_i) begin
    dma_err_q <= (dma_reg2hw_i.status.error.q === 1'b1);
    dma_abt_q <= (dma_aborted_i === 1'b1);
  end
  wire  dma_fail_rise = !in_reset &&
      (((dma_reg2hw_i.status.error.q === 1'b1) && !dma_err_q) ||
       ((dma_aborted_i === 1'b1) && !dma_abt_q));
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
  wire own_dma_zero = (graded_owner == FcovOwnSepDmaZeroFillRandTest);
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
  // CMDBUSY rose between the issue and B of a COMMAND written while READY = 0.
  wire cbz_early = sw_cmd && si_cb_q && s_es[4] && !si_es_q[4];
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
      // rise of ERROR_STATUS.CMDBUSY. A rise between the issue and B is
      // sampled at B (cbz_early) and opens no window.
      if (sw_cmd && si_cb_q && !cbz_early) begin
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
  localparam logic [31:0] DmaRegwen = SECURE_DMA_RANGE_REGWEN_REG_ADDR;
  // RANGE_REGWEN MuBi4 values (secure_dma.rdl): True 0x6, False 0x9.
  localparam logic [3:0] RegwenTrue = 4'(SECURE_DMA_RANGE_REGWEN_REG_DEFAULT);
  localparam logic [3:0] RegwenFalse = ~RegwenTrue;
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
  // A SHA2 opcode: the GO starts a hash (copy and zero fill do not).
  wire        di_hash = di_op inside {DmaOpSha256, DmaOpSha384, DmaOpSha512};
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
  logic [3:0]  rw_q;       // RANGE_REGWEN one clock earlier
  // Unlock values written to RANGE_REGWEN since it became False, one bit
  // each: 0 True, 1 0xF, 2 False, 3 0x0. Cleared whenever it is not False.
  logic [3:0]  lk_try_q;

  function automatic logic [3:0] lk_try_bit(input logic [3:0] v);
    case (v)
      RegwenTrue:  return 4'b0001;
      4'hF:        return 4'b0010;
      RegwenFalse: return 4'b0100;
      4'h0:        return 4'b1000;
      default:     return 4'b0000;
    endcase
  endfunction
  // A write that the DUT refuses because of the lock: RANGE_REGWEN is False
  // at the issue of the write and at its response.
  wire dl_locked = wr_ev && (rv_old_q == RegwenFalse) && (d_regwen == RegwenFalse);
  wire dl_regwen_wr = dl_locked && hit4(aw_addr_q, w_strb_q, DmaRegwen);
  wire [3:0] dl_wd = wr_data[3:0];
  wire dl_valid_wd = wr_data[SECURE_DMA_RANGE_VALID_RANGE_VALID_SHIFT];
  // A refused write of a value other than the stored one to BASE, LIMIT or
  // RANGE_VALID; the register value is unchanged.
  wire dl_base = dl_locked && hit4(aw_addr_q, w_strb_q, DmaBase) &&
      (wr_data != rb_old_q) && (d_base_now == rb_old_q);
  wire dl_limit = dl_locked && hit4(aw_addr_q, w_strb_q, DmaLimit) &&
      (wr_data != rl_old_q) && (d_limit_now == rl_old_q);
  wire dl_valid = dl_locked && hit4(aw_addr_q, w_strb_q, DmaRangeValid) &&
      (dl_valid_wd != rvv_old_q) && (d_valid_now == rvv_old_q);

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

  // Abort phase class from the read handshakes since the initial GO, with the
  // windows of the owning test: k beats per chunk, n in total, w = max(4, k/20).
  // 0 first transaction (b <= w), 3 final transaction (b >= n - n/10),
  // 2 chunk boundary (|b - j*k| <= w for a chunk end j*k below n), 1 mid chunk.
  function automatic logic [1:0] abort_cls(input logic [31:0] b, input logic [31:0] total,
                                           input logic [31:0] chunk, input logic [1:0] width);
    logic [31:0] k, n_all, w, j, d;
    k = chunk >> width;
    n_all = total >> width;
    w = ((k / 32'd20) > 32'd4) ? (k / 32'd20) : 32'd4;
    if (b <= w) return 2'd0;
    if ((n_all != 32'd0) && (b >= n_all - n_all / 32'd10)) return 2'd3;
    if (k != 32'd0) begin
      j = (b + k / 32'd2) / k;
      d = (b >= j * k) ? (b - j * k) : (j * k - b);
      if ((j != 32'd0) && (j * k < n_all) && (d <= w)) return 2'd2;
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
    rw_q <= d_regwen;
    if (in_reset || (d_regwen !== RegwenFalse)) lk_try_q <= 4'h0;
    else if (dl_regwen_wr) lk_try_q <= lk_try_q | lk_try_bit(dl_wd);
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
      if (di_go && di_init && di_hash) dv_arm_q <= 1'b1;
      else if ((dvalid_q && !d_dvalid) ||
               (dr_status && ((dr_status_d & SECURE_DMA_STATUS_BUSY_MASK) != 0) &&
                ((dr_status_d & SECURE_DMA_STATUS_SHA2_DIGEST_VALID_MASK) == 0)))
        dv_arm_q <= 1'b0;
      if (di_go && di_hash) dv_hash_q <= 1'b1;
      else if (d_dvalid && !dvalid_q) dv_hash_q <= 1'b0;

      // Configuration faults: the GO kind waits for the SIZE_ERROR rise.
      if (di_go) begin
        szk_v_q <= (d_total_q == 32'h0) || (d_chunk_q == 32'h0);
        szk_q   <= (d_total_q == 32'h0) ? ((d_chunk_q == 32'h0) ? 2'd2 : 2'd0) : 2'd1;
        hwf_v_q <= di_hash && (d_width_q <= 2'd1);
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

      if (dma_complete || dma_fail_rise) begin
        dma_copy_q <= 1'b0;
        dma_hash_q <= 1'b0;
      end
      if (dma_go) begin
        dma_copy_q <= dma_copy_go;
        dma_hash_q <= dma_hash_go;
        dma_hs_q   <= (wr_data & SECURE_DMA_CONTROL_HARDWARE_HANDSHAKE_ENABLE_MASK) != 32'h0;
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
  // Fabric and remap groups (docs/SEP_FCOV.adoc, fabric and remap groups).
  // VCS only, like the rest of this module.
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
  // Unit classes by aperture: the scratch banks, the system CSRs (alias remap
  // control to CPU control) and the mailboxes.
  localparam logic [31:0] FScrBase = FapBaseSepScratchCold;
  localparam logic [31:0] FScrLast = FapLastSepScratchWarm;
  localparam logic [31:0] FSysBase = FapBaseLocalMasterAliasRemapCtrl;
  localparam logic [31:0] FSysLast = FapLastSepCpuCtrl;
  localparam logic [31:0] FMbxBase = FapBaseAxilMailbox;
  localparam logic [31:0] FMbxLast = FapLastAxilMailbox;
  // OTBN registers: the OTBN aperture below IMEM.
  localparam logic [31:0] FOtbnRegLast = 32'(SEP_TOP_OTBN_IMEM_BASE_ADDR) - 32'd1;
  // The SMU aperture at its RDL reset (SEP_CPU_CTRL).
  localparam logic [55:0] FSmuResetBase = 56'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT);
  localparam logic [55:0] FSmuResetSize = 56'(SEP_CPU_CTRL_SMU_REGION_SIZE_REG_DEFAULT);
  // The peripheral crossbar forwards a local address below this limit to the
  // local crossbar and answers DECERR at or above it (fabric.adoc, "Fabric
  // Topology", input fabric).
  localparam logic [55:0] FXbarLimit = 56'h4000_0000;
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
      else if ((si_resp == FRespOkay) && si_c.csr && in_rng(l, FScrBase, FScrLast))
        ap_in_cls = 3'd2;
    end
    if ((si_c.addr == (sep_base_i + sep_size_i)) && (si_resp == FRespDecerr)) ap_out_cls = 3'd1;
    if ((si_c.addr == (sep_base_i - 56'd1)) && (si_resp == FRespDecerr)) ap_out_cls = 3'd2;
    if (si_c.xb) begin
      if (si_in_win && (si_c.xb_addr == 32'(si_c.addr - sep_base_i))) ap_tr_cls = 3'd1;
      if (!si_in_win && (si_c.xb_addr == si_c.addr[31:0])) ap_tr_cls = 3'd2;
    end
    if ((si_local < FXbarLimit) && si_c.xb) ap_lim_cls = 3'd1;
    if ((si_local >= FXbarLimit) && (si_resp == FRespDecerr) && !si_c.xb) ap_lim_cls = 3'd2;
    // Destination class by the local address (memory_map.adoc).
    if (si_local < FXbarLimit) begin
      if (in_rng(l, FMbxBase, FMbxLast)) cls = 2'd0;
      else if (in_rng(l, FSysBase, FSysLast) || in_rng(l, FScrBase, FScrLast)) cls = 2'd1;
      else if (in_rng(
              l, FRomBase, FRomEnd
          ) || in_rng(
              l, FapBaseSepResetCtrl, FapLastSepResetCtrl
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
            si_c.addr[31:0], FapBaseOtbn, FapLastAbr
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
      logic own_tcm,
      logic [3:0] tri_cell,
      logic tri_v,
      logic eri_v
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
    // CPU path cells (memory, boot, reset groups): {backdoor request, cell}.
    // Cell 0 IFU read ICCM, 1 LSU read ICCM, 2 LSU write ICCM, 3 LSU read
    // DCCM, 4 LSU write DCCM.
    cp_tcm_refused_initiator: coverpoint tri_cell iff (tri_v) {
      bins ifu_read_iccm = {4'b0_000};
      bins lsu_read_iccm = {4'b0_001};
      bins lsu_write_iccm = {4'b0_010};
      bins lsu_read_dccm = {4'b0_011};
      bins lsu_write_dccm = {4'b0_100};
      illegal_bins backdoor_request = {[4'b1_000 : 4'b1_111]};
    }
    cp_ext_refused_ifu: coverpoint eri_v iff (eri_v) {bins no_request_at_fetch_address = {1'b1};}
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
  // The base and the decoded extent of a unit row come from
  // sep_top_addrmap_pkg; the aperture end of each row and the Reserved rows
  // (13..20) have no generated symbol and are copied from that table.
  // ---------------------------------------------------------------------
  localparam int unsigned NRows = 21;
  localparam logic [31:0] RowBase[NRows] = '{
      32'(SEP_TOP_SECURE_DMA_BASE_ADDR),
      32'(SEP_TOP_WDT_TIMER_BASE_ADDR),
      32'(SEP_TOP_SEP_RESET_CTRL_BASE_ADDR),
      32'(SEP_TOP_OTBN_BASE_ADDR),
      32'(SEP_TOP_AES_BASE_ADDR),
      32'(SEP_TOP_HMAC_BASE_ADDR),
      32'(SEP_TOP_KMAC_BASE_ADDR),
      32'(SEP_TOP_CSRNG_BASE_ADDR),
      32'(SEP_TOP_EDN_BASE_ADDR),
      32'(SEP_TOP_ENTROPY_SOURCE_BASE_ADDR),
      32'(SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR),
      32'(SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR),
      32'(SEP_TOP_ABR_BASE_ADDR),
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
      32'(SEP_TOP_SECURE_DMA_SIZE),
      32'(SEP_TOP_WDT_TIMER_SIZE),
      32'(SEP_TOP_SEP_RESET_CTRL_SIZE),
      32'(SEP_TOP_OTBN_SIZE),
      32'(SEP_TOP_AES_SIZE),
      32'(SEP_TOP_HMAC_SIZE),
      32'(SEP_TOP_KMAC_SIZE),
      32'(SEP_TOP_CSRNG_SIZE),
      32'(SEP_TOP_EDN_SIZE),
      32'(SEP_TOP_ENTROPY_SOURCE_SIZE),
      32'(SEP_TOP_SEP_LIFECYCLE_CTRL_SIZE),
      32'(SEP_TOP_KM_MAILBOX_SEP_SIZE),
      32'(SEP_TOP_ABR_SIZE),
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
      logic [7:0] row_c,
      logic [1:0] init_dir,
      logic [2:0] rst_off,
      logic [1:0] noalias,
      logic own,
      logic [3:0] rfw,
      logic rfw_v
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
    // Write to reserved register bits, then the next read returns the written
    // field bits. {register 0 SW_RESET_N 1 cold SCRATCH 2 warm SCRATCH,
    // shape 0 64-bit lane 1 high half only 2 low half with data above the
    // field}.
    cp_reserved_field_write: coverpoint rfw iff (rfw_v) {
      bins sw_reset_n_lane64 = {4'b00_00};
      bins sw_reset_n_high_half = {4'b00_01};
      bins sw_reset_n_low_half_above_field = {4'b00_10};
      bins cold_scratch_lane64 = {4'b01_00};
      bins cold_scratch_high_half = {4'b01_01};
      bins warm_scratch_lane64 = {4'b10_00};
      bins warm_scratch_high_half = {4'b10_01};
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
    if ((raw >= local_base_i[31:0]) && (xl == FSramBase + (raw - local_base_i[31:0]))) return 2'd1;
    return 2'd2;
  endfunction

  // DMA endpoint class by DMA master address: 1 sram, 2 register, 3
  // reset_ctrl, 4 smc, 5 ap, 6 smu, 7 ext, 8 sys_csr, 0 other.
  function automatic logic [3:0] dma_cls(input logic [31:0] a);
    if (in_rng(a, FSramBase, FSramEnd)) return 4'd1;
    if (in_rng(a, FapBaseSepResetCtrl, FapLastSepResetCtrl)) return 4'd3;
    if ((smc_size_i != '0) && in_smc_ap({24'd0, a})) return 4'd4;
    if (in_rng(a, FApBase, FApEnd)) return 4'd5;
    if (in_smu_ap({24'd0, a})) return 4'd6;
    if (in_rng(a, FExtBase, FExtEnd)) return 4'd7;
    if (in_rng(a, FSysBase, FSysLast)) return 4'd8;
    if (in_rng(a, FapBaseSecureDma, FApBase - 32'd1)) return 4'd2;
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
  // The enable of the range that the pending DMA access addresses:
  // tcm_cell_q[0] is 0 for the ICCM range and 1 for the DCCM range.
  wire tcm_clken = tcm_cell_q[0] ? dccm_clken_i : iccm_clken_i;
  wire tcm_wren  = tcm_cell_q[0] ? dccm_wren_i : iccm_wren_i;
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
      end else if (tcm_pend_q && (tcm_clken === 1'b1) && ((tcm_wren === 1'b1) == tcm_cell_q[1])) begin
        tcm_pend_q <= 1'b0;
      end else if (dq_b_hs || dq_r_end) begin
        tcm_pend_q <= 1'b0;
      end
    end
  end
  wire tcm_hit = tcm_pend_q && (tcm_clken === 1'b1) && ((tcm_wren === 1'b1) == tcm_cell_q[1]) &&
                 !(dq_ar_hs || dq_aw_hs);

  // Non-aliasing: a gap, tail or hole write of {reset control, HMAC, KMAC}
  // that the decode refused, then an OKAY LSU read of the live reference.
  logic [3:1] na_wr_q;
  function automatic logic [1:0] na_unit(input logic [31:0] a);
    if (in_rng(a, RowBase[2] + RowExt[2], RowEnd[2])) return 2'd1;
    if (in_rng(a, RowBase[5], RowEnd[5]) && !fcov_crypto_reg_addr({a[31:2], 2'b00})) return 2'd2;
    if (in_rng(a, RowBase[6], RowEnd[6]) && !fcov_crypto_reg_addr({a[31:2], 2'b00})) return 2'd3;
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
                       (in_rng(lq_a, FScrBase, FScrLast) || in_rng(lq_a, FSysBase, FSysLast));
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
                        !si_c.csr && si_f.win && si_f.perm && (si_local >= FXbarLimit);
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
              {1'b1, si_dir_w}, 3'd0, 2'd0, own_row && (si_c.addr[55:32] == '0), 4'd0, 1'b0);
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
        if (in_rng(lq_a, RowBase[2], RowBase[2] + RowExt[2] - 1)) ro = {2'd1, lq_dir_w};
        else if (in_rng(lq_a, RowBase[2] + RowExt[2], RowBase[2] + 2 * RowExt[2] - 1))
          ro = {2'd2, lq_dir_w};
        else if (in_rng(lq_a, RowBase[2] + 2 * RowExt[2], RowEnd[2])) ro = {2'd3, lq_dir_w};
        u_sep_aperture_reserved_access_cg.sample(
            ((lq_c.size == 3'd2) && ((row_of(lq_a) == 2) || !lq_dir_w)) ? row_cell(
            lq_a, lq_dir_w, lq_resp, lq_a[2] ? lq_rdata[63:32] : lq_rdata[31:0]) : 8'hFF, {
            1'b0, lq_dir_w}, ro, na_sample, own_row, 4'd0, 1'b0);
        if (in_rng(
                lq_a, FapBaseOtbn, FOtbnRegLast
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
                                                ((c == 3'd1) && (smu_base_i == FSmuResetBase) && (smu_size_i == FSmuResetSize))
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
            own_ext, own_dma, ecls, ebu, 2'd0, 1'b0, 4'd0, 1'b0, 1'b0);
      end
      if (tcm_hit)
        u_sep_fabric_dedicated_port_cg.sample(3'd0, 1'b0, 1'b0, 2'd0, 2'd0, tcm_cell_q, own_tcm_dma,
                                              4'd0, 1'b0, 1'b0);
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
      logic [1:0] dom,
      logic dom_v,
      logic hold,
      logic hold_v,
      logic [3:0] rv,
      logic rv_v,
      logic nz,
      logic nz_v,
      logic [1:0] fs,
      logic fs_v
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
    // DMA register read after the rst_ni release, before any DMA write, that
    // the owner read at another value before the reset.
    cp_dma_reset_value: coverpoint rv iff (rv_v) {
      bins src_addr_lo = {4'd0};
      bins dst_addr_lo = {4'd1};
      bins enabled_memory_range_base = {4'd2};
      bins enabled_memory_range_limit = {4'd3};
      bins range_valid = {4'd4};
      bins range_regwen = {4'd5};
      bins total_data_size = {4'd6};
      bins chunk_data_size = {4'd7};
      bins handshake_intr_enable = {4'd8};
    }
    cp_dma_nonzero_reset: coverpoint nz iff (nz_v) {
      bins range_regwen_0x6_from_0x0 = {1'b0}; bins handshake_intr_enable_0x7ff_from_0 = {1'b1};
    }
    cp_dma_failsecure: coverpoint fs iff (fs_v) {
      bins range_valid_0 = {2'd0};
      bins range_regwen_0x6 = {2'd1};
      bins handshake_mask_open = {2'd2};
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

  covergroup sep_dma_range_config_cg with function sample (
      logic rv_v,
      logic bl_v,
      logic [2:0] ip,
      logic ip_v,
      logic [1:0] uw,
      logic uw_v,
      logic [3:0] rw,
      logic rw_v
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
    // RANGE_REGWEN at each change of its value.
    cp_regwen_value: coverpoint rw iff (rw_v) {
      bins false_0x9 = {RegwenFalse};
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

  // --- Secure DMA: zero fill ---------------------------------------------
  // A STATUS change belongs to a zero fill when the last initial GO carried
  // OPCODE ZERO. Its outcome is the first rise of DONE, ERROR or ABORTED after
  // that GO; ERROR is split by ERROR_CODE.
  logic dz_on_q, dz_err_q;
  always_ff @(posedge clk_i) begin
    dz_err_q <= d_err;
    if (in_reset) dz_on_q <= 1'b0;
    else if (d_go && dg_init) dz_on_q <= (dg_op == DmaOpZero);
  end
  wire dz_done = dz_on_q && d_done && !done_q;
  wire dz_err = dz_on_q && d_err && !dz_err_q;
  wire dz_aborted = dz_on_q && d_aborted && !aborted_q;
  wire dz_dst_err = (dma_err_code_i[SECURE_DMA_ERROR_CODE_DST_ADDR_ERROR_SHIFT] === 1'b1);
  wire dz_opc_err = (dma_err_code_i[SECURE_DMA_ERROR_CODE_OPCODE_ERROR_SHIFT] === 1'b1);

  covergroup sep_dma_zero_cg with function sample (
      logic [1:0] dst_mode, logic [1:0] width, logic go_v, logic [1:0] outcome, logic out_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_zero_cg";
    // {DST_CONFIG.INCREMENT, DST_CONFIG.WRAP} and TRANSFER_WIDTH at a zero-fill GO.
    cp_dst_mode: coverpoint dst_mode iff (go_v) {
      bins increment = {2'b10}; bins wrap = {2'b11}; bins fixed = {2'b00};
    }
    cp_width: coverpoint width iff (go_v) {bins w1 = {2'd0}; bins w2 = {2'd1}; bins w4 = {2'd2};}
    x_mode_width: cross cp_dst_mode, cp_width;
    cp_outcome: coverpoint outcome iff (out_v) {
      bins done = {2'd0};
      bins window_error = {2'd1};
      bins opcode_error = {2'd2};
      bins aborted = {2'd3};
    }
  endgroup

  // Range lock (sep-programming.adoc, zero fill procedure; dma.adoc, Zero
  // Fill). Every bin of the range-lock coverpoints is a write that the DUT
  // refuses while RANGE_REGWEN is False (dl_locked). cp_dma_lock_recovery is
  // sampled by the memory, boot and reset owner.
  covergroup sep_dma_containment_cg with function sample (
      logic [1:0] lw,
      logic lw_v,
      logic [1:0] iv,
      logic iv_v,
      logic lr_v,
      logic lc,
      logic lc_v,
      logic dlr,
      logic dlr_v
  );
    option.per_instance = 1;
    option.name = "sep_dma_containment_cg";
    // The register of a refused write; regwen_true is a write of True to
    // RANGE_REGWEN. The register value is unchanged.
    cp_locked_write_refused: coverpoint lw iff (lw_v) {
      bins base = {2'd0}; bins limit = {2'd1}; bins valid = {2'd2}; bins regwen_true = {2'd3};
    }
    // A refused RANGE_REGWEN write of a value other than True.
    cp_regwen_invalid_value: coverpoint iv iff (iv_v) {
      bins invalid_0xf = {2'd0}; bins false_0x9 = {2'd1}; bins zero_0x0 = {2'd2};
    }
    // RANGE_REGWEN stays False from the lock until each of True, 0xF, False
    // and 0x0 has been written to it.
    cp_lock_recovery: coverpoint lr_v {
      bins held_across_unlock_attempts = {1'b1};
    }
    // State of the engine at a refused write: idle (no BUSY, no ERROR) or
    // after an error (STATUS.ERROR set).
    cp_lock_ctx: coverpoint lc iff (lc_v) {
      bins idle = {1'b0}; bins after_error = {1'b1};
    }
    // RANGE_REGWEN cleared to 0x0: kept across a CPU-only reset pulse (0),
    // restored to 0x6 after rst_ni (1).
    cp_dma_lock_recovery: coverpoint dlr iff (dlr_v) {
      bins kept_across_cpu_only_pulse = {1'b0}; bins restored_after_rst_ni = {1'b1};
    }
  endgroup

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
  sep_dma_zero_cg            u_sep_dma_zero_cg            = new();
  sep_dma_containment_cg     u_sep_dma_containment_cg     = new();

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
  // A `high` beat carries AWADDR = pair + 4, so the pair is AWADDR aligned down to 8 bytes.
  wire [2:0] zs_p = zs_pair({aw_addr_q[31:3], 3'b000});

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
    if (cbz_early) u_sep_spi_illegal_access_cg.sample(4'd0, 1'b0, si_act_q, own_spi_csr, 1'b0);
    else if (cbz_v_q && s_es[4] && !es_q[4])
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
    // Only an 8-byte beat (AWSIZE = 3) has a zero-strobe half; a 4-byte write is not a cell.
    if (wr_ev && (aw_size_q == 3'd3) && (zs_p != 3'd4) &&
        (w_strb_q inside {8'h0F, 8'hF0, 8'hFF})) begin
      logic [2:0] zp;
      zp = zs_p;
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
      u_sep_periph_reset_state_cg.sample(2'(d), own_spi_csr, 1'b0, 1'b0, 4'd0, 1'b0, 1'b0, 1'b0,
                                         2'd0, 1'b0);
    end
    if (sr_ctrl && ctl_swrst && ((sr_ctrl_d & SPI_CONTROLLER_CONTROL_SW_RST_MASK) != 32'h0))
      u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, own_spi_csr, 4'd0, 1'b0, 1'b0, 1'b0,
                                         2'd0, 1'b0);
    if (sr_ctrl && swr_clr_q && !ctl_swrst &&
        ((sr_ctrl_d & SPI_CONTROLLER_CONTROL_SW_RST_MASK) == 32'h0))
      u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b1, own_spi_csr, 4'd0, 1'b0, 1'b0, 1'b0,
                                         2'd0, 1'b0);

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
          own_dma_matrix && (d_limit_q > d_base_q), 3'd0, 1'b0, 2'd0, 1'b0, 4'd0, 1'b0);
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
      // Handshake mode skips the per-chunk GO clear: GO reads 1 after at least one
      // chunk of write beats and below the total.
      if (dr_ctrl && d_hs_q && d_go_q && (d_chunk_q != 32'h0) &&
          (hs_aw_q >= (d_chunk_q >> d_width_q)) && (hs_aw_q < (d_total_q >> d_width_q)))
        u_sep_dma_completion_cg.sample(3'd3, own_spi_dma_hs, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd0,
                                       1'b0, 1'b0, 2'd0, 1'b0);
      // A handshake run ends in DONE at the total; CHUNK_DONE has not risen since GO.
      if (d_done && !done_q && d_hs_q)
        u_sep_dma_completion_cg.sample(3'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 2'd2,
                                       own_spi_dma_hs && !hs_chunk_rose_q && !(d_chunk && !chunk_q),
                                       1'b0, 2'd0, 1'b0);

      // ---- DMA range ----
      if (d_done && !done_q && ir_v_q && d_no_err && !d_err) begin
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, {1'b0, ir_src_q},
                                         own_dma_matrix && (ir_src_q != 2'd3), 2'd0, 1'b0, 4'd0,
                                         1'b0);
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, {1'b1, ir_dst_q},
                                         own_dma_matrix && (ir_dst_q != 2'd3), 2'd0, 1'b0, 4'd0,
                                         1'b0);
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
      if (d_go && dg_init && (dg_op == DmaOpZero))
        u_sep_dma_zero_cg.sample({d_dinc_q, d_dwrap_q}, d_width_q, own_dma_zero, 2'd0, 1'b0);
      if (dz_done || dz_aborted || (dz_err && (dz_dst_err || dz_opc_err)))
        u_sep_dma_zero_cg.sample(2'd0, 2'd0, 1'b0,
                                 dz_aborted ? 2'd3 : (dz_done ? 2'd0 : (dz_opc_err ? 2'd2 : 2'd1)),
                                 own_dma_zero);
      // An ABORT while the DMA is busy; one before the start or after the end is not a phase.
      if (d_abort && !abort_q && d_busy)
        u_sep_dma_xfer_rand_cg.sample(6'd0, 1'b0, 5'd0, 1'b0, 2'd0, 1'b0, abort_cls(
                                      x_ar_q, x_total_q, x_chunk_q, x_width_q),
                                      own_dma_abort && x_on_q && in_win(x_src_q, SramBase, SramEnd
                                      ) && in_win(x_dst_q, SramBase, SramEnd));
    end
    // Range writes while RANGE_REGWEN is 0x6 that change the value.
    if (wr_ev && (rv_old_q == 4'h6)) begin
      if (hit4(aw_addr_q, w_strb_q, DmaBase) && (d_base_now != rb_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd0,
                                         own_dma_matrix || own_dma_irq, 4'd0, 1'b0);
      if (hit4(aw_addr_q, w_strb_q, DmaLimit) && (d_limit_now != rl_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd1,
                                         own_dma_matrix || own_dma_irq, 4'd0, 1'b0);
      if (hit4(aw_addr_q, w_strb_q, DmaRangeValid) && (d_valid_now != rvv_old_q))
        u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd2,
                                         own_dma_matrix || own_dma_irq, 4'd0, 1'b0);
    end
    if (!in_reset && (d_regwen != rw_q))
      u_sep_dma_range_config_cg.sample(1'b0, 1'b0, 3'd0, 1'b0, 2'd0, 1'b0, d_regwen, own_dma_irq);
    // Refused writes while RANGE_REGWEN is False.
    if (dl_locked) begin
      if (dl_base || dl_limit || dl_valid)
        u_sep_dma_containment_cg.sample(dl_base ? 2'd0 : (dl_limit ? 2'd1 : 2'd2), own_dma_irq,
                                        2'd0, 1'b0, 1'b0, d_err, own_dma_irq && (d_err || !d_busy),
                                        1'b0, 1'b0);
      if (dl_regwen_wr) begin
        u_sep_dma_containment_cg.sample(
            2'd3, own_dma_irq && (dl_wd == RegwenTrue),
            (dl_wd == 4'hF) ? 2'd0 : ((dl_wd == RegwenFalse) ? 2'd1 : 2'd2),
            own_dma_irq && (dl_wd inside {4'hF, RegwenFalse, 4'h0}),
            own_dma_irq && ((lk_try_q | lk_try_bit(dl_wd)) == 4'hF) && (lk_try_q != 4'hF), d_err,
            own_dma_irq && (d_err || !d_busy), 1'b0, 1'b0);
      end
    end
  end

  // =====================================================================
  // Mailbox, IRQ and PIC groups (docs/SEP_FCOV.adoc, mailbox, IRQ and PIC
  // groups). VCS only.
  //
  // GATE. Every bin samples only while `graded_owner` holds the code of an
  // owning test of its coverpoint (own_* below, codes 313 to 324). The quiet
  // window bins of the mailbox groups also need `quiet_win` (written only by
  // the fifo-model leaf). A point ignores a sample while rst_ni is low,
  // except the reset points of sep_mbox_reset_cg.
  //
  // EVENTS. Each detector below registers its event and the sampled value
  // (the *_q structs). The sample block at the end of the section samples
  // the registered events one clock later. A detector that sees two events
  // of one coverpoint in one clock keeps the lowest index: a missed hit,
  // never a false one.
  //
  // HOLD. A "hold window" is HoldClk clocks. A "real stall" is a VALID that
  // waits StallClk clocks for its READY. The specification states no
  // handler time and no stall length, so these are sampler constants.
  // =====================================================================
  wire own_mfifo = (graded_owner == FcovOwnSepMailboxFifoModelRandTest);
  wire own_merr = (graded_owner == FcovOwnSepMailboxAccessErrorInjectTest);
  wire own_mfilt = (graded_owner == FcovOwnSepMailboxFilterTypeMatrixTest);
  wire own_mdbg = (graded_owner == FcovOwnSepMailboxDebugBypassTest);
  wire own_mrst = (graded_owner == FcovOwnSepMailboxResetClearTest);
  wire own_preg = (graded_owner == FcovOwnSepPicRegRandTest);
  wire own_pext = (graded_owner == FcovOwnSepPicExternalAccessRefuseTest);
  wire own_pprio = (graded_owner == FcovOwnSepPicPriorityGateRandTest);
  wire own_pwalk = (graded_owner == FcovOwnSepPicPendingMapWalkRandTest);
  wire own_bfault = (graded_owner == FcovOwnSepCpuBridgeFaultMatrixRandTest);
  wire own_tmo = (graded_owner == FcovOwnSepCpuCtrlTimeoutInertRandTest);
  wire own_nmi = (graded_owner == FcovOwnSepNmiVectorBarkRandTest);

  localparam int unsigned HoldClk = 32;
  localparam int unsigned StallClk = 16;
  localparam int unsigned SettleClk = 16;
  localparam int unsigned AlertWin = 64;
  localparam int unsigned PairWin = 256;
  localparam int unsigned NativeWin = 256;
  localparam int unsigned NmiWin = 4096;
  // Sources 1 to 43 are the individually assigned PIC slots.
  localparam int unsigned NumSrc = 43;

  // The six excluded idle bits (docs/SEP_FCOV.adoc, Excluded idle bits):
  // VEC[12], VEC[14], VEC[15], VEC[36], VEC[37], VEC[38], which are PIC
  // sources 13, 15, 16, 37, 38 and 39.
  localparam logic [42:0] VecIdleMask = (43'd1 << 12) | (43'd1 << 14) | (43'd1 << 15) |
      (43'd1 << 36) | (43'd1 << 37) | (43'd1 << 38);
  localparam logic [255:0] GwIdleMask = (256'd1 << 13) | (256'd1 << 15) | (256'd1 << 16) |
      (256'd1 << 37) | (256'd1 << 38) | (256'd1 << 39);

  localparam logic [1:0] AxiSlverr = 2'b10;
  localparam logic [1:0] AxiDecerr = 2'b11;

  // ---------------------------------------------------------------------
  // Common previous-clock copies.
  // ---------------------------------------------------------------------
  logic [42:0]  vec_q;
  logic [7:0]   smc_q;
  logic [255:0] gw_q;
  logic [255:0] req_q;
  logic take_ext_q, take_nmi_q, bark_q, mie_q, cfg_q, sep_rst_n_q;
  logic quiet_q;
  always_ff @(posedge clk_i) begin
    vec_q       <= vec_i;
    smc_q       <= smc_irq_i;
    gw_q        <= pic_req_gw_i;
    req_q       <= pic_req_i;
    take_ext_q  <= (tlu_take_ext_i === 1'b1);
    take_nmi_q  <= (tlu_take_nmi_i === 1'b1);
    bark_q      <= (wdt_bark_irq_i === 1'b1);
    mie_q       <= (tlu_mstatus_mie_i === 1'b1);
    cfg_q       <= (pic_cfg_i === 1'b1);
    sep_rst_n_q <= (sep_reset_n_i === 1'b1);
    quiet_q     <= quiet_win;
  end
  wire [42:0] vec_rise = vec_i & ~vec_q;
  wire [42:0] vec_fall = vec_q & ~vec_i;
  wire        take_r = !in_reset && (tlu_take_ext_i === 1'b1) && !take_ext_q;
  wire        nmi_r = !in_reset && (tlu_take_nmi_i === 1'b1) && !take_nmi_q;
  wire        bark_r = !in_reset && (wdt_bark_irq_i === 1'b1) && !bark_q;
  wire        mie = (tlu_mstatus_mie_i === 1'b1);
  wire        cfg = (pic_cfg_i === 1'b1);
  wire        sep_rst_fall = sep_rst_n_q && (sep_reset_n_i === 1'b0);
  wire        sep_rst_rise = !sep_rst_n_q && (sep_reset_n_i === 1'b1);

  // ---------------------------------------------------------------------
  // PIC register access (PICRD probe for reads, picm_*_ff for writes). A
  // register write lands on the clock after pic_wren_i.
  // ---------------------------------------------------------------------
  wire        pk_rv = !in_reset && (pic_rd_i[47] === 1'b1);
  wire [14:0] pk_ra = pic_rd_i[46:32];
  wire [31:0] pk_rd = pic_rd_i[31:0];
  wire        pk_wv = !in_reset && (pic_wren_i === 1'b1);
  logic       pk_wv_q;
  logic [14:0] pk_wa_q;
  logic [31:0] pk_wd_q;
  always_ff @(posedge clk_i) begin
    pk_wv_q <= pk_wv;
    pk_wa_q <= pic_waddr_i;
    pk_wd_q <= pic_wdata_i;
  end

  // Position in the PIC aperture: 0 decoded register; 1 hole 0x0400-0x0FFC;
  // 2 hole 0x1020-0x1FFC; 3 hole 0x2400-0x2FFC; 4 hole 0x3004-0x3FFC; 5 hole
  // 0x4400-0x4FFC; 6 past extent 0x5400-0x7FFC (el2_pic.adoc, memory_map.adoc).
  function automatic logic [2:0] pic_pos(input logic [14:0] a);
    if (a < 15'h0400) return 3'd0;
    if (a < 15'h1000) return 3'd1;
    if (a < 15'h1020) return 3'd0;
    if (a < 15'h2000) return 3'd2;
    if (a < 15'h2400) return 3'd0;
    if (a < 15'h3000) return 3'd3;
    if (a == 15'h3000) return 3'd0;
    if (a < 15'h4000) return 3'd4;
    if (a < 15'h4400) return 3'd0;
    if (a < 15'h5000) return 3'd5;
    if (a < 15'h5400) return 3'd0;
    return 3'd6;
  endfunction
  // Register group of a decoded address: 0 meipl, 1 meip, 2 meie, 3 mpiccfg,
  // 4 meigwctrl, 5 meigwclr (picm address bits [14:12]).
  localparam logic [2:0] PgMeipl = 3'd0;
  localparam logic [2:0] PgMeip = 3'd1;
  localparam logic [2:0] PgMeie = 3'd2;
  localparam logic [2:0] PgCfg = 3'd3;
  localparam logic [2:0] PgGwctrl = 3'd4;
  localparam logic [2:0] PgGwclr = 3'd5;
  // Array index of cp_entry_pos x cp_array: meipl 0, meie 1, meigwctrl 2,
  // meigwclr 3; 4 for a group with no entry array.
  function automatic logic [2:0] pic_arr(input logic [2:0] g);
    case (g)
      PgMeipl: return 3'd0;
      PgMeie: return 3'd1;
      PgGwctrl: return 3'd2;
      PgGwclr: return 3'd3;
      default: return 3'd4;
    endcase
  endfunction
  // Entry class: e0, e1, e2_42, e43, e44, e45_127, e128, e129_254, e255.
  function automatic logic [3:0] pic_ecls(input logic [7:0] e);
    if (e == 8'd0) return 4'd0;
    if (e == 8'd1) return 4'd1;
    if (e <= 8'd42) return 4'd2;
    if (e == 8'd43) return 4'd3;
    if (e == 8'd44) return 4'd4;
    if (e <= 8'd127) return 4'd5;
    if (e == 8'd128) return 4'd6;
    if (e <= 8'd254) return 4'd7;
    return 4'd8;
  endfunction
  // A priority value at the never level for the current order: 0 in standard
  // order and 15 in reverse order (el2_pic.adoc, meipl, mpiccfg).
  function automatic logic pic_never(input logic [3:0] p, input logic c);
    return c ? (p == 4'hF) : (p == 4'h0);
  endfunction
  function automatic logic [3:0] pic_eff(input logic [3:0] p, input logic c);
    return c ? ~p : p;
  endfunction

  wire [2:0] pk_rpos = pic_pos(pk_ra);
  wire [2:0] pk_rgrp = pk_ra[14:12];
  wire [2:0] pk_rarr = pic_arr(pk_rgrp);
  wire [7:0] pk_rent = pk_ra[9:2];
  wire       pk_rdec = pk_rv && (pk_rpos == 3'd0);
  wire [2:0] pk_wpos = pic_pos(pic_waddr_i);
  wire [2:0] pk_wgrp = pic_waddr_i[14:12];
  wire [2:0] pk_warr = pic_arr(pk_wgrp);
  wire [7:0] pk_went = pic_waddr_i[9:2];
  wire       pk_wdec = pk_wv && (pk_wpos == 3'd0);
  // The write of the previous clock, now visible in the registers.
  wire [2:0] pk_lgrp = pk_wa_q[14:12];
  wire [7:0] pk_lent = pk_wa_q[9:2];
  wire       pk_ldec = pk_wv_q && (pic_pos(pk_wa_q) == 3'd0);

  // Candidates: pending, enabled and at a usable priority.
  logic [255:0] usable, cand;
  always_comb begin
    for (int n = 0; n < 256; n++) begin
      usable[n] = !pic_never(pic_prio_i[n], cfg);
      cand[n]   = (pic_req_gw_i[n] === 1'b1) && (pic_en_i[n] === 1'b1) && usable[n];
    end
  end
  logic [255:0] cand_q1, cand_q2;
  always_ff @(posedge clk_i) begin
    cand_q1 <= cand;
    cand_q2 <= cand_q1;
  end
  wire [255:0] gw_live = pic_req_gw_i & ~GwIdleMask;
  wire         live_any = |gw_live[NumSrc:1];

  // =====================================================================
  // sep_pic_reg_map_cg
  // =====================================================================
  typedef struct packed {
    logic [3:0] grp_dir;
    logic grp_dir_v;   // {group, dir}: dir 1 write
    logic [5:0] ent_arr;
    logic ent_arr_v;   // {array[1:0], entry class[3:0]}
    logic [3:0] ap_dir;
    logic ap_dir_v;    // {position, dir}
    logic [4:0] meip_bc;
    logic meip_bc_v;   // {word, bit class}
    logic       hole_nb;
    logic hole_nb_v;   // 0 read zero, 1 write kept
    logic [3:0] rst_rd;
    logic rst_rd_v;    // {X, group}
    logic [1:0] e0;
    logic e0_v;        // array of the discarding entry 0
    logic       gwclr0_v;
    logic [1:0] gwctrl;
    logic gwctrl_v;
    logic       priord;
    logic priord_v;
    logic [1:0] arm;
    logic arm_v;       // {enable, usable priority}
  } prm_t;

  covergroup sep_pic_reg_map_cg with function sample (prm_t s);
    option.per_instance = 1;
    option.name = "sep_pic_reg_map_cg";
    cp_group_x_dir: coverpoint s.grp_dir iff (s.grp_dir_v) {
      bins meipl_rd = {4'd0};
      bins meipl_wr = {4'd1};
      bins meip_rd = {4'd2};
      ignore_bins meip_wr = {4'd3};
      bins meie_rd = {4'd4};
      bins meie_wr = {4'd5};
      bins mpiccfg_rd = {4'd6};
      bins mpiccfg_wr = {4'd7};
      bins meigwctrl_rd = {4'd8};
      bins meigwctrl_wr = {4'd9};
      bins meigwclr_rd = {4'd10};
      bins meigwclr_wr = {4'd11};
    }
    cp_entry_pos_x_array: coverpoint s.ent_arr iff (s.ent_arr_v) {
      bins meipl[] = {[6'd0 : 6'd8]};
      bins meie[] = {[6'd16 : 6'd24]};
      bins meigwctrl[] = {[6'd32 : 6'd40]};
      bins meigwclr[] = {[6'd48 : 6'd56]};
    }
    // Position 0 decoded, 1-5 the holes, 6 past extent; dir 1 write.
    cp_aperture_x_dir: coverpoint s.ap_dir iff (s.ap_dir_v) {
      bins cells[] = {[4'd0 : 4'd13]};
    }
    // Bit class 0 bit 0, 1 bits 1-30, 2 bit 31.
    cp_meip_word_x_bit_class: coverpoint s.meip_bc iff (s.meip_bc_v) {
      bins w0_mid = {5'b000_01};
      bins w1_mid = {5'b001_01};
      ignore_bins w0_edge = {5'b000_00, 5'b000_10};
      ignore_bins w1_edge = {5'b001_00, 5'b001_10};
      ignore_bins w2_7 = {[5'b010_00 : 5'b111_11]};
    }
    cp_hole_live_neighbour: coverpoint s.hole_nb iff (s.hole_nb_v) {
      bins hole_read_zero_with_live_neighbour = {1'b0};
      bins hole_write_kept_with_live_neighbour = {1'b1};
    }
    cp_reset_read: coverpoint s.rst_rd iff (s.rst_rd_v) {
      bins meipl = {4'd0};
      bins meip = {4'd1};
      bins meie = {4'd2};
      bins mpiccfg = {4'd3};
      bins meigwctrl = {4'd4};
      bins meigwclr = {4'd5};
      illegal_bins x_read = {[4'd8 : 4'd15]};
    }
    cp_entry0_discard: coverpoint s.e0 iff (s.e0_v) {
      bins meipl = {2'd0}; bins meie = {2'd1}; bins meigwctrl = {2'd2}; bins meigwclr = {2'd3};
    }
    cp_gwclr_read0: coverpoint s.gwclr0_v iff (s.gwclr0_v) {bins read0 = {1'b1};}
    cp_gwctrl_val: coverpoint s.gwctrl iff (s.gwctrl_v) {bins val[] = {[2'd0 : 2'd3]};}
    cp_priord_val: coverpoint s.priord iff (s.priord_v) {bins val[] = {1'b0, 1'b1};}
    cp_arm_state: coverpoint s.arm iff (s.arm_v) {
      bins both_unset = {2'b00};
      bins enable_only = {2'b10};
      bins priority_only = {2'b01};
      bins both_set = {2'b11};
    }
  endgroup

  // Entry 0 of each array: a non-zero write seen (bit), an all-ones write
  // seen, the entry-1 value at that write, and an entry-0 read of 0 after
  // the all-ones write.
  logic [3:0] e0w_q, e0ones_q, e0zero_q;
  logic [3:0][3:0] e1_q;
  logic gwclr_w_q, pk_wrote_q;
  logic hk_arm_q, hk_en_q;
  logic [7:0]      hk_ent_q;
  logic [3:0]      hk_prio_q;
  function automatic logic [3:0] pic_e1(input logic [2:0] arr, input logic [3:0] prio1,
                                        input logic en1, input logic [1:0] gw1);
    case (arr)
      3'd0: return prio1;
      3'd1: return {3'b000, en1};
      3'd2: return {2'b00, gw1};
      default: return 4'd0;
    endcase
  endfunction
  wire [3:0] pk_e1_now = pic_e1(pk_rarr, pic_prio_i[1], pic_en_i[1], pic_gw_cfg_i[1]);
  wire [3:0] pk_e1_wr = pic_e1(pk_warr, pic_prio_i[1], pic_en_i[1], pic_gw_cfg_i[1]);
  // meip read mask: the excluded idle bits of the word read.
  wire [31:0] pk_meip_mask = ~GwIdleMask[{pk_ra[4:2], 5'd0}+:32];

  prm_t prm_r_q, prm_w_q;
  always_ff @(posedge clk_i) begin
    prm_r_q <= '0;
    prm_w_q <= '0;
    if (in_reset || (cpu_reset_n_i === 1'b0)) begin
      e0w_q      <= '0;
      e0ones_q   <= '0;
      e0zero_q   <= '0;
      gwclr_w_q  <= 1'b0;
      pk_wrote_q <= 1'b0;
      hk_arm_q   <= 1'b0;
    end else begin
      // ---- read side ----
      if (pk_rv) begin
        prm_r_q.ap_dir   <= {pk_rpos, 1'b0};
        prm_r_q.ap_dir_v <= own_preg;
      end
      if (pk_rdec) begin
        prm_r_q.grp_dir   <= {pk_rgrp, 1'b0};
        prm_r_q.grp_dir_v <= own_preg;
        if (pk_rarr != 3'd4) begin
          prm_r_q.ent_arr   <= {pk_rarr[1:0], pic_ecls(pk_rent)};
          prm_r_q.ent_arr_v <= own_preg;
        end
        // The first read of each group before any PIC write after reset.
        if (!pk_wrote_q && ($isunknown(
                pk_rd
            ) || ((pk_rd & ((pk_rgrp == PgMeip) ? pk_meip_mask : 32'hFFFF_FFFF)) == 32'h0))) begin
          prm_r_q.rst_rd   <= {$isunknown(pk_rd), pk_rgrp};
          prm_r_q.rst_rd_v <= own_preg;
        end
        // Entry 0 reads 0 after a non-zero write; entry 1 kept its value.
        if ((pk_rarr != 3'd4) && (pk_rent == 8'd0) && (pk_rd == 32'h0)) begin
          if (e0w_q[pk_rarr[1:0]] && (pk_e1_now == e1_q[pk_rarr[1:0]])) begin
            prm_r_q.e0   <= pk_rarr[1:0];
            prm_r_q.e0_v <= own_preg;
          end
          if (e0ones_q[pk_rarr[1:0]]) e0zero_q[pk_rarr[1:0]] <= 1'b1;
        end
        if ((pk_rgrp == PgGwclr) && gwclr_w_q && (pk_rd == 32'h0)) prm_r_q.gwclr0_v <= own_preg;
        // meip read with exactly one pending bit in the masked vector.
        if ((pk_rgrp == PgMeip) && (pk_ra[11:5] == 7'd0) && ($countones(
                gw_live
            ) == 1) && ((pk_rd & pk_meip_mask) != 32'h0)) begin
          prm_r_q.meip_bc <= {pk_ra[4:2], (pk_rd[0] ? 2'd0 : (pk_rd[31] ? 2'd2 : 2'd1))};
          prm_r_q.meip_bc_v <= own_pwalk;
        end
      end
      // Hole read of 0 while entry K (address bits [9:2]) is enabled.
      if (pk_rv && (pk_rpos != 3'd0) && (pk_rpos != 3'd6) && (pk_rd == 32'h0) &&
          (pic_en_i[pk_rent] === 1'b1)) begin
        prm_r_q.hole_nb   <= 1'b0;
        prm_r_q.hole_nb_v <= own_preg;
      end
      // ---- write side ----
      if (pk_wv) begin
        pk_wrote_q       <= 1'b1;
        prm_w_q.ap_dir   <= {pk_wpos, 1'b1};
        prm_w_q.ap_dir_v <= own_preg;
      end
      if (pk_wdec) begin
        prm_w_q.grp_dir   <= {pk_wgrp, 1'b1};
        prm_w_q.grp_dir_v <= own_preg;
        if (pk_warr != 3'd4) begin
          prm_w_q.ent_arr   <= {pk_warr[1:0], pic_ecls(pk_went)};
          prm_w_q.ent_arr_v <= own_preg;
          if ((pk_went == 8'd0) && (pic_wdata_i != 32'h0)) begin
            e0w_q[pk_warr[1:0]] <= 1'b1;
            e1_q[pk_warr[1:0]]  <= pk_e1_wr;
          end
          if ((pk_went == 8'd0) && (pic_wdata_i == 32'hFFFF_FFFF)) e0ones_q[pk_warr[1:0]] <= 1'b1;
        end
        if ((pk_wgrp == PgGwclr) && (pic_wdata_i != 32'h0)) gwclr_w_q <= 1'b1;
      end
      // Hole write of all ones while entry K is enabled: check K next clock.
      hk_arm_q <= pk_wv && (pk_wpos != 3'd0) && (pk_wpos != 3'd6) &&
          (pic_wdata_i == 32'hFFFF_FFFF) && (pic_en_i[pk_went] === 1'b1);
      hk_ent_q  <= pk_went;
      hk_en_q   <= pic_en_i[pk_went];
      hk_prio_q <= pic_prio_i[pk_went];
      if (hk_arm_q && (pic_en_i[hk_ent_q] == hk_en_q) && (pic_prio_i[hk_ent_q] == hk_prio_q)) begin
        prm_w_q.hole_nb   <= 1'b1;
        prm_w_q.hole_nb_v <= own_preg;
      end
      // Register values one clock after the write.
      if (pk_ldec && (pk_lgrp == PgGwctrl) && (pk_lent != 8'd0)) begin
        prm_w_q.gwctrl   <= pic_gw_cfg_i[pk_lent];
        prm_w_q.gwctrl_v <= own_preg;
      end
      if (pk_ldec && (pk_lgrp == PgCfg)) begin
        prm_w_q.priord   <= cfg;
        prm_w_q.priord_v <= own_preg;
      end
      if (pk_ldec && ((pk_lgrp == PgMeie) || (pk_lgrp == PgMeipl)) && (pk_lent != 8'd0)) begin
        prm_w_q.arm   <= {pic_en_i[pk_lent], usable[pk_lent]};
        prm_w_q.arm_v <= own_preg;
      end
    end
  end

  // =====================================================================
  // sep_pic_source_map_cg
  // =====================================================================
  typedef struct packed {
    logic [5:0] src;
    logic src_v;    // source number of the asserting bit
    logic [5:0] excl;
    logic excl_v;   // source number, no other bit rose
    logic [1:0] mv;
    logic mv_v;     // 0 word 0 live, 1 word 1 live, 2 words 2-7 zero
    logic       pulse;
    logic pulse_v; // 0 source 12, 1 source 33
    logic       spi;
    logic spi_v;    // 0 raised, 1 cleared
    logic       fe;
    logic fe_v;     // 0 HMAC (19), 1 KMAC (22)
    logic       gwm;
    logic gwm_v;    // 0 source 12, 1 source 33
    logic [1:0] ext;
    logic ext_v;    // 0 one bit, 1 released, 2 two bits
  } psm_t;

  covergroup sep_pic_source_map_cg with function sample (psm_t s);
    option.per_instance = 1;
    option.name = "sep_pic_source_map_cg";
    cp_src_assert: coverpoint s.src iff (s.src_v) {
      bins src[] = {1, 2, 3, 4, 5, 6, 7, 8, 12, 14, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
                    29, 30, 33};
    }
    x_src_exclusive: coverpoint s.excl iff (s.excl_v) {
      bins own_only[] = {1, 2, 3, 4, 5, 6, 7, 8, 12, 14, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
                         28, 29, 30, 33};
    }
    cp_meip_vs_vec: coverpoint s.mv iff (s.mv_v) {
      bins word0_live = {2'd0}; bins word1_live = {2'd1}; bins words2_7_zero = {2'd2};
    }
    cp_pulse_catch: coverpoint s.pulse iff (s.pulse_v) {bins src12 = {1'b0}; bins src33 = {1'b1};}
    cp_spi_cause: coverpoint s.spi iff (s.spi_v) {bins raised = {1'b0}; bins cleared = {1'b1};}
    cp_fifo_empty_hold: coverpoint s.fe iff (s.fe_v) {bins hmac = {1'b0}; bins kmac = {1'b1};}
    cp_gw_mode_used: coverpoint s.gwm iff (s.gwm_v) {bins src12 = {1'b0}; bins src33 = {1'b1};}
    cp_ext_input: coverpoint s.ext iff (s.ext_v) {
      bins one_bit = {2'd0}; bins released = {2'd1}; bins two_bits = {2'd2};
    }
  endgroup

  // Vector bits of the 24 sources the walk asserts (bit = source - 1).
  localparam int unsigned PulseWin = 4;
  localparam logic [42:0] SrcWalkMask = 43'h0FF | (43'd1 << 11) | (43'd1 << 13) |
      (43'h1FFF << 17) | (43'd1 << 32);
  logic hm_arm_q, km_arm_q, ext_seen_q;
  // Gateway output of sources 19 and 22 at the LSU AW handshake of the
  // INTR_ENABLE write (before it lands).
  logic hm_aw_gw_q, km_aw_gw_q;
  // Clocks left to see the gateway output of source 12 / 33 rise after the
  // input pulse ends (two-flop synchronizer in front of the gateway).
  logic [2:0] pc12_cnt_q, pc33_cnt_q;
  psm_t psm_q;
  always_ff @(posedge clk_i) begin
    psm_q <= '0;
    if (in_reset) begin
      hm_arm_q   <= 1'b0;
      km_arm_q   <= 1'b0;
      ext_seen_q <= 1'b0;
      hm_aw_gw_q <= 1'b0;
      km_aw_gw_q <= 1'b0;
      pc12_cnt_q <= '0;
      pc33_cnt_q <= '0;
    end else begin
      // Rising edge of an asserted source with its enable at 1.
      for (int k = 42; k >= 0; k--) begin
        if (SrcWalkMask[k] && vec_rise[k] && (pic_en_i[k+1] === 1'b1)) begin
          psm_q.src   <= 6'(k + 1);
          psm_q.src_v <= own_pwalk;
          if ((vec_rise & ~VecIdleMask) == (43'd1 << k)) begin
            psm_q.excl   <= 6'(k + 1);
            psm_q.excl_v <= own_pwalk;
          end
        end
      end
      if (pk_rdec && (pk_rgrp == PgMeip) && (pk_ra[11:5] == 7'd0) &&
          (pk_rd == pic_req_gw_i[{pk_ra[4:2], 5'd0}+:32])) begin
        if ((pk_ra[4:2] == 3'd0) && ((pk_rd & pk_meip_mask) != 32'h0)) begin
          psm_q.mv   <= 2'd0;
          psm_q.mv_v <= own_pwalk;
        end else if ((pk_ra[4:2] == 3'd1) && ((pk_rd & pk_meip_mask) != 32'h0)) begin
          psm_q.mv   <= 2'd1;
          psm_q.mv_v <= own_pwalk;
        end else if ((pk_ra[4:2] >= 3'd2) && (pk_rd == 32'h0) && live_any) begin
          psm_q.mv   <= 2'd2;
          psm_q.mv_v <= own_pwalk;
        end
      end
      // The pulse ended and the edge, active-high gateway holds it: the
      // gateway output is 1 with the input back at 0 within PulseWin clocks
      // after the fall.
      if (vec_fall[11] && (pic_gw_cfg_i[12] == 2'b10)) pc12_cnt_q <= 3'(PulseWin);
      else if (pc12_cnt_q != 3'd0) begin
        if (pic_req_gw_i[12] && !vec_i[11]) begin
          pc12_cnt_q    <= 3'd0;
          psm_q.pulse   <= 1'b0;
          psm_q.pulse_v <= own_pwalk;
        end else pc12_cnt_q <= pc12_cnt_q - 3'd1;
      end
      if (vec_fall[32] && (pic_gw_cfg_i[33] == 2'b10)) pc33_cnt_q <= 3'(PulseWin);
      else if (pc33_cnt_q != 3'd0) begin
        if (pic_req_gw_i[33] && !vec_i[32]) begin
          pc33_cnt_q    <= 3'd0;
          psm_q.pulse   <= 1'b1;
          psm_q.pulse_v <= own_pwalk;
        end else pc33_cnt_q <= pc33_cnt_q - 3'd1;
      end
      if (vec_rise[13] && (vec_i[13] == spi_irq_field_i)) begin
        psm_q.spi   <= 1'b0;
        psm_q.spi_v <= own_pwalk;
      end else if (vec_fall[13] && (vec_i[13] == spi_irq_field_i)) begin
        psm_q.spi   <= 1'b1;
        psm_q.spi_v <= own_pwalk;
      end
      // INTR_ENABLE.fifo_empty cleared while the pending bit is 1 (taken at
      // the AW handshake of the write, before it lands), then the pending bit
      // is 0: at the B handshake or on a later clock.
      if (aw_hs && (lsu_aw_addr_i == HMAC_INTR_ENABLE_REG_ADDR))
        hm_aw_gw_q <= (pic_req_gw_i[19] === 1'b1);
      if (aw_hs && (lsu_aw_addr_i == KMAC_INTR_ENABLE_REG_ADDR))
        km_aw_gw_q <= (pic_req_gw_i[22] === 1'b1);
      if (wr_ev && (aw_addr_q == HMAC_INTR_ENABLE_REG_ADDR))
        hm_arm_q <= ((wr_data & HMAC_INTR_ENABLE_FIFO_EMPTY_MASK) == 32'h0) && hm_aw_gw_q;
      else if (hm_arm_q && !pic_req_gw_i[19]) begin
        hm_arm_q    <= 1'b0;
        psm_q.fe   <= 1'b0;
        psm_q.fe_v <= own_pwalk;
      end
      if (wr_ev && (aw_addr_q == KMAC_INTR_ENABLE_REG_ADDR))
        km_arm_q <= ((wr_data & KMAC_INTR_ENABLE_FIFO_EMPTY_MASK) == 32'h0) && km_aw_gw_q;
      else if (km_arm_q && !pic_req_gw_i[22]) begin
        km_arm_q    <= 1'b0;
        psm_q.fe   <= 1'b1;
        psm_q.fe_v <= own_pwalk;
      end
      if ((pic_req_gw_i[12] && !gw_q[12]) && (pic_gw_cfg_i[12] == 2'b10)) begin
        psm_q.gwm   <= 1'b0;
        psm_q.gwm_v <= own_pwalk;
      end else if ((pic_req_gw_i[33] && !gw_q[33]) && (pic_gw_cfg_i[33] == 2'b10)) begin
        psm_q.gwm   <= 1'b1;
        psm_q.gwm_v <= own_pwalk;
      end
      // Boundary input: pending count above source 43 at an meip read of a
      // word 1 to 7. The map of boundary bits to sources is not stated, so
      // only the count is binned.
      if (!own_pwalk) ext_seen_q <= 1'b0;
      else if (ext_irq_i != '0) ext_seen_q <= 1'b1;
      if (pk_rdec && (pk_rgrp == PgMeip) && (pk_ra[11:5] == 7'd0) && (pk_ra[4:2] != 3'd0)) begin
        if (($countones(ext_irq_i) == 1) && ($countones(pic_req_gw_i[255:44]) == 1)) begin
          psm_q.ext   <= 2'd0;
          psm_q.ext_v <= own_pwalk;
        end else if (($countones(ext_irq_i) == 2) && ($countones(pic_req_gw_i[255:44]) == 2)) begin
          psm_q.ext   <= 2'd2;
          psm_q.ext_v <= own_pwalk;
        end else if ((ext_irq_i == '0) && (pic_req_gw_i[255:44] == '0) && ext_seen_q) begin
          psm_q.ext   <= 2'd1;
          psm_q.ext_v <= own_pwalk;
        end
      end
    end
  end

  // =====================================================================
  // Gate tracker of sources 1 to 43 (sep_pic_enable_priority_cg,
  // sep_pic_delivery_cg). Gate class of a pending source: 1 enable 0, 2 never
  // priority, 3 mstatus.MIE 0, 0 open or not pending.
  // =====================================================================
  logic [NumSrc:1][1:0] gcls_q, rel_q;
  logic [NumSrc:1][5:0] hcnt_q;
  logic [NumSrc:1]      nh_q;
  function automatic logic [1:0] gate_cls(input logic pend, input logic en, input logic use_ok,
                                          input logic m);
    if (!pend) return 2'd0;
    if (!en) return 2'd1;
    if (!use_ok) return 2'd2;
    if (!m) return 2'd3;
    return 2'd0;
  endfunction

  // =====================================================================
  // sep_pic_enable_priority_cg
  // =====================================================================
  typedef struct packed {
    logic       priord;
    logic priord_v;
    logic [2:0] lco;
    logic lco_v;    // {order, class}: 0 never 1 lowest 2 interior 3 highest
    logic [3:0] lvl;
    logic lvl_v;
    logic [2:0] gp;
    logic gp_v;     // {phase, gate}: gate 0 enable, 1 never, 2 MIE
    logic [2:0] win;
    logic win_v;    // {first is highest, set size - 2}
    logic       stay_v;
    logic [1:0] nt;
    logic nt_v;     // {order, kind}: kind 0 never held, 1 eff 1 delivered
    logic       flip;
    logic flip_v;   // 0 priord 0 to 1, 1 priord 1 to 0
  } pep_t;

  covergroup sep_pic_enable_priority_cg with function sample (pep_t s);
    option.per_instance = 1;
    option.name = "sep_pic_enable_priority_cg";
    cp_priord: coverpoint s.priord iff (s.priord_v) {bins standard = {1'b0}; bins reverse = {1'b1};}
    x_level_class_order: coverpoint s.lco iff (s.lco_v) {
      bins std_never = {3'b0_00};
      bins std_lowest_usable = {3'b0_01};
      bins std_interior = {3'b0_10};
      bins std_highest_usable = {3'b0_11};
      bins rev_never = {3'b1_00};
      bins rev_lowest_usable = {3'b1_01};
      bins rev_interior = {3'b1_10};
      bins rev_highest_usable = {3'b1_11};
    }
    cp_level_val: coverpoint s.lvl iff (s.lvl_v) {bins val[] = {[4'd0 : 4'd15]};}
    x_gate_phase: coverpoint s.gp iff (s.gp_v) {
      bins enable0_held = {3'b0_00};
      bins never_held = {3'b0_01};
      bins mie0_held = {3'b0_10};
      bins enable0_released = {3'b1_00};
      bins never_released = {3'b1_01};
      bins mie0_released = {3'b1_10};
    }
    cp_winner: coverpoint s.win iff (s.win_v) {
      bins n2 = {3'b1_00};
      bins n3 = {3'b1_01};
      bins n4 = {3'b1_10};
      bins n5 = {3'b1_11};
      illegal_bins not_highest = {[3'b0_00 : 3'b0_11]};
    }
    cp_stay_pending: coverpoint s.stay_v iff (s.stay_v) {bins other_pending = {1'b1};}
    cp_never_twin: coverpoint s.nt iff (s.nt_v) {
      bins std_never_held = {2'b0_0};
      bins std_eff1_delivered = {2'b0_1};
      bins rev_never_held = {2'b1_0};
      bins rev_eff1_delivered = {2'b1_1};
    }
    cp_order_flip: coverpoint s.flip iff (s.flip_v) {bins up = {1'b0}; bins down = {1'b1};}
  endgroup

  // Highest effective priority among the candidates of a stable set.
  logic [3:0] win_eff;
  logic [7:0] win_id;
  logic [7:0] win_ties;
  always_comb begin
    win_eff  = 4'd0;
    win_id   = 8'd0;
    win_ties = 8'd0;
    for (int n = 1; n < 256; n++) begin
      if (cand_q2[n]) begin
        if ((win_ties == 8'd0) || (pic_eff(pic_prio_i[n], cfg) > win_eff)) begin
          win_eff  = pic_eff(pic_prio_i[n], cfg);
          win_id   = 8'(n);
          win_ties = 8'd1;
        end else if (pic_eff(pic_prio_i[n], cfg) == win_eff) begin
          win_ties = win_ties + 8'd1;
        end
      end
    end
  end
  wire [8:0] cand_n = 9'($countones(cand_q2));

  pep_t pep_q;
  always @(posedge clk_i) begin
    pep_q <= '0;
    if (in_reset) begin
      gcls_q <= '0;
      rel_q  <= '0;
      hcnt_q <= '0;
      nh_q   <= '0;
    end else begin
      if (take_r) begin
        pep_q.priord   <= cfg;
        pep_q.priord_v <= own_pprio;
        if ((cand_n >= 9'd2) && (cand_n <= 9'd5) && (cand_q2 == cand_q1) && (win_ties == 8'd1))
            begin
          pep_q.win   <= {(pic_claim_i == win_id), 2'(cand_n - 9'd2)};
          pep_q.win_v <= own_pprio;
        end
        if ((cand & ~(256'd1 << pic_claim_i)) != '0) pep_q.stay_v <= own_pprio;
        if (pic_eff(pic_prio_i[pic_claim_i], cfg) == 4'd1) begin
          if ((pic_claim_i >= 8'd1) && (pic_claim_i <= 8'(NumSrc)) && nh_q[pic_claim_i]) begin
            pep_q.nt   <= {cfg, 1'b1};
            pep_q.nt_v <= own_pprio;
          end
        end
      end
      if (pk_ldec && (pk_lgrp == PgMeipl) && (pk_lent != 8'd0)) begin
        pep_q.lvl   <= pic_prio_i[pk_lent];
        pep_q.lvl_v <= own_pprio;
        if (pic_never(pic_prio_i[pk_lent], cfg)) pep_q.lco <= {cfg, 2'd0};
        else if (pic_eff(pic_prio_i[pk_lent], cfg) == 4'd1) pep_q.lco <= {cfg, 2'd1};
        else if (pic_eff(pic_prio_i[pk_lent], cfg) == 4'd15) pep_q.lco <= {cfg, 2'd3};
        else pep_q.lco <= {cfg, 2'd2};
        pep_q.lco_v <= own_pprio;
      end
      if ((cfg != cfg_q) && ((pic_req_gw_i & pic_en_i) == '0)) begin
        pep_q.flip   <= cfg_q;
        pep_q.flip_v <= own_pprio;
      end
      // Gate tracker: held for HoldClk with no delivery of the source, then
      // released and delivered.
      for (int s = NumSrc; s >= 1; s--) begin
        logic [1:0] g;
        g = gate_cls(pic_req_gw_i[s] === 1'b1, pic_en_i[s] === 1'b1, usable[s], mie);
        gcls_q[s] <= g;
        if ((g != 2'd0) && (g == gcls_q[s]) && !(take_r && (pic_claim_i == 8'(s)))) begin
          if (hcnt_q[s] != 6'(HoldClk)) hcnt_q[s] <= hcnt_q[s] + 6'd1;
          if (hcnt_q[s] == 6'(HoldClk - 1)) begin
            pep_q.gp   <= {1'b0, g - 2'd1};
            pep_q.gp_v <= own_pprio;
            if ((g == 2'd2) && mie) begin
              nh_q[s]    <= 1'b1;
              pep_q.nt   <= {cfg, 1'b0};
              pep_q.nt_v <= own_pprio;
            end
          end
        end else begin
          hcnt_q[s] <= (g != 2'd0) ? 6'd1 : 6'd0;
        end
        if ((gcls_q[s] != 2'd0) && (g == 2'd0) && (pic_req_gw_i[s] === 1'b1) &&
            (hcnt_q[s] == 6'(HoldClk)))
          rel_q[s] <= gcls_q[s];
        else if (pic_req_gw_i[s] !== 1'b1) rel_q[s] <= 2'd0;
        if (take_r && (pic_claim_i == 8'(s)) && (rel_q[s] != 2'd0)) begin
          rel_q[s]   <= 2'd0;
          pep_q.gp   <= {1'b1, rel_q[s] - 2'd1};
          pep_q.gp_v <= own_pprio;
        end
      end
    end
  end

  // =====================================================================
  // sep_pic_gateway_cg
  // =====================================================================
  typedef struct packed {
    logic [1:0] tp;
    logic tp_v;    // gateway cell {type, polarity}
    logic [2:0] sc;
    logic sc_v;    // {class (0 event, 1 mailbox), cell}
    logic [2:0] co;
    logic co_v;    // cell outcome
    logic [1:0] cv;
    logic cv_v;    // clear value class
    logic       cs;
    logic cs_v;    // 0 pending drops, 1 idle stays 0
    logic       lh;
    logic lh_v;    // 0 held, 1 drops after clear
  } pgw_t;

  covergroup sep_pic_gateway_cg with function sample (pgw_t s);
    option.per_instance = 1;
    option.name = "sep_pic_gateway_cg";
    cp_type_pol: coverpoint s.tp iff (s.tp_v) {
      bins level_high = {2'b00};
      bins level_low = {2'b01};
      bins edge_high = {2'b10};
      ignore_bins edge_low = {2'b11};
    }
    x_srcclass_cell: coverpoint s.sc iff (s.sc_v) {
      bins event_level_high = {3'b0_00};
      bins event_level_low = {3'b0_01};
      bins event_edge_high = {3'b0_10};
      bins mailbox_level_high = {3'b1_00};
      bins mailbox_level_low = {3'b1_01};
      bins mailbox_edge_high = {3'b1_10};
      ignore_bins edge_low = {3'b0_11, 3'b1_11};
    }
    cp_cell_outcome: coverpoint s.co iff (s.co_v) {
      bins lh_assert_1 = {3'd0};
      bins lh_deassert_0 = {3'd1};
      bins ll_idle_1 = {3'd2};
      bins ll_assert_0 = {3'd3};
      bins ll_deassert_1 = {3'd4};
      bins eh_assert_1 = {3'd5};
      bins eh_deassert_held_1 = {3'd6};
      bins eh_clear_0 = {3'd7};
    }
    cp_clr_value: coverpoint s.cv iff (s.cv_v) {
      bins zero = {2'd0}; bins one = {2'd1}; bins msb = {2'd2}; bins other = {2'd3};
    }
    cp_clr_state: coverpoint s.cs iff (s.cs_v) {
      bins pending_drops = {1'b0}; bins idle_stays_0 = {1'b1};
    }
    cp_level_hold: coverpoint s.lh iff (s.lh_v) {bins held = {1'b0}; bins drops = {1'b1};}
  endgroup

  function automatic logic [1:0] clr_cls(input logic [31:0] v);
    if (v == 32'h0) return 2'd0;
    if (v == 32'h1) return 2'd1;
    if (v == 32'h8000_0000) return 2'd2;
    return 2'd3;
  endfunction
  logic [NumSrc:1][1:0] ecnt_q, icnt_q, ccnt_q;
  logic [NumSrc:1] edir_q, cgw_q, creq_q;
  logic [NumSrc:1][1:0] ccv_q;
  logic [NumSrc:1][5:0] lcnt_q;
  pgw_t pgw_q;
  always_ff @(posedge clk_i) begin
    pgw_q <= '0;
    if (in_reset) begin
      ecnt_q <= '0;
      icnt_q <= '0;
      ccnt_q <= '0;
      lcnt_q <= '0;
    end else begin
      if (pk_ldec && (pk_lgrp == PgGwctrl) && (pk_lent != 8'd0)) begin
        pgw_q.tp   <= pic_gw_cfg_i[pk_lent];
        pgw_q.tp_v <= own_pwalk;
        if ((pk_lent >= 8'd1) && (pk_lent <= 8'd8)) begin
          pgw_q.sc   <= {1'b1, pic_gw_cfg_i[pk_lent]};
          pgw_q.sc_v <= own_pwalk;
        end else if ((pk_lent == 8'd18) || (pk_lent == 8'd21) || (pk_lent == 8'd24) ||
                     (pk_lent == 8'd28)) begin
          pgw_q.sc   <= {1'b0, pic_gw_cfg_i[pk_lent]};
          pgw_q.sc_v <= own_pwalk;
        end
      end
      for (int s = NumSrc; s >= 1; s--) begin
        // Raw input edge, evaluated two clocks later through the gateway.
        if (pic_req_i[s] != req_q[s]) begin
          ecnt_q[s] <= 2'd3;
          edir_q[s] <= pic_req_i[s];
        end else if (ecnt_q[s] != 2'd0) begin
          ecnt_q[s] <= ecnt_q[s] - 2'd1;
        end
        if (ecnt_q[s] == 2'd1) begin
          case (pic_gw_cfg_i[s])
            2'b00: begin
              if (edir_q[s] && pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd0;
                pgw_q.co_v <= own_pwalk;
              end else if (!edir_q[s] && !pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd1;
                pgw_q.co_v <= own_pwalk;
              end
            end
            2'b01: begin
              if (edir_q[s] && !pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd3;
                pgw_q.co_v <= own_pwalk;
              end else if (!edir_q[s] && pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd4;
                pgw_q.co_v <= own_pwalk;
              end
            end
            2'b10: begin
              if (edir_q[s] && pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd5;
                pgw_q.co_v <= own_pwalk;
              end else if (!edir_q[s] && pic_req_gw_i[s]) begin
                pgw_q.co <= 3'd6;
                pgw_q.co_v <= own_pwalk;
              end
            end
            default: ;
          endcase
        end
        // Level-low cell written with the input idle (0): pending reads 1.
        if (pk_ldec && (pk_lgrp == PgGwctrl) && (pk_lent == 8'(s)) &&
            (pic_gw_cfg_i[s] == 2'b01) && !pic_req_i[s])
          icnt_q[s] <= 2'd3;
        else if (icnt_q[s] != 2'd0) icnt_q[s] <= icnt_q[s] - 2'd1;
        if ((icnt_q[s] == 2'd1) && (pic_gw_cfg_i[s] == 2'b01) && !pic_req_i[s] &&
            pic_req_gw_i[s]) begin
          pgw_q.co <= 3'd2;
          pgw_q.co_v <= own_pwalk;
        end
        // meigwclr write: the state before it and the value class.
        if (pic_gw_clr_i[s]) begin
          ccnt_q[s] <= 2'd3;
          cgw_q[s]  <= pic_req_gw_i[s];
          creq_q[s] <= pic_req_i[s];
          ccv_q[s]  <= clr_cls(pic_wdata_i);
        end else if (ccnt_q[s] != 2'd0) begin
          ccnt_q[s] <= ccnt_q[s] - 2'd1;
        end
        if ((ccnt_q[s] == 2'd1) && !pic_req_gw_i[s]) begin
          if (pic_gw_cfg_i[s][1] && cgw_q[s] && !creq_q[s]) begin
            pgw_q.co <= 3'd7;
            pgw_q.co_v <= own_pwalk;
            pgw_q.cs <= 1'b0;
            pgw_q.cs_v <= own_pwalk;
            pgw_q.cv <= ccv_q[s];
            pgw_q.cv_v <= own_pwalk;
          end else if (!cgw_q[s]) begin
            pgw_q.cs <= 1'b1;
            pgw_q.cs_v <= own_pwalk;
          end
        end
        // Level-high source held pending, then dropped.
        if ((pic_gw_cfg_i[s] == 2'b00) && pic_req_gw_i[s]) begin
          if (lcnt_q[s] != 6'(HoldClk)) lcnt_q[s] <= lcnt_q[s] + 6'd1;
          if (lcnt_q[s] == 6'(HoldClk - 1)) begin
            pgw_q.lh <= 1'b0;
            pgw_q.lh_v <= own_pwalk;
          end
        end else begin
          if ((pic_gw_cfg_i[s] == 2'b00) && gw_q[s] && (lcnt_q[s] == 6'(HoldClk))) begin
            pgw_q.lh <= 1'b1;
            pgw_q.lh_v <= own_pwalk;
          end
          lcnt_q[s] <= 6'd0;
        end
      end
    end
  end

  // =====================================================================
  // sep_pic_delivery_cg
  // =====================================================================
  typedef struct packed {
    logic [1:0] mp;
    logic mp_v;    // {MIE, candidate}
    logic       dr_v;
  } pdl_t;

  covergroup sep_pic_delivery_cg with function sample (pdl_t s);
    option.per_instance = 1;
    option.name = "sep_pic_delivery_cg";
    cp_mie_x_pending: coverpoint s.mp iff (s.mp_v) {
      bins mie0_idle = {2'b00};
      bins mie0_deferred = {2'b01};
      bins mie1_idle = {2'b10};
      bins mie1_taken = {2'b11};
    }
    cp_deferred_release: coverpoint s.dr_v iff (s.dr_v) {bins delivered = {1'b1};}
  endgroup

  logic [1:0] dl_st_q;
  logic       dl_arm_q;
  pdl_t pdl_q;
  wire  cand_any = |cand[255:1];
  always_ff @(posedge clk_i) begin
    pdl_q <= '0;
    if (in_reset) begin
      dl_st_q  <= 2'b11;
      dl_arm_q <= 1'b0;
    end else begin
      dl_st_q <= {mie, cand_any};
      if (({mie, cand_any} != dl_st_q) && ({mie, cand_any} != 2'b11)) begin
        pdl_q.mp   <= {mie, cand_any};
        pdl_q.mp_v <= own_pprio;
      end
      if (take_r && mie) begin
        pdl_q.mp   <= 2'b11;
        pdl_q.mp_v <= own_pprio;
      end
      if (mie && !mie_q && cand_any) dl_arm_q <= 1'b1;
      else if (!mie) dl_arm_q <= 1'b0;
      if (take_r && dl_arm_q) begin
        dl_arm_q    <= 1'b0;
        pdl_q.dr_v <= own_pprio;
      end
    end
  end

  // =====================================================================
  // sep_pic_no_delivery_cg
  // =====================================================================
  typedef struct packed {
    logic [4:0] s0;
    logic s0_v;    // 0 discard, 1 no delivery; 2-16 other configurations
    logic       ib;
    logic ib_v;    // 0 pending band, 1 meip band words
    logic       tied_v;
    logic [1:0] sl;
    logic sl_v;    // 0 OTP read, 1 LC read, 2 AES
    logic       qx;
    logic qx_v;    // 1 X on the vector
    logic       bark_v;
  } pnd_t;

  covergroup sep_pic_no_delivery_cg with function sample (pnd_t s);
    option.per_instance = 1;
    option.name = "sep_pic_no_delivery_cg";
    cp_src0: coverpoint s.s0 iff (s.s0_v) {
      bins discard = {5'd0};
      bins no_delivery = {5'd1};
      ignore_bins other_configurations = {[5'd2 : 5'd16]};
    }
    cp_idle_band: coverpoint s.ib iff (s.ib_v) {
      bins pending_band_zero = {1'b0}; bins meip_band_zero = {1'b1};
    }
    cp_tied_sources: coverpoint s.tied_v iff (s.tied_v) {bins src17_zero = {1'b1};}
    cp_slotless_block: coverpoint s.sl iff (s.sl_v) {
      bins otp_read = {2'd0}; bins lc_read = {2'd1}; ignore_bins aes_operation = {2'd2};
    }
    cp_quiet_vector_x: coverpoint s.qx iff (s.qx_v) {bins clean = {1'b0}; illegal_bins x = {1'b1};}
    cp_bark_vec_same: coverpoint s.bark_v iff (s.bark_v) {bins unchanged = {1'b1};}
  endgroup

  logic [5:0] s0cnt_q;
  logic s0done_q, band_lv_q;
  logic [7:1] band_ok_q;
  logic sl_on_q, sl_ok_q, sl_kind_q;
  logic [42:0]  sl_start_q;
  logic         bk_arm_q;
  logic [255:0] bk_snap_q;
  pnd_t pnd_q;
  wire          sl_blk_otp = (blk_of(lsu_ar_addr_i) == BLK_EFUSE_MAP) ||
      (blk_of(lsu_ar_addr_i) == BLK_EFUSE_MMR) || (blk_of(lsu_ar_addr_i) == BLK_EFUSE_CTRL);
  wire          sl_blk_lc = (blk_of(lsu_ar_addr_i) == BLK_LIFECYCLE);
  wire [42:0]   sl_mask = ~VecIdleMask & ~(43'd1 << 23) & (sl_kind_q ? 43'h7FF_FFFF_FFFF :
      ~(43'd1 << 33));
  always_ff @(posedge clk_i) begin
    pnd_q <= '0;
    if (in_reset) begin
      s0cnt_q   <= '0;
      s0done_q  <= 1'b0;
      band_ok_q <= '0;
      band_lv_q <= 1'b0;
      sl_on_q   <= 1'b0;
      bk_arm_q  <= 1'b0;
    end else begin
      // Source 0: the four entry-0 reads of 0 after all-ones writes.
      if ((e0zero_q == 4'hF) && !s0done_q) begin
        s0done_q    <= 1'b1;
        pnd_q.s0   <= 5'd0;
        pnd_q.s0_v <= own_preg;
      end
      // Source 0 never pends and never delivers over a hold window with
      // mie.MEIE and mstatus.MIE set.
      if ((tlu_mie_i[2] === 1'b1) && mie && (pic_req_gw_i[0] !== 1'b1) &&
          !(take_r && (pic_claim_i == 8'd0))) begin
        if (s0cnt_q != 6'(HoldClk)) s0cnt_q <= s0cnt_q + 6'd1;
        if (s0cnt_q == 6'(HoldClk - 1)) begin
          pnd_q.s0   <= 5'd1;
          pnd_q.s0_v <= own_preg;
        end
      end else begin
        s0cnt_q <= '0;
      end
      // Idle band: sources 44-255 not pending while a live source is.
      band_lv_q <= live_any && (pic_req_gw_i[255:44] == '0);
      if (live_any && (pic_req_gw_i[255:44] == '0) && !band_lv_q) begin
        pnd_q.ib   <= 1'b0;
        pnd_q.ib_v <= own_pwalk;
      end
      if (!live_any) band_ok_q <= '0;
      else if (pk_rdec && (pk_rgrp == PgMeip) && (pk_ra[11:5] == 7'd0) && (pk_ra[4:2] != 3'd0) &&
               ((pk_ra[4:2] == 3'd1) ? (pk_rd[31:12] == 20'h0) : (pk_rd == 32'h0)))
        band_ok_q[pk_ra[4:2]] <= 1'b1;
      if ((band_ok_q == 7'h7F) && live_any) begin
        band_ok_q   <= '0;
        pnd_q.ib   <= 1'b1;
        pnd_q.ib_v <= own_pwalk;
      end
      // Source 17 (VEC[16]) stays 0 while a live source rises.
      if (((vec_rise & ~VecIdleMask & ~(43'd1 << 16)) != '0) && !vec_i[16])
        pnd_q.tied_v <= own_pwalk;
      // Slotless blocks: every unmasked vector bit holds its start value on
      // every clock of an OTP or LC read, and the control source 24 is high.
      if (ar_hs && (ar_out_q == 4'd0) && (sl_blk_otp || sl_blk_lc)) begin
        sl_on_q    <= 1'b1;
        sl_ok_q    <= vec_i[23];
        sl_kind_q  <= sl_blk_lc;
        sl_start_q <= vec_i;
      end else if (sl_on_q) begin
        if ((((vec_i ^ sl_start_q) & sl_mask) != '0) || !vec_i[23]) sl_ok_q <= 1'b0;
        if (r_hs) begin
          sl_on_q <= 1'b0;
          if (sl_ok_q && (((vec_i ^ sl_start_q) & sl_mask) == '0) && vec_i[23]) begin
            pnd_q.sl   <= {1'b0, sl_kind_q};
            pnd_q.sl_v <= own_pwalk;
          end
        end
      end
      pnd_q.qx   <= $isunknown(vec_i);
      pnd_q.qx_v <= own_pwalk;
      // Bark: the pending band at NMI entry equals the band at the first
      // retired instruction after it, with a live bit set.
      if (nmi_r && live_any) begin
        bk_arm_q  <= 1'b1;
        bk_snap_q <= gw_live;
      end else if (bk_arm_q && (cpu_trace_valid_i === 1'b1)) begin
        bk_arm_q <= 1'b0;
        if (gw_live == bk_snap_q) pnd_q.bark_v <= own_nmi;
      end
    end
  end

  // =====================================================================
  // sep_pic_fabric_isolation_cg
  // =====================================================================
  typedef struct packed {
    logic       ini;
    logic ini_v;   // 0 external master, 1 CPU
    logic [2:0] tgt;
    logic tgt_v;
    logic [3:0] tdr;
    logic tdr_v;   // {target, dir}
    logic [1:0] rsp;
    logic rsp_v;
    logic       nl;
    logic nl_v;    // 0 external write, state unchanged; 1 state changed
    logic       wl_v;
    logic       cl_v;
  } pfi_t;

  covergroup sep_pic_fabric_isolation_cg with function sample (pfi_t s);
    option.per_instance = 1;
    option.name = "sep_pic_fabric_isolation_cg";
    cp_initiator: coverpoint s.ini iff (s.ini_v) {bins external = {1'b0}; bins cpu = {1'b1};}
    cp_target: coverpoint s.tgt iff (s.tgt_v) {
      bins mpiccfg = {3'd0};
      bins meipl = {3'd1};
      bins meie = {3'd2};
      bins meigwctrl = {3'd3};
      bins meigwclr = {3'd4};
      bins meip = {3'd5};
      bins hole = {3'd6};
      bins past_extent = {3'd7};
    }
    x_target_dir_regime: coverpoint s.tdr iff (s.tdr_v) {bins allow_window[] = {[4'd0 : 4'd15]};}
    cp_resp: coverpoint s.rsp iff (s.rsp_v) {
      bins decerr = {AxiDecerr}; illegal_bins okay_or_slverr = {AxiOkay, AxiSlverr};
    }
    cp_no_land: coverpoint s.nl iff (s.nl_v) {
      bins external_write_state_unchanged = {1'b0}; illegal_bins state_changed = {1'b1};
    }
    cp_window_live: coverpoint s.wl_v iff (s.wl_v) {bins mailbox_okay = {1'b1};}
    cp_cpu_live: coverpoint s.cl_v iff (s.cl_v) {bins nonzero_read = {1'b1};}
  endgroup

  localparam logic [31:0] PicBase = 32'(SEP_TOP_PIC_BASE_ADDR);
  localparam logic [31:0] MbxBase = AXIL_MAILBOX_REG_MAP_BASE_ADDR;
  localparam logic [31:0] MbxEnd = MbxBase + AXIL_MAILBOX_REG_MAP_SIZE;
  // Target of a PIC offset: 0 mpiccfg, 1 meipl, 2 meie, 3 meigwctrl,
  // 4 meigwclr, 5 meip, 6 hole, 7 past extent.
  function automatic logic [2:0] pic_tgt(input logic [14:0] o);
    logic [2:0] p;
    p = pic_pos(o);
    if (p == 3'd6) return 3'd7;
    if (p != 3'd0) return 3'd6;
    case (o[14:12])
      PgCfg: return 3'd0;
      PgMeipl: return 3'd1;
      PgMeie: return 3'd2;
      PgGwctrl: return 3'd3;
      PgGwclr: return 3'd4;
      default: return 3'd5;
    endcase
  endfunction
  // Filter verdict of the latest inbound request at the filter input:
  // allowed by a matching entry (the allow-window regime).
  logic fw_allow_q, fr_allow_q, fw_iso_q, fw_nwm_q;
  logic [3:0] fw_hit_q;
  always_ff @(posedge clk_i) begin
    if (filt_awvalid_i === 1'b1) begin
      fw_allow_q <= !filt_nwm_i && !filt_iso_w_i;
      fw_iso_q   <= filt_iso_w_i;
      fw_nwm_q   <= filt_nwm_i;
      fw_hit_q   <= filt_hit_i;
    end
    if (filt_arvalid_i === 1'b1) fr_allow_q <= !filt_nrm_i && !filt_iso_r_i;
  end
  // Local address of an inbound access: rebased inside the SEP window,
  // unchanged outside it. The mailbox and PIC decode uses it in both cases.
  wire [31:0] xm_loc = si_local[31:0];
  wire        xm_pic = (xm_loc >= PicBase) && (xm_loc < (PicBase + 32'h8000));
  wire        xm_allow = si_dir_w ? fw_allow_q : fr_allow_q;

  // PIC state: the arrays a write lands in.
  wire [1792:0] pic_state = {pic_prio_i, pic_en_i, pic_gw_cfg_i, pic_cfg_i};
  logic [1792:0] pic_state_q;
  logic pic_rst_q, chg_since_q;
  wire           pic_chg = !in_reset && pic_rst_q && (cpu_reset_n_i === 1'b1) &&
      (pic_state != pic_state_q) && !pk_wv_q;
  pfi_t pfi_q;
  always_ff @(posedge clk_i) begin
    pfi_q       <= '0;
    pic_state_q <= pic_state;
    pic_rst_q   <= (cpu_reset_n_i === 1'b1);
    if (si_aw_hs) chg_since_q <= 1'b0;
    else if (pic_chg) chg_since_q <= 1'b1;
    if (pic_chg) begin
      pfi_q.nl   <= 1'b1;
      pfi_q.nl_v <= own_pext;
    end
    if (si_done && xm_pic) begin
      pfi_q.ini   <= 1'b0;
      pfi_q.ini_v <= own_pext;
      pfi_q.tgt   <= pic_tgt(xm_loc[14:0]);
      pfi_q.tgt_v <= own_pext;
      pfi_q.rsp   <= si_resp;
      pfi_q.rsp_v <= own_pext;
      if (xm_allow) begin
        pfi_q.tdr   <= {pic_tgt(xm_loc[14:0]), si_dir_w};
        pfi_q.tdr_v <= own_pext;
      end
      if (si_dir_w && !chg_since_q && !pic_chg) begin
        pfi_q.nl   <= 1'b0;
        pfi_q.nl_v <= own_pext;
      end
    end else if (pk_rdec) begin
      pfi_q.ini   <= 1'b1;
      pfi_q.ini_v <= own_pext;
    end
    if (pk_rdec && (pk_rd != 32'h0)) pfi_q.cl_v <= own_pext;
    if (si_done && si_dir_w && (xm_loc >= MbxBase) && (xm_loc < MbxEnd) &&
        (si_resp == AxiOkay) && fw_allow_q)
      pfi_q.wl_v <= own_pext;
    if (in_reset) pfi_q <= '0;
  end

  // =====================================================================
  // sep_cpu_nonpic_irq_cg
  // =====================================================================
  typedef struct packed {
    logic [1:0] mi;
    logic mi_v;   // {MTIP idle, MSIP idle} over a hold window
    logic       nt;
    logic nt_v;   // 0 hold window clean, 1 timer or software trap
    logic       tl_v;
  } pnp_t;

  covergroup sep_cpu_nonpic_irq_cg with function sample (pnp_t s);
    option.per_instance = 1;
    option.name = "sep_cpu_nonpic_irq_cg";
    cp_mip_idle: coverpoint s.mi iff (s.mi_v) {
      wildcard bins mtip_idle = {2'b1?}; wildcard bins msip_idle = {2'b?1};
    }
    cp_no_nonpic_trap: coverpoint s.nt iff (s.nt_v) {
      bins hold_window_clean = {1'b0}; illegal_bins timer_or_soft_trap = {1'b1};
    }
    cp_trap_path_live: coverpoint s.tl_v iff (s.tl_v) {bins pic_delivery = {1'b1};}
  endgroup

  logic [5:0] np_cnt_q;
  logic np_mt_q, np_ms_q;
  pnp_t pnp_q;
  wire  np_win = (tlu_mie_i[1] === 1'b1) && (tlu_mie_i[0] === 1'b1) && mie;
  always_ff @(posedge clk_i) begin
    pnp_q <= '0;
    if (in_reset || !np_win) begin
      np_cnt_q <= '0;
      np_mt_q  <= 1'b1;
      np_ms_q  <= 1'b1;
    end else begin
      if (np_cnt_q != 6'(HoldClk)) np_cnt_q <= np_cnt_q + 6'd1;
      if (tlu_mip_i[1] !== 1'b0) np_mt_q <= 1'b0;
      if (tlu_mip_i[0] !== 1'b0) np_ms_q <= 1'b0;
      if (np_cnt_q == 6'(HoldClk - 1)) begin
        pnp_q.mi   <= {np_mt_q && (tlu_mip_i[1] === 1'b0), np_ms_q && (tlu_mip_i[0] === 1'b0)};
        pnp_q.mi_v <= own_pprio && ((np_mt_q && (tlu_mip_i[1] === 1'b0)) ||
                                    (np_ms_q && (tlu_mip_i[0] === 1'b0)));
        pnp_q.nt   <= 1'b0;
        pnp_q.nt_v <= own_pprio && !(tlu_take_timer_i === 1'b1) && !(tlu_take_soft_i === 1'b1);
      end
    end
    if (!in_reset && ((tlu_take_timer_i === 1'b1) || (tlu_take_soft_i === 1'b1))) begin
      pnp_q.nt   <= 1'b1;
      pnp_q.nt_v <= own_pprio;
    end
    if (take_r) pnp_q.tl_v <= own_pprio;
  end

  // =====================================================================
  // sep_nmi_vector_cfg_cg
  // =====================================================================
  typedef struct packed {
    logic [2:0] vc;
    logic vc_v;   // 0 ICCM, 1 reset value, 2 DCCM, 3 CPU tail, 4 other
    logic [1:0] oe;
    logic oe_v;   // 0 vector at reset, 1 written and locked, 2 written, lock clear
    logic [2:0] tg;
    logic tg_v;   // 0 reset vector, 1-4 trampoline copy 0-3, 5 free address
  } nvc_t;

  covergroup sep_nmi_vector_cfg_cg with function sample (nvc_t s);
    option.per_instance = 1;
    option.name = "sep_nmi_vector_cfg_cg";
    cp_vec_class: coverpoint s.vc iff (s.vc_v) {
      bins iccm = {3'd0};
      ignore_bins reset_value = {3'd1};
      ignore_bins dccm = {3'd2};
      ignore_bins cpu_tail = {3'd3};
      ignore_bins other = {3'd4};
    }
    cp_order_at_enable: coverpoint s.oe iff (s.oe_v) {
      bins vector_at_reset = {2'd0};
      bins written_and_locked = {2'd1};
      ignore_bins written_lock_clear = {2'd2};
    }
    cp_nmi_target: coverpoint s.tg iff (s.tg_v) {
      bins reset_vector = {3'd0};
      bins trampoline_copy0 = {3'd1};
      bins trampoline_copy1 = {3'd2};
      bins trampoline_copy2 = {3'd3};
      bins trampoline_copy3 = {3'd4};
      bins free_address = {3'd5};
    }
  endgroup

  localparam logic [31:0] NmiResetVec = 32'(SEP_CPU_CTRL_SEP_NMI_VEC_REG_DEFAULT);
  localparam logic [31:0] IccmBase = 32'(SEP_TOP_SEP_ICCM_BASE_ADDR);
  localparam logic [31:0] IccmEnd = IccmBase + 32'(SEP_TOP_SEP_ICCM_SIZE);
  localparam logic [31:0] DccmBase = 32'(SEP_TOP_SEP_DCCM_BASE_ADDR);
  localparam logic [31:0] DccmEnd = DccmBase + 32'(SEP_TOP_SEP_DCCM_SIZE);
  // Vector value class of a SEP_NMI_VEC write (field bits [31:1] as an
  // address). The CPU tail is the reserved span from the DCCM end to the PIC.
  function automatic logic [2:0] nmi_vcls(input logic [31:0] v);
    if (v == NmiResetVec) return 3'd1;
    if ((v >= IccmBase) && (v < IccmEnd)) return 3'd0;
    if ((v >= DccmBase) && (v < DccmEnd)) return 3'd2;
    if ((v >= DccmEnd) && (v < PicBase)) return 3'd3;
    return 3'd4;
  endfunction
  // WDOG_CTRL.enable is bit 0 (OpenTitan aon_timer WDOG_CTRL; the vendored
  // block exports no field symbol).
  localparam logic [31:0] WdogEnMask = 32'h1;
  logic nv_wr_q, nv_lock_q, nv_en_q, nv_bark_q, nv_nmi_q, nv_entry_q;
  logic [31:0] nv_val_q;
  logic [2:0]  nv_cls_q;
  nvc_t nvc_q;
  always_ff @(posedge clk_i) begin
    nvc_q <= '0;
    if (in_reset || (sep_reset_n_i === 1'b0)) begin
      nv_wr_q    <= 1'b0;
      nv_lock_q  <= 1'b0;
      nv_en_q    <= 1'b0;
      nv_bark_q  <= 1'b0;
      nv_nmi_q   <= 1'b0;
      nv_entry_q <= 1'b0;
    end else begin
      if (wr_ev && (aw_addr_q == SEP_CPU_CTRL_SEP_NMI_VEC_REG_ADDR)) begin
        nv_wr_q    <= 1'b1;
        nv_val_q   <= wr_data & 32'(SEP_CPU_CTRL_SEP_NMI_VEC_NMI_VEC_MASK);
        nv_cls_q   <= nmi_vcls(wr_data & 32'(SEP_CPU_CTRL_SEP_NMI_VEC_NMI_VEC_MASK));
      end
      if (wr_ev && (aw_addr_q == SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_REG_ADDR) &&
          ((wr_data & 32'(SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_LOCK_MASK)) != 32'h0))
        nv_lock_q <= 1'b1;
      if (wr_ev && (aw_addr_q == WDT_TIMER_WDOG_CTRL_REG_ADDR)) begin
        nv_en_q <= ((wr_data & WdogEnMask) != 32'h0);
        if (((wr_data & WdogEnMask) != 32'h0) && !nv_en_q) begin
          nvc_q.oe   <= !nv_wr_q ? 2'd0 : (nv_lock_q ? 2'd1 : 2'd2);
          nvc_q.oe_v <= own_nmi;
          // Class of the last SEP_NMI_VEC write, taken at that write and
          // sampled at the bark enable that arms it.
          if (nv_wr_q) begin
            nvc_q.vc   <= nv_cls_q;
            nvc_q.vc_v <= own_nmi;
          end
        end
      end
      // Bark, then the NMI is taken, then its trap packet (exception and
      // interrupt flags set), then the first retired PC. Instructions that
      // retire between the NMI decision and the trap packet belong to the
      // interrupted code and are skipped.
      if (bark_r) nv_bark_q <= 1'b1;
      if (nv_bark_q && nmi_r) nv_nmi_q <= 1'b1;
      if (nv_bark_q && (nv_nmi_q || nmi_r) && (cpu_trace_valid_i === 1'b1) &&
          (cpu_trace_exc_i === 1'b1) && (cpu_trace_interrupt_i === 1'b1)) begin
        nv_bark_q  <= 1'b0;
        nv_nmi_q   <= 1'b0;
        nv_entry_q <= 1'b1;
      end else if (nv_entry_q && (cpu_trace_valid_i === 1'b1) && (cpu_trace_exc_i !== 1'b1)) begin
        nv_entry_q <= 1'b0;
        if (!nv_wr_q && (cpu_trace_addr_i == NmiResetVec)) begin
          nvc_q.tg   <= 3'd0;
          nvc_q.tg_v <= own_nmi;
        end else if (nv_wr_q && (cpu_trace_addr_i == nv_val_q)) begin
          // A trampoline copy is 256-byte aligned in ICCM; its index is
          // address bits [9:8]. The free address A is any other ICCM address.
          nvc_q.tg   <= (nv_val_q[7:0] == 8'h00) ? (3'd1 + 3'(nv_val_q[9:8])) : 3'd5;
          nvc_q.tg_v <= own_nmi;
        end
      end
    end
  end

  // =====================================================================
  // sep_nmi_concurrency_cg
  // =====================================================================
  typedef struct packed {
    logic [1:0] ct;
    logic ct_v;   // case a-d
    logic [2:0] vu;
    logic vu_v;   // {dropped, case}
    logic       pl_v;
  } ncc_t;

  covergroup sep_nmi_concurrency_cg with function sample (ncc_t s);
    option.per_instance = 1;
    option.name = "sep_nmi_concurrency_cg";
    x_case_taken: coverpoint s.ct iff (s.ct_v) {
      bins a_mie0_pending_enabled = {2'd0};
      bins b_mie1_pending_meie0 = {2'd1};
      bins c_mie1_pending_never = {2'd2};
      bins d_mie1_nothing_pending = {2'd3};
    }
    cp_vec_unchanged: coverpoint s.vu iff (s.vu_v) {
      bins case_a = {3'b0_00};
      bins case_b = {3'b0_01};
      bins case_c = {3'b0_10};
      illegal_bins live_bit_dropped = {[3'b1_00 : 3'b1_11]};
    }
    cp_pic_live_after: coverpoint s.pl_v iff (s.pl_v) {bins delivered_once = {1'b1};}
  endgroup

  logic nc_on_q, nc_seen_q;
  logic [1:0]   nc_case_q;
  logic [255:0] nc_snap_q;
  logic [12:0]  nc_cnt_q;
  ncc_t ncc_q;
  wire [255:0] pend_live = gw_live & ~256'd1;
  always @(posedge clk_i) begin
    ncc_q <= '0;
    if (in_reset) begin
      nc_on_q   <= 1'b0;
      nc_seen_q <= 1'b0;
    end else begin
      if (!own_nmi) nc_seen_q <= 1'b0;
      if (nmi_r) begin
        logic [1:0] c;
        logic       ok;
        ok = 1'b1;
        if (!mie && ((pend_live & pic_en_i & usable) != '0)) c = 2'd0;
        else if (mie && ((pend_live & ~pic_en_i) != '0) && ((pend_live & cand) == '0)) c = 2'd1;
        else if (mie && ((pend_live & pic_en_i & ~usable) != '0) && ((pend_live & cand) == '0))
          c = 2'd2;
        else if (mie && (pend_live == '0)) c = 2'd3;
        else begin
          c  = 2'd0;
          ok = 1'b0;
        end
        if (ok) begin
          ncc_q.ct   <= c;
          ncc_q.ct_v <= own_nmi;
          nc_seen_q  <= 1'b1;
          if (c != 2'd3) begin
            nc_on_q   <= 1'b1;
            nc_case_q <= c;
            nc_snap_q <= pend_live;
            nc_cnt_q  <= '0;
          end
        end
      end else if (nc_on_q) begin
        nc_cnt_q <= nc_cnt_q + 13'd1;
        if ((nc_snap_q & ~pend_live) != '0) begin
          nc_on_q    <= 1'b0;
          ncc_q.vu   <= {1'b1, nc_case_q};
          ncc_q.vu_v <= own_nmi;
        end else if (take_r || (nc_cnt_q == 13'(NmiWin))) begin
          nc_on_q    <= 1'b0;
          ncc_q.vu   <= {1'b0, nc_case_q};
          ncc_q.vu_v <= own_nmi;
        end
      end
      // After an NMI, the pending source of the snapshot delivers.
      if (take_r && nc_seen_q && nc_snap_q[pic_claim_i]) begin
        nc_seen_q   <= 1'b0;
        ncc_q.pl_v <= own_nmi;
      end
    end
  end

  // =====================================================================
  // Peripheral bridge and DMA fault latches (sep_fault_source_report_cg,
  // sep_fault_source_ack_cg, sep_dma_host_fault_cg). ERRP[8:0] are the set
  // terms and ERRP[17:9] the clear pulses, bit order aes, hmac, kmac, otbn,
  // csrng, edn, wdt, DMA register path, DMA host path. The status bit of
  // PERIPH_BUS_ERR_STATUS has the same index.
  // =====================================================================
  localparam logic [31:0] PbeStatus = SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_REG_ADDR;
  localparam logic [31:0] PbeClear = SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_REG_ADDR;
  localparam logic [31:0] DbeStatus = SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_ADDR;
  localparam logic [31:0] DbeClear = SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_REG_ADDR;
  // Any response of a single outstanding LSU transaction.
  wire b_any = !in_reset && b_hs && (aw_out_q == 4'd1) && (w_beats_q == 2'd1);
  wire r_any = !in_reset && r_hs && (ar_out_q == 4'd1) && !r_multi_q;
  wire pbe_rd = rd_ev && (ar_addr_q == PbeStatus);
  wire dbe_rd = rd_ev && (ar_addr_q == DbeStatus);
  wire [6:0] pbe_val = rd_data[6:0];
  wire [1:0] dbe_val = rd_data[1:0];
  // Block index (status bit) of an LSU address: 1 hmac, 2 kmac, 3 otbn.
  function automatic logic [1:0] flt_blk(input logic [31:0] a);
    if (in_blk(a, HMAC_REG_MAP_BASE_ADDR, HMAC_REG_MAP_SIZE)) return 2'd1;
    if (in_blk(a, KMAC_REG_MAP_BASE_ADDR, KMAC_REG_MAP_SIZE)) return 2'd2;
    if (in_blk(a, OTBN_REG_MAP_BASE_ADDR, OTBN_REG_MAP_SIZE)) return 2'd3;
    return 2'd0;
  endfunction

  typedef struct packed {
    logic [1:0] site;
    logic site_v;   // 0 source 41, 1 source 42, 2 source 43
    logic [2:0] blk;
    logic blk_v;    // status bit index
    logic [2:0] ss;
    logic ss_v;     // latched blocks
    logic [3:0] sr;
    logic sr_v;     // {block, response}
    logic       sx;
    logic sx_v;     // 1 X on the status read
  } fsr_t;

  covergroup sep_fault_source_report_cg with function sample (fsr_t s);
    option.per_instance = 1;
    option.name = "sep_fault_source_report_cg";
    cp_site: coverpoint s.site iff (s.site_v) {
      bins src41_dma_reg_path = {2'd0};
      bins src42_dma_host_path = {2'd1};
      bins src43_bridge_or = {2'd2};
    }
    cp_block: coverpoint s.blk iff (s.blk_v) {
      bins hmac = {3'd1};
      bins kmac = {3'd2};
      bins otbn = {3'd3};
      ignore_bins no_stated_hole = {3'd0, 3'd4, 3'd5, 3'd6};
    }
    cp_set_size: coverpoint s.ss iff (s.ss_v) {
      bins one = {3'd1}; bins two = {3'd2}; bins three = {3'd3};
    }
    x_site_resp: coverpoint s.sr iff (s.sr_v) {
      bins hmac_slverr = {4'b01_10};
      bins kmac_slverr = {4'b10_10};
      bins otbn_slverr = {4'b11_10};
      illegal_bins okay_or_decerr = {4'b01_00, 4'b01_11, 4'b10_00, 4'b10_11, 4'b11_00, 4'b11_11};
    }
    cp_status_x: coverpoint s.sx iff (s.sx_v) {bins clean = {1'b0}; illegal_bins x = {1'b1};}
  endgroup

  typedef struct packed {
    logic [2:0]  dc;
    logic dc_v;   // {clear write, latch state before}
    logic        cr;
    logic cr_v;   // 0 DMA_BUS_ERR_CLEAR, 1 PERIPH_BUS_ERR_CLEAR read 0
    logic [4:0]  cm;
    logic cm_v;   // clear bit i * 3 + (status bit j - 1)
    logic [2:0]  cs;
    logic cs_v;   // {includes unlatched, multi, single}
    logic        of;
    logic of_v;   // 0 source 43 stays, 1 drops with the last bit
    logic        rt;
    logic rt_v;   // 0 cleared block latches again, 1 still set
    logic        da_v;
    logic [2:0]  rl;
    logic rl_v;   // {latched, kind}: kind 0 hmac 1 kmac 2 otbn 3 host path
    logic [1:0]  lk;
    logic lk_v;   // {latch 0 DMA reg_path_err 1 PERIPH bit of L, reset 0 wdt_rst_ni 1 rst_ni}
    logic        bc;
    logic bc_v;   // 0 source 41 (bit 40), 1 source 43 (bit 42)
  } fsa_t;

  covergroup sep_fault_source_ack_cg with function sample (fsa_t s);
    option.per_instance = 1;
    option.name = "sep_fault_source_ack_cg";
    x_dma_clr: coverpoint s.dc iff (s.dc_v) {
      bins write0_reg_only = {3'b0_01};
      bins write0_both = {3'b0_11};
      bins write1_both = {3'b1_11};
      bins write1_host_only = {3'b1_10};
      ignore_bins write1_reg_only = {3'b1_01};
    }
    cp_clr_read0: coverpoint s.cr iff (s.cr_v) {
      bins dma_bus_err_clear = {1'b0}; bins periph_bus_err_clear = {1'b1};
    }
    x_clear_matrix: coverpoint s.cm iff (s.cm_v) {bins cells[] = {[5'd0 : 5'd20]};}
    cp_clear_shape: coverpoint s.cs iff (s.cs_v) {
      wildcard bins single_bit = {3'b??1};
      wildcard bins multi_bit = {3'b?1?};
      wildcard bins includes_unlatched = {3'b1??};
    }
    cp_or_follow: coverpoint s.of iff (s.of_v) {
      bins stays_while_bit_left = {1'b0}; bins drops_with_last_bit = {1'b1};
    }
    cp_retrigger: coverpoint s.rt iff (s.rt_v) {
      bins cleared_latches_again = {1'b0}; bins still_set_others_kept = {1'b1};
    }
    cp_dma_clr_alias: coverpoint s.da_v iff (s.da_v) {bins both_drop = {1'b1};}
    cp_race_latch: coverpoint s.rl iff (s.rl_v) {
      bins hmac = {3'b1_00};
      bins kmac = {3'b1_01};
      bins otbn = {3'b1_10};
      bins host_path_err = {3'b1_11};
      illegal_bins latch_dropped = {[3'b0_00 : 3'b0_11]};
    }
    // A CPU-only reset keeps the latch and a full reset clears it.
    cp_latch_x_reset_kind: coverpoint s.lk iff (s.lk_v) {
      bins dma_kept_cpu_only = {2'b0_0};
      bins dma_cleared_full = {2'b0_1};
      bins periph_kept_cpu_only = {2'b1_0};
      bins periph_cleared_full = {2'b1_1};
    }
    cp_boot_consequence: coverpoint s.bc iff (s.bc_v) {
      bins source41_pending = {1'b0}; bins source43_pending = {1'b1};
    }
  endgroup

  typedef struct packed {logic bes_v;} dhf_t;

  covergroup sep_dma_host_fault_cg with function sample (dhf_t s);
    option.per_instance = 1;
    option.name = "sep_dma_host_fault_cg";
    cp_bus_error_src: coverpoint s.bes_v iff (s.bes_v) {bins source_read_fault = {1'b1};}
  endgroup

  logic hw_on_q, hw_flt_q;
  logic [1:0] hw_blk_q;
  logic [3:1] pend_blk_q, cleared_q;
  logic [6:0] pp_q, pflt_q, clr_pre_q, clr_mask_q;
  logic pp_v_q, clr_pend_q;
  logic [1:0] dp_q, dflt_q, dclr_pre_q;
  logic dp_v_q, dclr_pend_q, dclr_w_q;
  logic [3:0] race_q, race_late_q;  // hmac, kmac, otbn, host path
  logic slverr_seen_q, ec_ok_q, st_ok_q;
  logic [20:0] cm_q;
  fsr_t fsr_q;
  fsa_t fsa_q;
  dhf_t dhf_q;
  wire [8:0] errp_set = err_pulse_i[8:0];
  wire [8:0] errp_clr = err_pulse_i[17:9];
  wire       out_r_slverr = (out_resp_i.r_valid === 1'b1) && (out_req_i.r_ready === 1'b1) &&
      (out_resp_i.r.resp == AxiSlverr);
  always @(posedge clk_i) begin
    fsr_q <= '0;
    fsa_q <= '0;
    dhf_q <= '0;
    cm_q  <= '0;
    if (in_reset) begin
      hw_on_q       <= 1'b0;
      pend_blk_q    <= '0;
      cleared_q     <= '0;
      pp_v_q        <= 1'b0;
      clr_pend_q    <= 1'b0;
      dp_v_q        <= 1'b0;
      dclr_pend_q   <= 1'b0;
      race_q        <= '0;
      race_late_q   <= '0;
      slverr_seen_q <= 1'b0;
      ec_ok_q       <= 1'b0;
      st_ok_q       <= 1'b0;
    end else begin
      // ---- sources 41, 42, 43 ----
      if (out_r_slverr || (out_rd_slverr_i === 1'b1)) slverr_seen_q <= 1'b1;
      if (vec_rise[40]) begin
        fsr_q.site <= 2'd0;
        fsr_q.site_v <= own_bfault;
      end else if (vec_rise[41] && slverr_seen_q) begin
        fsr_q.site <= 2'd1;
        fsr_q.site_v <= own_bfault;
      end else if (vec_rise[42]) begin
        fsr_q.site <= 2'd2;
        fsr_q.site_v <= own_bfault;
      end
      // ---- hole write: a write to hmac, kmac or otbn that raises the set
      // term of its latch before its response ----
      if (aw_hs && (aw_out_q == 4'd0) && (flt_blk(lsu_aw_addr_i) != 2'd0)) begin
        hw_on_q  <= 1'b1;
        hw_blk_q <= flt_blk(lsu_aw_addr_i);
        hw_flt_q <= 1'b0;
      end else if (hw_on_q) begin
        if (errp_set[hw_blk_q]) hw_flt_q <= 1'b1;
        if (b_any) begin
          hw_on_q <= 1'b0;
          if (hw_flt_q || errp_set[hw_blk_q]) begin
            fsr_q.sr   <= {hw_blk_q, lsu_b_resp_i};
            fsr_q.sr_v <= own_bfault;
            pend_blk_q[hw_blk_q] <= 1'b1;
          end
        end
      end
      // ---- PERIPH_BUS_ERR_STATUS reads ----
      pflt_q <= pflt_q | errp_set[6:0];
      if (pbe_rd || dbe_rd) begin
        fsr_q.sx   <= pbe_rd ? $isunknown(pbe_val) : $isunknown(dbe_val);
        fsr_q.sx_v <= own_bfault;
      end
      if (pbe_rd) begin
        for (int j = 3; j >= 1; j--) begin
          if (pend_blk_q[j] && pbe_val[j]) begin
            fsr_q.blk  <= 3'(j);
            fsr_q.blk_v <= own_bfault;
            pend_blk_q[j] <= 1'b0;
          end
        end
        if (($countones(pbe_val) >= 1) && ($countones(pbe_val) <= 3)) begin
          fsr_q.ss   <= 3'($countones(pbe_val));
          fsr_q.ss_v <= own_bfault;
        end
        // Outcome of the latest PERIPH_BUS_ERR_CLEAR write.
        if (clr_pend_q && (pflt_q == '0) && (pbe_val == (clr_pre_q & ~clr_mask_q))) begin
          for (int i = 0; i < 7; i++) begin
            for (int j = 1; j <= 3; j++) begin
              if (clr_mask_q[i] && clr_pre_q[j] && ((i == j) || !clr_mask_q[j]))
                cm_q[i*3+j-1] <= own_bfault;
            end
          end
          fsa_q.cs <= {((clr_mask_q & ~clr_pre_q) != '0), ($countones(clr_mask_q) > 1),
                       ($countones(clr_mask_q) == 1)};
          fsa_q.cs_v <= own_bfault && (clr_mask_q != '0);
          if ((pbe_val != '0) && vec_i[42]) begin
            fsa_q.of <= 1'b0;
            fsa_q.of_v <= own_bfault;
          end else if ((pbe_val == '0) && (clr_pre_q != '0) && !vec_i[42]) begin
            fsa_q.of <= 1'b1;
            fsa_q.of_v <= own_bfault;
          end
        end
        clr_pend_q <= 1'b0;
        // Re-trigger: exactly one block faulted since the previous read.
        if (pp_v_q) begin
          for (int j = 1; j <= 3; j++) begin
            if (pflt_q == (7'd1 << j)) begin
              if (!pp_q[j] && cleared_q[j] && pbe_val[j] &&
                  ((pbe_val & ~pflt_q) == (pp_q & ~pflt_q))) begin
                fsa_q.rt <= 1'b0;
                fsa_q.rt_v <= own_bfault;
              end else if (pp_q[j] && (pbe_val == pp_q)) begin
                fsa_q.rt <= 1'b1;
                fsa_q.rt_v <= own_bfault;
              end
            end
            if (pp_q[j] && !pbe_val[j]) cleared_q[j] <= 1'b1;
            else if (pbe_val[j]) cleared_q[j] <= 1'b0;
          end
        end
        // Same-cycle fault and clear of a peripheral latch.
        for (int k = 2; k >= 0; k--) begin
          if (race_q[k]) begin
            race_q[k] <= 1'b0;
            if (!race_late_q[k]) begin
              fsa_q.rl   <= {pbe_val[k+1], 2'(k)};
              fsa_q.rl_v <= own_bfault;
            end
          end
        end
        pp_q   <= pbe_val;
        pp_v_q <= 1'b1;
        pflt_q <= errp_set[6:0];
      end
      if (wr_ev && (aw_addr_q == PbeClear)) begin
        clr_pend_q <= pp_v_q && (pflt_q == '0);
        clr_pre_q  <= pp_q;
        clr_mask_q <= wr_data[6:0];
        pflt_q     <= errp_set[6:0];
      end
      if (rd_ev && (ar_addr_q == PbeClear) && (rd_data[6:0] == 7'h0)) begin
        fsa_q.cr <= 1'b1;
        fsa_q.cr_v <= own_bfault;
      end
      if (rd_ev && (ar_addr_q == DbeClear) && (rd_data[0] == 1'b0)) begin
        fsa_q.cr <= 1'b0;
        fsa_q.cr_v <= own_bfault;
      end
      // ---- DMA_BUS_ERR latches ----
      dflt_q <= dflt_q | errp_set[8:7];
      if (wr_ev && (aw_addr_q == DbeClear)) begin
        dclr_pend_q <= dp_v_q && (dflt_q == '0);
        dclr_pre_q  <= dp_q;
        dclr_w_q    <= wr_data[0];
        dflt_q      <= errp_set[8:7];
      end
      if (dbe_rd) begin
        if (dclr_pend_q && (dflt_q == '0)) begin
          if (!dclr_w_q && (dbe_val == dclr_pre_q)) begin
            fsa_q.dc <= {1'b0, dclr_pre_q};
            fsa_q.dc_v <= own_bfault;
          end else if (dclr_w_q && (dbe_val == 2'b00)) begin
            fsa_q.dc <= {1'b1, dclr_pre_q};
            fsa_q.dc_v <= own_bfault;
            if ((dclr_pre_q == 2'b11) && !vec_i[40] && !vec_i[41]) fsa_q.da_v <= own_bfault;
          end
        end
        dclr_pend_q <= 1'b0;
        if (race_q[3]) begin
          race_q[3] <= 1'b0;
          if (!race_late_q[3]) begin
            fsa_q.rl   <= {dbe_val[1], 2'd3};
            fsa_q.rl_v <= own_bfault;
          end
        end
        // Host-path fault on a DMA source read: ERROR_CODE.BUS_ERROR and
        // STATUS.ERROR read 1 since the SLVERR, then status 0b10.
        if (slverr_seen_q && ec_ok_q && st_ok_q && (dbe_val == 2'b10) && vec_i[41] && !vec_i[40])
          dhf_q.bes_v <= own_bfault;
        dp_q   <= dbe_val;
        dp_v_q <= 1'b1;
        dflt_q <= errp_set[8:7];
      end
      if (rd_ev && (ar_addr_q == SECURE_DMA_ERROR_CODE_REG_ADDR) &&
          ((rd_data & SECURE_DMA_ERROR_CODE_BUS_ERROR_MASK) != 32'h0) && slverr_seen_q)
        ec_ok_q <= 1'b1;
      if (rd_ev && (ar_addr_q == SECURE_DMA_STATUS_REG_ADDR) &&
          ((rd_data & SECURE_DMA_STATUS_ERROR_MASK) != 32'h0) && slverr_seen_q)
        st_ok_q <= 1'b1;
      // Coincidence of the set term and the clear pulse of one latch.
      for (int k = 0; k < 4; k++) begin
        int unsigned b;
        b = (k == 3) ? 8 : (k + 1);
        if (errp_set[b] && errp_clr[b]) begin
          race_q[k]      <= 1'b1;
          race_late_q[k] <= 1'b0;
        end else if (race_q[k] && errp_set[b]) begin
          race_late_q[k] <= 1'b1;
        end
      end
    end
  end

  // =====================================================================
  // Mailbox unit bus decode (sep_mbox_* groups). One outstanding read and
  // one outstanding write at the mailbox unit; deeper traffic is skipped.
  // Address a - AXIL_MAILBOX base: mailbox a[14:12], port a[11] (0 outbound
  // i_slv_port_0, 1 inbound i_slv_port_1), offset a[10:0]. A port writes
  // FIFO index p and reads FIFO index !p.
  // =====================================================================
  localparam logic [10:0] MoWdata = 11'h000;
  localparam logic [10:0] MoRdata = 11'h008;
  localparam logic [10:0] MoStatus = 11'h010;
  localparam logic [10:0] MoErr = 11'h018;
  localparam logic [10:0] MoWirqt = 11'h020;
  localparam logic [10:0] MoRirqt = 11'h028;
  localparam logic [10:0] MoIrqs = 11'h030;
  localparam logic [10:0] MoIrqen = 11'h038;
  localparam logic [10:0] MoIrqp = 11'h040;
  localparam logic [10:0] MoCtrl = 11'h048;
  localparam logic [10:0] MoHole = 11'h050;
  localparam logic [10:0] MoLast = 11'h7F8;

  wire mx_aw_hs = (mbx_req_i.aw_valid === 1'b1) && (mbx_resp_i.aw_ready === 1'b1);
  wire mx_w_hs = (mbx_req_i.w_valid === 1'b1) && (mbx_resp_i.w_ready === 1'b1);
  wire mx_b_hs = (mbx_resp_i.b_valid === 1'b1) && (mbx_req_i.b_ready === 1'b1);
  wire mx_ar_hs = (mbx_req_i.ar_valid === 1'b1) && (mbx_resp_i.ar_ready === 1'b1);
  wire mx_r_hs = (mbx_resp_i.r_valid === 1'b1) && (mbx_req_i.r_ready === 1'b1);
  wire mx_any_hs = mx_aw_hs || mx_w_hs || mx_b_hs || mx_ar_hs || mx_r_hs;
  logic [3:0] mx_wo_q, mx_ro_q;
  logic [31:0] mx_wa_q, mx_ra_q;
  logic [63:0] mx_wd_q;
  // Kind of the access, decided at its request: 0 none, 1 K1, 2 K2, 3 K3, 4 K4.
  logic [2:0] mx_wk_q, mx_rk_q;
  // Occupancy of every FIFO at the latest write request.
  logic [7:0][1:0][3:0] occ_aw_q;
  logic [7:0][1:0][3:0] occ, occ_q;
  always_comb begin
    for (int m = 0; m < 8; m++) begin
      for (int f = 0; f < 2; f++) occ[m][f] = mf_full_i[m][f] ? 4'd8 : {1'b0, mf_usage_i[m][f]};
    end
  end
  function automatic logic [31:0] mx_off(input logic [31:0] a);
    return a - MbxBase;
  endfunction
  function automatic logic [2:0] mx_kind(input logic [31:0] a, input logic wr,
                                         input logic [7:0][1:0][3:0] o);
    logic [31:0] r;
    logic [2:0]  m;
    logic        p;
    logic [10:0] off;
    r   = a - MbxBase;
    m   = r[14:12];
    p   = r[11];
    off = r[10:0];
    if (r >= AXIL_MAILBOX_REG_MAP_SIZE) return 3'd0;
    if (off >= MoHole) return 3'd4;
    if (wr) begin
      if ((off == MoWdata) && (o[m][p] == 4'd8)) return 3'd2;
      if ((off == MoRdata) || (off == MoStatus) || (off == MoErr) || (off == MoIrqp)) return 3'd3;
    end else begin
      if ((off == MoRdata) && (o[m][!p] == 4'd0)) return 3'd1;
    end
    return 3'd0;
  endfunction
  always_ff @(posedge clk_i) begin
    occ_q <= occ;
    if (sep_reset_n_i !== 1'b1) begin
      mx_wo_q <= '0;
      mx_ro_q <= '0;
    end else begin
      mx_wo_q <= mx_wo_q + 4'(mx_aw_hs) - 4'(mx_b_hs && ((mx_wo_q != 4'd0) || mx_aw_hs));
      mx_ro_q <= mx_ro_q + 4'(mx_ar_hs) - 4'(mx_r_hs && ((mx_ro_q != 4'd0) || mx_ar_hs));
      if (mx_aw_hs) begin
        mx_wa_q  <= mbx_req_i.aw.addr;
        mx_wk_q  <= mx_kind(mbx_req_i.aw.addr, 1'b1, occ);
        occ_aw_q <= occ;
      end
      if (mx_w_hs) mx_wd_q <= mbx_req_i.w.data;
      if (mx_ar_hs) begin
        mx_ra_q <= mbx_req_i.ar.addr;
        mx_rk_q <= mx_kind(mbx_req_i.ar.addr, 1'b0, occ);
      end
    end
  end
  // Completions of a single outstanding access.
  wire         mx_wdone = !in_reset && mx_b_hs && (mx_wo_q == 4'd1) && !mx_aw_hs;
  wire         mx_rdone = !in_reset && mx_r_hs && (mx_ro_q == 4'd1) && !mx_ar_hs;
  wire [31:0]  mx_wr = mx_off(mx_wa_q);
  wire [31:0]  mx_rr = mx_off(mx_ra_q);
  wire [2:0]   mx_wm = mx_wr[14:12];
  wire         mx_wp = mx_wr[11];
  wire [10:0]  mx_wo = mx_wr[10:0];
  wire [2:0]   mx_rm = mx_rr[14:12];
  wire         mx_rp = mx_rr[11];
  wire [10:0]  mx_ro = mx_rr[10:0];
  wire         mx_win = mx_wr < AXIL_MAILBOX_REG_MAP_SIZE;
  wire         mx_rin = mx_rr < AXIL_MAILBOX_REG_MAP_SIZE;
  wire [1:0]   mx_bresp = mbx_resp_i.b.resp;
  wire [1:0]   mx_rresp = mbx_resp_i.r.resp;
  wire [63:0]  mx_rdata = mbx_resp_i.r.data;

  // Aperture position of a 64-bit word (an access to either 32-bit half): 0
  // first register word, 1 last register word 0x48, 2 first hole word 0x50, 3
  // interior hole word, 4 last hole word 0x7F8.
  function automatic logic [3:0] mx_pos(input logic [10:0] off);
    if (off == MoWdata) return 4'd0;
    if (off == MoCtrl) return 4'd1;
    if (off == MoHole) return 4'd2;
    if (off == MoLast) return 4'd4;
    if ((off > MoHole) && (off < MoLast)) return 4'd3;
    return 4'd8;
  endfunction
  wire [3:0] mx_wpos = mx_pos({mx_wo[10:3], 3'b000});
  wire [3:0] mx_rpos = mx_pos({mx_ro[10:3], 3'b000});

  // ---- quiet window state (fifo-model leaf) ----
  // *_qs hold the values of the last clock with quiet_win at 1.
  logic [42:0] vec_qs, vec_pq;
  logic [7:0] smc_qs, smc_pq;
  logic [7:0][1:0][2:0] irqs_qs, irqen_qs;
  logic [7:0][1:0]      irq_qs;
  logic [7:0]           pend_out_pq;
  logic q_beat_q, q_high_q, q_prev_v_q;
  logic [2:0]           lastk_q;
  logic                 lastk_v_q;
  wire                  q_open = quiet_win && !quiet_q;
  wire                  q_end = quiet_q && !quiet_win;
  function automatic logic [2:0] cnt_cls(input int unsigned n);
    if (n <= 2) return 3'(n);
    if (n <= 7) return 3'd3;
    return 3'd4;
  endfunction
  logic [7:0] pend_out_qs, pend_in_qs;
  always_comb begin
    for (int m = 0; m < 8; m++) begin
      pend_out_qs[m] = |(irqs_qs[m][0] & irqen_qs[m][0]);
      pend_in_qs[m]  = |(irqs_qs[m][1] & irqen_qs[m][1]);
    end
  end

  // =====================================================================
  // sep_mbox_transfer_cg
  // =====================================================================
  typedef struct packed {
    logic [6:0] ia;
    logic ia_v;   // {mismatch, written channel k, line j}
    logic [3:0] oc;
    logic oc_v;   // {mismatch, SMC count class}
    logic [3:0] ap;
    logic ap_v;   // {port, position}
    logic       oe;
    logic oe_v;   // 0 read, 1 write
    logic [3:0] ek;
    logic ek_v;   // {kind - 1, port}
    logic [3:0] er;
    logic er_v;   // {not SLVERR, kind - 1}
    logic [1:0] ef;
    logic ef_v;
    logic       wo;
    logic wo_v;   // port
  } mbt_t;

  covergroup sep_mbox_transfer_cg with function sample (mbt_t s);
    option.per_instance = 1;
    option.name = "sep_mbox_transfer_cg";
    x_in_attr: coverpoint s.ia iff (s.ia_v) {
      bins cells[] = {[7'd0 : 7'd63]}; illegal_bins line_mismatch = {[7'd64 : 7'd127]};
    }
    x_out_count: coverpoint s.oc iff (s.oc_v) {
      bins n0 = {4'd0};
      bins n1 = {4'd1};
      bins n2 = {4'd2};
      bins n3_7 = {4'd3};
      bins n8 = {4'd4};
      illegal_bins count_mismatch = {[4'd8 : 4'd15]};
    }
    cp_aperture_pos: coverpoint s.ap iff (s.ap_v) {
      bins out_first_reg = {4'b0_000};
      ignore_bins out_last_reg = {4'b0_001};
      bins out_first_hole = {4'b0_010};
      bins out_interior_hole = {4'b0_011};
      bins out_last_hole = {4'b0_100};
      bins in_first_reg = {4'b1_000};
      ignore_bins in_last_reg = {4'b1_001};
      bins in_first_hole = {4'b1_010};
      bins in_interior_hole = {4'b1_011};
      bins in_last_hole = {4'b1_100};
    }
    cp_out_of_extent: coverpoint s.oe iff (s.oe_v) {bins read = {1'b0}; bins write = {1'b1};}
    x_err_kind_port: coverpoint s.ek iff (s.ek_v) {
      bins k1_empty_read_out = {4'b000_0};
      bins k1_empty_read_in = {4'b000_1};
      bins k2_full_write_out = {4'b001_0};
      bins k2_full_write_in = {4'b001_1};
      bins k3_ro_write_out = {4'b010_0};
      bins k3_ro_write_in = {4'b010_1};
      bins k4_hole_out = {4'b011_0};
      bins k4_hole_in = {4'b011_1};
      ignore_bins k5_past_extent_out = {4'b100_0};
      bins k5_past_extent_in = {4'b100_1};
    }
    cp_err_resp: coverpoint s.er iff (s.er_v) {
      bins k1_slverr = {4'd0};
      bins k2_slverr = {4'd1};
      bins k3_slverr = {4'd2};
      bins k4_slverr = {4'd3};
      bins k5_slverr = {4'd4};
      illegal_bins okay_or_decerr = {[4'd8 : 4'd12]};
    }
    cp_err_flags: coverpoint s.ef iff (s.ef_v) {
      bins first_read_reports = {2'd0};
      bins second_read_zero = {2'd1};
      bins irqs_eirq_held_until_w1c = {2'd2};
      bins both_flags_then_zero = {2'd3};
    }
    cp_wo_read: coverpoint s.wo iff (s.wo_v) {bins outbound = {1'b0}; bins inbound = {1'b1};}
  endgroup

  logic [15:0] ef_nz_q, ef_both_q, ef_clr_q;
  logic [7:0] ia_line_q, ia_exp_q;
  logic [2:0]  ia_k_q;
  logic        ia_go_q;
  mbt_t mbt_q;
  wire  xm_ext = si_done && (xm_loc >= MbxEnd) && (xm_loc < (MbxBase + 32'h8000));
  always_ff @(posedge clk_i) begin
    mbt_q   <= '0;
    ia_go_q <= 1'b0;
    if (in_reset) begin
      ef_nz_q   <= '0;
      ef_both_q <= '0;
      ef_clr_q  <= '0;
    end else begin
      // ---- quiet-window bins ----
      if (q_end && !q_beat_q) begin
        ia_go_q   <= lastk_v_q;
        ia_k_q    <= lastk_q;
        ia_line_q <= vec_qs[7:0];
        ia_exp_q  <= pend_in_qs;
        mbt_q.oc  <= {($countones(smc_qs) != $countones(pend_out_qs)),
                      cnt_cls($countones(smc_qs))};
        mbt_q.oc_v <= own_mfifo;
      end
      // ---- error injections ----
      if (mx_wdone && mx_win) begin
        if (mx_wpos != 4'd8) begin
          mbt_q.ap   <= {mx_wp, mx_wpos[2:0]};
          mbt_q.ap_v <= own_merr;
        end
        if (mx_wk_q != 3'd0) begin
          mbt_q.ek   <= {mx_wk_q - 3'd1, mx_wp};
          mbt_q.ek_v <= own_merr;
          mbt_q.er   <= {(mx_bresp != AxiSlverr), mx_wk_q - 3'd1};
          mbt_q.er_v <= own_merr;
        end
        if ((mx_wo == MoIrqs) && mx_wd_q[2]) ef_clr_q[{mx_wm, mx_wp}] <= 1'b0;
      end
      if (mx_rdone && mx_rin) begin
        if (mx_rpos != 4'd8) begin
          mbt_q.ap   <= {mx_rp, mx_rpos[2:0]};
          mbt_q.ap_v <= own_merr;
        end
        if (mx_rk_q != 3'd0) begin
          mbt_q.ek   <= {mx_rk_q - 3'd1, mx_rp};
          mbt_q.ek_v <= own_merr;
          mbt_q.er   <= {(mx_rresp != AxiSlverr), mx_rk_q - 3'd1};
          mbt_q.er_v <= own_merr;
        end
        // ERROR_FLAGS reads clear the flags.
        if ((mx_ro == MoErr) && (mx_rresp == AxiOkay)) begin
          if (mx_rdata[1:0] != 2'b00) begin
            mbt_q.ef   <= 2'd0;
            mbt_q.ef_v <= own_merr;
            ef_nz_q[{mx_rm, mx_rp}]   <= 1'b1;
            ef_both_q[{mx_rm, mx_rp}] <= (mx_rdata[1:0] == 2'b11);
            ef_clr_q[{mx_rm, mx_rp}]  <= 1'b1;
          end else if (ef_nz_q[{mx_rm, mx_rp}]) begin
            mbt_q.ef   <= ef_both_q[{mx_rm, mx_rp}] ? 2'd3 : 2'd1;
            mbt_q.ef_v <= own_merr;
            ef_nz_q[{mx_rm, mx_rp}]   <= 1'b0;
            ef_both_q[{mx_rm, mx_rp}] <= 1'b0;
          end
        end
        if ((mx_ro == MoIrqs) && (mx_rresp == AxiOkay) && mx_rdata[2] &&
            ef_clr_q[{mx_rm, mx_rp}]) begin
          mbt_q.ef   <= 2'd2;
          mbt_q.ef_v <= own_merr;
        end
        // WRITE_DATA read: OKAY with 0xFEEDC0DE and no error flag.
        if ((mx_ro == MoWdata) && (mx_rresp == AxiOkay) && (mx_rdata[31:0] == 32'hFEED_C0DE) &&
            (mb_error_i[mx_rm][mx_rp] == 2'b00) && (mx_rp || (mx_rm != 3'd0))) begin
          mbt_q.wo   <= mx_rp;
          mbt_q.wo_v <= own_merr;
        end
      end
      // Past the wrapper extent (inbound aperture of mailbox 7): K5.
      if (xm_ext) begin
        mbt_q.oe   <= si_dir_w;
        mbt_q.oe_v <= own_merr;
        mbt_q.ek   <= {3'd4, 1'b1};
        mbt_q.ek_v <= own_merr;
        mbt_q.er   <= {(si_resp != AxiSlverr), 3'd4};
        mbt_q.er_v <= own_merr;
      end
    end
  end

  // =====================================================================
  // sep_mbox_qualification_cg
  // =====================================================================
  typedef struct packed {
    logic [1:0] ty;
    logic ty_v;   // 0 ISS, 1 NS-only, 2 both-NS
    logic [2:0] tl;
    logic tl_v;   // {type, landed}
    logic [4:0] ac;
    logic ac_v;   // {mismatch, blocked, channel}
    logic       lk;
    logic lk_v;   // 0 old ID admitted, 1 new ID rejected
    logic       iso_v;
    logic [2:0] ba;
    logic ba_v;   // mailbox
    logic       bp_v;
  } mbq_t;

  covergroup sep_mbox_qualification_cg with function sample (mbq_t s);
    option.per_instance = 1;
    option.name = "sep_mbox_qualification_cg";
    cp_type: coverpoint s.ty iff (s.ty_v) {
      bins iss = {2'd0}; bins ns_only = {2'd1}; bins both_ns = {2'd2};
    }
    x_type_landing: coverpoint s.tl iff (s.tl_v) {
      bins iss_landed = {3'b00_1};
      bins iss_blocked = {3'b00_0};
      bins ns_only_landed = {3'b01_1};
      bins ns_only_blocked = {3'b01_0};
      bins both_ns_landed = {3'b10_1};
      ignore_bins both_ns_blocked = {3'b10_0};
    }
    x_admit_ch_line: coverpoint s.ac iff (s.ac_v) {
      bins admitted_line1[] = {[5'd0 : 5'd7]};
      bins blocked_line0[] = {[5'd8 : 5'd15]};
      illegal_bins line_mismatch = {[5'd16 : 5'd31]};
    }
    cp_lock: coverpoint s.lk iff (s.lk_v) {
      bins old_id_admitted = {1'b0}; bins new_id_rejected = {1'b1};
    }
    cp_isolation: coverpoint s.iso_v iff (s.iso_v) {bins others_unchanged = {1'b1};}
    cp_bypass_accept: coverpoint s.ba iff (s.ba_v) {bins mbox[] = {[3'd0 : 3'd7]};}
    cp_bypass_pair: coverpoint s.bp_v iff (s.bp_v) {bins none_then_one = {1'b1};}
  endgroup

  // Entry class of filter entry f over its window.
  function automatic logic [1:0] ent_type(input logic [15:0] en, input logic [15:0] ns,
                                          input logic [15:0][3:0] src, input logic [15:0][55:0] st,
                                          input logic [15:0][55:0] nd, input int f);
    if (src[f] != 4'd0) return 2'd0;
    for (int g = 0; g < 16; g++) begin
      if ((g != f) && en[g] && (src[g] == 4'd0) && (ns[g] != ns[f]) && (st[g] == st[f]) &&
          (nd[g] == nd[f]))
        return 2'd2;
    end
    return 2'd1;
  endfunction
  logic [4:0]      qs_cnt_q;
  logic [2:0]      qs_m_q;
  logic qs_push_q, qs_blk_q, qs_dbg_q, qs_admit_q, qs_okay_q;
  logic [1:0] qs_ty_q;
  logic [3:0] qs_f_q, qs_user_q;
  logic [7:0][3:0] qs_st_q;
  logic [7:0]      qs_vec_q;
  logic [15:0]     lock_try_q;
  logic [7:0]      pre_none_q;
  logic [3:0]      qs_occ_q;
  logic [7:0][3:0] qs_occ_aw_q;
  logic            qs_wv_q;
  mbq_t mbq_q;
  // Entry of the window of an inbound write: the hit entry, or for a write
  // that matches no entry (a foreign source ID or NS value fails the match
  // and the default policy blocks it) the lowest enabled entry whose range
  // covers the address.
  logic [3:0] xm_wf;
  logic       xm_wf_v;
  always_comb begin
    xm_wf   = '0;
    xm_wf_v = 1'b0;
    for (int i = 15; i >= 0; i--) begin
      if (in_f[i].en && f_cov(in_f[i], si_c.addr)) begin
        xm_wf   = 4'(i);
        xm_wf_v = 1'b1;
      end
    end
  end
  // An inbound write to the WRITE_DATA word of an inbound aperture.
  wire [31:0] xm_moff = xm_loc - MbxBase;
  wire        xm_mbw = si_done && si_dir_w && (xm_loc >= MbxBase) &&
      (xm_loc < MbxEnd) && xm_moff[11] && (xm_moff[10:0] == MoWdata);
  always @(posedge clk_i) begin
    mbq_q <= '0;
    if (in_reset) begin
      qs_cnt_q   <= '0;
      qs_push_q  <= 1'b0;
      lock_try_q <= '0;
      pre_none_q <= '0;
    end else begin
      // Snapshot of the other mailboxes at the inbound write request.
      if (si_aw_hs) begin
        qs_push_q <= 1'b0;
        for (int m = 0; m < 8; m++) qs_st_q[m] <= mb_status_i[m][0];
        for (int m = 0; m < 8; m++) qs_occ_aw_q[m] <= occ[m][1];
        qs_vec_q <= vec_i[7:0];
      end else if (|mf_push_i[7:0]) begin
        for (int m = 0; m < 8; m++) if (mf_push_i[m][1]) qs_push_q <= 1'b1;
      end
      // A locked entry takes a FILTER_CONFIG write from the LSU.
      for (int f = 0; f < 16; f++) begin
        if (b_any && (aw_addr_q == (FiltBase + FiltStride * f)) && filt_locked_i[f])
          lock_try_q[f] <= 1'b1;
      end
      if (xm_mbw) begin
        qs_cnt_q   <= 5'(SettleClk);
        qs_m_q     <= xm_moff[14:12];
        qs_blk_q   <= fw_iso_q;
        qs_f_q     <= fw_nwm_q ? xm_wf : fw_hit_q;
        qs_wv_q    <= !fw_nwm_q || xm_wf_v;
        qs_ty_q    <= ent_type(in_f_en_i, in_f_ns_i, in_f_src_i, in_f_start_i, in_f_end_i,
                               int'(fw_nwm_q ? xm_wf : fw_hit_q));
        qs_dbg_q   <= (sep_debug_i === 1'b1);
        qs_user_q  <= si_c.user;
        qs_okay_q  <= (si_resp == AxiOkay);
        qs_occ_q   <= qs_occ_aw_q[xm_moff[14:12]];
      end else if (qs_cnt_q != 5'd0) begin
        qs_cnt_q <= qs_cnt_q - 5'd1;
      end
      // Settled: landing, line and isolation.
      if (qs_cnt_q == 5'd1) begin
        logic landed, none, line;
        landed = qs_push_q && vec_i[qs_m_q];
        none   = !qs_push_q && !vec_i[qs_m_q];
        line   = vec_i[qs_m_q];
        if (qs_wv_q) begin
          mbq_q.ty   <= qs_ty_q;
          mbq_q.ty_v <= own_mfilt;
          if (landed || none) begin
            mbq_q.tl   <= {qs_ty_q, landed};
            mbq_q.tl_v <= own_mfilt;
          end
        end
        mbq_q.ac   <= {(qs_blk_q == line), qs_blk_q, qs_m_q};
        mbq_q.ac_v <= own_mfilt;
        if (qs_wv_q && filt_locked_i[qs_f_q] && lock_try_q[qs_f_q]) begin
          if ((qs_user_q == in_f_src_i[qs_f_q]) && qs_okay_q && qs_push_q) begin
            mbq_q.lk   <= 1'b0;
            mbq_q.lk_v <= own_mfilt;
          end else if ((qs_user_q != in_f_src_i[qs_f_q]) && !qs_okay_q && !qs_push_q) begin
            mbq_q.lk   <= 1'b1;
            mbq_q.lk_v <= own_mfilt;
          end
        end
        if (qs_push_q && !qs_blk_q) begin
          logic same;
          same = 1'b1;
          for (int m = 0; m < 8; m++) begin
            if ((3'(m) != qs_m_q) && ((mb_status_i[m][0] != qs_st_q[m]) ||
                                      (vec_i[m] != qs_vec_q[m])))
              same = 1'b0;
          end
          if (same) mbq_q.iso_v <= own_mfilt;
        end
        // Filter bypass (SEP_DBG): one entry added and the line rises.
        if (qs_dbg_q && qs_push_q && (occ[qs_m_q][1] == (qs_occ_q + 4'd1)) && line) begin
          mbq_q.ba   <= qs_m_q;
          mbq_q.ba_v <= own_mdbg;
          if (pre_none_q[qs_m_q] && (occ[qs_m_q][1] == 4'd1)) mbq_q.bp_v <= own_mdbg;
        end
        if (!qs_dbg_q && !qs_push_q && (occ[qs_m_q][1] == 4'd0)) pre_none_q[qs_m_q] <= 1'b1;
      end
    end
  end

  // =====================================================================
  // sep_cpu_ctrl_timeout_inert_cg
  // =====================================================================
  typedef struct packed {
    logic [4:0] rd;
    logic rd_v;   // {register index, dir}
    logic [2:0] sb;
    logic sb_v;   // stalled block
    logic [3:0] si;
    logic si_v;   // {not inert, block}
    logic       ti;
    logic ti_v;   // 0 TIMEOUT_CLEAR, 1 TIMEOUT_MODE
  } tmo_t;

  covergroup sep_cpu_ctrl_timeout_inert_cg with function sample (tmo_t s);
    option.per_instance = 1;
    option.name = "sep_cpu_ctrl_timeout_inert_cg";
    // Register index: 0 TIMEOUT_INTERRUPT, 1 COUNT_DMA, 2 COUNT_SYS_IN,
    // 3 COUNT_MAILBOX_INBOUND, 4 COUNT_MAILBOX_OUTBOUND, 5 COUNT_ENTROPY_WRITE,
    // 6 COUNT_ENTROPY_READ, 7 COUNT_FILTER_OUT, 8 COUNT_ALIAS_REMAP,
    // 9 ENABLE, 10 CLEAR, 11 MODE.
    x_reg_dir: coverpoint s.rd iff (s.rd_v) {
      bins six_counts[] = {[5'd6 : 5'd17]};
      ignore_bins other_owners = {[5'd0 : 5'd5], [5'd18 : 5'd23]};
    }
    cp_stall_block: coverpoint s.sb iff (s.sb_v) {
      bins system_input = {3'd0};
      bins mailbox_inbound = {3'd1};
      bins mailbox_outbound = {3'd2};
      bins outbound_filter = {3'd3};
      bins alias_remap = {3'd4};
      bins dma = {3'd5};
      bins entropy_write = {3'd6};
      bins entropy_read = {3'd7};
    }
    cp_stall_inert: coverpoint s.si iff (s.si_v) {
      bins inert[] = {[4'd0 : 4'd7]}; illegal_bins timeout_or_vector = {[4'd8 : 4'd15]};
    }
    cp_timeout_write_inert: coverpoint s.ti iff (s.ti_v) {
      bins timeout_clear_write = {1'b0}; bins timeout_mode_write = {1'b1};
    }
  endgroup

  function automatic logic [3:0] to_idx(input logic [31:0] a);
    case (a)
      SEP_CPU_CTRL_TIMEOUT_INTERRUPT_REG_ADDR: return 4'd0;
      SEP_CPU_CTRL_TIMEOUT_COUNT_DMA_REG_ADDR: return 4'd1;
      SEP_CPU_CTRL_TIMEOUT_COUNT_SYS_IN_REG_ADDR: return 4'd2;
      SEP_CPU_CTRL_TIMEOUT_COUNT_MAILBOX_INBOUND_REG_ADDR: return 4'd3;
      SEP_CPU_CTRL_TIMEOUT_COUNT_MAILBOX_OUTBOUND_REG_ADDR: return 4'd4;
      SEP_CPU_CTRL_TIMEOUT_COUNT_ENTROPY_WRITE_REG_ADDR: return 4'd5;
      SEP_CPU_CTRL_TIMEOUT_COUNT_ENTROPY_READ_REG_ADDR: return 4'd6;
      SEP_CPU_CTRL_TIMEOUT_COUNT_FILTER_OUT_REG_ADDR: return 4'd7;
      SEP_CPU_CTRL_TIMEOUT_COUNT_ALIAS_REMAP_REG_ADDR: return 4'd8;
      SEP_CPU_CTRL_TIMEOUT_ENABLE_REG_ADDR: return 4'd9;
      SEP_CPU_CTRL_TIMEOUT_CLEAR_REG_ADDR: return 4'd10;
      SEP_CPU_CTRL_TIMEOUT_MODE_REG_ADDR: return 4'd11;
      default: return 4'd15;
    endcase
  endfunction
  // Count register index of each stalled block.
  function automatic logic [3:0] blk_cnt(input logic [2:0] b);
    case (b)
      3'd0: return 4'd2;
      3'd1: return 4'd3;
      3'd2: return 4'd4;
      3'd3: return 4'd7;
      3'd4: return 4'd8;
      3'd5: return 4'd1;
      3'd6: return 4'd5;
      default: return 4'd6;
    endcase
  endfunction
  localparam logic [31:0] SmuApBase = 32'h8000_0000;
  localparam logic [31:0] SmuApEnd = 32'hC000_0000;
  logic [8:1]  cnt_one_q;
  logic        to_en_q;
  logic [4:0] xs_cnt_q, ls_cnt_q, os_cnt_q;
  logic [3:0]  out_n_q;
  logic        st_pend_q;
  logic [2:0]  st_blk_q;
  logic [42:0] st_base_q;
  tmo_t tmo_q;
  wire  xs_wait = ((in_resp_i.r_valid === 1'b1) && (in_req_i.r_ready !== 1'b1)) ||
      ((in_resp_i.b_valid === 1'b1) && (in_req_i.b_ready !== 1'b1));
  wire  xs_rd = (in_resp_i.r_valid === 1'b1) && (in_req_i.r_ready !== 1'b1);
  wire  ls_wait_r = (lsu_r_valid_i === 1'b1) && (lsu_r_ready_i !== 1'b1);
  wire  ls_wait_b = (lsu_b_valid_i === 1'b1) && (lsu_b_ready_i !== 1'b1);
  wire  out_b_hs = (out_resp_i.b_valid === 1'b1) && (out_req_i.b_ready === 1'b1);
  wire  out_r_end = (out_resp_i.r_valid === 1'b1) && (out_req_i.r_ready === 1'b1) &&
      (out_resp_i.r.last === 1'b1);
  wire [31:0] xs_addr = xs_rd ? si_rd_q.addr[31:0] - sep_base_i[31:0] :
      si_wr_q.addr[31:0] - sep_base_i[31:0];
  wire [31:0] ls_addr = ls_wait_r ? ar_addr_q : aw_addr_q;
  function automatic logic [2:0] stall_ls(input logic [31:0] a, input logic rd);
    if ((a >= MbxBase) && (a < MbxEnd)) return 3'd2;
    if (blk_of(a) == BLK_POOL) return rd ? 3'd7 : 3'd6;
    return 3'd7;
  endfunction
  wire ls_known = ((ls_addr >= MbxBase) && (ls_addr < MbxEnd)) || (blk_of(ls_addr) == BLK_POOL);
  wire [2:0] os_blk = (dma_busy_i === 1'b1) ? 3'd5 :
      (((ls_addr >= SmuApBase) && (ls_addr < SmuApEnd)) ? 3'd3 : 3'd4);
  always @(posedge clk_i) begin
    tmo_q <= '0;
    if (in_reset) begin
      cnt_one_q <= '0;
      to_en_q   <= 1'b0;
      xs_cnt_q  <= '0;
      ls_cnt_q  <= '0;
      os_cnt_q  <= '0;
      out_n_q   <= '0;
      st_pend_q <= 1'b0;
    end else begin
      if (wr_ev && (to_idx(aw_addr_q) != 4'd15)) begin
        tmo_q.rd   <= {to_idx(aw_addr_q), 1'b1};
        tmo_q.rd_v <= own_tmo;
        if ((to_idx(aw_addr_q) >= 4'd1) && (to_idx(aw_addr_q) <= 4'd8))
          cnt_one_q[to_idx(aw_addr_q)] <= (wr_data == 32'h1);
        if (to_idx(aw_addr_q) == 4'd9) to_en_q <= (wr_data == 32'h1);
      end
      if (rd_ev && (to_idx(ar_addr_q) != 4'd15)) begin
        tmo_q.rd   <= {to_idx(ar_addr_q), 1'b0};
        tmo_q.rd_v <= own_tmo;
        // TIMEOUT_INTERRUPT after a stall: 0, and the vector at its baseline.
        if ((to_idx(ar_addr_q) == 4'd0) && st_pend_q) begin
          st_pend_q  <= 1'b0;
          tmo_q.si   <= {(rd_data[0] != 1'b0) || (((vec_i ^ st_base_q) & ~VecIdleMask) != '0),
                         st_blk_q};
          tmo_q.si_v <= own_tmo;
        end
      end
      // Real stalls with the block count at 1 and ENABLE at 1.
      out_n_q <= out_n_q + 4'(out_aw_hs) + 4'(out_ar_hs) - 4'(out_b_hs) - 4'(out_r_end);
      xs_cnt_q <= xs_wait ? ((xs_cnt_q != 5'(StallClk)) ? xs_cnt_q + 5'd1 : xs_cnt_q) : 5'd0;
      ls_cnt_q <= ((ls_wait_r || ls_wait_b) && ls_known) ?
          ((ls_cnt_q != 5'(StallClk)) ? ls_cnt_q + 5'd1 : ls_cnt_q) : 5'd0;
      os_cnt_q <= ((out_resp_hold_i === 1'b1) && (out_n_q != 4'd0)) ?
          ((os_cnt_q != 5'(StallClk)) ? os_cnt_q + 5'd1 : os_cnt_q) : 5'd0;
      if (xs_cnt_q == 5'd1) st_base_q <= vec_i;
      if (ls_cnt_q == 5'd1) st_base_q <= vec_i;
      if (os_cnt_q == 5'd1) st_base_q <= vec_i;
      if (xs_cnt_q == 5'(StallClk - 1)) begin
        logic [2:0] b;
        b = ((xs_addr >= MbxBase) && (xs_addr < MbxEnd)) ? 3'd1 : 3'd0;
        if (to_en_q && cnt_one_q[blk_cnt(b)]) begin
          tmo_q.sb   <= b;
          tmo_q.sb_v <= own_tmo;
          st_pend_q  <= 1'b1;
          st_blk_q   <= b;
        end
      end else if (ls_cnt_q == 5'(StallClk - 1)) begin
        logic [2:0] b;
        b = stall_ls(ls_addr, ls_wait_r);
        if (to_en_q && cnt_one_q[blk_cnt(b)]) begin
          tmo_q.sb   <= b;
          tmo_q.sb_v <= own_tmo;
          st_pend_q  <= 1'b1;
          st_blk_q   <= b;
        end
      end else if (os_cnt_q == 5'(StallClk - 1)) begin
        if (to_en_q && cnt_one_q[blk_cnt(os_blk)]) begin
          tmo_q.sb   <= os_blk;
          tmo_q.sb_v <= own_tmo;
          st_pend_q  <= 1'b1;
          st_blk_q   <= os_blk;
        end
      end
    end
  end

  // =====================================================================
  // sep_mbox_irq_line_cg
  // =====================================================================
  typedef struct packed {
    logic [4:0] gt;
    logic gt_v;   // {mismatch, port, cause, IRQS bit, IRQEN bit}
    logic [1:0] wa;
    logic wa_v;   // {cause, kind}: kind 0 drops, 1 stays
    logic [1:0] el;
    logic el_v;
    logic       li_v;
    logic       qg;
    logic qg_v;   // 0 quiet window with a line high, 1 toggle
  } mil_t;

  covergroup sep_mbox_irq_line_cg with function sample (mil_t s);
    option.per_instance = 1;
    option.name = "sep_mbox_irq_line_cg";
    x_gate: coverpoint s.gt iff (s.gt_v) {
      bins cells[] = {[5'd0 : 5'd15]}; illegal_bins line_mismatch = {[5'd16 : 5'd31]};
    }
    cp_w1c_ack: coverpoint s.wa iff (s.wa_v) {
      bins wtirq_below_drops = {2'b0_0};
      bins wtirq_above_stays = {2'b0_1};
      bins rtirq_below_drops = {2'b1_0};
      bins rtirq_above_stays = {2'b1_1};
    }
    cp_err_line: coverpoint s.el iff (s.el_v) {
      bins empty_read_eirq_masked = {2'd0};
      bins eirq_enable_rises = {2'd1};
      bins flags_read_stays = {2'd2};
      bins eirq_w1c_drops = {2'd3};
    }
    cp_line_iso: coverpoint s.li_v iff (s.li_v) {bins other_lines_own_state = {1'b1};}
    cp_quiet_glitch: coverpoint s.qg iff (s.qg_v) {
      bins quiet_window_line_high = {1'b0}; illegal_bins line_toggle = {1'b1};
    }
  endgroup

  logic [1:0] wa_cnt_q, el_cnt_q;
  logic [2:0] wa_m_q, el_m_q;
  logic wa_p_q, wa_c_q, el_p_q;
  logic [1:0] el_k_q;
  logic       gt_go_q;
  // IRQS and line of every port at the mailbox AW handshake: the state before
  // the write lands.
  logic [7:0][1:0][2:0] el_irqs_aw_q;
  logic [7:0][1:0]      el_irq_aw_q;
  mil_t mil_q;
  always @(posedge clk_i) begin
    mil_q   <= '0;
    gt_go_q <= 1'b0;
    if (mx_aw_hs) begin
      el_irqs_aw_q <= mb_irqs_i;
      el_irq_aw_q  <= mb_irq_i;
    end
    if (in_reset) begin
      wa_cnt_q   <= '0;
      el_cnt_q   <= '0;
      q_beat_q   <= 1'b0;
      q_high_q   <= 1'b0;
      q_prev_v_q <= 1'b0;
      lastk_v_q  <= 1'b0;
    end else begin
      // ---- quiet window bookkeeping ----
      if (q_open) begin
        q_beat_q <= mx_any_hs;
        q_high_q <= 1'b0;
      end else if (quiet_win && mx_any_hs) begin
        q_beat_q <= 1'b1;
      end
      if (quiet_win) begin
        vec_qs   <= vec_i;
        smc_qs   <= smc_irq_i;
        irqs_qs  <= mb_irqs_i;
        irqen_qs <= mb_irqen_i;
        irq_qs   <= mb_irq_i;
        if ((vec_i[7:0] != 8'h0) || (smc_irq_i != 8'h0)) q_high_q <= 1'b1;
        if (quiet_q && !mx_any_hs && !q_beat_q &&
            ((vec_i[7:0] != vec_q[7:0]) || (smc_irq_i != smc_q))) begin
          mil_q.qg   <= 1'b1;
          mil_q.qg_v <= own_mfifo;
        end
      end
      for (int m = 7; m >= 0; m--) begin
        if (mf_push_i[m][1]) begin
          lastk_q   <= 3'(m);
          lastk_v_q <= 1'b1;
        end
      end
      if (q_end) begin
        if (!q_beat_q) begin
          gt_go_q <= 1'b1;
          if (q_high_q) begin
            mil_q.qg   <= 1'b0;
            mil_q.qg_v <= own_mfifo;
          end
          // Line isolation against the previous quiet sample.
          if (q_prev_v_q && ((vec_qs[7:0] & ~vec_pq[7:0]) != 8'h0)) begin
            logic ok;
            ok = ($countones(smc_qs ^ smc_pq) == $countones(pend_out_qs ^ pend_out_pq));
            for (int j = 0; j < 8; j++) begin
              if (!(vec_qs[j] && !vec_pq[j]) && (vec_qs[j] != pend_in_qs[j])) ok = 1'b0;
            end
            if (ok) mil_q.li_v <= own_mfifo;
          end
          vec_pq      <= vec_qs;
          smc_pq      <= smc_qs;
          pend_out_pq <= pend_out_qs;
          q_prev_v_q  <= 1'b1;
          lastk_v_q   <= 1'b0;
        end
      end
      // ---- IRQS write-one-to-clear of wtirq or rtirq (fifo-model leaf) ----
      if (mx_wdone && mx_win && (mx_wo == MoIrqs) && (mx_bresp == AxiOkay) &&
          (mx_wd_q[1:0] != 2'b00) && (mx_wp || (mx_wm != 3'd0))) begin
        wa_cnt_q <= 2'd3;
        wa_m_q   <= mx_wm;
        wa_p_q   <= mx_wp;
        wa_c_q   <= !mx_wd_q[0];
      end else if (wa_cnt_q != 2'd0) begin
        wa_cnt_q <= wa_cnt_q - 2'd1;
      end
      if (wa_cnt_q == 2'd1) begin
        logic above;
        above = wa_c_q ? mb_status_i[wa_m_q][wa_p_q][3] : mb_status_i[wa_m_q][wa_p_q][2];
        if (!above && !mb_irqs_i[wa_m_q][wa_p_q][wa_c_q] && !mb_irq_i[wa_m_q][wa_p_q]) begin
          mil_q.wa   <= {wa_c_q, 1'b0};
          mil_q.wa_v <= own_mfifo;
        end else if (above && mb_irqs_i[wa_m_q][wa_p_q][wa_c_q] && mb_irq_i[wa_m_q][wa_p_q]) begin
          mil_q.wa   <= {wa_c_q, 1'b1};
          mil_q.wa_v <= own_mfifo;
        end
      end
      // ---- eirq line gate (error-inject leaf) ----
      if (mx_rdone && mx_rin && (mx_ro == MoRdata) && (mx_rresp == AxiSlverr) &&
          !mb_irqen_i[mx_rm][mx_rp][2]) begin
        el_cnt_q <= 2'd3;
        el_m_q <= mx_rm;
        el_p_q <= mx_rp;
        el_k_q <= 2'd0;
      end else if (mx_wdone && mx_win && (mx_wo == MoIrqen) && mx_wd_q[2] &&
                   el_irqs_aw_q[mx_wm][mx_wp][2] && !el_irq_aw_q[mx_wm][mx_wp]) begin
        el_cnt_q <= 2'd3;
        el_m_q <= mx_wm;
        el_p_q <= mx_wp;
        el_k_q <= 2'd1;
      end else if (mx_rdone && mx_rin && (mx_ro == MoErr) && mb_irq_i[mx_rm][mx_rp] &&
                   mb_irqs_i[mx_rm][mx_rp][2]) begin
        el_cnt_q <= 2'd3;
        el_m_q <= mx_rm;
        el_p_q <= mx_rp;
        el_k_q <= 2'd2;
      end else if (mx_wdone && mx_win && (mx_wo == MoIrqs) && mx_wd_q[2] &&
                   el_irq_aw_q[mx_wm][mx_wp]) begin
        el_cnt_q <= 2'd3;
        el_m_q <= mx_wm;
        el_p_q <= mx_wp;
        el_k_q <= 2'd3;
      end else if (el_cnt_q != 2'd0) begin
        el_cnt_q <= el_cnt_q - 2'd1;
      end
      if (el_cnt_q == 2'd1) begin
        logic ok;
        case (el_k_q)
          2'd0: ok = mb_irqs_i[el_m_q][el_p_q][2] && !mb_irq_i[el_m_q][el_p_q];
          2'd1: ok = mb_irq_i[el_m_q][el_p_q];
          2'd2: ok = mb_irq_i[el_m_q][el_p_q];
          default: ok = !mb_irq_i[el_m_q][el_p_q];
        endcase
        if (ok) begin
          mil_q.el   <= el_k_q;
          mil_q.el_v <= own_merr;
        end
      end
    end
  end

  // =====================================================================
  // sep_mbox_fifo_model_cg
  // =====================================================================
  typedef struct packed {
    logic [4:0] oo;
    logic oo_v;   // {FIFO, op (1 pop), occupancy class}
    logic [2:0] bm;
    logic bm_v;   // {FIFO, move}: 0 7-8, 1 8-7, 2 1-0, 3 0-1
    logic [3:0] tv;
    logic tv_v;   // {register (1 RIRQT), value class}
    logic [2:0] cl;
    logic cl_v;   // {role (1 read), kind}: 0 >=8, 1 7, 2 0
    logic [1:0] fl;
    logic fl_v;   // {kind (1 rflush), port}
    logic       al_v;
  } mfm_t;

  covergroup sep_mbox_fifo_model_cg with function sample (mfm_t s);
    option.per_instance = 1;
    option.name = "sep_mbox_fifo_model_cg";
    // Occupancy class 0 zero, 1 one, 2 two to six, 3 seven, 4 eight.
    x_occ_op: coverpoint s.oo iff (s.oo_v) {
      bins a_push[] = {[5'd0 : 5'd3]};
      ignore_bins a_push_full = {5'd4};
      ignore_bins a_pop_empty = {5'd8};
      bins a_pop[] = {[5'd9 : 5'd12]};
      bins b_push[] = {[5'd16 : 5'd19]};
      ignore_bins b_push_full = {5'd20};
      ignore_bins b_pop_empty = {5'd24};
      bins b_pop[] = {[5'd25 : 5'd28]};
    }
    cp_boundary_move: coverpoint s.bm iff (s.bm_v) {
      bins a_7_to_8 = {3'd0};
      bins a_8_to_7 = {3'd1};
      bins a_1_to_0 = {3'd2};
      bins a_0_to_1 = {3'd3};
      bins b_7_to_8 = {3'd4};
      bins b_8_to_7 = {3'd5};
      bins b_1_to_0 = {3'd6};
      bins b_0_to_1 = {3'd7};
    }
    // Value class 0 v0, 1 v1, 2 v6, 3 v7, 4 v8, 5 v9, 6 v255, 7 other 8-bit.
    cp_thresh_val: coverpoint s.tv iff (s.tv_v) {
      bins wirqt[] = {[4'd0 : 4'd7]}; bins rirqt[] = {[4'd8 : 4'd15]};
    }
    x_clamp: coverpoint s.cl iff (s.cl_v) {
      bins write_ge8_fires_at_8 = {3'b0_00};
      bins write_7_fires_at_8 = {3'b0_01};
      bins write_0_fires_at_1 = {3'b0_10};
      bins read_ge8_fires_at_8 = {3'b1_00};
      bins read_7_fires_at_8 = {3'b1_01};
      bins read_0_fires_at_1 = {3'b1_10};
    }
    x_flush: coverpoint s.fl iff (s.fl_v) {
      bins wflush_outbound = {2'b0_0};
      bins wflush_inbound = {2'b0_1};
      bins rflush_outbound = {2'b1_0};
      bins rflush_inbound = {2'b1_1};
    }
    x_alias_thresh: coverpoint s.al_v iff (s.al_v) {bins above_bits_differ = {1'b1};}
  endgroup

  function automatic logic [2:0] mocc_cls(input logic [3:0] o);
    if (o == 4'd0) return 3'd0;
    if (o == 4'd1) return 3'd1;
    if (o <= 4'd6) return 3'd2;
    if (o == 4'd7) return 3'd3;
    return 3'd4;
  endfunction
  function automatic logic [2:0] thr_cls(input logic [63:0] v);
    case (v)
      64'd0: return 3'd0;
      64'd1: return 3'd1;
      64'd6: return 3'd2;
      64'd7: return 3'd3;
      64'd8: return 3'd4;
      64'd9: return 3'd5;
      64'd255: return 3'd6;
      default: return 3'd7;
    endcase
  endfunction
  // Per (mailbox, port, role): the written threshold (256 = above 8 bits).
  logic [7:0][1:0][1:0][8:0] thr_q;
  logic [7:0][1:0][1:0]      fl_pend_q;
  logic [7:0]                al_q;
  // Per-index events of this group (several mailboxes may move in one clock).
  logic [7:0][1:0][1:0]      oo_ev_q;   // [m][fifo][op]
  logic [7:0][1:0][1:0][2:0] oo_cls_q;
  logic [7:0][1:0]           bm_ev_q;
  logic [7:0][1:0][1:0]      bm_mv_q;
  logic [7:0][1:0][1:0]      cl_ev_q;   // [m][port][role]
  logic [7:0][1:0][1:0][1:0] cl_k_q;
  logic [7:0][1:0][1:0]      fl_ev_q;   // [m][port][kind]
  logic [7:0][1:0][3:0]      mbs_q;
  mfm_t mfm_q;
  always_ff @(posedge clk_i) mbs_q <= mb_status_i;
  always @(posedge clk_i) begin
    mfm_q   <= '0;
    oo_ev_q <= '0;
    bm_ev_q <= '0;
    cl_ev_q <= '0;
    fl_ev_q <= '0;
    if (in_reset) begin
      thr_q     <= '0;
      fl_pend_q <= '0;
      al_q      <= '0;
    end else begin
      for (int m = 0; m < 8; m++) begin
        for (int f = 0; f < 2; f++) begin
          if (mf_push_i[m][f] && (occ[m][f] != 4'd8)) begin
            oo_ev_q[m][f][0]  <= own_mfifo;
            oo_cls_q[m][f][0] <= mocc_cls(occ[m][f]);
          end
          if (mf_pop_i[m][f] && (occ[m][f] != 4'd0)) begin
            oo_ev_q[m][f][1]  <= own_mfifo;
            oo_cls_q[m][f][1] <= mocc_cls(occ[m][f]);
          end
          if ((occ_q[m][f] == 4'd7) && (occ[m][f] == 4'd8)) begin
            bm_ev_q[m][f] <= own_mfifo;
            bm_mv_q[m][f] <= 2'd0;
          end else if ((occ_q[m][f] == 4'd8) && (occ[m][f] == 4'd7)) begin
            bm_ev_q[m][f] <= own_mfifo;
            bm_mv_q[m][f] <= 2'd1;
          end else if ((occ_q[m][f] == 4'd1) && (occ[m][f] == 4'd0) && !mf_flush_i[m][f]) begin
            bm_ev_q[m][f] <= own_mfifo;
            bm_mv_q[m][f] <= 2'd2;
          end else if ((occ_q[m][f] == 4'd0) && (occ[m][f] == 4'd1)) begin
            bm_ev_q[m][f] <= own_mfifo;
            bm_mv_q[m][f] <= 2'd3;
          end
        end
        // Clamp: role 0 is the write threshold of port p over FIFO p
        // (STATUS bit 2), role 1 the read threshold over FIFO !p (bit 3).
        for (int p = 0; p < 2; p++) begin
          for (int r = 0; r < 2; r++) begin
            int unsigned f;
            logic now, was;
            f   = (r == 0) ? p : (1 - p);
            now = mb_status_i[m][p][2+r];
            was = mbs_q[m][p][2+r];
            if ((occ_q[m][f] == 4'd7) && (occ[m][f] == 4'd8) && now && !was) begin
              if (thr_q[m][p][r] >= 9'd8) begin
                cl_ev_q[m][p][r] <= own_mfifo;
                cl_k_q[m][p][r] <= 2'd0;
              end else if (thr_q[m][p][r] == 9'd7) begin
                cl_ev_q[m][p][r] <= own_mfifo;
                cl_k_q[m][p][r] <= 2'd1;
              end
            end
            if ((occ_q[m][f] == 4'd0) && (occ[m][f] == 4'd1) && now && !was &&
                (thr_q[m][p][r] == 9'd0)) begin
              cl_ev_q[m][p][r] <= own_mfifo;
              cl_k_q[m][p][r] <= 2'd2;
            end
          end
        end
        // Both above bits of FIFO A differ while the two thresholds differ.
        al_q[m] <= (mb_status_i[m][0][2] != mb_status_i[m][1][3]) &&
            (mb_wirqt_i[m][0] != mb_rirqt_i[m][1]);
        if ((mb_status_i[m][0][2] != mb_status_i[m][1][3]) &&
            (mb_wirqt_i[m][0] != mb_rirqt_i[m][1]) && !al_q[m])
          mfm_q.al_v <= own_mfifo;
      end
      // Threshold writes.
      if (mx_wdone && mx_win && (mx_bresp == AxiOkay) &&
          ((mx_wo == MoWirqt) || (mx_wo == MoRirqt))) begin
        logic       r;
        logic [2:0] c;
        r = (mx_wo == MoRirqt);
        c = thr_cls(mx_wd_q);
        thr_q[mx_wm][mx_wp][r] <= (mx_wd_q[63:8] == '0) ? {1'b0, mx_wd_q[7:0]} : 9'd256;
        if ((mx_wd_q[63:8] == '0) &&
            ((mx_wm != 3'd0) || mx_wp || (c == 3'd0) || (c == 3'd3) || (c == 3'd4) ||
             (c == 3'd5) || (c == 3'd6))) begin
          mfm_q.tv   <= {r, c};
          mfm_q.tv_v <= own_mfifo;
        end
      end
      // Flush: CTRL write with the flushed FIFO non-empty at the request,
      // then a CTRL read of 0 on the same port.
      if (mx_wdone && mx_win && (mx_wo == MoCtrl) && (mx_bresp == AxiOkay)) begin
        if (mx_wd_q[0] && (occ_aw_q[mx_wm][mx_wp] != 4'd0) && (mx_wp || (mx_wm != 3'd0)))
          fl_pend_q[mx_wm][mx_wp][0] <= 1'b1;
        if (mx_wd_q[1] && (occ_aw_q[mx_wm][!mx_wp] != 4'd0)) fl_pend_q[mx_wm][mx_wp][1] <= 1'b1;
      end
      if (mx_rdone && mx_rin && (mx_ro == MoCtrl) && (mx_rresp == AxiOkay) &&
          (mx_rdata[1:0] == 2'b00)) begin
        fl_ev_q[mx_rm][mx_rp]   <= fl_pend_q[mx_rm][mx_rp] & {2{own_mfifo}};
        fl_pend_q[mx_rm][mx_rp] <= '0;
      end
    end
  end

  // =====================================================================
  // sep_mbox_reset_cg
  // =====================================================================
  typedef struct packed {
    logic [3:0] oo;
    logic oo_v;   // {op, offset class}: op 0 push 1 pop 2 IRQS write
    logic [7:0] pn;
    logic pn_v;   // {vacuous, flags}
    logic [4:0] ps;
    logic ps_v;   // {X, mailbox, port}
    logic       ll_v;
    logic       fr;
    logic fr_v;   // 0 before reset non-zero, 1 after reset 0
    logic       ru_v;
  } mrs_t;

  covergroup sep_mbox_reset_cg with function sample (mrs_t s);
    option.per_instance = 1;
    option.name = "sep_mbox_reset_cg";
    x_op_offset: coverpoint s.oo iff (s.oo_v) {
      bins push_0_7 = {4'b00_00};
      bins push_8_31 = {4'b00_01};
      bins push_32_64 = {4'b00_10};
      bins pop_0_7 = {4'b01_00};
      bins pop_8_31 = {4'b01_01};
      bins pop_32_64 = {4'b01_10};
      bins irqs_write_0_7 = {4'b10_00};
      bins irqs_write_8_31 = {4'b10_01};
      bins irqs_write_32_64 = {4'b10_10};
    }
    cp_pre_nonzero: coverpoint s.pn iff (s.pn_v) {
      wildcard bins status_not_empty_all = {8'b0??????1};
      wildcard bins threshold_nonzero = {8'b0?????1?};
      wildcard bins irqen_nonzero = {8'b0????1??};
      wildcard bins irqs0_outbound_all = {8'b0???1???};
      wildcard bins error_flag_set = {8'b0??1????};
      wildcard bins inbound_line_high = {8'b0?1?????};
      wildcard bins outbound_line_high = {8'b01??????};
      wildcard illegal_bins vacuous_reset = {8'b1???????};
    }
    cp_post_state: coverpoint s.ps iff (s.ps_v) {
      bins aperture[] = {[5'd0 : 5'd15]}; illegal_bins x = {[5'd16 : 5'd31]};
    }
    cp_lines_low: coverpoint s.ll_v iff (s.ll_v) {bins all_low = {1'b1};}
    cp_filter_restore: coverpoint s.fr iff (s.fr_v) {
      bins before_nonzero = {1'b0}; bins after_zero = {1'b1};
    }
    cp_reuse: coverpoint s.ru_v iff (s.ru_v) {bins push_and_pop = {1'b1};}
  endgroup

  // Pre-state flags of the mailbox unit (cp_pre_nonzero).
  logic [6:0] pre_flags;
  always_comb begin
    logic all_ne, thr_nz, en_nz, irqs0_all, err_nz;
    all_ne    = 1'b1;
    thr_nz    = 1'b0;
    en_nz     = 1'b0;
    irqs0_all = 1'b1;
    err_nz    = 1'b0;
    for (int m = 0; m < 8; m++) begin
      for (int p = 0; p < 2; p++) begin
        if (mb_status_i[m][p][0]) all_ne = 1'b0;
        if ((mb_wirqt_i[m][p] != 8'd0) || (mb_rirqt_i[m][p] != 8'd0)) thr_nz = 1'b1;
        if (mb_irqen_i[m][p] != 3'd0) en_nz = 1'b1;
        if (mb_error_i[m][p] != 2'd0) err_nz = 1'b1;
      end
      if (!mb_irqs_i[m][0][0]) irqs0_all = 1'b0;
    end
    pre_flags = {
      (smc_irq_i != 8'h0), (vec_i[7:0] != 8'h0), err_nz, irqs0_all, en_nz, thr_nz, all_ne
    };
  end
  logic        rs_on_q;
  logic [1:0]  rs_op_q;
  logic [6:0]  rs_cnt_q;
  logic [6:0]  rs_flags_q;
  logic [15:0] ps_pend_q;
  logic [2:0]  ll_cnt_q;
  logic fr_v_q, ru_push_q, ru_done_q;
  logic [3:0]  fr_f_q;
  mrs_t mrs_q;
  logic [15:0][3:0] fr_src_q;
  logic             rs_pw_q;
  logic [1:0]       rs_pw_op_q;
  // The in-flight operation at the LSU: a request handshake (the later of AW
  // and W for a write) to a mailbox WRITE_DATA, IRQS or READ_DATA word with
  // no response handshake yet. The mailbox unit bus has registered stages
  // between it and the LSU, so its own response can complete while the LSU
  // response is still held.
  wire [31:0] rs_awr = mx_off(lsu_aw_addr_i);
  wire [31:0] rs_arr = mx_off(lsu_ar_addr_i);
  always @(posedge clk_i) begin
    mrs_q <= '0;
    // The filter source IDs reset asynchronously with sep_reset_n, so the
    // value before the reset is the copy of the last clock with it high.
    if (sep_reset_n_i === 1'b1) fr_src_q <= in_f_src_i;
    // Operation tracker: a request handshake with no response yet.
    if (sep_reset_n_i === 1'b1) begin
      if (aw_hs && (rs_awr < AXIL_MAILBOX_REG_MAP_SIZE) &&
          ((rs_awr[10:0] == MoWdata) || (rs_awr[10:0] == MoIrqs))) begin
        if (w_hs || (w_beats_q != 2'd0)) begin
          rs_on_q    <= 1'b1;
          rs_op_q    <= (rs_awr[10:0] == MoWdata) ? 2'd0 : 2'd2;
          rs_cnt_q   <= '0;
          rs_flags_q <= pre_flags;
        end else begin
          rs_on_q    <= 1'b0;
          rs_pw_q    <= 1'b1;
          rs_pw_op_q <= (rs_awr[10:0] == MoWdata) ? 2'd0 : 2'd2;
          rs_flags_q <= pre_flags;
        end
      end else if (rs_pw_q && w_hs) begin
        rs_pw_q  <= 1'b0;
        rs_on_q  <= 1'b1;
        rs_op_q  <= rs_pw_op_q;
        rs_cnt_q <= '0;
      end else if (ar_hs && (rs_arr < AXIL_MAILBOX_REG_MAP_SIZE) && (rs_arr[10:0] == MoRdata)) begin
        rs_on_q    <= 1'b1;
        rs_op_q    <= 2'd1;
        rs_cnt_q   <= '0;
        rs_flags_q <= pre_flags;
      end else if (rs_on_q) begin
        if ((rs_op_q == 2'd1) ? r_hs : b_hs) rs_on_q <= 1'b0;
        else if (rs_cnt_q != 7'd127) rs_cnt_q <= rs_cnt_q + 7'd1;
      end
    end
    // Falling edge of sep_reset_n inside the window.
    if (sep_rst_fall) begin
      rs_on_q <= 1'b0;
      rs_pw_q <= 1'b0;
      if (rs_on_q && (rs_cnt_q <= 7'd64)) begin
        mrs_q.oo   <= {rs_op_q, (rs_cnt_q <= 7'd7) ? 2'd0 : ((rs_cnt_q <= 7'd31) ? 2'd1 : 2'd2)};
        mrs_q.oo_v <= own_mrst;
        mrs_q.pn   <= {!(&rs_flags_q[3:0]) || !rs_flags_q[5] || !rs_flags_q[6], rs_flags_q};
        mrs_q.pn_v <= own_mrst;
      end
      fr_v_q <= 1'b0;
      for (int f = 15; f >= 0; f--) begin
        if (fr_src_q[f] == 4'd5) begin
          fr_v_q <= 1'b1;
          fr_f_q <= 4'(f);
          mrs_q.fr   <= 1'b0;
          mrs_q.fr_v <= own_mrst;
        end
      end
    end
    // After the release.
    if (sep_rst_rise) begin
      ps_pend_q <= '1;
      ll_cnt_q  <= 3'd4;
      ru_push_q <= 1'b0;
      ru_done_q <= 1'b0;
    end else begin
      if (ll_cnt_q != 3'd0) ll_cnt_q <= ll_cnt_q - 3'd1;
      if ((ll_cnt_q == 3'd1) && (vec_i[7:0] == 8'h0) && (smc_irq_i == 8'h0)) mrs_q.ll_v <= own_mrst;
      if ((ll_cnt_q == 3'd1) && fr_v_q && (in_f_src_i[fr_f_q] == 4'd0)) begin
        fr_v_q     <= 1'b0;
        mrs_q.fr   <= 1'b1;
        mrs_q.fr_v <= own_mrst;
      end
      if (mx_rdone && mx_rin && ps_pend_q[{mx_rm, mx_rp}]) begin
        logic x, ok;
        x  = $isunknown({mb_status_i[mx_rm][mx_rp], mb_irqs_i[mx_rm][mx_rp],
                         mb_irqen_i[mx_rm][mx_rp], mb_wirqt_i[mx_rm][mx_rp],
                         mb_rirqt_i[mx_rm][mx_rp], mb_error_i[mx_rm][mx_rp]});
        ok = (mb_status_i[mx_rm][mx_rp] == 4'b0001) && (mb_irqs_i[mx_rm][mx_rp] == 3'd0) &&
            (mb_irqen_i[mx_rm][mx_rp] == 3'd0) && (mb_wirqt_i[mx_rm][mx_rp] == 8'd0) &&
            (mb_rirqt_i[mx_rm][mx_rp] == 8'd0) && (mb_error_i[mx_rm][mx_rp] == 2'd0);
        ps_pend_q[{mx_rm, mx_rp}] <= 1'b0;
        if (x || ok) begin
          mrs_q.ps   <= {x, mx_rm, mx_rp};
          mrs_q.ps_v <= own_mrst;
        end
      end
      if (|mf_push_i) ru_push_q <= 1'b1;
      if (ru_push_q && (|mf_pop_i) && !ru_done_q) begin
        ru_done_q  <= 1'b1;
        mrs_q.ru_v <= own_mrst;
      end
    end
  end

  // =====================================================================
  // sep_pic_alert_cg
  // =====================================================================
  typedef struct packed {
    logic [3:0] ka;
    logic ka_v;   // receiver index
    logic       pr_v;
    logic [2:0] na;
    logic na_v;   // 0 HMAC err, 1 KMAC err, 2 CSRNG fatal, 3 EDN fatal, 4 OTBN done
    logic       ai_v;
  } pal_t;

  covergroup sep_pic_alert_cg with function sample (pal_t s);
    option.per_instance = 1;
    option.name = "sep_pic_alert_cg";
    // Receiver index of crypto_alert_pulse: HMAC [0], OTBN [2:1], AES [4:3],
    // KMAC [6:5], CSRNG [8:7], EDN [10:9].
    x_alert_kind_agg: coverpoint s.ka iff (s.ka_v) {
      bins hmac_idx0 = {4'd0};
      bins otbn_idx1 = {4'd1};
      bins otbn_idx2 = {4'd2};
      bins aes_idx3 = {4'd3};
      bins aes_idx4 = {4'd4};
      bins kmac_idx5 = {4'd5};
      bins kmac_idx6 = {4'd6};
      bins csrng_idx7 = {4'd7};
      bins csrng_idx8 = {4'd8};
      bins edn_idx9 = {4'd9};
      bins edn_idx10 = {4'd10};
    }
    cp_alert_pair: coverpoint s.pr_v iff (s.pr_v) {bins two_blocks = {1'b1};}
    cp_alert_native: coverpoint s.na iff (s.na_v) {
      bins hmac_err_src20 = {3'd0};
      bins kmac_err_src23 = {3'd1};
      bins csrng_fatal_src27 = {3'd2};
      bins edn_fatal_src29 = {3'd3};
      bins otbn_done_src30 = {3'd4};
    }
    cp_alert_idle: coverpoint s.ai_v iff (s.ai_v) {bins no_source33 = {1'b1};}
  endgroup

  function automatic logic [2:0] alert_blk(input int unsigned k);
    if (k == 0) return 3'd0;
    if (k <= 2) return 3'd1;
    if (k <= 4) return 3'd2;
    if (k <= 6) return 3'd3;
    if (k <= 8) return 3'd4;
    return 3'd5;
  endfunction
  function automatic logic [10:0] alert_rng(input logic [2:0] b);
    case (b)
      3'd0: return 11'b000_0000_0001;
      3'd1: return 11'b000_0000_0110;
      3'd2: return 11'b000_0001_1000;
      3'd3: return 11'b000_0110_0000;
      3'd4: return 11'b001_1000_0000;
      default: return 11'b110_0000_0000;
    endcase
  endfunction
  // Vector bit of each native negative.
  localparam int unsigned NatBit[5] = '{19, 22, 26, 28, 29};
  logic ka_on_q, pr_on_q, na_on_q;
  logic [3:0] ka_k_q;
  logic [2:0] pr_b_q, na_k_q;
  logic [6:0] ka_cnt_q;
  logic [8:0] pr_cnt_q;
  logic [8:0] na_cnt_q;
  logic ai_h_q, ai_k_q, ai_o_q;
  pal_t pal_q;
  always_ff @(posedge clk_i) begin
    pal_q <= '0;
    if (in_reset) begin
      ka_on_q <= 1'b0;
      pr_on_q <= 1'b0;
      na_on_q <= 1'b0;
      ai_h_q  <= 1'b0;
      ai_k_q  <= 1'b0;
      ai_o_q  <= 1'b0;
    end else begin
      // Alert kind: one receiver index of its block pulses, with source 33
      // high in the same clock (VEC[32] is combinational on the pulse) or
      // within AlertWin clocks after it.
      for (int k = 10; k >= 0; k--) begin
        if (alert_pulse_i[k] && ((alert_pulse_i & alert_rng(alert_blk(k))) == (11'd1 << k))) begin
          if (vec_i[32] === 1'b1) begin
            ka_on_q    <= 1'b0;
            pal_q.ka   <= 4'(k);
            pal_q.ka_v <= own_pwalk;
          end else begin
            ka_on_q  <= 1'b1;
            ka_k_q   <= 4'(k);
            ka_cnt_q <= '0;
          end
        end
      end
      if (ka_on_q && (alert_pulse_i == '0)) begin
        if (vec_i[32]) begin
          ka_on_q    <= 1'b0;
          pal_q.ka   <= ka_k_q;
          pal_q.ka_v <= own_pwalk;
        end else if (ka_cnt_q == 7'(AlertWin)) begin
          ka_on_q <= 1'b0;
        end else begin
          ka_cnt_q <= ka_cnt_q + 7'd1;
        end
      end
      // Pair: pulses of two blocks within PairWin clocks. PairWin covers the
      // drawn alert gap (0 to 64 clocks) plus the firmware store path.
      if (alert_pulse_i != '0) begin
        for (int k = 0; k < 11; k++) begin
          if (alert_pulse_i[k]) begin
            if (pr_on_q && (alert_blk(k) != pr_b_q)) begin
              pal_q.pr_v <= own_pwalk;
            end
            pr_on_q  <= 1'b1;
            pr_b_q   <= alert_blk(k);
            pr_cnt_q <= '0;
          end
        end
      end else if (pr_on_q) begin
        if (pr_cnt_q == 9'(PairWin)) pr_on_q <= 1'b0;
        else pr_cnt_q <= pr_cnt_q + 9'd1;
      end
      // Native negative: source 33 stays low for NativeWin clocks.
      for (int n = 4; n >= 0; n--) begin
        if (vec_rise[NatBit[n]] && !na_on_q) begin
          na_on_q  <= 1'b1;
          na_k_q   <= 3'(n);
          na_cnt_q <= '0;
        end
      end
      if (na_on_q) begin
        if (vec_i[32]) begin
          na_on_q <= 1'b0;
        end else if (na_cnt_q == 9'(NativeWin)) begin
          na_on_q    <= 1'b0;
          pal_q.na   <= na_k_q;
          pal_q.na_v <= own_pwalk;
        end else begin
          na_cnt_q <= na_cnt_q + 9'd1;
        end
      end
      // Idle engines: HMAC, KMAC and OTBN done each rise with source 33 low.
      if (vec_i[32] || !own_pwalk) begin
        ai_h_q <= 1'b0;
        ai_k_q <= 1'b0;
        ai_o_q <= 1'b0;
      end else begin
        if (vec_rise[17]) ai_h_q <= 1'b1;
        if (vec_rise[20]) ai_k_q <= 1'b1;
        if (vec_rise[29]) ai_o_q <= 1'b1;
        if (ai_h_q && ai_k_q && ai_o_q) begin
          ai_h_q     <= 1'b0;
          ai_k_q     <= 1'b0;
          ai_o_q     <= 1'b0;
          pal_q.ai_v <= own_pwalk;
        end
      end
    end
  end

  // =====================================================================
  // Mailbox, IRQ and PIC sampling.
  // =====================================================================
  sep_pic_reg_map_cg            u_sep_pic_reg_map_cg            = new();
  sep_pic_source_map_cg         u_sep_pic_source_map_cg         = new();
  sep_pic_enable_priority_cg    u_sep_pic_enable_priority_cg    = new();
  sep_pic_gateway_cg            u_sep_pic_gateway_cg            = new();
  sep_pic_delivery_cg           u_sep_pic_delivery_cg           = new();
  sep_pic_no_delivery_cg        u_sep_pic_no_delivery_cg        = new();
  sep_pic_fabric_isolation_cg   u_sep_pic_fabric_isolation_cg   = new();
  sep_cpu_nonpic_irq_cg         u_sep_cpu_nonpic_irq_cg         = new();
  sep_nmi_vector_cfg_cg         u_sep_nmi_vector_cfg_cg         = new();
  sep_nmi_concurrency_cg        u_sep_nmi_concurrency_cg        = new();
  sep_fault_source_report_cg    u_sep_fault_source_report_cg    = new();
  sep_fault_source_ack_cg       u_sep_fault_source_ack_cg       = new();
  sep_mbox_transfer_cg          u_sep_mbox_transfer_cg          = new();
  sep_mbox_qualification_cg     u_sep_mbox_qualification_cg     = new();
  sep_cpu_ctrl_timeout_inert_cg u_sep_cpu_ctrl_timeout_inert_cg = new();
  sep_mbox_irq_line_cg          u_sep_mbox_irq_line_cg          = new();
  sep_mbox_fifo_model_cg        u_sep_mbox_fifo_model_cg        = new();
  sep_mbox_reset_cg             u_sep_mbox_reset_cg             = new();
  sep_pic_alert_cg              u_sep_pic_alert_cg              = new();
  sep_dma_host_fault_cg         u_sep_dma_host_fault_cg         = new();

  always @(posedge clk_i) begin
    // The reset points of sep_mbox_reset_cg sample while rst_ni is low.
    if (mrs_q != '0) u_sep_mbox_reset_cg.sample(mrs_q);
    if (!in_reset) begin
      if (prm_r_q != '0) u_sep_pic_reg_map_cg.sample(prm_r_q);
      if (prm_w_q != '0) u_sep_pic_reg_map_cg.sample(prm_w_q);
      if (psm_q != '0) u_sep_pic_source_map_cg.sample(psm_q);
      if (pep_q != '0) u_sep_pic_enable_priority_cg.sample(pep_q);
      if (pgw_q != '0) u_sep_pic_gateway_cg.sample(pgw_q);
      if (pdl_q != '0) u_sep_pic_delivery_cg.sample(pdl_q);
      if (pnd_q != '0) u_sep_pic_no_delivery_cg.sample(pnd_q);
      if (pfi_q != '0) u_sep_pic_fabric_isolation_cg.sample(pfi_q);
      if (pnp_q != '0) u_sep_cpu_nonpic_irq_cg.sample(pnp_q);
      if (nvc_q != '0) u_sep_nmi_vector_cfg_cg.sample(nvc_q);
      if (ncc_q != '0) u_sep_nmi_concurrency_cg.sample(ncc_q);
      if (fsr_q != '0) u_sep_fault_source_report_cg.sample(fsr_q);
      if (fsa_q != '0) u_sep_fault_source_ack_cg.sample(fsa_q);
      for (int c = 0; c < 21; c++) begin
        if (cm_q[c]) begin
          fsa_t e;
          e      = '0;
          e.cm   = 5'(c);
          e.cm_v = 1'b1;
          u_sep_fault_source_ack_cg.sample(e);
        end
      end
      if (dhf_q != '0) u_sep_dma_host_fault_cg.sample(dhf_q);
      if (mbt_q != '0) u_sep_mbox_transfer_cg.sample(mbt_q);
      // x_in_attr: written inbound channel k against every line j.
      if (ia_go_q) begin
        for (int j = 0; j < 8; j++) begin
          logic bad;
          bad = (ia_line_q[j] != ia_exp_q[j]);
          if (bad || !((3'(j) == ia_k_q) && !ia_exp_q[j])) begin
            mbt_t e;
            e      = '0;
            e.ia   = {bad, ia_k_q, 3'(j)};
            e.ia_v = own_mfifo;
            u_sep_mbox_transfer_cg.sample(e);
          end
        end
      end
      if (mbq_q != '0) u_sep_mbox_qualification_cg.sample(mbq_q);
      if (tmo_q != '0) u_sep_cpu_ctrl_timeout_inert_cg.sample(tmo_q);
      if (mil_q != '0) u_sep_mbox_irq_line_cg.sample(mil_q);
      // x_gate: every port line after the quiet window (outbound mailbox 0
      // is graded by the open mailbox tests and not counted here).
      if (gt_go_q) begin
        for (int m = 0; m < 8; m++) begin
          for (int p = 0; p < 2; p++) begin
            for (int c = 0; c < 2; c++) begin
              if ((m != 0) || (p != 0)) begin
                mil_t e;
                e      = '0;
                e.gt   = {(irq_qs[m][p] != |(irqs_qs[m][p] & irqen_qs[m][p])), 1'(p), 1'(c),
                          irqs_qs[m][p][c], irqen_qs[m][p][c]};
                e.gt_v = own_mfifo;
                u_sep_mbox_irq_line_cg.sample(e);
              end
            end
          end
        end
      end
      if (mfm_q != '0) u_sep_mbox_fifo_model_cg.sample(mfm_q);
      for (int m = 0; m < 8; m++) begin
        for (int f = 0; f < 2; f++) begin
          for (int o = 0; o < 2; o++) begin
            if (oo_ev_q[m][f][o]) begin
              mfm_t e;
              e      = '0;
              e.oo   = {1'(f), 1'(o), oo_cls_q[m][f][o]};
              e.oo_v = 1'b1;
              u_sep_mbox_fifo_model_cg.sample(e);
            end
          end
          if (bm_ev_q[m][f]) begin
            mfm_t e;
            e      = '0;
            e.bm   = {1'(f), bm_mv_q[m][f]};
            e.bm_v = 1'b1;
            u_sep_mbox_fifo_model_cg.sample(e);
          end
        end
        for (int p = 0; p < 2; p++) begin
          for (int r = 0; r < 2; r++) begin
            if (cl_ev_q[m][p][r]) begin
              mfm_t e;
              e      = '0;
              e.cl   = {1'(r), cl_k_q[m][p][r]};
              e.cl_v = 1'b1;
              u_sep_mbox_fifo_model_cg.sample(e);
            end
            if (fl_ev_q[m][p][r]) begin
              mfm_t e;
              e      = '0;
              e.fl   = {1'(r), 1'(p)};
              e.fl_v = 1'b1;
              u_sep_mbox_fifo_model_cg.sample(e);
            end
          end
        end
      end
      if (pal_q != '0) u_sep_pic_alert_cg.sample(pal_q);
    end
  end

  // =====================================================================
  // Memory, boot, reset, WDT and clock groups (docs/SEP_FCOV.adoc, memory,
  // boot, reset, WDT and clock groups). Every point samples only while
  // graded_owner holds the code of a test that owns the point or the cell.
  // The reset-edge and sub-cycle points sample in blocks that the in_reset
  // gate does not hold off. The tolerances, settle times, bands and timeouts
  // below are choices of the environment; the specification gives none.
  // =====================================================================
  wire mr_own_rel = (graded_owner == FcovOwnSepBootReleaseTermsTest);
  wire mr_own_cold = (graded_owner == FcovOwnSepColdResetPhaseTest);
  wire mr_own_ret = (graded_owner == FcovOwnSepCpuResetRetentionTest);
  wire mr_own_swiso = (graded_owner == FcovOwnSepSwResetIsolationMatrixTest);
  wire mr_own_ovr = (graded_owner == FcovOwnSepIpResetOverrideMatrixTest);
  wire mr_own_scan = (graded_owner == FcovOwnSepScanResetOverrideTest);
  wire mr_own_entry = (graded_owner == FcovOwnSepCpuResetEntryTest);
  wire mr_own_stm = (graded_owner == FcovOwnSepSecureTmStrapSamplingTest);
  wire mr_own_ccreg = (graded_owner == FcovOwnSepCpuCtrlRegShapeTest);
  wire mr_own_tmr = (graded_owner == FcovOwnSepTimerClockContractTest);

  localparam realtime MrEdgeTol = 1.0;  // 1 ps with `timescale 1ps/1fs
  localparam int unsigned MrHeldK = 401;  // cp_release_order K, from 401 to 514
  localparam int unsigned MrSmcSettle = 8;  // smc_fuse_sense_done_i stable cycles
  localparam int unsigned MrClkRecent = 64;  // exception clock toggled within
  localparam int unsigned MrScanMinW = 4;  // scan_rst_ni low width
  localparam int unsigned MrMpcAllow = 4;  // two-flop latency 2 plus 2
  localparam int unsigned MrIsoAllow = 16;  // isolate-complete fall vs reset rise
  localparam int unsigned MrSeqTimeout = 4096;  // SW_RESET_N assert sequence
  localparam int unsigned MrPulseBand = 64;  // cp_pulse_vs_sequence band
  localparam int unsigned MrOvrdSettle = 8;  // override settle (at least 3)
  localparam int unsigned MrSwSettle = 256;  // sequenced software reset settle
  localparam int unsigned MrRelSettle = 4;  // cycles after a CPU-only release
  localparam int unsigned MrWdtGap = 64;  // clk_wdt_i ticks between count reads
  localparam int unsigned MrStmCapWin = 3;  // early capture edges after release
  localparam int unsigned MrStmSenseWin = 8;  // cycles after the sense-done rise
  localparam int unsigned MrStmHold = 64;  // hold after a strap change
  localparam int unsigned MrStmSettle = 8;  // hold after a non-sampling event
  localparam int unsigned MrTeSettle = 2;  // test_en_i to consumer pins

  localparam logic [31:0] MrSwRst = SEP_RESET_CTRL_SW_RESET_N_REG_ADDR;
  localparam logic [31:0] MrRefCnt = SEP_CPU_CTRL_REFERENCE_COUNTER_REG_ADDR;
  localparam logic [31:0] MrVerId = SEP_CPU_CTRL_SEP_VERSION_ID_REG_ADDR;
  localparam logic [31:0] MrNmiVec = SEP_CPU_CTRL_SEP_NMI_VEC_REG_ADDR;
  localparam logic [31:0] MrNmiLock = SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_REG_ADDR;
  localparam logic [31:0] MrSepSense = SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_REG_ADDR;
  localparam logic [31:0] MrSmcSense = SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_REG_ADDR;
  localparam logic [31:0] MrTmoClear = SEP_CPU_CTRL_TIMEOUT_CLEAR_REG_ADDR;
  localparam logic [31:0] MrTmoMode = SEP_CPU_CTRL_TIMEOUT_MODE_REG_ADDR;
  localparam logic [31:0] MrWkCtrl = WDT_TIMER_WKUP_CTRL_REG_ADDR;
  localparam logic [31:0] MrWkThHi = WDT_TIMER_WKUP_THOLD_HI_REG_ADDR;
  localparam logic [31:0] MrWkThLo = WDT_TIMER_WKUP_THOLD_LO_REG_ADDR;
  localparam logic [31:0] MrWkCntLo = WDT_TIMER_WKUP_COUNT_LO_REG_ADDR;
  localparam logic [31:0] MrWdRegwen = WDT_TIMER_WDOG_REGWEN_REG_ADDR;
  localparam logic [31:0] MrWdCtrl = WDT_TIMER_WDOG_CTRL_REG_ADDR;
  localparam logic [31:0] MrWdBark = WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR;
  localparam logic [31:0] MrWdBite = WDT_TIMER_WDOG_BITE_THOLD_REG_ADDR;
  localparam logic [31:0] MrWdCount = WDT_TIMER_WDOG_COUNT_REG_ADDR;
  localparam logic [31:0] MrWdIntrState = WDT_TIMER_INTR_STATE_REG_ADDR;
  localparam logic [31:0] MrWdIntrTest = WDT_TIMER_INTR_TEST_REG_ADDR;
  localparam logic [31:0] MrTrngLo = TRNG_APERTURE_MEM_BASE_ADDR;
  localparam logic [31:0] MrTrngHi = TRNG_APERTURE_MEM_BASE_ADDR + TRNG_APERTURE_MEM_SIZE;
  localparam logic [31:0] MrPoolStatus = ENTROPY_POOL_STATUS_REG_ADDR;
  // Isolated-window read data (hw/sys/sep/doc/reset_controller.adoc,
  // Isolation and Reset Sequencing, step 2) and the SEP_VERSION_ID reset value
  // (regs/blocks/sep_cpu_ctrl.adoc).
  localparam logic [31:0] MrIsoData = 32'h1501_A7ED;
  localparam logic [31:0] MrVerVal = 32'(SEP_CPU_CTRL_SEP_VERSION_ID_REG_DEFAULT);
  localparam logic [6:0] MrSwRstDef = 7'(SEP_RESET_CTRL_SW_RESET_N_REG_DEFAULT);
  localparam logic [30:0] MrRomVec = BootRomBase[31:1];
  // aon_timer fields (aon_timer.hjson): WKUP_CTRL enable[0] prescaler[12:1],
  // WDOG_CTRL enable[0], WDOG_REGWEN regwen[0], INTR_STATE and INTR_TEST
  // wkup_timer_expired[0] wdog_timer_bark[1].
  localparam int unsigned MrWdBarkBit = 1;
  // Reset-vector TDR (doc/cpu.adoc, Reset Vector): IR 0x18 and a 32-bit shift
  // path from jtag_tdi_i to jtag_tdo_o.
  localparam logic [4:0] MrIrRstVec = 5'h18;
  localparam int unsigned MrTdrLen = 32;

  // Isolate stages in the VPLAN bench index of the tb_top isolate taps: 0
  // host_otbn, 1 host_aes, 2 host_hmac, 3 host_kmac, 4 host_abr, 5
  // trng_entropy_source, 6 trng_csrng, 7 trng_edn, 8 km_otbn, 9 km_aes, 10
  // km_hmac, 11 km_kmac, 12 km_abr, 13 km_efuse. Table sets of
  // reset_controller.adoc.
  localparam logic [13:0] MrSetKm = 14'b11_1111_0000_0000;
  localparam logic [13:0] MrSetOtbn = 14'b00_0001_0000_0001;
  localparam logic [13:0] MrSetAes = 14'b00_0010_0000_0010;
  localparam logic [13:0] MrSetKmac = 14'b00_1000_0000_1000;
  localparam logic [13:0] MrSetTrng = 14'b00_0000_1110_0000;
  // Host-path bits per software reset field (SW_RESET_N bit order 1 otbn,
  // 2 aes, 3 hmac, 4 kmac, 5 trng, 6 abr).
  localparam logic [13:0] MrHostOtbn = 14'b00_0000_0000_0001;
  localparam logic [13:0] MrHostAes = 14'b00_0000_0000_0010;
  localparam logic [13:0] MrHostHmac = 14'b00_0000_0000_0100;
  localparam logic [13:0] MrHostKmac = 14'b00_0000_0000_1000;
  localparam logic [13:0] MrHostTrng = 14'b00_0000_1110_0000;
  localparam logic [13:0] MrHostAbr = 14'b00_0000_0001_0000;
  // Approved isolate-complete probes: HMAC, KMAC and Adams Bridge host and key
  // paths, and the three TRNG paths.
  localparam logic [13:0] MrAckApproved = 14'b01_1100_1111_1100;

  function automatic logic [13:0] mr_host_set(input int unsigned i);
    case (i)
      1: return MrHostOtbn;
      2: return MrHostAes;
      3: return MrHostHmac;
      4: return MrHostKmac;
      5: return MrHostTrng;
      6: return MrHostAbr;
      default: return 14'd0;
    endcase
  endfunction

  // Domains of cp_iso_order_per_domain: 0 Key Manager, 1 OTBN, 2 AES, 3 KMAC,
  // 4 TRNG, with their ip_rst_n index and isolate set.
  localparam int unsigned MrIsoIdx[5] = '{0, 1, 2, 4, 5};
  function automatic logic [13:0] mr_iso_set(input int unsigned d);
    case (d)
      0: return MrSetKm;
      1: return MrSetOtbn;
      2: return MrSetAes;
      3: return MrSetKmac;
      default: return MrSetTrng;
    endcase
  endfunction

  // Secure DMA registers of the cold-reset points and their RDL reset values
  // (secure_dma.adoc, Reset column, through sep_reg.svh).
  localparam logic [31:0] MrDmaAddr[9] = '{
      SECURE_DMA_SRC_ADDR_LO_REG_ADDR,
      SECURE_DMA_DST_ADDR_LO_REG_ADDR,
      SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR,
      SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR,
      SECURE_DMA_RANGE_VALID_REG_ADDR,
      SECURE_DMA_RANGE_REGWEN_REG_ADDR,
      SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR,
      SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR,
      SECURE_DMA_HANDSHAKE_INTR_ENABLE_REG_ADDR
  };
  localparam logic [31:0] MrDmaDef[9] = '{
      32'(SECURE_DMA_SRC_ADDR_LO_REG_DEFAULT),
      32'(SECURE_DMA_DST_ADDR_LO_REG_DEFAULT),
      32'(SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_DEFAULT),
      32'(SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_DEFAULT),
      32'(SECURE_DMA_RANGE_VALID_REG_DEFAULT),
      32'(SECURE_DMA_RANGE_REGWEN_REG_DEFAULT),
      32'(SECURE_DMA_TOTAL_DATA_SIZE_REG_DEFAULT),
      32'(SECURE_DMA_CHUNK_DATA_SIZE_REG_DEFAULT),
      32'(SECURE_DMA_HANDSHAKE_INTR_ENABLE_REG_DEFAULT)
  };
  localparam int unsigned MrDmaRangeValid = 4;
  localparam int unsigned MrDmaRegwen = 5;
  localparam int unsigned MrDmaHsie = 8;

  function automatic logic [1:0] mr_third(input realtime off, input realtime per);
    if (per <= 0.0) return 2'd3;
    if (off * 3.0 < per) return 2'd0;
    if (off * 3.0 < per * 2.0) return 2'd1;
    return 2'd2;
  endfunction

  function automatic logic [1:0] mr_quart(input realtime off, input realtime per);
    if (per <= 0.0) return 2'd0;
    if (off * 4.0 < per) return 2'd0;
    if (off * 4.0 < per * 2.0) return 2'd1;
    if (off * 4.0 < per * 3.0) return 2'd2;
    return 2'd3;
  endfunction

  // TAP states (IEEE 1149.1; the encoding of dmi/rvjtag_tap.v).
  localparam logic [3:0] TapTlr = 4'd0;
  localparam logic [3:0] TapRti = 4'd1;
  localparam logic [3:0] TapSelDr = 4'd2;
  localparam logic [3:0] TapCapDr = 4'd3;
  localparam logic [3:0] TapShDr = 4'd4;
  localparam logic [3:0] TapEx1Dr = 4'd5;
  localparam logic [3:0] TapPauseDr = 4'd6;
  localparam logic [3:0] TapEx2Dr = 4'd7;
  localparam logic [3:0] TapUpdDr = 4'd8;
  localparam logic [3:0] TapSelIr = 4'd9;
  localparam logic [3:0] TapCapIr = 4'd10;
  localparam logic [3:0] TapShIr = 4'd11;
  localparam logic [3:0] TapEx1Ir = 4'd12;
  localparam logic [3:0] TapPauseIr = 4'd13;
  localparam logic [3:0] TapEx2Ir = 4'd14;
  localparam logic [3:0] TapUpdIr = 4'd15;

  function automatic logic [3:0] mr_tap_next(input logic [3:0] s, input logic tms);
    case (s)
      TapTlr: return tms ? TapTlr : TapRti;
      TapRti: return tms ? TapSelDr : TapRti;
      TapSelDr: return tms ? TapSelIr : TapCapDr;
      TapCapDr: return tms ? TapEx1Dr : TapShDr;
      TapShDr: return tms ? TapEx1Dr : TapShDr;
      TapEx1Dr: return tms ? TapUpdDr : TapPauseDr;
      TapPauseDr: return tms ? TapEx2Dr : TapPauseDr;
      TapEx2Dr: return tms ? TapUpdDr : TapShDr;
      TapUpdDr: return tms ? TapSelDr : TapRti;
      TapSelIr: return tms ? TapTlr : TapCapIr;
      TapCapIr: return tms ? TapEx1Ir : TapShIr;
      TapShIr: return tms ? TapEx1Ir : TapShIr;
      TapEx1Ir: return tms ? TapUpdIr : TapPauseIr;
      TapPauseIr: return tms ? TapEx2Ir : TapPauseIr;
      TapEx2Ir: return tms ? TapUpdIr : TapShIr;
      default: return tms ? TapSelDr : TapRti;
    endcase
  endfunction

  // ---------------------------------------------------------------------
  // Covergroups. Each sample carries one point; the valid bit is set only
  // when the owner of the point is in its window.
  // ---------------------------------------------------------------------
  typedef struct packed {
    logic [3:0] se;
    logic se_v;  // {source, 0 assert / 1 release}
    logic [2:0] rs;
    logic rs_v;  // {aligned, third}
    logic [2:0] as;
    logic as_v;  // {aligned, third}
    logic [1:0] ro;
    logic ro_v;  // 0 held window, 1 release after it, 2 early release
    logic [1:0] sb;
    logic sb_v;  // {scan_rst_ni, test_en_i}
    logic [5:0] sn;
    logic sn_v;  // {case, net}
    logic [1:0] jm;
    logic jm_v;  // {mechanism, programmed}
    logic ms;
    logic ms_v;  // 0 held while low, 1 follows after release
  } mr_src_t;

  covergroup sep_reset_source_cg with function sample (mr_src_t s);
    option.per_instance = 1;
    option.name = "sep_reset_source_cg";
    // Source: 0 rst_ni, 1 wdt_rst_ni, 2 dbg_rstb_i, 3 scan_rst_ni,
    // 4 jtag_trst_ni, 5 TAP Test-Logic-Reset.
    cp_source_edge: coverpoint s.se iff (s.se_v) {
      bins rst_ni_assert = {4'b000_0};
      bins rst_ni_release = {4'b000_1};
      bins wdt_rst_ni_assert = {4'b001_0};
      bins wdt_rst_ni_release = {4'b001_1};
      bins dbg_rstb_i_assert = {4'b010_0};
      bins dbg_rstb_i_release = {4'b010_1};
      bins scan_rst_ni_assert = {4'b011_0};
      bins scan_rst_ni_release = {4'b011_1};
      bins jtag_trst_ni_assert = {4'b100_0};
      bins jtag_trst_ni_release = {4'b100_1};
      bins tlr_entry = {4'b101_0};
      bins tlr_exit = {4'b101_1};
    }
    cp_rst_release_sync: coverpoint s.rs iff (s.rs_v) {
      bins third0_aligned = {3'b1_00};
      bins third1_aligned = {3'b1_01};
      bins third2_aligned = {3'b1_10};
      illegal_bins unaligned = {3'b0_00, 3'b0_01, 3'b0_10};
    }
    cp_aon_release_sync: coverpoint s.as iff (s.as_v) {
      bins third0_aligned = {3'b1_00};
      bins third1_aligned = {3'b1_01};
      bins third2_aligned = {3'b1_10};
      illegal_bins unaligned = {3'b0_00, 3'b0_01, 3'b0_10};
    }
    cp_release_order: coverpoint s.ro iff (s.ro_v) {
      bins held_window = {2'd0};
      bins release_after_ext_boot_rise = {2'd1};
      illegal_bins released_before_terms = {2'd2};
    }
    cp_scan_bypass: coverpoint s.sb iff (s.sb_v) {
      bins scan0_te0 = {2'b00};
      bins scan0_te1 = {2'b01};
      bins scan1_te0 = {2'b10};
      bins scan1_te1 = {2'b11};
    }
    // Net: 0 sep_reset_n, 1 sep_cpu_reset_n, 2..7 ip_rst_n[1..6],
    // 8 aon_rst_n, 9 Key Manager cold, 10 Key Manager warm. Case 0 keeps
    // its value (test_en_i 0), 1 low before the rise (test_en_i 1), 2 the
    // release of net 0 or 8 off the clock edge.
    cp_scan_net_effect: coverpoint s.sn iff (s.sn_v) {
      bins te0_keeps[] = {[6'd0 : 6'd10]};
      bins te1_low[] = {[6'd16 : 6'd26]};
      bins sep_reset_n_release_bypassed = {6'd32};
      bins aon_rst_n_release_bypassed = {6'd40};
    }
    cp_jtag_mech: coverpoint s.jm iff (s.jm_v) {
      bins trst_default = {2'b00};
      bins trst_programmed = {2'b01};
      bins tlr_default = {2'b10};
      bins tlr_programmed = {2'b11};
    }
    cp_mpc_sync_reset: coverpoint s.ms iff (s.ms_v) {
      bins held_while_dbg_rstb_low = {1'b0}; bins follows_after_release = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic [1:0] dc;
    logic dc_v;  // 0 clk_wdt_i, 1 clk_ref_i, 2 jtag_tck_i
    logic [1:0] xp;
    logic xp_v;  // clk_ref_i quartile
  } mr_clk_t;

  covergroup sep_clk_domain_cg with function sample (mr_clk_t s);
    option.per_instance = 1;
    option.name = "sep_clk_domain_cg";
    cp_domain_crossing: coverpoint s.dc iff (s.dc_v) {
      bins clk_wdt_i = {2'd0}; bins clk_ref_i = {2'd1}; bins jtag_tck_i = {2'd2};
    }
    cp_xdomain_phase: coverpoint s.xp iff (s.xp_v) {
      bins clk_ref_q1 = {2'd0};
      bins clk_ref_q2 = {2'd1};
      bins clk_ref_q3 = {2'd2};
      bins clk_ref_q4 = {2'd3};
    }
  endgroup

  typedef struct packed {
    logic [1:0] sf;
    logic sf_v;  // {smc_fuse_sense_done_i, readback}
    logic [1:0] pw;
    logic pw_v;  // 0 SLVERR before sense, 1 OKAY readback, 2 OKAY before sense
    logic [1:0] ff;
    logic ff_v;  // 0 Boot ROM base, 1 other, 2 retired in reset
  } mr_boot_t;

  covergroup sep_boot_milestone_cg with function sample (mr_boot_t s);
    option.per_instance = 1;
    option.name = "sep_boot_milestone_cg";
    cp_smc_status_follow: coverpoint s.sf iff (s.sf_v) {
      bins done0_read0 = {2'b00};
      bins done1_read1 = {2'b11};
      illegal_bins mismatch = {2'b01, 2'b10};
    }
    cp_presense_window: coverpoint s.pw iff (s.pw_v) {
      bins slverr_sense0 = {2'd0};
      bins okay_sense1_after_slverr = {2'd1};
      illegal_bins okay_sense0 = {2'd2};
    }
    cp_first_fetch: coverpoint s.ff iff (s.ff_v) {
      bins boot_rom_base = {2'd0};
      bins other_address = {2'd1};
      illegal_bins retired_in_reset = {2'd2};
    }
  endgroup

  typedef struct packed {
    logic [1:0] tc;
    logic tc_v;  // {test_en_i, class 0 clock gater 1 AXI cell}
  } mr_tie_t;

  covergroup sep_static_tieoff_cg with function sample (mr_tie_t s);
    option.per_instance = 1;
    option.name = "sep_static_tieoff_cg";
    cp_test_en_consumer: coverpoint s.tc iff (s.tc_v) {
      option.weight = 0;
      bins te0_clock_gater = {2'b00};
      bins te0_axi_cell = {2'b01};
      bins te1_clock_gater = {2'b10};
      bins te1_axi_cell = {2'b11};
    }
  endgroup

  typedef struct packed {
    logic [3:0] ft;
    logic ft_v;  // {field, 0 assert / 1 release}
    logic mw;
    logic mw_v;  // 0 assert, 1 release
    logic pu;
    logic pu_v;  // 0 hmac field, 1 aggregate
  } mr_swc_t;

  covergroup sep_reset_sw_ctrl_cg with function sample (mr_swc_t s);
    option.per_instance = 1;
    option.name = "sep_reset_sw_ctrl_cg";
    // Field in SW_RESET_N bit order: 0 km, 1 otbn, 2 aes, 3 hmac, 4 kmac,
    // 5 trng, 6 abr.
    cp_field_transition: coverpoint s.ft iff (s.ft_v) {
      bins km_assert = {4'b000_0};
      bins km_release = {4'b000_1};
      bins otbn_assert = {4'b001_0};
      bins otbn_release = {4'b001_1};
      bins aes_assert = {4'b010_0};
      bins aes_release = {4'b010_1};
      bins hmac_assert = {4'b011_0};
      bins hmac_release = {4'b011_1};
      bins kmac_assert = {4'b100_0};
      bins kmac_release = {4'b100_1};
      bins trng_assert = {4'b101_0};
      bins trng_release = {4'b101_1};
      bins abr_assert = {4'b110_0};
      bins abr_release = {4'b110_1};
    }
    cp_multi_field_write: coverpoint s.mw iff (s.mw_v) {
      bins asserts_two_or_more = {1'b0}; bins releases_two_or_more = {1'b1};
    }
    cp_power_up_value: coverpoint s.pu iff (s.pu_v) {
      bins hmac_field_1 = {1'b0}; bins aggregate_0x7e = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic [3:0] eo;
    logic eo_v;  // {enable, outcome 0 no count 1 advances 2 crossed}
    logic [2:0] bs;
    logic bs_v;  // bark status cell, 4 bite in a forced window
    logic [1:0] lk;
    logic lk_v;  // 0 sticky, 1 cold landed, 2 locked landed, 3 unlocked ignored
    logic [2:0] ad;
    logic ad_v;  // {stage, high half}
    logic ax;
    logic ax_v;  // 0 WDOG_CTRL, 1 WDOG_COUNT
    logic [1:0] to;
    logic to_v;  // 0 bark first, 1 later bark, 2 near 2^32, 3 bite without bark
  } mr_wdt_t;

  covergroup sep_wdt_config_bark_cg with function sample (mr_wdt_t s);
    option.per_instance = 1;
    option.name = "sep_wdt_config_bark_cg";
    cp_enable_outcome: coverpoint s.eo iff (s.eo_v) {
      bins enable1_crossed = {4'b1_010};
      ignore_bins control_cells = {4'b0_000, 4'b1_001};
      illegal_bins enable0_counts = {4'b0_001, 4'b0_010};
      illegal_bins enable1_no_count = {4'b1_000};
    }
    cp_bark_status: coverpoint s.bs iff (s.bs_v) {
      bins set_by_threshold = {3'd0};
      bins cleared_w1c_after_forced = {3'd1};
      bins forced_enable0 = {3'd2};
      bins forced_enable1_count_far_below = {3'd3};
      illegal_bins bite_in_forced_window = {3'd4};
    }
    cp_lock_x_reg: coverpoint s.lk iff (s.lk_v) {
      bins regwen_sticky_after_clear = {2'd0};
      bins cold_reset_regwen1_write_lands = {2'd1};
      illegal_bins regwen0_landed = {2'd2};
      illegal_bins regwen1_ignored = {2'd3};
    }
    // Stage: 0 sep_wdt_tlul_axi_req, 1 sep_wdt_tlul_axi_req_offset,
    // 2 axi_lite_req, 3 tl_d_i.
    cp_adapt_stage: coverpoint s.ad iff (s.ad_v) {
      bins dw_conv_low = {3'b00_0};
      bins dw_conv_high = {3'b00_1};
      bins offset_low = {3'b01_0};
      bins offset_high = {3'b01_1};
      bins axi_lite_low = {3'b10_0};
      bins axi_lite_high = {3'b10_1};
      bins tlul_low = {3'b11_0};
      bins tlul_high = {3'b11_1};
    }
    cp_access_x_register: coverpoint s.ax iff (s.ax_v) {
      bins wdog_ctrl_read = {1'b0}; bins wdog_count_read = {1'b1};
    }
    cp_thold_order: coverpoint s.to iff (s.to_v) {
      bins bark_with_bite_low = {2'd0};
      bins larger_threshold_later_bark = {2'd1};
      bins near_2_32_bark_and_bite = {2'd2};
      illegal_bins bite_without_bark = {2'd3};
    }
  endgroup

  typedef struct packed {
    logic [2:0] wp;
    logic wp_v;  // 0..3 prescaler class, 4 HI first, 5 LO first, 6 expired
  } mr_wkup_t;

  covergroup sep_wdt_wakeup_timer_cg with function sample (mr_wkup_t s);
    option.per_instance = 1;
    option.name = "sep_wdt_wakeup_timer_cg";
    cp_wkup_thold_x_presc: coverpoint s.wp iff (s.wp_v) {
      bins presc0_crossing = {3'd0};
      bins presc1_crossing = {3'd1};
      bins presc_mid_crossing = {3'd2};
      bins split_hi_first = {3'd4};
      bins split_lo_first = {3'd5};
      bins expired_crossing = {3'd6};
      ignore_bins presc_4095 = {3'd3};
    }
  endgroup

  typedef struct packed {
    logic cs;
    logic cs_v;  // 0 DMA_BUS_ERR_STATUS (bit 40), 1 PERIPH_BUS_ERR_STATUS (bit 42)
  } mr_esc_t;

  covergroup sep_wdt_escalation_fault_cg with function sample (mr_esc_t s);
    option.per_instance = 1;
    option.name = "sep_wdt_escalation_fault_cg";
    cp_cpu_only_reset_scope: coverpoint s.cs iff (s.cs_v) {
      bins dma_reg_path_err_kept = {1'b0}; bins periph_bus_err_kept = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic rc;
    logic rc_v;  // 0 restart after the cold reset, 1 write takes effect
    logic [2:0] rr;
    logic rr_v;  // ratio code
    logic [1:0] rw;
    logic rw_v;  // {low word class, carry}
    logic vi_v;
    logic nv_v;
    logic nl;
    logic nl_v;  // written 0 or all-ones
    logic sr;
    logic sr_v;  // 0 SEP_FUSE_SENSE_STATUS, 1 SMC_FUSE_SENSE_STATUS
  } mr_cc_t;

  covergroup sep_cpu_ctrl_reg_cg with function sample (mr_cc_t s);
    option.per_instance = 1;
    option.name = "sep_cpu_ctrl_reg_cg";
    cp_refcnt: coverpoint s.rc iff (s.rc_v) {
      bins restarts_after_cold_reset = {1'b0}; bins write_takes_effect = {1'b1};
    }
    // Ratio: 0 two, 1 three, 2 five, 3 eight, 4 thirteen.
    cp_refcnt_ratio: coverpoint s.rr iff (s.rr_v) {
      bins ratio_2 = {3'd0};
      bins ratio_3 = {3'd1};
      bins ratio_5 = {3'd2};
      bins ratio_8 = {3'd3};
      bins ratio_13 = {3'd4};
    }
    cp_refcnt_write_class: coverpoint s.rw iff (s.rw_v) {
      bins low_equal = {2'b00};
      bins high_equal = {2'b10};
      bins high_carry = {2'b11};
      ignore_bins low_carry = {2'b01};
    }
    cp_version_id: coverpoint s.vi_v iff (s.vi_v) {bins write_ignored = {1'b1};}
    cp_nmi_vec: coverpoint s.nv_v iff (s.nv_v) {bins locked_write_ignored = {1'b1};}
    cp_nmi_lock: coverpoint s.nl iff (s.nl_v) {
      bins write_zero_keeps_lock = {1'b0}; bins write_ones_keeps_lock = {1'b1};
    }
    cp_status_ro_write: coverpoint s.sr iff (s.sr_v) {
      bins sep_fuse_sense_status = {1'b0}; bins smc_fuse_sense_status = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic [4:0] ba;
    logic ba_v;  // {bank, index, shape}
  } mr_scr_t;

  covergroup sep_scratch_reg_access_cg with function sample (mr_scr_t s);
    option.per_instance = 1;
    option.name = "sep_scratch_reg_access_cg";
    // {bank 0 cold 1 warm, register index, shape 0 one 64-bit lane write
    // 1 two 32-bit half writes}.
    cp_bank_reg_access: coverpoint s.ba iff (s.ba_v) {
      bins cells[] = {[5'd0 : 5'd31]};
    }
  endgroup

  typedef struct packed {
    logic [2:0] rc;
    logic rc_v;  // reset class
    logic [4:0] bo;
    logic bo_v;  // {bank, class, retained}
    logic km;
    logic km_v;  // 0 asserted idle, 1 released
    logic ti_v;  // TRNG release
    logic [2:0] nu;
    logic nu_v;  // unit
    logic [4:0] io;
    logic io_v;  // {domain, event}
    logic [2:0] np;
    logic np_v;  // {port, isolated answer}
    logic [2:0] pv;
    logic pv_v;  // {pulse class, position}
    logic [3:0] on;
    logic on_v;  // {domain, rises}
  } mr_scope_t;

  covergroup sep_reset_scope_retention_cg with function sample (mr_scope_t s);
    option.per_instance = 1;
    option.name = "sep_reset_scope_retention_cg";
    cp_reset_class: coverpoint s.rc iff (s.rc_v) {
      bins power_on = {3'd0};
      bins watchdog = {3'd1};
      bins per_ip_software = {3'd2};
      bins dbg_rstb = {3'd3};
      bins jtag_tap = {3'd4};
      bins jtag_sep_reset_n_override = {3'd5};
    }
    // Class: 0 power-on, 1 watchdog, 2 per-IP software, 3 dbg_rstb_i, 4 TAP.
    cp_bank_class_outcome: coverpoint s.bo iff (s.bo_v) {
      bins cold_software_retained = {5'b0_010_1};
      bins warm_software_retained = {5'b1_010_1};
      bins cold_tap_retained = {5'b0_100_1};
      bins warm_tap_retained = {5'b1_100_1};
      ignore_bins phase1_watchdog = {5'b0_001_1, 5'b1_001_0};
      ignore_bins power_on_cleared = {5'b0_000_0, 5'b1_000_0};
      ignore_bins dbg_retained = {5'b0_011_1, 5'b1_011_1};
      illegal_bins cold_cleared = {5'b0_001_0, 5'b0_010_0, 5'b0_011_0, 5'b0_100_0};
      illegal_bins warm_cleared = {5'b1_010_0, 5'b1_011_0, 5'b1_100_0};
      illegal_bins power_on_retained = {5'b0_000_1, 5'b1_000_1};
      illegal_bins warm_retained_watchdog = {5'b1_001_1};
    }
    cp_km_reset_condition: coverpoint s.km iff (s.km_v) {
      bins asserted_idle = {1'b0}; bins released = {1'b1};
    }
    cp_trng_iso_order: coverpoint s.ti_v iff (s.ti_v) {bins release_with_reset = {1'b1};}
    // Unit: 0 SPI host, 1 DMA engine, 2 watchdog timer, 3 inbound mailbox
    // window, 4 scratch banks.
    cp_no_sw_reset_units: coverpoint s.nu iff (s.nu_v) {
      bins spi_host = {3'd0};
      bins dma_engine = {3'd1};
      bins watchdog_timer = {3'd2};
      bins mailbox_inbound_window = {3'd3};
      bins scratch_banks = {3'd4};
    }
    // {domain 0 km 1 otbn 2 aes 3 kmac 4 trng, event 0 fall 1 release 2 fall
    // before the set is isolated}.
    cp_iso_order_per_domain: coverpoint s.io iff (s.io_v) {
      bins km_fall = {5'b000_00};
      bins km_release = {5'b000_01};
      bins otbn_fall = {5'b001_00};
      bins otbn_release = {5'b001_01};
      bins aes_fall = {5'b010_00};
      bins aes_release = {5'b010_01};
      bins kmac_release = {5'b011_01};
      bins trng_release = {5'b100_01};
      ignore_bins open_owner_falls = {5'b011_00, 5'b100_00};
      illegal_bins fall_before_isolated = {5'b000_10, 5'b001_10, 5'b010_10, 5'b011_10, 5'b100_10};
    }
    // Port: 0 external TRNG window, 1 Key Manager mailbox, 2 lifecycle,
    // 3 entropy pool STATUS.
    cp_never_isolated_port: coverpoint s.np iff (s.np_v) {
      bins ext_trng = {3'b00_0};
      bins km_mailbox = {3'b01_0};
      bins lifecycle = {3'b10_0};
      bins pool_status = {3'b11_0};
      illegal_bins isolated_answer = {3'b00_1, 3'b01_1, 3'b10_1, 3'b11_1};
    }
    // {class 0 wdt_rst_ni 1 dbg_rstb_i, position 0 before the write 1 between
    // write and fall 2 while low or after the fall}; 3'b111 the sequence lost.
    cp_pulse_vs_sequence: coverpoint s.pv iff (s.pv_v) {
      bins wdt_before_write = {3'b0_00};
      bins wdt_between = {3'b0_01};
      bins wdt_while_low = {3'b0_10};
      bins dbg_before_write = {3'b1_00};
      bins dbg_between = {3'b1_01};
      bins dbg_while_low = {3'b1_10};
      illegal_bins sequence_lost = {3'b0_11, 3'b1_11};
    }
    // {domain 0 otbn 1 aes 2 hmac 3 kmac 4 trng 5 abr, isolate bit rose}.
    cp_ovrd_no_iso: coverpoint s.on iff (s.on_v) {
      bins otbn = {4'b000_0};
      bins aes = {4'b001_0};
      bins hmac = {4'b010_0};
      bins kmac = {4'b011_0};
      bins trng = {4'b100_0};
      bins abr = {4'b101_0};
      illegal_bins isolated_under_override = {4'b000_1, 4'b001_1, 4'b010_1, 4'b011_1, 4'b100_1, 4'b101_1};
    }
  endgroup

  typedef struct packed {
    logic [5:0] ip;
    logic ip_v;  // {aggressor, victim}
    logic [6:0] ox;
    logic ox_v;  // {domain, E, V, sw, mismatch}
    logic [3:0] op;
    logic op_v;  // {domain, first released 0 sw 1 override, rose early}
    logic tn;
    logic tn_v;  // 0 pool OKAY, 1 external TRNG window
  } mr_crst_t;

  covergroup sep_crypto_reset_cg with function sample (mr_crst_t s);
    option.per_instance = 1;
    option.name = "sep_crypto_reset_cg";
    // Domain codes 1 otbn, 2 aes, 3 hmac, 4 kmac, 5 trng.
    cp_independence_pair: coverpoint s.ip iff (s.ip_v) {
      bins pairs[] = {
        6'o12, 6'o13, 6'o14, 6'o15, 6'o21, 6'o23, 6'o24, 6'o25, 6'o31, 6'o32,
        6'o34, 6'o35, 6'o41, 6'o42, 6'o43, 6'o45, 6'o51, 6'o52, 6'o53, 6'o54
      };
    }
    // Domain 0 otbn 1 aes 2 hmac 3 kmac 4 trng 5 abr; E = 0 carries V = 0.
    cp_ip_ovrd_x_sw: coverpoint s.ox iff (s.ox_v) {
      bins cells[] = {
        7'b000_000_0, 7'b000_001_0, 7'b000_100_0, 7'b000_101_0, 7'b000_110_0, 7'b000_111_0,
        7'b001_000_0, 7'b001_001_0, 7'b001_100_0, 7'b001_101_0, 7'b001_110_0, 7'b001_111_0,
        7'b010_000_0, 7'b010_001_0, 7'b010_100_0, 7'b010_101_0, 7'b010_110_0, 7'b010_111_0,
        7'b011_000_0, 7'b011_001_0, 7'b011_100_0, 7'b011_101_0, 7'b011_110_0, 7'b011_111_0,
        7'b100_000_0, 7'b100_001_0, 7'b100_110_0, 7'b100_111_0,
        7'b101_000_0, 7'b101_001_0, 7'b101_110_0, 7'b101_111_0
      };
      ignore_bins open_owner_e1_v0 = {7'b100_100_0, 7'b100_101_0, 7'b101_100_0, 7'b101_101_0};
      wildcard illegal_bins tap_differs = {7'b???_???_1};
    }
    cp_ovrd_priority: coverpoint s.op iff (s.op_v) {
      bins otbn_sw_first = {4'b00_0_0};
      bins otbn_ovrd_first = {4'b00_1_0};
      bins aes_sw_first = {4'b01_0_0};
      bins aes_ovrd_first = {4'b01_1_0};
      bins hmac_sw_first = {4'b10_0_0};
      bins hmac_ovrd_first = {4'b10_1_0};
      bins kmac_sw_first = {4'b11_0_0};
      bins kmac_ovrd_first = {4'b11_1_0};
      wildcard illegal_bins rose_after_first_release = {4'b??_?_1};
    }
    cp_trng_nonmember: coverpoint s.tn iff (s.tn_v) {
      bins pool_read_okay = {1'b0}; bins ext_trng_window_completes = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic [4:0] ti;
    logic ti_v;  // IR value at Update-IR
    logic rt;
    logic rt_v;  // 0 shift through, 1 dmi_rst_vec changes at Update-DR
    logic ta;
    logic ta_v;  // 0 quiet reset then a beat, 1 beat in reset
    logic [1:0] da;
    logic da_v;  // {dmi_core_enable_i, DMI address 0x50 and above}
    logic [1:0] tv;
    logic tv_v;  // 0 taken trap, 1 interrupt cause 0x1E, 2 NMI
    logic [2:0] ic;
    logic ic_v;  // 0 M, 1 C, 2 Zba, 3 Zbb, 4 Zbc retired, 5 Zbs trapped
  } mr_dbg_t;

  covergroup sep_debug_trace_cg with function sample (mr_dbg_t s);
    option.per_instance = 1;
    option.name = "sep_debug_trace_cg";
    cp_tap_instruction: coverpoint s.ti iff (s.ti_v) {
      bins reset_vector_tdr = {5'h18}; ignore_bins not_stated = {[5'h00 : 5'h17], [5'h19 : 5'h1F]};
    }
    cp_rstvec_tdr: coverpoint s.rt iff (s.rt_v) {
      bins shift_tdi_to_tdo = {1'b0}; bins update_dr_changes_vector = {1'b1};
    }
    cp_trace_activity: coverpoint s.ta iff (s.ta_v) {
      bins quiet_reset_then_beat = {1'b0}; illegal_bins beat_in_reset = {1'b1};
    }
    cp_dmi_aperture: coverpoint s.da iff (s.da_v) {
      bins enable0_core = {2'b00};
      bins enable0_upper = {2'b01};
      bins enable1_core = {2'b10};
      bins enable1_upper = {2'b11};
    }
    cp_traced_event: coverpoint s.tv iff (s.tv_v) {
      bins taken_trap = {2'd0}; bins interrupt_0x1e = {2'd1}; bins nmi = {2'd2};
    }
    cp_instr_class: coverpoint s.ic iff (s.ic_v) {
      bins retired_m = {3'd0};
      bins retired_c = {3'd1};
      bins retired_zba = {3'd2};
      bins retired_zbb = {3'd3};
      bins retired_zbc = {3'd4};
      bins trapped_zbs = {3'd5};
    }
  endgroup

  typedef struct packed {
    logic st_v;
    logic [2:0] ev;
    logic ev_v;  // 0 early capture, 1..4 non-sampling event, 5 change outside
    logic sk;
    logic sk_v;  // 0 strap change held, 1 change after the capture
    logic rw;
    logic rw_v;  // 0 macro request at the store word only for readbacks, 1 other
    logic rr_v;  // byte or halfword ROM store response
    logic [1:0] du;
    logic du_v;  // {uncore DMI output high, DMI address 0x50 and above}
  } mr_abs_t;

  covergroup sep_documented_absence_cg with function sample (mr_abs_t s);
    option.per_instance = 1;
    option.name = "sep_documented_absence_cg";
    cp_secure_tm_state: coverpoint s.st_v iff (s.st_v) {bins cold_reset_clear = {1'b1};}
    cp_stm_event_x_strap: coverpoint s.ev iff (s.ev_v) {
      bins early_capture_strap1 = {3'd0};
      bins wdt_rst_ni_unchanged = {3'd1};
      bins dbg_rstb_i_unchanged = {3'd2};
      bins sw_engine_reset_unchanged = {3'd3};
      bins sep_reset_n_override_unchanged = {3'd4};
      illegal_bins change_outside_sampling_event = {3'd5};
    }
    cp_stm_strap_stability: coverpoint s.sk iff (s.sk_v) {
      bins strap_change_held = {1'b0}; illegal_bins change_after_capture = {1'b1};
    }
    cp_rom_write_master: coverpoint s.rw iff (s.rw_v) {
      bins cpu_store_readback_only = {1'b0}; illegal_bins macro_request_not_readback = {1'b1};
    }
    cp_rom_write_response: coverpoint s.rr_v iff (s.rr_v) {bins byte_half_store_response = {1'b1};}
    cp_dmi_uncore: coverpoint s.du iff (s.du_v) {
      bins disabled_lower_never = {2'b00};
      bins disabled_upper_never = {2'b01};
      illegal_bins uncore_output_with_enable_0 = {2'b10, 2'b11};
    }
  endgroup

  sep_reset_source_cg          u_sep_reset_source_cg          = new();
  sep_clk_domain_cg            u_sep_clk_domain_cg            = new();
  sep_boot_milestone_cg        u_sep_boot_milestone_cg        = new();
  sep_static_tieoff_cg         u_sep_static_tieoff_cg         = new();
  sep_reset_sw_ctrl_cg         u_sep_reset_sw_ctrl_cg         = new();
  sep_wdt_config_bark_cg       u_sep_wdt_config_bark_cg       = new();
  sep_wdt_wakeup_timer_cg      u_sep_wdt_wakeup_timer_cg      = new();
  sep_wdt_escalation_fault_cg  u_sep_wdt_escalation_fault_cg  = new();
  sep_cpu_ctrl_reg_cg          u_sep_cpu_ctrl_reg_cg          = new();
  sep_scratch_reg_access_cg    u_sep_scratch_reg_access_cg    = new();
  sep_reset_scope_retention_cg u_sep_reset_scope_retention_cg = new();
  sep_crypto_reset_cg          u_sep_crypto_reset_cg          = new();
  sep_debug_trace_cg           u_sep_debug_trace_cg           = new();
  sep_documented_absence_cg    u_sep_documented_absence_cg    = new();

  // One-point sample helpers.
  task automatic mr_se(input logic [2:0] src, input logic rel);
    mr_src_t e;
    e      = '0;
    e.se   = {src, rel};
    e.se_v = 1'b1;
    u_sep_reset_source_cg.sample(e);
  endtask

  task automatic mr_rc(input logic [2:0] c);
    mr_scope_t e;
    e      = '0;
    e.rc   = c;
    e.rc_v = 1'b1;
    u_sep_reset_scope_retention_cg.sample(e);
  endtask

  task automatic mr_jm(input logic tlr, input logic [30:0] vec);
    mr_src_t e;
    e      = '0;
    e.jm   = {tlr, vec != MrRomVec};
    e.jm_v = 1'b1;
    u_sep_reset_source_cg.sample(e);
  endtask

  task automatic mr_dc(input logic [1:0] d);
    mr_clk_t e;
    e      = '0;
    e.dc   = d;
    e.dc_v = 1'b1;
    u_sep_clk_domain_cg.sample(e);
  endtask

  task automatic mr_dbg_s(input logic [1:0] which, input logic [4:0] v);
    mr_dbg_t e;
    e = '0;
    case (which)
      2'd0: begin
        e.ti   = v;
        e.ti_v = 1'b1;
      end
      2'd1: begin
        e.rt   = v[0];
        e.rt_v = 1'b1;
      end
      default: begin
        e.ta   = v[0];
        e.ta_v = 1'b1;
      end
    endcase
    u_sep_debug_trace_cg.sample(e);
  endtask

  // ---------------------------------------------------------------------
  // Levels, edges and clock edge times.
  // ---------------------------------------------------------------------
  wire mr_rst = (rst_ni === 1'b1);
  wire mr_wdt = (wdt_rst_n_i !== 1'b0);
  wire mr_dbg = (dbg_rstb_i !== 1'b0);
  wire mr_scan = (scan_rst_n_i !== 1'b0);
  wire mr_te = (test_en_i === 1'b1);
  wire mr_trst = (jtag_trst_n_i === 1'b1);
  wire mr_srn = (sep_reset_n_i === 1'b1);
  wire mr_cpurn = (cpu_reset_n_i === 1'b1);
  wire mr_ext = (ext_boot_done_i === 1'b1);
  wire mr_fuse = (fuse_sense_done_i === 1'b1);
  wire mr_secdis = (sec_dis_i === 1'b1);
  wire mr_stm = (secure_tm_i === 1'b1);
  wire mr_strap = (strap_i === 1'b1);
  wire mr_bark = (wdt_bark_irq_i === 1'b1);
  wire mr_bite = (wdt_rst_req_i === 1'b1);
  wire mr_sovr = (jtag_sep_reset_n_ovrd_i === 1'b1);
  wire mr_ovr_cond = mr_sovr && (jtag_sep_reset_n_val_i !== 1'b1);
  logic [6:0] mr_ip;
  always_comb begin
    for (int i = 0; i < 7; i++) mr_ip[i] = (ip_rst_n_i[i] !== 1'b0);
  end
  // Per-domain override enable and value, SW_RESET_N bit order.
  wire [6:0] mr_ovrd = {
    jtag_rst_ctrl_i.ovrd.abr_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.trng_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.kmac_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.hmac_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.aes_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.otbn_jtag_rst_n_ovrd,
    jtag_rst_ctrl_i.ovrd.km_jtag_rst_n_ovrd
  };
  wire [6:0] mr_oval = {
    jtag_rst_ctrl_i.val.abr_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.trng_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.kmac_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.hmac_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.aes_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.otbn_jtag_rst_n_val,
    jtag_rst_ctrl_i.val.km_jtag_rst_n_val
  };
  // A software-path reset event: sep_reset_n high and every override off.
  wire mr_sw_ok = mr_srn && !mr_sovr;

  logic mr_rst_q = 1'b0;
  logic mr_wdt_q = 1'b1;
  logic mr_dbg_q = 1'b1;
  logic mr_scan_q = 1'b1;
  logic mr_te_q = 1'b0;
  logic mr_trst_q = 1'b0;
  logic mr_srn_q = 1'b0;
  logic mr_cpurn_q = 1'b0;
  logic mr_ext_q = 1'b0;
  logic mr_fuse_q = 1'b0;
  logic mr_stm_q = 1'b0;
  logic mr_strap_q = 1'b0;
  logic mr_bark_q = 1'b0;
  logic mr_bite_q = 1'b0;
  logic mr_ovr_cond_q = 1'b0;
  logic [6:0] mr_ip_q = '1;
  logic [6:0] mr_ovrd_q = '0;
  logic [13:0] mr_ack_q = '0;
  logic [42:0] mr_vec_q = '0;
  logic mr_mpc_q = 1'b0;
  logic [30:0] mr_rv_q = '0;  // dmi_rst_vec at the previous clk_i edge
  always @(posedge clk_i) begin
    mr_rst_q      <= mr_rst;
    mr_wdt_q      <= mr_wdt;
    mr_dbg_q      <= mr_dbg;
    mr_scan_q     <= mr_scan;
    mr_te_q       <= mr_te;
    mr_trst_q     <= mr_trst;
    mr_srn_q      <= mr_srn;
    mr_cpurn_q    <= mr_cpurn;
    mr_ext_q      <= mr_ext;
    mr_fuse_q     <= mr_fuse;
    mr_stm_q      <= mr_stm;
    mr_strap_q    <= mr_strap;
    mr_bark_q     <= mr_bark;
    mr_bite_q     <= mr_bite;
    mr_ovr_cond_q <= mr_ovr_cond;
    mr_ip_q       <= mr_ip;
    mr_ovrd_q     <= mr_ovrd;
    mr_ack_q      <= iso_ack_i;
    mr_vec_q      <= vec_i;
    mr_mpc_q      <= (mpc_run_req_i === 1'b1);
    mr_rv_q       <= dmi_rst_vec_i;
  end
  wire mr_rst_fall = mr_rst_q && !mr_rst;
  wire mr_rst_rise = !mr_rst_q && mr_rst;
  wire mr_wdt_fall = mr_wdt_q && !mr_wdt;
  wire mr_wdt_rise = !mr_wdt_q && mr_wdt;
  wire mr_dbg_fall = mr_dbg_q && !mr_dbg;
  wire mr_dbg_rise = !mr_dbg_q && mr_dbg;
  wire mr_trst_fall = mr_trst_q && !mr_trst;
  wire mr_trst_rise = !mr_trst_q && mr_trst;
  wire mr_ovr_rise = !mr_ovr_cond_q && mr_ovr_cond;
  wire mr_ovr_fall = mr_ovr_cond_q && !mr_ovr_cond;
  wire [6:0] mr_ip_fall = mr_ip_q & ~mr_ip;
  wire [6:0] mr_ip_rise = ~mr_ip_q & mr_ip;
  // ip_rst_n falls of the software path (sep_reset_n high, overrides off).
  wire [6:0] mr_ip_sw_fall = mr_ip_fall & ~mr_ovrd & {7{mr_sw_ok}};
  wire mr_eng_rst = |mr_ip_sw_fall[6:1];

  longint unsigned mr_cyc = 0;
  always @(posedge clk_i) mr_cyc <= mr_cyc + 1;

  realtime mr_t_clk = 0.0;
  realtime mr_t_clk_p = 0.0;
  realtime mr_t_wdt = 0.0;
  realtime mr_t_wdt_p = 0.0;
  realtime mr_t_ref[5] = '{default: 0.0};
  always @(posedge clk_i) begin
    mr_t_clk_p = mr_t_clk;
    mr_t_clk   = $realtime;
  end
  always @(posedge clk_wdt_i) begin
    mr_t_wdt_p = mr_t_wdt;
    mr_t_wdt   = $realtime;
  end

  // ---------------------------------------------------------------------
  // Sub-cycle release points (cp_rst_release_sync, cp_aon_release_sync, the
  // two release cells of cp_scan_net_effect). The phase is taken at the
  // rst_ni or scan_rst_ni rise; the release net rise is compared with the
  // last edge of its clock.
  // ---------------------------------------------------------------------
  logic [1:0] mr_rr_third = 2'd3;
  logic [1:0] mr_ar_third = 2'd3;
  logic mr_rr_arm = 1'b0;
  logic mr_ar_arm = 1'b0;
  logic mr_sn_arm = 1'b0;
  always @(posedge rst_ni) begin
    mr_rr_arm   = mr_own_cold;
    mr_ar_arm   = mr_own_cold;
    mr_rr_third = mr_third($realtime - mr_t_clk, mr_t_clk - mr_t_clk_p);
    mr_ar_third = mr_third($realtime - mr_t_wdt, mr_t_wdt - mr_t_wdt_p);
  end
  always @(posedge scan_rst_n_i) mr_sn_arm = mr_own_scan && mr_te;
  always @(negedge scan_rst_n_i) mr_sn_arm = 1'b0;
  always @(posedge sep_reset_n_i) begin
    if (sep_reset_n_i === 1'b1) begin
      realtime off;
      realtime per;
      off = $realtime - mr_t_clk;
      per = mr_t_clk - mr_t_clk_p;
      if (mr_rr_arm && mr_own_cold && (mr_rr_third != 2'd3)) begin
        mr_src_t e;
        e      = '0;
        e.rs   = {(off <= MrEdgeTol), mr_rr_third};
        e.rs_v = 1'b1;
        u_sep_reset_source_cg.sample(e);
      end
      mr_rr_arm = 1'b0;
      if (mr_sn_arm && mr_own_scan && (off > MrEdgeTol) && (off < per - MrEdgeTol)) begin
        mr_src_t e;
        e      = '0;
        e.sn   = 6'd32;
        e.sn_v = 1'b1;
        u_sep_reset_source_cg.sample(e);
      end
    end
  end
  always @(posedge aon_rst_n_i) begin
    if (aon_rst_n_i === 1'b1) begin
      realtime off;
      realtime per;
      off = $realtime - mr_t_wdt;
      per = mr_t_wdt - mr_t_wdt_p;
      if (mr_ar_arm && mr_own_cold && (mr_ar_third != 2'd3)) begin
        mr_src_t e;
        e      = '0;
        e.as   = {(off <= MrEdgeTol), mr_ar_third};
        e.as_v = 1'b1;
        u_sep_reset_source_cg.sample(e);
      end
      mr_ar_arm = 1'b0;
      if (mr_sn_arm && mr_own_scan && (off > MrEdgeTol) && (off < per - MrEdgeTol)) begin
        mr_src_t e;
        e      = '0;
        e.sn   = 6'd40;
        e.sn_v = 1'b1;
        u_sep_reset_source_cg.sample(e);
      end
    end
  end

  // ---------------------------------------------------------------------
  // TAP state tracker: a model of the TAP from the pins only. It reads no
  // RTL net of the TAP. dmi_rst_vec is read at the Update-DR edge (before
  // the TDR takes the shifted value) and at the Test-Logic-Reset entry.
  // ---------------------------------------------------------------------
  logic [3:0] mr_tap = TapTlr;
  logic [4:0] mr_irs = 5'd0;
  logic [4:0] mr_ir = 5'd1;
  logic [63:0] mr_tdi_h = '0;
  int unsigned mr_sh_n = 0;
  int unsigned mr_sh_cmp = 0;
  logic mr_sh_bad = 1'b0;
  logic [30:0] mr_tdr_before = '0;
  int unsigned mr_tdr_upd = 0;
  int unsigned mr_tlr_ev = 0;
  always @(posedge jtag_tck_i or negedge jtag_trst_n_i) begin
    if (jtag_trst_n_i !== 1'b1) begin
      mr_tap <= TapTlr;
      mr_ir  <= 5'd1;
    end else begin
      logic [3:0] nx;
      nx = mr_tap_next(mr_tap, jtag_tms_i === 1'b1);
      case (mr_tap)
        TapTlr: mr_ir <= 5'd1;
        TapCapDr: begin
          mr_sh_n   <= 0;
          mr_sh_cmp <= 0;
          mr_sh_bad <= 1'b0;
        end
        TapShDr: begin
          if ((mr_ir == MrIrRstVec) && (mr_sh_n >= MrTdrLen)) begin
            mr_sh_cmp <= mr_sh_cmp + 1;
            if ((jtag_tdo_i === 1'b1) != mr_tdi_h[MrTdrLen-1]) mr_sh_bad <= 1'b1;
          end
          mr_tdi_h <= {mr_tdi_h[62:0], (jtag_tdi_i === 1'b1)};
          mr_sh_n  <= mr_sh_n + 1;
        end
        TapUpdDr: begin
          if (mr_ir == MrIrRstVec) begin
            if (mr_own_entry) begin
              if ((mr_sh_cmp != 0) && !mr_sh_bad) mr_dbg_s(2'd1, 5'd0);
              mr_dc(2'd2);
            end
            mr_tdr_before <= dmi_rst_vec_i;
            mr_tdr_upd    <= mr_tdr_upd + 1;
          end
        end
        TapShIr: mr_irs <= {(jtag_tdi_i === 1'b1), mr_irs[4:1]};
        TapUpdIr: begin
          mr_ir <= (mr_irs == 5'd0) ? 5'h1f : mr_irs;
          if (mr_own_entry) mr_dbg_s(2'd0, (mr_irs == 5'd0) ? 5'h1f : mr_irs);
        end
        default: ;
      endcase
      if ((nx == TapTlr) && (mr_tap != TapTlr)) begin
        if (mr_own_entry) begin
          mr_se(3'd5, 1'b0);
          mr_rc(3'd4);
          mr_jm(1'b1, dmi_rst_vec_i);
        end
        mr_tlr_ev <= mr_tlr_ev + 1;
      end
      if ((nx != TapTlr) && (mr_tap == TapTlr) && mr_own_entry) mr_se(3'd5, 1'b1);
      mr_tap <= nx;
    end
  end

  // ---------------------------------------------------------------------
  // Register trackers. The tracked value of a register is the last value the
  // LSU wrote or read, so a readback always resynchronises it.
  // ---------------------------------------------------------------------
  wire [31:0] mr_wbase = {aw_addr_q[31:3], 3'b000};
  wire [31:0] mr_rbase = {ar_addr_q[31:3], 3'b000};
  wire mr_wlo = wr_ev && (aw_addr_q[2:0] == 3'd0) && (w_strb_q[3:0] == 4'hF);
  wire mr_rd_lo = rd_ev && (ar_addr_q[2:0] == 3'd0);
  wire mr_rd64 = mr_rd_lo && (ar_size_q == 3'd3);
  wire [31:0] mr_rlo = lsu_r_data_i[31:0];
  // A full 32-bit lane write and its lane data, for the 32-bit registers.
  wire mr_wl32 = wr_ev && (wr_strb == 4'hF);
  function automatic int mr_scr_idx(input logic [31:0] a);
    if (in_win(a, ColdBase, ColdEnd)) return int'(a[5:3]);
    if (in_win(a, WarmBase, WarmEnd)) return 8 + int'(a[5:3]);
    return -1;
  endfunction

  logic [6:0] mr_swv = MrSwRstDef;  // SW_RESET_N fields
  logic [6:0] mr_sw_wd = MrSwRstDef;  // last written fields
  logic mr_sw_wd_v = 1'b0;
  // SW_RESET_N fields as the register holds them: the write lands when its
  // AW and W beats are accepted, cycles before the B beat that updates
  // mr_swv. The reset sequencer can move ip_rst_n before that B beat, so the
  // points that compare a tap with the software bit use this copy.
  logic [6:0] mr_swv_e = MrSwRstDef;
  wire [31:0] mr_w_addr = aw_hs ? lsu_aw_addr_i : aw_addr_q;
  wire mr_w_sw = w_hs && (lsu_w_strb_i[0] === 1'b1) && (aw_hs || (aw_out_q != 4'd0)) &&
      (mr_w_addr == MrSwRst);
  logic [31:0] mr_scr[16] = '{default: '0};
  logic [15:0] mr_scr_v = '0;
  always @(posedge clk_i) begin
    if (!mr_srn) mr_swv <= MrSwRstDef;
    else if (mr_wlo && (aw_addr_q == MrSwRst)) mr_swv <= w_data_q[6:0];
    else if (mr_rd_lo && (ar_addr_q == MrSwRst)) mr_swv <= lsu_r_data_i[6:0];
    if (!mr_srn) mr_swv_e <= MrSwRstDef;
    else if (mr_w_sw) mr_swv_e <= lsu_w_data_i[6:0];
    else if (mr_rd_lo && (ar_addr_q == MrSwRst)) mr_swv_e <= lsu_r_data_i[6:0];
    if (mr_w_sw) begin
      mr_sw_wd   <= lsu_w_data_i[6:0];
      mr_sw_wd_v <= 1'b1;
    end
    if (!mr_rst) mr_scr_v <= '0;
    else begin
      int k;
      if (!mr_cpurn) mr_scr_v[15:8] <= '0;
      k = mr_scr_idx(aw_addr_q);
      if (mr_wlo && (k >= 0)) begin
        mr_scr[k]   <= w_data_q[31:0];
        mr_scr_v[k] <= 1'b1;
      end
      k = mr_scr_idx(ar_addr_q);
      if (mr_rd_lo && (k >= 0)) begin
        mr_scr[k]   <= mr_rlo;
        mr_scr_v[k] <= 1'b1;
      end
    end
  end

  // ---------------------------------------------------------------------
  // sep_reset_source_cg (clocked points), cp_reset_class and the TAP reset
  // events of the clock domain.
  // ---------------------------------------------------------------------
  int unsigned mr_ro_cnt = 0;
  logic mr_ro_held = 1'b0;
  logic mr_ro_arm = 1'b0;
  logic mr_ro_low = 1'b0;
  logic mr_ro_bad_q = 1'b0;
  logic [10:0] mr_sn_snap = '0;
  logic [10:0] mr_sn_keep = '0;
  logic [10:0] mr_sn_now_q = '0;
  logic mr_sn_on = 1'b0;
  logic mr_sn_te = 1'b0;
  logic mr_sn_te_ok = 1'b0;
  int unsigned mr_sn_w = 0;
  logic mr_mp_on = 1'b0;
  logic mr_mp_hold = 1'b0;
  logic mr_mp_s0 = 1'b0;
  int unsigned mr_mp_tog = 0;
  logic mr_mp_rel = 1'b0;
  int unsigned mr_mp_cnt = 0;
  wire [10:0] mr_sn_now = {
    km_cond_rst_n_i[0] === 1'b1,
    km_cond_rst_n_i[1] === 1'b1,
    aon_rst_n_i === 1'b1,
    mr_ip[6:1],
    mr_cpurn,
    mr_srn
  };
  always @(posedge clk_i) begin
    logic held;
    logic bad;
    mr_sn_now_q <= mr_sn_now;
    // cp_source_edge
    if (mr_own_cold && mr_rst_fall) mr_se(3'd0, 1'b0);
    if (mr_own_cold && mr_rst_rise) mr_se(3'd0, 1'b1);
    if (mr_own_ret && mr_wdt_fall) mr_se(3'd1, 1'b0);
    if (mr_own_ret && mr_wdt_rise) mr_se(3'd1, 1'b1);
    if (mr_own_ret && mr_dbg_fall) mr_se(3'd2, 1'b0);
    if (mr_own_ret && mr_dbg_rise) mr_se(3'd2, 1'b1);
    if (mr_own_scan && mr_scan_q && !mr_scan) mr_se(3'd3, 1'b0);
    if (mr_own_scan && !mr_scan_q && mr_scan) mr_se(3'd3, 1'b1);
    if (mr_own_entry && mr_trst_fall) mr_se(3'd4, 1'b0);
    if (mr_own_entry && mr_trst_rise) mr_se(3'd4, 1'b1);
    // cp_reset_class (the TAP walk is sampled by the TAP tracker)
    if (mr_rst_fall && (mr_own_ret || mr_own_tmr)) mr_rc(3'd0);
    if (mr_wdt_fall && mr_srn && (mr_own_ret || mr_own_ovr || mr_own_tmr)) mr_rc(3'd1);
    if ((mr_own_ret && |(mr_ip_sw_fall & 7'b101_0110)) ||
        ((mr_own_ovr || mr_own_tmr) && |mr_ip_sw_fall[6:1]))
      mr_rc(3'd2);
    if (mr_dbg_fall && (mr_own_ret || mr_own_tmr)) mr_rc(3'd3);
    if (mr_trst_fall && mr_own_entry) mr_rc(3'd4);
    if (mr_ovr_rise && (mr_own_ovr || mr_own_tmr)) mr_rc(3'd5);
    // cp_jtag_mech, jtag_trst_ni mechanism: the vector before the reset.
    if (mr_trst_fall && mr_own_entry) mr_jm(1'b0, mr_rv_q);

    // cp_release_order
    held = mr_own_rel && mr_rst && mr_fuse && !mr_ext && !mr_srn;
    mr_ro_cnt <= held ? ((mr_ro_cnt < MrHeldK) ? mr_ro_cnt + 1 : mr_ro_cnt) : 0;
    if (!mr_rst || !mr_own_rel) begin
      mr_ro_held <= 1'b0;
      mr_ro_arm  <= 1'b0;
      mr_ro_low  <= 1'b0;
    end else begin
      if (!mr_srn) mr_ro_low <= 1'b1;
      if (held && (mr_ro_cnt == MrHeldK - 1)) begin
        mr_src_t e;
        e          = '0;
        e.ro       = 2'd0;
        e.ro_v     = 1'b1;
        u_sep_reset_source_cg.sample(e);
        mr_ro_held <= 1'b1;
      end
      if (mr_ro_held && !mr_ext_q && mr_ext) mr_ro_arm <= 1'b1;
      if (mr_ro_arm && !mr_srn_q && mr_srn) begin
        mr_src_t e;
        e          = '0;
        e.ro       = 2'd1;
        e.ro_v     = 1'b1;
        u_sep_reset_source_cg.sample(e);
        mr_ro_arm  <= 1'b0;
        mr_ro_held <= 1'b0;
      end
    end
    // Illegal cell: released while a term is missing, override off and no
    // SEC_DIS release, after sep_reset_n was low in this rst_ni high window.
    bad = mr_own_rel && mr_rst && mr_ro_low && mr_srn && (!mr_ext || !mr_fuse) && !mr_sovr &&
        !mr_secdis;
    mr_ro_bad_q <= bad;
    if (bad && !mr_ro_bad_q) begin
      mr_src_t e;
      e      = '0;
      e.ro   = 2'd2;
      e.ro_v = 1'b1;
      u_sep_reset_source_cg.sample(e);
    end

    // cp_scan_bypass
    if (mr_own_scan && ((mr_scan != mr_scan_q) || (mr_te != mr_te_q))) begin
      mr_src_t e;
      e      = '0;
      e.sb   = {mr_scan, mr_te};
      e.sb_v = 1'b1;
      u_sep_reset_source_cg.sample(e);
    end

    // cp_scan_net_effect, the 22 net cells
    if (mr_scan_q && !mr_scan) begin
      mr_sn_on    <= mr_own_scan;
      mr_sn_snap  <= mr_sn_now_q;
      mr_sn_keep  <= ~(mr_sn_now ^ mr_sn_now_q);
      mr_sn_te    <= mr_te;
      mr_sn_te_ok <= 1'b1;
      mr_sn_w     <= 1;
    end else if (mr_sn_on && !mr_scan) begin
      mr_sn_keep <= mr_sn_keep & ~(mr_sn_now ^ mr_sn_snap);
      if (mr_te != mr_sn_te) mr_sn_te_ok <= 1'b0;
      mr_sn_w <= mr_sn_w + 1;
    end else if (mr_sn_on && !mr_scan_q && mr_scan) begin
      mr_sn_on <= 1'b0;
      if (mr_own_scan && mr_sn_te_ok && (mr_sn_w >= MrScanMinW)) begin
        for (int n = 0; n < 11; n++) begin
          if (mr_sn_te ? !mr_sn_now_q[n] : mr_sn_keep[n]) begin
            mr_src_t e;
            e      = '0;
            e.sn   = {1'b0, mr_sn_te, 4'(n)};
            e.sn_v = 1'b1;
            u_sep_reset_source_cg.sample(e);
          end
        end
      end
    end

    // cp_mpc_sync_reset
    if (mr_dbg_fall && mr_own_ret) begin
      mr_mp_on   <= 1'b1;
      mr_mp_hold <= 1'b1;
      mr_mp_s0   <= (mpc_run_sync_i === 1'b1);
      mr_mp_tog  <= 0;
      mr_mp_rel  <= 1'b0;
    end else if (mr_mp_on && !mr_dbg) begin
      if ((mpc_run_req_i === 1'b1) != mr_mpc_q) mr_mp_tog <= mr_mp_tog + 1;
      if ((mpc_run_sync_i === 1'b1) != mr_mp_s0) mr_mp_hold <= 1'b0;
    end else if (mr_mp_on && mr_dbg_rise) begin
      mr_mp_on <= 1'b0;
      if (mr_own_ret && (mr_mp_tog != 0) && mr_mp_hold) begin
        mr_src_t e;
        e      = '0;
        e.ms   = 1'b0;
        e.ms_v = 1'b1;
        u_sep_reset_source_cg.sample(e);
      end
      mr_mp_rel <= 1'b1;
      mr_mp_cnt <= 0;
    end else if (mr_mp_rel) begin
      mr_mp_cnt <= mr_mp_cnt + 1;
      if ((mpc_run_sync_i === 1'b1) == (mpc_run_req_i === 1'b1)) begin
        mr_mp_rel <= 1'b0;
        if (mr_own_ret) begin
          mr_src_t e;
          e      = '0;
          e.ms   = 1'b1;
          e.ms_v = 1'b1;
          u_sep_reset_source_cg.sample(e);
        end
      end else if (mr_mp_cnt >= 2 + MrMpcAllow) mr_mp_rel <= 1'b0;
    end
  end

  // ---------------------------------------------------------------------
  // sep_clk_domain_cg, cp_refcnt_ratio and the TDR update check.
  // ---------------------------------------------------------------------
  logic mr_wclk_l = 1'b0;
  logic mr_rclk_l = 1'b0;
  int unsigned mr_wclk_age = MrClkRecent;
  int unsigned mr_rclk_age = MrClkRecent;
  int unsigned mr_tdr_seen = 0;
  logic [1:0] mr_tdr_dly = 2'd0;
  always @(posedge clk_i) begin
    logic [31:0] wa;
    logic [31:0] ra;
    mr_wclk_l   <= (clk_wdt_i === 1'b1);
    mr_rclk_l   <= (clk_ref_i === 1'b1);
    mr_wclk_age <= ((clk_wdt_i === 1'b1) != mr_wclk_l) ? 0 :
        ((mr_wclk_age < MrClkRecent) ? mr_wclk_age + 1 : mr_wclk_age);
    mr_rclk_age <= ((clk_ref_i === 1'b1) != mr_rclk_l) ? 0 :
        ((mr_rclk_age < MrClkRecent) ? mr_rclk_age + 1 : mr_rclk_age);
    wa = aw_addr_q;
    ra = ar_addr_q;
    if (((wr_ev && in_blk(
            wa, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE
        )) || (rd_ev && in_blk(
            ra, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE
        ))) && (mr_wclk_age < MrClkRecent) && (mr_own_cold || mr_own_tmr))
      mr_dc(2'd0);
    if (((wr_ev && ({wa[31:3], 3'b000} == MrRefCnt)) ||
         (rd_ev && ({ra[31:3], 3'b000} == MrRefCnt))) && (mr_rclk_age < MrClkRecent) &&
        mr_own_tmr)
      mr_dc(2'd1);
    // cp_xdomain_phase: clk_ref_i quartile at the clk_i edge that completes
    // a REFERENCE_COUNTER read.
    if (rd_ev && ({ra[31:3], 3'b000} == MrRefCnt) && mr_own_tmr) begin
      mr_clk_t e;
      e      = '0;
      e.xp   = mr_quart($realtime - mr_t_ref[0], mr_t_ref[0] - mr_t_ref[1]);
      e.xp_v = 1'b1;
      u_sep_clk_domain_cg.sample(e);
    end
    // cp_rstvec_tdr, the Update-DR cell: two clk_i edges after the update.
    if (mr_tdr_upd != mr_tdr_seen) begin
      mr_tdr_seen <= mr_tdr_upd;
      mr_tdr_dly  <= 2'd2;
    end else if (mr_tdr_dly != 2'd0) begin
      mr_tdr_dly <= mr_tdr_dly - 2'd1;
      if ((mr_tdr_dly == 2'd1) && (dmi_rst_vec_i != mr_tdr_before) && mr_own_entry)
        mr_dbg_s(2'd1, 5'd1);
    end
  end

  // cp_refcnt_ratio: four clk_ref_i periods against the clk_i period, exact
  // to MrEdgeTol over the four periods.
  logic [2:0] mr_ratio_last = 3'd7;
  always @(posedge clk_ref_i) begin
    realtime p4;
    realtime pc;
    int n;
    for (int i = 4; i > 0; i--) mr_t_ref[i] = mr_t_ref[i-1];
    mr_t_ref[0] = $realtime;
    p4 = mr_t_ref[0] - mr_t_ref[4];
    pc = mr_t_clk - mr_t_clk_p;
    if (!mr_own_tmr) mr_ratio_last = 3'd7;
    else if ((mr_t_ref[4] > 0.0) && (pc > 0.0)) begin
      logic [2:0] code;
      n    = int'(p4 / (4.0 * pc));
      code = 3'd7;
      if ((p4 - 4.0 * n * pc <= MrEdgeTol) && (4.0 * n * pc - p4 <= MrEdgeTol)) begin
        case (n)
          2: code = 3'd0;
          3: code = 3'd1;
          5: code = 3'd2;
          8: code = 3'd3;
          13: code = 3'd4;
          default: code = 3'd7;
        endcase
      end
      if ((code != 3'd7) && (code != mr_ratio_last)) begin
        mr_cc_t e;
        e      = '0;
        e.rr   = code;
        e.rr_v = 1'b1;
        u_sep_cpu_ctrl_reg_cg.sample(e);
      end
      mr_ratio_last = code;
    end
  end

  // ---------------------------------------------------------------------
  // sep_boot_milestone_cg, cp_trace_activity, sep_static_tieoff_cg.
  // ---------------------------------------------------------------------
  int unsigned mr_smc_st = 0;
  logic mr_smc_l = 1'b0;
  logic [31:0] mr_pw_addr[16] = '{default: '0};
  logic [15:0] mr_pw_v = '0;
  logic [3:0] mr_pw_wp = '0;
  logic mr_ff_arm = 1'b0;
  logic mr_ta_on = 1'b0;
  logic mr_ta_clean = 1'b0;
  logic mr_ta_arm = 1'b0;
  int unsigned mr_te_st = 0;
  always @(posedge clk_i) begin
    logic tv;
    tv = (cpu_trace_valid_i === 1'b1);
    // cp_smc_status_follow
    mr_smc_l  <= (smc_fuse_done_i === 1'b1);
    mr_smc_st <= ((smc_fuse_done_i === 1'b1) != mr_smc_l) ? 0 :
        ((mr_smc_st < MrSmcSettle) ? mr_smc_st + 1 : mr_smc_st);
    if (mr_own_rel && mr_rd_lo && (ar_addr_q == MrSmcSense) && (mr_smc_st >= MrSmcSettle)) begin
      mr_boot_t e;
      e      = '0;
      e.sf   = {(smc_fuse_done_i === 1'b1), lsu_r_data_i[0]};
      e.sf_v = 1'b1;
      u_sep_boot_milestone_cg.sample(e);
    end
    // cp_presense_window
    if (!mr_rst) mr_pw_v <= '0;
    else if (mr_own_rel && r_any && !mr_secdis && in_blk(
            ar_addr_q, SEP_EFUSE_MAP_REG_MAP_BASE_ADDR, SEP_EFUSE_MAP_REG_MAP_SIZE
        )) begin
      logic hit;
      hit = 1'b0;
      for (int i = 0; i < 16; i++) if (mr_pw_v[i] && (mr_pw_addr[i] == ar_addr_q)) hit = 1'b1;
      if (!mr_fuse && (lsu_r_resp_i == 2'b10)) begin
        mr_boot_t e;
        e                   = '0;
        e.pw                = 2'd0;
        e.pw_v              = 1'b1;
        u_sep_boot_milestone_cg.sample(e);
        mr_pw_addr[mr_pw_wp] <= ar_addr_q;
        mr_pw_v[mr_pw_wp]    <= 1'b1;
        mr_pw_wp             <= mr_pw_wp + 4'd1;
      end else if (lsu_r_resp_i == AxiOkay) begin
        if (!mr_fuse || hit) begin
          mr_boot_t e;
          e      = '0;
          e.pw   = mr_fuse ? 2'd1 : 2'd2;
          e.pw_v = 1'b1;
          u_sep_boot_milestone_cg.sample(e);
        end
      end
    end
    // cp_first_fetch and cp_trace_activity
    if (!mr_cpurn_q && mr_cpurn) begin
      mr_ff_arm <= (mpc_run_req_i === 1'b1);
      mr_ta_arm <= mr_ta_on && mr_ta_clean;
      mr_ta_on  <= 1'b0;
    end else if (tv && mr_cpurn) begin
      if (mr_ff_arm && mr_own_entry) begin
        mr_boot_t e;
        e      = '0;
        e.ff   = (cpu_trace_addr_i == BootRomBase) ? 2'd0 : 2'd1;
        e.ff_v = 1'b1;
        u_sep_boot_milestone_cg.sample(e);
      end
      if (mr_ta_arm && mr_own_entry) mr_dbg_s(2'd2, 5'd0);
      mr_ff_arm <= 1'b0;
      mr_ta_arm <= 1'b0;
    end
    if (mr_cpurn_q && !mr_cpurn) begin
      mr_ta_on    <= 1'b1;
      mr_ta_clean <= !tv;
    end else if (!mr_cpurn && tv) mr_ta_clean <= 1'b0;
    if (!mr_cpurn && tv && mr_own_entry) begin
      mr_boot_t e;
      e      = '0;
      e.ff   = 2'd2;
      e.ff_v = 1'b1;
      u_sep_boot_milestone_cg.sample(e);
      mr_dbg_s(2'd2, 5'd1);
    end
    // cp_test_en_consumer: every pin of a class equals test_en_i after the
    // settle.
    mr_te_st <= (mr_te != mr_te_q) ? 0 : ((mr_te_st < MrTeSettle + 1) ? mr_te_st + 1 : mr_te_st);
    if (mr_own_scan && (mr_te_st == MrTeSettle)) begin
      for (int c = 0; c < 2; c++) begin
        if (mr_te ? te_pins_one_i[c] : te_pins_zero_i[c]) begin
          mr_tie_t e;
          e      = '0;
          e.tc   = {mr_te, 1'(c)};
          e.tc_v = 1'b1;
          u_sep_static_tieoff_cg.sample(e);
        end
      end
    end
  end

  // ---------------------------------------------------------------------
  // sep_reset_sw_ctrl_cg, cp_reserved_field_write.
  // ---------------------------------------------------------------------
  logic [6:0] mr_mw_a = '0;
  logic [6:0] mr_mw_r = '0;
  longint unsigned mr_mw_t = 0;
  logic mr_pu_arm = 1'b0;
  logic mr_rf_pend = 1'b0;
  logic [1:0] mr_rf_reg = '0;
  logic [1:0] mr_rf_shape = '0;
  logic [31:0] mr_rf_exp = '0;
  logic [31:0] mr_rf_base = '0;
  always @(posedge clk_i) begin
    // cp_field_transition
    if (mr_own_swiso && mr_sw_wd_v && mr_srn && !mr_sovr) begin
      for (int i = 0; i < 7; i++) begin
        if (!mr_ovrd[i] && ((mr_ip_fall[i] && !mr_sw_wd[i]) || (mr_ip_rise[i] && mr_sw_wd[i]))) begin
          mr_swc_t e;
          e      = '0;
          e.ft   = {3'(i), mr_ip_rise[i]};
          e.ft_v = 1'b1;
          u_sep_reset_sw_ctrl_cg.sample(e);
        end
      end
    end
    // cp_multi_field_write: the write, then every written tap moves.
    if (mr_own_swiso && mr_wlo && (aw_addr_q == MrSwRst)) begin
      logic [6:0] a;
      logic [6:0] r;
      a = mr_swv & ~w_data_q[6:0];
      r = ~mr_swv & w_data_q[6:0];
      mr_mw_a <= ($countones(a) >= 2) ? a : 7'd0;
      mr_mw_r <= ($countones(r) >= 2) ? r : 7'd0;
      mr_mw_t <= mr_cyc;
    end else begin
      if ((mr_mw_a != 0) && ((mr_ip & mr_mw_a) == 7'd0)) begin
        if (mr_own_swiso) begin
          mr_swc_t e;
          e      = '0;
          e.mw   = 1'b0;
          e.mw_v = 1'b1;
          u_sep_reset_sw_ctrl_cg.sample(e);
        end
        mr_mw_a <= '0;
      end
      if ((mr_mw_r != 0) && ((mr_ip & mr_mw_r) == mr_mw_r)) begin
        if (mr_own_swiso) begin
          mr_swc_t e;
          e      = '0;
          e.mw   = 1'b1;
          e.mw_v = 1'b1;
          u_sep_reset_sw_ctrl_cg.sample(e);
        end
        mr_mw_r <= '0;
      end
      if (mr_cyc - mr_mw_t > MrSeqTimeout) begin
        mr_mw_a <= '0;
        mr_mw_r <= '0;
      end
    end
    // cp_power_up_value: a cold reset with the hmac field at 0 and a copy
    // running, then the first SW_RESET_N read after the release.
    if (mr_rst_fall) mr_pu_arm <= mr_own_ret && !mr_swv[3] && (dma_busy_i === 1'b1);
    else if (mr_pu_arm && mr_rd_lo && (ar_addr_q == MrSwRst)) begin
      if (mr_own_ret) begin
        mr_swc_t e;
        e = '0;
        if (lsu_r_data_i[3]) begin
          e.pu   = 1'b0;
          e.pu_v = 1'b1;
          u_sep_reset_sw_ctrl_cg.sample(e);
        end
        if (lsu_r_data_i[6:0] == MrSwRstDef) begin
          e.pu   = 1'b1;
          e.pu_v = 1'b1;
          u_sep_reset_sw_ctrl_cg.sample(e);
        end
      end
      mr_pu_arm <= 1'b0;
    end
    // cp_reserved_field_write: register 0 SW_RESET_N, 1 cold, 2 warm SCRATCH.
    if (b_any) begin
      int k;
      k = mr_scr_idx(aw_addr_q);
      if (mr_own_swiso && (mr_wbase == MrSwRst)) begin
        if ((aw_addr_q[2:0] == 3'd0) && (w_strb_q == 8'hFF) && (w_data_q[63:7] != '0)) begin
          mr_rf_pend  <= 1'b1;
          mr_rf_reg   <= 2'd0;
          mr_rf_shape <= 2'd0;
          mr_rf_exp   <= 32'(w_data_q[6:0]);
          mr_rf_base  <= MrSwRst;
        end else if ((aw_addr_q[2:0] == 3'd4) && (w_strb_q == 8'hF0) &&
                     (w_data_q[63:32] != '0)) begin
          mr_rf_pend  <= 1'b1;
          mr_rf_reg   <= 2'd0;
          mr_rf_shape <= 2'd1;
          mr_rf_exp   <= 32'(mr_swv);
          mr_rf_base  <= MrSwRst;
        end else if ((aw_addr_q[2:0] == 3'd0) && (w_strb_q == 8'h0F) &&
                     (w_data_q[31:7] != '0)) begin
          mr_rf_pend  <= 1'b1;
          mr_rf_reg   <= 2'd0;
          mr_rf_shape <= 2'd2;
          mr_rf_exp   <= 32'(w_data_q[6:0]);
          mr_rf_base  <= MrSwRst;
        end
      end else if (mr_own_ccreg && (k >= 0)) begin
        if ((aw_addr_q[2:0] == 3'd0) && (w_strb_q == 8'hFF) && (w_data_q[63:32] != '0)) begin
          mr_rf_pend  <= 1'b1;
          mr_rf_reg   <= (k >= 8) ? 2'd2 : 2'd1;
          mr_rf_shape <= 2'd0;
          mr_rf_exp   <= w_data_q[31:0];
          mr_rf_base  <= mr_wbase;
        end else if ((aw_addr_q[2:0] == 3'd4) && (w_strb_q == 8'hF0) &&
                     (w_data_q[63:32] != '0) && mr_scr_v[k]) begin
          mr_rf_pend  <= 1'b1;
          mr_rf_reg   <= (k >= 8) ? 2'd2 : 2'd1;
          mr_rf_shape <= 2'd1;
          mr_rf_exp   <= mr_scr[k];
          mr_rf_base  <= mr_wbase;
        end
      end
    end else if (mr_rf_pend && mr_rd_lo && (ar_addr_q == mr_rf_base)) begin
      mr_rf_pend <= 1'b0;
      if (((mr_rf_reg == 2'd0) ? (32'(lsu_r_data_i[6:0]) == mr_rf_exp) : (mr_rlo == mr_rf_exp)) &&
          ((mr_rf_reg == 2'd0) ? mr_own_swiso : mr_own_ccreg))
        u_sep_aperture_reserved_access_cg.sample(8'hFF, 2'd0, 3'd0, 2'd0, 1'b0, {
                                                 mr_rf_reg, mr_rf_shape}, 1'b1);
    end
  end

  // ---------------------------------------------------------------------
  // sep_cpu_ctrl_reg_cg (register points), sep_scratch_reg_access_cg and
  // cp_timeout_write_inert.
  // ---------------------------------------------------------------------
  logic mr_rc_armed = 1'b0;
  logic mr_rc_cold = 1'b0;
  logic mr_rc_v1_ok = 1'b0;
  logic [63:0] mr_rc_v1 = '0;
  logic mr_rc_wpend = 1'b0;
  logic [63:0] mr_rc_w = '0;
  logic mr_vi_pend = 1'b0;
  logic mr_nl = 1'b0;
  logic mr_nl_ok = 1'b0;
  logic [30:0] mr_nv = '0;
  logic mr_nv_ok = 1'b0;
  logic mr_nv_pend = 1'b0;
  logic [1:0] mr_nl_pend = '0;  // {pending, value}
  logic [1:0] mr_ss = '0;  // tracked bit 0 of SEP_ and SMC_FUSE_SENSE_STATUS
  logic [1:0] mr_ss_ok = '0;
  logic [1:0] mr_ss_pend = '0;
  logic [1:0] mr_ba_pend[16] = '{default: '0};  // {pending, shape}
  logic [31:0] mr_ba_exp[16] = '{default: '0};
  logic [15:0] mr_ba_lo = '0;
  logic [15:0] mr_ba_hi = '0;
  logic [31:0] mr_ba_lov[16] = '{default: '0};
  always @(posedge clk_i) begin
    int k;
    // cp_refcnt (a): a readback at or above 2^40, the rst_ni pulse, then a
    // first read below 2^40 and a later larger read.
    if (mr_rd64 && (ar_addr_q == MrRefCnt)) begin
      mr_rc_armed <= (lsu_r_data_i >= 64'h100_0000_0000);
      if (mr_rc_cold) begin
        if (!mr_rc_v1_ok) begin
          if (lsu_r_data_i < 64'h100_0000_0000) begin
            mr_rc_v1    <= lsu_r_data_i;
            mr_rc_v1_ok <= 1'b1;
          end else mr_rc_cold <= 1'b0;
        end else begin
          if ((lsu_r_data_i > mr_rc_v1) && mr_own_tmr) begin
            mr_cc_t e;
            e      = '0;
            e.rc   = 1'b0;
            e.rc_v = 1'b1;
            u_sep_cpu_ctrl_reg_cg.sample(e);
          end
          mr_rc_cold <= 1'b0;
        end
      end
      // cp_refcnt (b) and cp_refcnt_write_class: the first read after a
      // 64-bit write.
      if (mr_rc_wpend) begin
        mr_rc_wpend <= 1'b0;
        if (mr_own_tmr) begin
          mr_cc_t e;
          e = '0;
          if (lsu_r_data_i >= mr_rc_w) begin
            e.rc   = 1'b1;
            e.rc_v = 1'b1;
            u_sep_cpu_ctrl_reg_cg.sample(e);
          end
          e = '0;
          if (lsu_r_data_i[63:32] == mr_rc_w[63:32]) begin
            e.rw   = {(mr_rc_w[31:0] >= 32'hFFFF_FFF0), 1'b0};
            e.rw_v = 1'b1;
          end else if (lsu_r_data_i[63:32] == mr_rc_w[63:32] + 32'd1) begin
            e.rw   = {(mr_rc_w[31:0] >= 32'hFFFF_FFF0), 1'b1};
            e.rw_v = 1'b1;
          end
          if (e.rw_v) u_sep_cpu_ctrl_reg_cg.sample(e);
        end
      end
    end
    if (mr_rst_fall) begin
      mr_rc_cold  <= mr_own_tmr && mr_rc_armed;
      mr_rc_v1_ok <= 1'b0;
    end
    if (wr_ev && (aw_addr_q == MrRefCnt) && (w_strb_q == 8'hFF)) begin
      mr_rc_wpend <= 1'b1;
      mr_rc_w     <= w_data_q;
    end

    // cp_version_id
    if (b_any && (mr_wbase == MrVerId)) mr_vi_pend <= 1'b1;
    else if (mr_vi_pend && mr_rd_lo && (ar_addr_q == MrVerId)) begin
      mr_vi_pend <= 1'b0;
      if ((mr_rlo == MrVerVal) && mr_own_ccreg) begin
        mr_cc_t e;
        e      = '0;
        e.vi_v = 1'b1;
        u_sep_cpu_ctrl_reg_cg.sample(e);
      end
    end
    // SEP_NMI_VEC_LOCK and SEP_NMI_VEC trackers, cp_nmi_lock, cp_nmi_vec.
    if (!mr_srn) begin
      mr_nl_ok <= 1'b0;
      mr_nv_ok <= 1'b0;
    end else begin
      if (mr_rd_lo && (ar_addr_q == MrNmiLock)) begin
        mr_nl    <= lsu_r_data_i[0];
        mr_nl_ok <= 1'b1;
        if (mr_nl_pend[1] && lsu_r_data_i[0] && mr_own_ccreg) begin
          mr_cc_t e;
          e      = '0;
          e.nl   = mr_nl_pend[0];
          e.nl_v = 1'b1;
          u_sep_cpu_ctrl_reg_cg.sample(e);
        end
        mr_nl_pend <= '0;
      end else if (b_any && (aw_addr_q == MrNmiLock) && (w_strb_q[3:0] == 4'hF)) begin
        if (mr_nl_ok && mr_nl) begin
          if (w_data_q[31:0] == 32'h0) mr_nl_pend <= 2'b10;
          else if (w_data_q[31:0] == 32'hFFFF_FFFF) mr_nl_pend <= 2'b11;
        end
        if (w_data_q[0]) mr_nl <= 1'b1;
      end
      if (mr_rd_lo && (ar_addr_q == MrNmiVec)) begin
        if (mr_nv_pend && mr_nv_ok && (lsu_r_data_i[31:1] == mr_nv) && mr_own_ccreg) begin
          mr_cc_t e;
          e      = '0;
          e.nv_v = 1'b1;
          u_sep_cpu_ctrl_reg_cg.sample(e);
        end
        mr_nv      <= lsu_r_data_i[31:1];
        mr_nv_ok   <= 1'b1;
        mr_nv_pend <= 1'b0;
      end else if (b_any && (aw_addr_q == MrNmiVec)) begin
        mr_nv_pend <= mr_nl_ok && mr_nl && mr_nv_ok && (w_data_q[31:1] != mr_nv) &&
            (((w_strb_q == 8'hFF) && (w_data_q[63:32] != '0)) || (w_strb_q == 8'h0F));
        if (!(mr_nl_ok && mr_nl)) mr_nv_ok <= 1'b0;
      end
    end
    // cp_status_ro_write: 0 SEP_FUSE_SENSE_STATUS, 1 SMC_FUSE_SENSE_STATUS.
    for (int r = 0; r < 2; r++) begin
      logic [31:0] ra;
      ra = (r == 0) ? MrSepSense : MrSmcSense;
      if (mr_rd_lo && (ar_addr_q == ra)) begin
        if (mr_ss_pend[r] && mr_ss_ok[r] && (lsu_r_data_i[0] == mr_ss[r]) && mr_own_ccreg) begin
          mr_cc_t e;
          e      = '0;
          e.sr   = 1'(r);
          e.sr_v = 1'b1;
          u_sep_cpu_ctrl_reg_cg.sample(e);
        end
        mr_ss[r]      <= lsu_r_data_i[0];
        mr_ss_ok[r]   <= 1'b1;
        mr_ss_pend[r] <= 1'b0;
      end else if (b_any && (aw_addr_q == ra) && w_strb_q[0]) begin
        mr_ss_pend[r] <= mr_ss_ok[r] && (w_data_q[0] != mr_ss[r]);
      end
    end
    // cp_timeout_write_inert
    if (wr_ev && ((mr_wbase == MrTmoClear) || (mr_wbase == MrTmoMode)) && mr_own_ccreg) begin
      tmo_t e;
      e      = '0;
      e.ti   = (mr_wbase == MrTmoMode);
      e.ti_v = 1'b1;
      u_sep_cpu_ctrl_timeout_inert_cg.sample(e);
    end
    // cp_bank_reg_access
    k = mr_scr_idx(aw_addr_q);
    if (wr_ev && (k >= 0)) begin
      if ((aw_addr_q[2:0] == 3'd0) && (w_strb_q == 8'hFF)) begin
        mr_ba_pend[k] <= {(w_data_q[63:32] != '0), 1'b0};
        mr_ba_exp[k]  <= w_data_q[31:0];
        mr_ba_lo[k]   <= 1'b0;
        mr_ba_hi[k]   <= 1'b0;
      end else if ((aw_addr_q[2:0] == 3'd0) && (w_strb_q == 8'h0F)) begin
        mr_ba_lov[k] <= w_data_q[31:0];
        if (mr_ba_hi[k]) begin
          mr_ba_pend[k] <= 2'b11;
          mr_ba_exp[k]  <= w_data_q[31:0];
          mr_ba_hi[k]   <= 1'b0;
        end else mr_ba_lo[k] <= 1'b1;
      end else if ((aw_addr_q[2:0] == 3'd4) && (w_strb_q == 8'hF0)) begin
        if (w_data_q[63:32] == '0) begin
          mr_ba_lo[k] <= 1'b0;
          mr_ba_hi[k] <= 1'b0;
        end else if (mr_ba_lo[k]) begin
          mr_ba_pend[k] <= 2'b11;
          mr_ba_exp[k]  <= mr_ba_lov[k];
          mr_ba_lo[k]   <= 1'b0;
        end else mr_ba_hi[k] <= 1'b1;
      end
    end
    k = mr_scr_idx(ar_addr_q);
    if (mr_rd64 && (k >= 0)) begin
      if (mr_ba_pend[k][1] && (mr_rlo == mr_ba_exp[k]) && mr_own_ccreg) begin
        mr_scr_t e;
        e      = '0;
        e.ba   = {(k >= 8), 3'(k % 8), mr_ba_pend[k][0]};
        e.ba_v = 1'b1;
        u_sep_scratch_reg_access_cg.sample(e);
      end
      mr_ba_pend[k] <= '0;
    end
  end

  // ---------------------------------------------------------------------
  // Watchdog and wakeup timer (sep_wdt_config_bark_cg,
  // sep_wdt_wakeup_timer_cg). WDT state follows the 32-bit lane of each
  // register; the aon_timer resets with rst_ni.
  // ---------------------------------------------------------------------
  longint unsigned mr_wtick = 0;
  always @(posedge clk_wdt_i) mr_wtick <= mr_wtick + 1;
  logic mr_wd_en = 1'b0;
  logic mr_wd_en_ok = 1'b0;
  logic [31:0] mr_wd_bark = '0;
  logic mr_wd_bark_ok = 1'b0;
  logic [31:0] mr_wd_bite = '0;
  logic [31:0] mr_wd_cnt = '0;
  logic mr_wd_cnt_ok = 1'b0;
  longint unsigned mr_wd_cnt_t = 0;
  logic mr_wd_pair = 1'b0;  // no write between two count reads
  logic [31:0] mr_wd_prev_rd = '0;  // previous WDT read address
  logic mr_ax_ctrl = 1'b0;
  logic mr_bs_forced = 1'b0;
  logic mr_bs_clr = 1'b0;
  logic mr_bs_f0 = 1'b0;
  logic mr_bs_f1 = 1'b0;
  logic mr_rw = 1'b1;
  logic mr_rw_ok = 1'b0;
  logic mr_lk_sticky = 1'b0;
  logic mr_lk_cold = 1'b0;
  logic mr_lk_rw1 = 1'b0;
  logic mr_bt_pend = 1'b0;
  logic [31:0] mr_bt_w = '0;
  logic [31:0] mr_bt_prev = '0;
  logic mr_bt_prev_ok = 1'b0;
  logic [1:0] mr_bt_rw = '0;  // {known, regwen}
  logic mr_bt_cold = 1'b0;
  logic [31:0] mr_to_prev = '0;
  logic mr_to_prev_ok = 1'b0;
  logic mr_to_near = 1'b0;
  logic mr_ad_sz32 = 1'b0;
  logic [31:0] mr_wk_hi = '0;
  logic mr_wk_pre = 1'b0;
  logic [1:0] mr_wk_seen = '0;  // {LO written, HI written} since WKUP_CTRL
  logic mr_wk_first = 1'b0;  // 1 LO written first
  logic mr_wk_exp = 1'b0;
  logic mr_bs_bad_q = 1'b0;
  wire mr_wd_wr = mr_wl32;
  wire [31:0] mr_wd_wa = aw_addr_q;
  wire [31:0] mr_wd_ra = ar_addr_q;
  always @(posedge clk_i) begin
    if (!mr_rst) begin
      mr_wd_en_ok   <= 1'b0;
      mr_wd_bark_ok <= 1'b0;
      mr_wd_cnt_ok  <= 1'b0;
      mr_bs_forced  <= 1'b0;
      mr_bs_clr     <= 1'b0;
      mr_bs_f0      <= 1'b0;
      mr_bs_f1      <= 1'b0;
      mr_rw_ok      <= 1'b0;
      mr_lk_sticky  <= 1'b0;
      mr_bt_pend    <= 1'b0;
      mr_to_near    <= 1'b0;
      mr_wk_exp     <= 1'b0;
      mr_wk_seen    <= '0;
      mr_wk_pre     <= 1'b0;
    end else begin
      if (mr_rst_rise) mr_lk_cold <= mr_own_tmr;
      // Writes.
      if (mr_wd_wr && in_blk(mr_wd_wa, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE)) begin
        case (mr_wd_wa)
          MrWdCtrl: begin
            mr_wd_en    <= wr_data[0];
            mr_wd_en_ok <= 1'b1;
            mr_wd_pair  <= 1'b0;
          end
          MrWdCount: mr_wd_pair <= 1'b0;
          MrWdBark: begin
            mr_bt_pend    <= 1'b1;
            mr_bt_w       <= wr_data;
            mr_bt_prev    <= mr_wd_bark;
            mr_bt_prev_ok <= mr_wd_bark_ok;
            mr_bt_rw      <= {mr_rw_ok, mr_rw};
            mr_bt_cold    <= mr_lk_rw1;
            mr_wd_pair    <= 1'b0;
          end
          MrWdBite: mr_wd_bite <= wr_data;
          MrWdRegwen: begin
            if (!wr_data[0]) begin
              mr_rw    <= 1'b0;
              mr_rw_ok <= 1'b1;
            end else if (mr_rw_ok && !mr_rw) mr_lk_sticky <= 1'b1;
          end
          MrWdIntrTest: begin
            if (wr_data[MrWdBarkBit]) begin
              mr_bs_forced <= 1'b1;
              if (mr_wd_en_ok && !mr_wd_en) mr_bs_f0 <= 1'b1;
              if (mr_wd_en_ok && mr_wd_en && mr_wd_cnt_ok && mr_wd_bark_ok &&
                  (mr_wd_cnt < (mr_wd_bark >> 1)))
                mr_bs_f1 <= 1'b1;
            end
          end
          MrWdIntrState: begin
            if (wr_data[MrWdBarkBit] && mr_bs_forced) begin
              mr_bs_forced <= 1'b0;
              mr_bs_clr    <= 1'b1;
            end
          end
          MrWkCtrl: begin
            mr_wk_exp <= 1'b0;
            if (wr_data[0] && mr_own_tmr && (mr_wk_hi != 0) && mr_wk_pre) begin
              mr_wkup_t e;
              logic [11:0] p;
              p      = wr_data[12:1];
              e      = '0;
              e.wp   = (p == 12'd0) ? 3'd0 : ((p == 12'd1) ? 3'd1 : ((p == 12'hFFF) ? 3'd3 : 3'd2));
              e.wp_v = 1'b1;
              u_sep_wdt_wakeup_timer_cg.sample(e);
              if (mr_wk_seen == 2'b11) begin
                e.wp = mr_wk_first ? 3'd5 : 3'd4;
                u_sep_wdt_wakeup_timer_cg.sample(e);
              end
              mr_wk_exp <= 1'b1;
            end
            mr_wk_seen <= '0;
          end
          MrWkThHi: begin
            mr_wk_hi <= wr_data;
            if (mr_wk_seen == 2'b00) mr_wk_first <= 1'b0;
            mr_wk_seen[0] <= 1'b1;
          end
          MrWkThLo: begin
            if (mr_wk_seen == 2'b00) mr_wk_first <= 1'b1;
            mr_wk_seen[1] <= 1'b1;
          end
          MrWkCntLo: mr_wk_pre <= (wr_data == 32'hFFFF_FFF0);
          default: ;
        endcase
      end
      // Reads.
      if (rd_ev && in_blk(mr_wd_ra, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE)) begin
        mr_wd_prev_rd <= mr_wd_ra;
        case (mr_wd_ra)
          MrWdCtrl: begin
            mr_wd_en    <= rd_data[0];
            mr_wd_en_ok <= 1'b1;
            if (mr_wd_prev_rd == MrWdCount) mr_ax_ctrl <= 1'b1;
          end
          MrWdBark: begin
            mr_wd_bark    <= rd_data;
            mr_wd_bark_ok <= 1'b1;
            if (mr_bt_pend && mr_bt_prev_ok && (mr_bt_w != mr_bt_prev) && mr_own_tmr) begin
              mr_wdt_t e;
              e    = '0;
              e.lk = 2'd0;
              if (rd_data == mr_bt_w) begin
                if (mr_bt_cold) begin
                  e.lk   = 2'd1;
                  e.lk_v = 1'b1;
                end else if (mr_bt_rw == 2'b10) begin
                  e.lk   = 2'd2;
                  e.lk_v = 1'b1;
                end
              end else if ((rd_data == mr_bt_prev) && (mr_bt_rw == 2'b11)) begin
                e.lk   = 2'd3;
                e.lk_v = 1'b1;
              end
              if (e.lk_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            mr_bt_pend <= 1'b0;
            if (mr_bt_cold) mr_lk_rw1 <= 1'b0;
          end
          MrWdBite: mr_wd_bite <= rd_data;
          MrWdRegwen: begin
            if (mr_lk_sticky && !rd_data[0] && mr_own_tmr) begin
              mr_wdt_t e;
              e      = '0;
              e.lk   = 2'd0;
              e.lk_v = 1'b1;
              u_sep_wdt_config_bark_cg.sample(e);
            end
            mr_lk_sticky <= 1'b0;
            mr_rw        <= rd_data[0];
            mr_rw_ok     <= 1'b1;
            if (mr_lk_cold) begin
              mr_lk_rw1  <= rd_data[0];
              mr_lk_cold <= 1'b0;
            end
          end
          MrWdCount: begin
            logic chg;
            chg = mr_wd_cnt_ok && (rd_data != mr_wd_cnt);
            // cp_enable_outcome
            if (mr_own_tmr && mr_wd_cnt_ok && mr_wd_pair && mr_wd_en_ok) begin
              mr_wdt_t e;
              e = '0;
              if (mr_wd_bark_ok && (mr_wd_cnt < mr_wd_bark) && (rd_data >= mr_wd_bark)) begin
                e.eo   = {mr_wd_en, 3'd2};
                e.eo_v = 1'b1;
              end else if (mr_wtick - mr_wd_cnt_t >= MrWdtGap) begin
                e.eo   = {mr_wd_en, (rd_data == mr_wd_cnt) ? 3'd0 : 3'd1};
                e.eo_v = 1'b1;
              end
              if (e.eo_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            // cp_access_x_register
            if (mr_own_tmr && chg && mr_wd_en_ok && mr_wd_en) begin
              mr_wdt_t e;
              e      = '0;
              e.ax_v = 1'b1;
              if (mr_ax_ctrl) begin
                e.ax = 1'b0;
                u_sep_wdt_config_bark_cg.sample(e);
              end
              if ((mr_wd_prev_rd == MrWdCount) || (mr_wd_prev_rd == MrWdCtrl)) begin
                e.ax = 1'b1;
                u_sep_wdt_config_bark_cg.sample(e);
              end
            end
            mr_ax_ctrl   <= 1'b0;
            mr_wd_cnt    <= rd_data;
            mr_wd_cnt_ok <= 1'b1;
            mr_wd_cnt_t  <= mr_wtick;
            mr_wd_pair   <= 1'b1;
          end
          MrWdIntrState: begin
            mr_wdt_t e;
            e      = '0;
            e.bs_v = mr_own_tmr;
            if (mr_bs_f0 && rd_data[MrWdBarkBit]) begin
              e.bs = 3'd2;
              if (e.bs_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            if (mr_bs_f1 && rd_data[MrWdBarkBit]) begin
              e.bs = 3'd3;
              if (e.bs_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            if (mr_bs_clr && !rd_data[MrWdBarkBit]) begin
              e.bs = 3'd1;
              if (e.bs_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            if (rd_data[MrWdBarkBit] && !mr_bs_forced) begin
              e.bs = 3'd0;
              if (e.bs_v) u_sep_wdt_config_bark_cg.sample(e);
            end
            mr_bs_f0  <= 1'b0;
            mr_bs_f1  <= 1'b0;
            mr_bs_clr <= 1'b0;
            if (rd_data[0] && mr_wk_exp && (mr_wk_hi != 0) && mr_own_tmr) begin
              mr_wkup_t w;
              w         = '0;
              w.wp      = 3'd6;
              w.wp_v    = 1'b1;
              u_sep_wdt_wakeup_timer_cg.sample(w);
              mr_wk_exp <= 1'b0;
            end
          end
          MrWkThHi: mr_wk_hi <= rd_data;
          default: ;
        endcase
      end
    end
    // cp_bark_status illegal cell: the bite request in a forced window.
    mr_bs_bad_q <= mr_bs_forced && mr_bite;
    if (mr_bs_forced && mr_bite && !mr_bs_bad_q && mr_own_tmr) begin
      mr_wdt_t e;
      e      = '0;
      e.bs   = 3'd4;
      e.bs_v = 1'b1;
      u_sep_wdt_config_bark_cg.sample(e);
    end
    // cp_thold_order
    if (!mr_own_tmr) mr_to_prev_ok <= 1'b0;
    if (!mr_bark_q && mr_bark && mr_own_tmr) begin
      mr_wdt_t e;
      e      = '0;
      e.to_v = 1'b1;
      if (!mr_bite) begin
        e.to = 2'd0;
        u_sep_wdt_config_bark_cg.sample(e);
      end
      if (mr_to_prev_ok && mr_wd_bark_ok && (mr_wd_bark > mr_to_prev)) begin
        e.to = 2'd1;
        u_sep_wdt_config_bark_cg.sample(e);
      end
      mr_to_prev    <= mr_wd_bark;
      mr_to_prev_ok <= mr_wd_bark_ok;
      mr_to_near    <= mr_wd_bark_ok && (mr_wd_bark[31:16] == 16'hFFFF);
    end
    if (!mr_bite_q && mr_bite && mr_own_tmr) begin
      mr_wdt_t e;
      e      = '0;
      e.to_v = 1'b1;
      if (mr_to_near && (mr_wd_bite[31:16] == 16'hFFFF)) begin
        e.to = 2'd2;
        u_sep_wdt_config_bark_cg.sample(e);
      end
      if (!mr_bark) begin
        e.to = 2'd3;
        u_sep_wdt_config_bark_cg.sample(e);
      end
      mr_to_near <= 1'b0;
    end
    // cp_adapt_stage: a stage handshake of a 32-bit LSU access to the
    // watchdog window, by the lane of the stage address.
    if ((aw_hs && in_blk(lsu_aw_addr_i, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE)))
      mr_ad_sz32 <= (lsu_aw_size_i == 3'd2);
    else if (ar_hs && in_blk(lsu_ar_addr_i, WDT_TIMER_REG_MAP_BASE_ADDR, WDT_TIMER_REG_MAP_SIZE))
      mr_ad_sz32 <= (lsu_ar_size_i == 3'd2);
    if (mr_own_tmr && mr_ad_sz32) begin
      logic [3:0] hs;
      logic [3:0] hi;
      hs[0] = (wdt_axi_req_i.ar_valid && wdt_axi_resp_i.ar_ready) ||
          (wdt_axi_req_i.aw_valid && wdt_axi_resp_i.aw_ready);
      hi[0] = (wdt_axi_req_i.ar_valid && wdt_axi_resp_i.ar_ready) ?
          wdt_axi_req_i.ar.addr[2] : wdt_axi_req_i.aw.addr[2];
      hs[1] = (wdt_axi_off_req_i.ar_valid && wdt_axi_resp_i.ar_ready) ||
          (wdt_axi_off_req_i.aw_valid && wdt_axi_resp_i.aw_ready);
      hi[1] = (wdt_axi_off_req_i.ar_valid && wdt_axi_resp_i.ar_ready) ?
          wdt_axi_off_req_i.ar.addr[2] : wdt_axi_off_req_i.aw.addr[2];
      hs[2] = (wdt_axil_req_i.ar_valid && wdt_axil_resp_i.ar_ready) ||
          (wdt_axil_req_i.aw_valid && wdt_axil_resp_i.aw_ready);
      hi[2] = (wdt_axil_req_i.ar_valid && wdt_axil_resp_i.ar_ready) ?
          wdt_axil_req_i.ar.addr[2] : wdt_axil_req_i.aw.addr[2];
      hs[3] = wdt_tl_h2d_i.a_valid && wdt_tl_d2h_i.a_ready;
      hi[3] = wdt_tl_h2d_i.a_address[2];
      for (int g = 0; g < 4; g++) begin
        if (hs[g] === 1'b1) begin
          mr_wdt_t e;
          e      = '0;
          e.ad   = {2'(g), hi[g] === 1'b1};
          e.ad_v = 1'b1;
          u_sep_wdt_config_bark_cg.sample(e);
        end
      end
    end
  end

  // ---------------------------------------------------------------------
  // CPU-only reset and the bus-error latches (sep_wdt_escalation_fault_cg,
  // cp_latch_x_reset_kind, cp_boot_consequence), the DMA reset points
  // (sep_periph_reset_state_cg, sep_dma_containment_cg).
  // ---------------------------------------------------------------------
  logic [1:0] mr_co_pre = '0;  // {bit 42, bit 40} before the pulse
  logic mr_co_newf = 1'b0;
  logic mr_co_on = 1'b0;
  logic mr_co_rel = 1'b0;
  int unsigned mr_co_cnt = 0;
  logic mr_lt_dma = 1'b0;
  logic [1:0] mr_lt_per = '0;  // PERIPH_BUS_ERR_STATUS bits 3 (otbn) and 2 (kmac)
  logic [1:0] mr_lk_pend = '0;  // {pending, kind}
  logic mr_lk_dma = 1'b0;
  logic [1:0] mr_lk_per = '0;
  logic mr_lk_dma_done = 1'b0;
  logic mr_lk_per_done = 1'b0;
  logic [31:0] mr_dr_pre[9] = '{default: '0};
  logic [8:0] mr_dr_pre_ok = '0;
  logic [31:0] mr_dr_snap[9] = '{default: '0};
  logic [8:0] mr_dr_snap_ok = '0;
  logic [8:0] mr_dr_done = '0;
  logic mr_dr_arm = 1'b0;
  logic mr_dr_wr = 1'b0;
  logic mr_rg_cleared = 1'b0;
  logic mr_rg_pulse = 1'b0;
  logic mr_rg_cold = 1'b0;
  always @(posedge clk_i) begin
    int di;
    // CPU-only pulse.
    if (mr_wdt_fall) begin
      mr_co_pre  <= {mr_vec_q[42], mr_vec_q[40]};
      mr_co_newf <= 1'b0;
      mr_co_on   <= mr_own_ret;
      mr_co_rel  <= 1'b0;
    end else if (mr_co_on && !mr_wdt) begin
      if (|err_pulse_i[8:0]) mr_co_newf <= 1'b1;
    end else if (mr_co_on && mr_wdt_rise) begin
      mr_co_on  <= 1'b0;
      mr_co_rel <= 1'b1;
      mr_co_cnt <= 0;
      if (|err_pulse_i[8:0]) mr_co_newf <= 1'b1;
    end else if (mr_co_rel) begin
      mr_co_cnt <= mr_co_cnt + 1;
      if (|err_pulse_i[8:0]) mr_co_newf <= 1'b1;
      if (mr_co_cnt == MrRelSettle) begin
        mr_co_rel <= 1'b0;
        if (mr_own_ret && !mr_co_newf) begin
          for (int b = 0; b < 2; b++) begin
            logic now;
            now = (b == 0) ? vec_i[40] : vec_i[42];
            if (now) begin
              mr_esc_t e;
              fsa_t    f;
              f      = '0;
              f.bc   = 1'(b);
              f.bc_v = 1'b1;
              u_sep_fault_source_ack_cg.sample(f);
              if (mr_co_pre[b]) begin
                e      = '0;
                e.cs   = 1'(b);
                e.cs_v = 1'b1;
                u_sep_wdt_escalation_fault_cg.sample(e);
              end
            end
          end
        end
      end
    end
    // cp_latch_x_reset_kind: the latch read set before the reset, then the
    // first status read after it.
    if (dbe_rd) mr_lt_dma <= dbe_val[0];
    if (pbe_rd) mr_lt_per <= {pbe_val[3], pbe_val[2]};
    if ((mr_wdt_fall || mr_rst_fall) && mr_own_ret) begin
      mr_lk_pend     <= {1'b1, mr_rst_fall};
      mr_lk_dma      <= mr_lt_dma;
      mr_lk_per      <= mr_lt_per;
      mr_lk_dma_done <= 1'b0;
      mr_lk_per_done <= 1'b0;
    end else if (mr_lk_pend[1]) begin
      if (dbe_rd && mr_lk_dma && !mr_lk_dma_done) begin
        mr_lk_dma_done <= 1'b1;
        if ((dbe_val[0] != mr_lk_pend[0]) && mr_own_ret) begin
          fsa_t f;
          f      = '0;
          f.lk   = {1'b0, mr_lk_pend[0]};
          f.lk_v = 1'b1;
          u_sep_fault_source_ack_cg.sample(f);
        end
      end
      if (pbe_rd && (mr_lk_per != 0) && !mr_lk_per_done) begin
        mr_lk_per_done <= 1'b1;
        if ((((pbe_val[3] & mr_lk_per[1]) | (pbe_val[2] & mr_lk_per[0])) != mr_lk_pend[0]) &&
            mr_own_ret) begin
          fsa_t f;
          f      = '0;
          f.lk   = {1'b1, mr_lk_pend[0]};
          f.lk_v = 1'b1;
          u_sep_fault_source_ack_cg.sample(f);
        end
      end
    end
    // DMA registers: the value read before the cold reset, then the first
    // read after the release and before any DMA write.
    di = -1;
    for (int i = 0; i < 9; i++) if (ar_addr_q == MrDmaAddr[i]) di = i;
    if (rd_ev && (di >= 0)) begin
      mr_dr_pre[di]    <= rd_data;
      mr_dr_pre_ok[di] <= 1'b1;
    end
    if (mr_rst_fall) begin
      mr_dr_arm     <= mr_own_ret;
      mr_dr_snap    <= mr_dr_pre;
      mr_dr_snap_ok <= mr_dr_pre_ok;
      mr_dr_done    <= '0;
      mr_dr_wr      <= 1'b0;
    end else if (mr_dr_arm && mr_rst) begin
      if (wr_ev && in_blk(aw_addr_q, SECURE_DMA_REG_MAP_BASE_ADDR, SECURE_DMA_REG_MAP_SIZE))
        mr_dr_wr <= 1'b1;
      if (rd_ev && (di >= 0) && !mr_dr_wr && mr_dr_snap_ok[di] && !mr_dr_done[di] &&
          mr_own_ret) begin
        logic [31:0] pre;
        pre = mr_dr_snap[di];
        mr_dr_done[di] <= 1'b1;
        if (pre != MrDmaDef[di])
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'(di), 1'b1, 1'b0, 1'b0, 2'd0,
                                             1'b0);
        if ((di == MrDmaRegwen) && (pre[3:0] == 4'h0) && (rd_data[3:0] == 4'h6))
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, 1'b0, 1'b1, 2'd0,
                                             1'b0);
        if ((di == MrDmaHsie) && (pre[10:0] == 11'h0) && (rd_data[10:0] == 11'h7FF))
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, 1'b1, 1'b1, 2'd0,
                                             1'b0);
        if ((di == MrDmaRangeValid) && (pre[0] != 1'b0) && (rd_data[0] == 1'b0))
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, 1'b0, 1'b0, 2'd0,
                                             1'b1);
        if ((di == MrDmaRegwen) && (pre[3:0] != 4'h6) && (rd_data[3:0] == 4'h6))
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, 1'b0, 1'b0, 2'd1,
                                             1'b1);
        if ((di == MrDmaHsie) && (pre[10:0] != 11'h7FF) && (rd_data[10:0] == 11'h7FF))
          u_sep_periph_reset_state_cg.sample(2'd0, 1'b0, 1'b0, 1'b0, 4'd0, 1'b0, 1'b0, 1'b0, 2'd2,
                                             1'b1);
      end
    end
    // cp_dma_lock_recovery: RANGE_REGWEN cleared to 0x0, then a CPU-only pulse
    // or a cold reset, then the next read.
    if (rd_ev && (di == MrDmaRegwen)) begin
      if (mr_rg_pulse && (rd_data[3:0] == 4'h0) && mr_own_ret) begin
        u_sep_dma_containment_cg.sample(2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b1);
      end
      if (mr_rg_cold && (rd_data[3:0] == 4'h6) && mr_own_ret) begin
        u_sep_dma_containment_cg.sample(2'd0, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b1, 1'b1);
      end
      mr_rg_pulse   <= 1'b0;
      mr_rg_cold    <= 1'b0;
      mr_rg_cleared <= (rd_data[3:0] == 4'h0);
    end else begin
      if ((mr_wdt_fall || mr_dbg_fall) && mr_rg_cleared && mr_own_ret) mr_rg_pulse <= 1'b1;
      if (mr_rst_fall && mr_rg_cleared && mr_own_ret) begin
        mr_rg_cold    <= 1'b1;
        mr_rg_pulse   <= 1'b0;
        mr_rg_cleared <= 1'b0;
      end
    end
  end

  // ---------------------------------------------------------------------
  // sep_reset_scope_retention_cg (bank outcome, units, isolation order,
  // never-isolated ports, pulse position, override without isolation) and
  // sep_crypto_reset_cg.
  // ---------------------------------------------------------------------
  int unsigned mr_tlr_seen = 0;
  logic [1:0] mr_bo_pend = '0;
  logic [2:0] mr_bo_cls[2] = '{default: '0};
  logic [31:0] mr_bo_snap[16] = '{default: '0};
  logic [15:0] mr_bo_snap_ok = '0;
  logic [31:0] mr_nu_addr[5][4] = '{default: '{default: '0}};
  logic [31:0] mr_nu_data[5][4] = '{default: '{default: '0}};
  logic [3:0] mr_nu_v[5] = '{default: '0};
  logic [3:0] mr_nu_arm[5] = '{default: '0};
  logic [1:0] mr_nu_wp[5] = '{default: '0};
  longint unsigned mr_ack_clr_t[5] = '{default: 0};
  logic [4:0] mr_rel_wait = '0;
  longint unsigned mr_rel_t[5] = '{default: 0};
  logic mr_ps_on = 1'b0;
  logic mr_ps_fell = 1'b0;
  int unsigned mr_ps_d = 0;
  longint unsigned mr_ps_tw = 0;
  longint unsigned mr_ps_tf = 0;
  logic [1:0] mr_lp_ok = '0;
  longint unsigned mr_lp_t[2] = '{default: 0};
  logic [5:0] mr_on_on = '0;
  logic [5:0] mr_on_ok = '0;
  logic [5:0] mr_on_cond_q = '0;
  logic [5:0] mr_ox_combo_q[6] = '{default: '0};
  int unsigned mr_ox_cnt[6] = '{default: 0};
  logic [3:0] mr_op_state[4] = '{default: '0};  // {phase, first 0 sw 1 override, 0}
  longint unsigned mr_op_t[4] = '{default: 0};
  logic [5:0] mr_ip_s = '0;  // independence step set, ip_rst_n[6:1]
  logic mr_ip_post = 1'b0;
  logic [5:0] mr_ip_done = '0;
  logic [31:0] mr_eg_addr[6][4] = '{default: '{default: '0}};
  logic [31:0] mr_eg_data[6][4] = '{default: '{default: '0}};
  logic [3:0] mr_eg_v[6] = '{default: '0};
  logic [1:0] mr_eg_wp[6] = '{default: '0};

  function automatic int mr_unit(input logic [31:0] a);
    blk_e b;
    b = blk_of(a);
    case (b)
      BLK_SPI: return 0;
      BLK_DMA: return 1;
      BLK_WDT: return 2;
      BLK_AXIL_MBOX: return 3;
      BLK_SCRATCH_COLD, BLK_SCRATCH_WARM: return 4;
      default: return -1;
    endcase
  endfunction

  // Engine domain of a register block, SW_RESET_N bit order 1..5.
  function automatic int mr_engine(input logic [31:0] a);
    blk_e b;
    b = blk_of(a);
    case (b)
      BLK_OTBN: return 1;
      BLK_AES: return 2;
      BLK_HMAC: return 3;
      BLK_KMAC: return 4;
      BLK_ESRC, BLK_CSRNG, BLK_EDN: return 5;
      default: return -1;
    endcase
  endfunction

  always @(posedge clk_i) begin
    int u;
    int g;
    logic tap_ev;
    // Event classes of cp_bank_class_outcome: 0 power-on, 1 watchdog,
    // 2 per-IP software, 3 dbg_rstb_i, 4 TAP.
    tap_ev = mr_trst_fall || (mr_tlr_ev != mr_tlr_seen);
    mr_tlr_seen <= mr_tlr_ev;
    if ((mr_own_swiso || mr_own_entry) &&
        (mr_rst_fall || mr_wdt_fall || mr_eng_rst || mr_dbg_fall || tap_ev)) begin
      logic [2:0] c;
      c = mr_rst_fall ? 3'd0 : (mr_wdt_fall ? 3'd1 : (mr_eng_rst ? 3'd2 :
          (mr_dbg_fall ? 3'd3 : 3'd4)));
      mr_bo_pend    <= 2'b11;
      mr_bo_cls[0]  <= c;
      mr_bo_cls[1]  <= c;
      mr_bo_snap    <= mr_scr;
      for (int k = 0; k < 16; k++) mr_bo_snap_ok[k] <= mr_scr_v[k] && (mr_scr[k] != '0);
    end else if (mr_rd_lo && (mr_scr_idx(ar_addr_q) >= 0)) begin
      int k;
      int b;
      k = mr_scr_idx(ar_addr_q);
      b = (k >= 8) ? 1 : 0;
      if (mr_bo_pend[b] && mr_bo_snap_ok[k]) begin
        mr_bo_pend[b] <= 1'b0;
        if ((mr_own_swiso || mr_own_entry) && ((mr_rlo == mr_bo_snap[k]) || (mr_rlo == '0))) begin
          mr_scope_t e;
          e      = '0;
          e.bo   = {1'(b), mr_bo_cls[b], (mr_rlo == mr_bo_snap[k])};
          e.bo_v = 1'b1;
          u_sep_reset_scope_retention_cg.sample(e);
        end
      end
    end
    if (!mr_own_swiso && !mr_own_entry) mr_bo_pend <= '0;

    // cp_km_reset_condition
    if (mr_own_swiso && mr_sw_ok && !mr_ovrd[0]) begin
      if (mr_ip_fall[0] && (&iso_req_i[13:8])) begin
        mr_scope_t e;
        e      = '0;
        e.km   = 1'b0;
        e.km_v = 1'b1;
        u_sep_reset_scope_retention_cg.sample(e);
      end
      if (mr_ip_rise[0]) begin
        mr_scope_t e;
        e      = '0;
        e.km   = 1'b1;
        e.km_v = 1'b1;
        u_sep_reset_scope_retention_cg.sample(e);
      end
    end

    // cp_iso_order_per_domain and cp_trng_iso_order.
    for (int d = 0; d < 5; d++) begin
      int i;
      logic [13:0] set;
      i   = MrIsoIdx[d];
      set = mr_iso_set(d);
      if (((mr_ack_q & set) != 0) && ((iso_ack_i & set) == 0)) mr_ack_clr_t[d] <= mr_cyc;
      if (mr_own_swiso && mr_ip_sw_fall[i]) begin
        mr_scope_t e;
        e      = '0;
        e.io   = {3'(d), ((iso_ack_i & set) == set) ? 2'd0 : 2'd2};
        e.io_v = 1'b1;
        u_sep_reset_scope_retention_cg.sample(e);
      end
      if (mr_ip_rise[i] && mr_sw_ok && !mr_ovrd[i]) begin
        if (((iso_ack_i & set) == 0) && (mr_cyc - mr_ack_clr_t[d] <= MrIsoAllow)) begin
          if (mr_own_swiso) begin
            mr_scope_t e;
            e      = '0;
            e.io   = {3'(d), 2'd1};
            e.io_v = 1'b1;
            u_sep_reset_scope_retention_cg.sample(e);
            if (d == 4) begin
              e      = '0;
              e.ti_v = 1'b1;
              u_sep_reset_scope_retention_cg.sample(e);
            end
          end
        end else if ((iso_ack_i & set) != 0) begin
          mr_rel_wait[d] <= 1'b1;
          mr_rel_t[d]    <= mr_cyc;
        end
      end else if (mr_rel_wait[d]) begin
        if ((iso_ack_i & set) == 0) begin
          mr_rel_wait[d] <= 1'b0;
          if (mr_own_swiso) begin
            mr_scope_t e;
            e      = '0;
            e.io   = {3'(d), 2'd1};
            e.io_v = 1'b1;
            u_sep_reset_scope_retention_cg.sample(e);
            if (d == 4) begin
              e      = '0;
              e.ti_v = 1'b1;
              u_sep_reset_scope_retention_cg.sample(e);
            end
          end
        end else if (mr_cyc - mr_rel_t[d] > MrIsoAllow) mr_rel_wait[d] <= 1'b0;
      end
    end

    // cp_never_isolated_port and cp_trng_nonmember.
    if (r_any && (mr_own_swiso)) begin
      int p;
      logic iso;
      logic [31:0] a;
      a   = ar_addr_q;
      iso = (lsu_r_resp_i == 2'b10) && (rd_data == MrIsoData);
      p   = -1;
      if (in_win(a, MrTrngLo, MrTrngHi)) p = 0;
      else if (blk_of(a) == BLK_KM_MBOX) p = 1;
      else if (blk_of(a) == BLK_LIFECYCLE) p = 2;
      else if (a == MrPoolStatus) p = 3;
      if ((p >= 0) && ((iso_ack_i & MrAckApproved) != 0)) begin
        if (iso || ((p == 0) ? 1'b1 : (lsu_r_resp_i == AxiOkay))) begin
          mr_scope_t e;
          e      = '0;
          e.np   = {2'(p), iso};
          e.np_v = 1'b1;
          u_sep_reset_scope_retention_cg.sample(e);
        end
      end
      if (!mr_ip[5]) begin
        mr_crst_t e;
        e = '0;
        if ((blk_of(a) == BLK_POOL) && (lsu_r_resp_i == AxiOkay)) begin
          e.tn   = 1'b0;
          e.tn_v = 1'b1;
        end else if (in_win(a, MrTrngLo, MrTrngHi) && !iso) begin
          e.tn   = 1'b1;
          e.tn_v = 1'b1;
        end
        if (e.tn_v) u_sep_crypto_reset_cg.sample(e);
      end
    end

    // cp_no_sw_reset_units: an armed write that reads back unchanged after
    // a software engine reset.
    u = mr_unit(aw_addr_q);
    if (mr_wl32 && (u >= 0)) begin
      logic hit;
      hit = 1'b0;
      for (int j = 0; j < 4; j++) begin
        if (mr_nu_v[u][j] && (mr_nu_addr[u][j] == aw_addr_q)) begin
          mr_nu_data[u][j] <= wr_data;
          mr_nu_arm[u][j]  <= 1'b0;
          hit = 1'b1;
        end
      end
      if (!hit) begin
        mr_nu_addr[u][mr_nu_wp[u]] <= aw_addr_q;
        mr_nu_data[u][mr_nu_wp[u]] <= wr_data;
        mr_nu_v[u][mr_nu_wp[u]]    <= 1'b1;
        mr_nu_arm[u][mr_nu_wp[u]]  <= 1'b0;
        mr_nu_wp[u]                <= mr_nu_wp[u] + 2'd1;
      end
    end else if (mr_eng_rst) begin
      for (int x = 0; x < 5; x++) mr_nu_arm[x] <= mr_nu_v[x];
    end
    u = mr_unit(ar_addr_q);
    if (rd_ev && (u >= 0)) begin
      for (int j = 0; j < 4; j++) begin
        if (mr_nu_arm[u][j] && (mr_nu_addr[u][j] == ar_addr_q)) begin
          mr_nu_arm[u][j] <= 1'b0;
          if ((rd_data == mr_nu_data[u][j]) && ((u == 2) ? mr_own_tmr : mr_own_swiso)) begin
            mr_scope_t e;
            e      = '0;
            e.nu   = 3'(u);
            e.nu_v = 1'b1;
            u_sep_reset_scope_retention_cg.sample(e);
          end
        end
      end
    end

    // cp_pulse_vs_sequence: the domain D of an overlap run is the first
    // field of OTBN, AES, KMAC or Adams Bridge that the write clears.
    if (mr_w_sw && mr_own_ret) begin
      logic [6:0] clr;
      int dd;
      clr = mr_swv_e & ~lsu_w_data_i[6:0] & 7'b101_0110;
      dd  = -1;
      for (int i = 6; i >= 1; i--) if (clr[i]) dd = i;
      if (dd >= 0) begin
        mr_ps_on   <= 1'b1;
        mr_ps_fell <= 1'b0;
        mr_ps_d    <= dd;
        mr_ps_tw   <= mr_cyc;
        for (int c = 0; c < 2; c++) begin
          if (mr_lp_ok[c] && (mr_cyc - mr_lp_t[c] <= MrPulseBand)) begin
            mr_scope_t e;
            e      = '0;
            e.pv   = {1'(c), 2'd0};
            e.pv_v = 1'b1;
            u_sep_reset_scope_retention_cg.sample(e);
          end
        end
      end
    end else if (mr_ps_on) begin
      if (!mr_ps_fell && mr_ip_fall[mr_ps_d]) begin
        mr_ps_fell <= 1'b1;
        mr_ps_tf   <= mr_cyc;
      end else if (!mr_ps_fell && (mr_cyc - mr_ps_tw > MrSeqTimeout)) begin
        mr_ps_on <= 1'b0;
        if (mr_own_ret) begin
          mr_scope_t e;
          e      = '0;
          e.pv   = 3'b0_11;
          e.pv_v = 1'b1;
          u_sep_reset_scope_retention_cg.sample(e);
        end
      end else if (mr_ps_fell && mr_ip[mr_ps_d] && (mr_cyc - mr_ps_tf > MrPulseBand))
        mr_ps_on <= 1'b0;
    end
    for (int c = 0; c < 2; c++) begin
      if ((c == 0) ? mr_wdt_fall : mr_dbg_fall) begin
        mr_lp_ok[c] <= 1'b1;
        mr_lp_t[c]  <= mr_cyc;
        if (mr_ps_on && mr_own_ret) begin
          mr_scope_t e;
          e = '0;
          if (!mr_ps_fell) begin
            e.pv   = {1'(c), 2'd1};
            e.pv_v = 1'b1;
          end else if (!mr_ip[mr_ps_d] || (mr_cyc - mr_ps_tf <= MrPulseBand)) begin
            e.pv   = {1'(c), 2'd2};
            e.pv_v = 1'b1;
          end
          if (e.pv_v) u_sep_reset_scope_retention_cg.sample(e);
        end
      end
    end
    if (!mr_own_ret) begin
      mr_ps_on <= 1'b0;
      mr_lp_ok <= '0;
    end

    // cp_ovrd_no_iso: an override with value 0 while the software bit is 1;
    // the host-path isolate-complete bits of the domain stay 0.
    for (int j = 0; j < 6; j++) begin
      int i;
      logic cond;
      logic [13:0] hm;
      i    = j + 1;
      hm   = mr_host_set(i);
      cond = mr_ovrd[i] && !mr_oval[i];
      mr_on_cond_q[j] <= cond;
      if (cond && !mr_on_cond_q[j]) begin
        mr_on_on[j] <= mr_own_ovr && mr_swv_e[i];
        mr_on_ok[j] <= 1'b1;
      end else if (mr_on_on[j] && cond) begin
        if (!mr_swv_e[i] || !mr_own_ovr) mr_on_on[j] <= 1'b0;
        else if (((iso_ack_i & hm) != 0) && mr_on_ok[j]) begin
          mr_scope_t e;
          mr_on_ok[j] <= 1'b0;
          e      = '0;
          e.on   = {3'(j), 1'b1};
          e.on_v = 1'b1;
          u_sep_reset_scope_retention_cg.sample(e);
        end
      end else if (mr_on_on[j] && !cond) begin
        mr_on_on[j] <= 1'b0;
        if (mr_on_ok[j] && mr_own_ovr) begin
          mr_scope_t e;
          e      = '0;
          e.on   = {3'(j), 1'b0};
          e.on_v = 1'b1;
          u_sep_reset_scope_retention_cg.sample(e);
        end
      end
    end

    // cp_ip_ovrd_x_sw: each (E, V, software bit) held for its settle time.
    for (int j = 0; j < 6; j++) begin
      int i;
      logic [5:0] combo;
      i     = j + 1;
      combo = {3'(j), mr_ovrd[i], mr_ovrd[i] && mr_oval[i], mr_swv_e[i]};
      if ((combo != mr_ox_combo_q[j]) || !mr_sw_ok) mr_ox_cnt[j] <= 0;
      else if (mr_ox_cnt[j] <= MrSwSettle) mr_ox_cnt[j] <= mr_ox_cnt[j] + 1;
      mr_ox_combo_q[j] <= combo;
      if (mr_own_ovr && mr_sw_ok && (combo == mr_ox_combo_q[j]) &&
          (mr_ox_cnt[j] == (mr_ovrd[i] ? MrOvrdSettle : MrSwSettle))) begin
        mr_crst_t e;
        logic expv;
        expv   = mr_ovrd[i] ? mr_oval[i] : mr_swv_e[i];
        e      = '0;
        e.ox   = {combo, (mr_ip[i] != expv)};
        e.ox_v = 1'b1;
        u_sep_crypto_reset_cg.sample(e);
      end
    end

    // cp_ovrd_priority: both the software bit and the override hold the
    // domain; the tap stays low after the first release and rises after the
    // second. State: 0 idle, 1 both, 2 one released, 3 both released.
    for (int j = 0; j < 4; j++) begin
      int i;
      logic swa;
      logic ova;
      i   = j + 1;
      swa = !mr_swv_e[i];
      ova = mr_ovrd[i] && !mr_oval[i];
      case (mr_op_state[j][3:2])
        2'd0: if (swa && ova && !mr_ip[i] && mr_own_ovr) mr_op_state[j] <= 4'b01_0_0;
        2'd1: begin
          if (!swa && !ova) mr_op_state[j] <= '0;
          else if (!swa || !ova) mr_op_state[j] <= {2'd2, swa, 1'b0};
        end
        2'd2: begin
          if (mr_ip[i]) begin
            if (mr_own_ovr) begin
              mr_crst_t e;
              e      = '0;
              e.op   = {2'(j), mr_op_state[j][1], 1'b1};
              e.op_v = 1'b1;
              u_sep_crypto_reset_cg.sample(e);
            end
            mr_op_state[j] <= '0;
          end else if (!swa && !ova) begin
            mr_op_state[j] <= {2'd3, mr_op_state[j][1], 1'b0};
            mr_op_t[j]     <= mr_cyc;
          end
        end
        default: begin
          if (mr_ip[i]) begin
            if (mr_own_ovr) begin
              mr_crst_t e;
              e      = '0;
              e.op   = {2'(j), mr_op_state[j][1], 1'b0};
              e.op_v = 1'b1;
              u_sep_crypto_reset_cg.sample(e);
            end
            mr_op_state[j] <= '0;
          end else if (mr_cyc - mr_op_t[j] > MrSeqTimeout) mr_op_state[j] <= '0;
        end
      endcase
      // An override with value 1 forces the tap high: it is neither a release
      // of the pair nor part of the priority case, so the case ends unsampled.
      if (!mr_own_ovr || (mr_ovrd[i] && mr_oval[i])) mr_op_state[j] <= '0;
    end

    // cp_independence_pair: a step that asserts two or more domains, its
    // release, then a victim read that returns an armed value.
    g = mr_engine(aw_addr_q);
    if (mr_wl32 && (g >= 1)) begin
      logic hit;
      hit = 1'b0;
      for (int j = 0; j < 4; j++) begin
        if (mr_eg_v[g][j] && (mr_eg_addr[g][j] == aw_addr_q)) begin
          mr_eg_data[g][j] <= wr_data;
          hit = 1'b1;
        end
      end
      if (!hit) begin
        mr_eg_addr[g][mr_eg_wp[g]] <= aw_addr_q;
        mr_eg_data[g][mr_eg_wp[g]] <= wr_data;
        mr_eg_v[g][mr_eg_wp[g]]    <= 1'b1;
        mr_eg_wp[g]                <= mr_eg_wp[g] + 2'd1;
      end
    end
    if (mr_wlo && (aw_addr_q == MrSwRst)) begin
      logic [6:0] a;
      a = mr_swv & ~w_data_q[6:0];
      if (a[6:1] != 0) begin
        mr_ip_s    <= ($countones(a[6:1]) >= 2) ? a[6:1] : 6'd0;
        mr_ip_post <= 1'b0;
      end else if ((mr_ip_s != 0) && ((w_data_q[6:1] & mr_ip_s) == mr_ip_s)) begin
        mr_ip_post <= 1'b1;
        mr_ip_done <= '0;
      end
    end
    g = mr_engine(ar_addr_q);
    if (rd_ev && (g >= 1) && mr_ip_post && !mr_ip_s[g-1] && !mr_ip_done[g-1] && mr_own_swiso) begin
      for (int j = 0; j < 4; j++) begin
        if (mr_eg_v[g][j] && (mr_eg_addr[g][j] == ar_addr_q) && (rd_data == mr_eg_data[g][j])) begin
          mr_ip_done[g-1] <= 1'b1;
          for (int ag = 1; ag <= 5; ag++) begin
            if (mr_ip_s[ag-1]) begin
              mr_crst_t e;
              e      = '0;
              e.ip   = {3'(ag), 3'(g)};
              e.ip_v = 1'b1;
              u_sep_crypto_reset_cg.sample(e);
            end
          end
        end
      end
    end
    if (!mr_own_swiso) begin
      mr_ip_s    <= '0;
      mr_ip_post <= 1'b0;
    end
  end

  // ---------------------------------------------------------------------
  // sep_documented_absence_cg: secure_tm_o around the sampling events.
  // ---------------------------------------------------------------------
  logic mr_st_was1 = 1'b0;
  logic mr_st_arm = 1'b0;
  logic mr_st_lvl = 1'b0;
  logic mr_st_strap = 1'b0;
  int unsigned mr_st_rel = 0;  // clk_i edges since the rst_ni release
  int unsigned mr_st_sense = 0;  // clk_i edges since the sense-done rise
  logic mr_st_cap = 1'b0;
  logic [3:0] mr_ne_on = '0;
  logic [3:0] mr_ne_ok = '0;
  logic [3:0] mr_ne_s0 = '0;
  int unsigned mr_ne_hold[4] = '{default: 0};
  logic mr_ss_on = 1'b0;
  logic mr_ss_s0 = 1'b0;
  int unsigned mr_ss_cnt = 0;
  always @(posedge clk_i) begin
    logic chg;
    logic in_win_ev;
    logic [3:0] ev_start;
    logic [3:0] ev_end;
    // cp_secure_tm_state: the clear with rst_ni low and the strap at 1.
    if (mr_rst && mr_stm) mr_st_was1 <= 1'b1;
    if (mr_rst_fall) begin
      mr_st_arm  <= mr_own_stm && mr_st_was1;
      mr_st_was1 <= 1'b0;
    end
    if (!mr_rst) begin
      mr_st_lvl   <= mr_stm;
      mr_st_strap <= mr_strap;
    end
    if (mr_rst_rise) begin
      if (mr_st_arm && mr_own_stm && !mr_st_lvl && mr_st_strap) begin
        mr_abs_t e;
        e      = '0;
        e.st_v = 1'b1;
        u_sep_documented_absence_cg.sample(e);
      end
      mr_st_arm <= 1'b0;
    end
    // Sampling-event windows.
    if (!mr_rst) begin
      mr_st_rel <= 0;
      mr_st_cap <= 1'b0;
    end else if (mr_st_rel < MrStmCapWin + 2) mr_st_rel <= mr_st_rel + 1;
    if (!mr_fuse_q && mr_fuse) mr_st_sense <= 1;
    else if ((mr_st_sense != 0) && (mr_st_sense < MrStmSenseWin + 1))
      mr_st_sense <= mr_st_sense + 1;
    else if (mr_st_sense == MrStmSenseWin + 1) begin
      mr_st_sense <= 0;
      mr_st_cap   <= mr_rst;
    end
    // Early capture: secure_tm_o rises within MrStmCapWin edges of the
    // release, SEC_DIS asserted and the strap at 1.
    chg = mr_rst && mr_rst_q && (mr_stm != mr_stm_q);
    if (chg && mr_stm && (mr_st_rel <= MrStmCapWin) && mr_secdis && mr_strap && mr_own_stm) begin
      mr_abs_t e;
      e      = '0;
      e.ev   = 3'd0;
      e.ev_v = 1'b1;
      u_sep_documented_absence_cg.sample(e);
      mr_st_cap <= 1'b1;
    end
    in_win_ev = (mr_st_rel <= MrStmCapWin + 1) || (mr_st_sense != 0) || (!mr_fuse_q && mr_fuse);
    if (chg && !in_win_ev && mr_own_stm) begin
      mr_abs_t e;
      e      = '0;
      e.ev   = 3'd5;
      e.ev_v = 1'b1;
      if (mr_st_cap) begin
        e.sk   = 1'b1;
        e.sk_v = 1'b1;
      end
      u_sep_documented_absence_cg.sample(e);
    end
    // Non-sampling events: 0 wdt_rst_ni, 1 dbg_rstb_i, 2 software engine
    // reset (ip_rst_n[3]), 3 sep_reset_n override.
    ev_start = {mr_ovr_rise, mr_ip_sw_fall[3], mr_dbg_fall, mr_wdt_fall};
    ev_end   = {mr_ovr_fall, mr_ip_rise[3], mr_dbg_rise, mr_wdt_rise};
    for (int x = 0; x < 4; x++) begin
      if (!mr_rst || !mr_own_stm) mr_ne_on[x] <= 1'b0;
      else if (ev_start[x]) begin
        mr_ne_on[x]   <= 1'b1;
        mr_ne_ok[x]   <= 1'b1;
        mr_ne_s0[x]   <= mr_stm_q;
        mr_ne_hold[x] <= 0;
      end else if (mr_ne_on[x]) begin
        if (mr_stm != mr_ne_s0[x]) mr_ne_ok[x] <= 1'b0;
        if (ev_end[x] || (mr_ne_hold[x] != 0)) mr_ne_hold[x] <= mr_ne_hold[x] + 1;
        if (mr_ne_hold[x] == MrStmSettle) begin
          mr_ne_on[x] <= 1'b0;
          if (mr_ne_ok[x] && (mr_stm == mr_ne_s0[x])) begin
            mr_abs_t e;
            e      = '0;
            e.ev   = 3'(x + 1);
            e.ev_v = 1'b1;
            u_sep_documented_absence_cg.sample(e);
          end
        end
      end
    end
    // cp_stm_strap_stability: after a capture, a strap change and a hold.
    if (!mr_rst || !mr_own_stm) mr_ss_on <= 1'b0;
    else if (mr_st_cap && (mr_strap != mr_strap_q)) begin
      mr_ss_on  <= 1'b1;
      mr_ss_s0  <= mr_stm;
      mr_ss_cnt <= 0;
    end else if (mr_ss_on) begin
      if (mr_stm != mr_ss_s0) mr_ss_on <= 1'b0;
      else if (mr_ss_cnt == MrStmHold) begin
        mr_abs_t e;
        mr_ss_on <= 1'b0;
        e      = '0;
        e.sk   = 1'b0;
        e.sk_v = 1'b1;
        u_sep_documented_absence_cg.sample(e);
      end else mr_ss_cnt <= mr_ss_cnt + 1;
    end
  end

  // =====================================================================
  // Memory apertures, CPU ECC and the CPU debug paths (docs/SEP_FCOV.adoc,
  // memory, boot, reset, WDT and clock groups): sep_mem_aperture_cg,
  // sep_cpu_ecc_irq_cg, and the CPU-path points of sep_debug_trace_cg,
  // sep_documented_absence_cg and sep_fabric_dedicated_port_cg. Every point
  // samples only while graded_owner holds the code of a test that owns the
  // point or the cell. The windows, ages and waits below are choices of the
  // environment; the specification gives none.
  // =====================================================================
  wire mm_own_rom = (graded_owner == FcovOwnSepBootRomApertureSweepTest);
  wire mm_own_sram = (graded_owner == FcovOwnSepSramAxiShapeMatrixTest);
  wire mm_own_tdma = (graded_owner == FcovOwnSepTcmDmaApertureEccTest);
  wire mm_own_trap = (graded_owner == FcovOwnSepTcmEccCpuTrapTest);
  wire mm_own_demux = (graded_owner == FcovOwnSepCpuDemuxUnmappedFetchTest);
  wire mm_own_dmi = (graded_owner == FcovOwnSepDebugMasterTargetMatrixTest);
  wire mm_own_isa = (graded_owner == FcovOwnSepCpuIsaPmpCsrTest);

  localparam int unsigned MmRomRdAge = 16;  // a ROM read request this recent explains a macro request
  localparam int unsigned MmStoreQuiet = 32;  // clk_i edges watched after a ROM store response
  localparam int unsigned MmCoreQuiet = 16;  // edges watched after a core TCM access
  localparam int unsigned MmCeSilent = 64;  // edges of ce_int with mie[30] clear and no trap
  localparam int unsigned MmVecWin = 4;  // clocks on each side of a correctable pulse
  localparam int unsigned MmTrapWait = 8;  // edges from a trace trap beat to its mcause
  localparam int unsigned MmKindWin = 4;  // edges from a macro ECC read to its pulse

  localparam logic [31:0] MmRomLast = BootRomEnd - 32'd8;  // last 64-bit ROM word
  localparam logic [31:0] MmIccmBase = 32'(SEP_ICCM_MEM_BASE_ADDR);
  localparam logic [31:0] MmIccmEnd = MmIccmBase + 32'(SEP_ICCM_MEM_SIZE);
  localparam logic [31:0] MmDccmBase = 32'(SEP_DCCM_MEM_BASE_ADDR);
  localparam logic [31:0] MmDccmEnd = MmDccmBase + 32'(SEP_DCCM_MEM_SIZE);
  // Trap causes (doc/interrupts.adoc, Memory ECC Errors and Non-PIC
  // Interrupt Paths).
  localparam logic [31:0] MmMcauseNmi = 32'hF000_1000;
  localparam logic [4:0] MmCauseCe = 5'h1E;
  localparam logic [1:0] MmBurstFixed = 2'd0;
  localparam logic [1:0] MmBurstIncr = 2'd1;
  localparam logic [1:0] MmBurstWrap = 2'd2;
  localparam logic [1:0] MmRespSlverr = 2'b10;
  localparam logic [1:0] MmRespDecerr = 2'b11;

  typedef struct packed {
    logic [2:0] mx;
    logic mx_v;  // 0..3 ROM {last word, half}; 4/5 ICCM first/last; 6/7 DCCM first/last
    logic as;
    logic as_v;  // ROM access size: 0 byte, 1 half
    logic [2:0] mi;
    logic mi_v;  // 0 ROM request, 1 ROM response, 2 SRAM request, 3 SRAM response, 4 TCM request
    logic [2:0] rm;
    logic rm_v;  // {not OKAY, master 0 CPU LSU 1 m_axi, burst 0 FIXED 1 WRAP}
    logic [3:0] sb;
    logic sb_v;  // {AxBURST, response 0 OKAY 1 SLVERR 2 other}
    logic [3:0] otf;
    logic otf_v;  // {path 0 SRAM read 1 SRAM write 2 ROM read 3 stale beat, third}
    logic [4:0] te;
    logic te_v;  // {double with OKAY, memory 0 ICCM 1 DCCM, class}
    logic [2:0] dt;
    logic dt_v;  // see cp_demux_target
    logic ci;
    logic ci_v;  // 0 ICCM fetch by the IFU, 1 DCCM access by the LSU
  } mm_ap_t;

  covergroup sep_mem_aperture_cg with function sample (mm_ap_t s);
    option.per_instance = 1;
    option.name = "sep_mem_aperture_cg";
    cp_mem_x_class: coverpoint s.mx iff (s.mx_v) {
      bins rom_first_byte = {3'd0};
      bins rom_first_half = {3'd1};
      bins rom_last_byte = {3'd2};
      bins rom_last_half = {3'd3};
      bins iccm_first = {3'd4};
      bins iccm_last = {3'd5};
      bins dccm_first = {3'd6};
      bins dccm_last = {3'd7};
    }
    cp_access_size: coverpoint s.as iff (s.as_v) {bins rom_byte = {1'b0}; bins rom_half = {1'b1};}
    cp_macro_if: coverpoint s.mi iff (s.mi_v) {
      bins rom_request = {3'd0};
      bins rom_response = {3'd1};
      bins sram_request = {3'd2};
      bins sram_response = {3'd3};
      bins tcm_request = {3'd4};
    }
    cp_requesting_master: coverpoint s.rm iff (s.rm_v) {
      bins cpu_lsu_fixed = {3'b000};
      bins cpu_lsu_wrap = {3'b001};
      bins m_axi_fixed = {3'b010};
      bins m_axi_wrap = {3'b011};
      illegal_bins single_beat_not_okay = {[3'b100 : 3'b111]};
    }
    // AxBURST 0 FIXED, 1 INCR, 2 WRAP. FIXED and WRAP sample with 2 or
    // more beats; INCR samples at any length.
    cp_sram_burst: coverpoint s.sb iff (s.sb_v) {
      bins fixed_multi_slverr = {4'b00_01};
      bins wrap_multi_slverr = {4'b10_01};
      illegal_bins fixed_wrap_multi_okay = {4'b00_00, 4'b10_00};
      illegal_bins incr_slverr = {4'b01_01};
    }
    cp_otf_reset_x_path: coverpoint s.otf iff (s.otf_v) {
      bins sram_read_third[] = {[4'b00_00 : 4'b00_10]};
      bins sram_write_third[] = {[4'b01_00 : 4'b01_10]};
      bins rom_read = {4'b10_00};
      illegal_bins beat_without_request_after_release = {[4'b11_00 : 4'b11_11]};
    }
    // Class 0 single data, 1 single ECC, 2 two data, 3 data and ECC, 4 two ECC.
    cp_tcm_ecc: coverpoint s.te iff (s.te_v) {
      bins iccm_single_data = {5'b0_0_000};
      bins iccm_single_ecc = {5'b0_0_001};
      bins iccm_double_2data = {5'b0_0_010};
      bins iccm_double_data_ecc = {5'b0_0_011};
      bins iccm_double_2ecc = {5'b0_0_100};
      bins dccm_single_data = {5'b0_1_000};
      bins dccm_single_ecc = {5'b0_1_001};
      bins dccm_double_2data = {5'b0_1_010};
      bins dccm_double_data_ecc = {5'b0_1_011};
      bins dccm_double_2ecc = {5'b0_1_100};
      illegal_bins double_okay = {
        5'b1_0_010, 5'b1_0_011, 5'b1_0_100, 5'b1_1_010, 5'b1_1_011, 5'b1_1_100
      };
    }
    cp_demux_target: coverpoint s.dt iff (s.dt_v) {
      bins ifu_error_responder = {3'd0};
      bins lsu_rom_port = {3'd1};
      bins lsu_xbar_port = {3'd2};
      illegal_bins ifu_unmapped_not_decerr = {3'd4};
      illegal_bins ifu_port_other_class = {3'd5};
      illegal_bins lsu_rom_address_on_xbar = {3'd6};
      illegal_bins lsu_sram_address_on_rom = {3'd7};
    }
    cp_core_internal_path: coverpoint s.ci iff (s.ci_v) {
      bins iccm_ifu_fetch = {1'b0}; bins dccm_lsu_access = {1'b1};
    }
  endgroup

  typedef struct packed {
    logic [3:0] cc;
    logic cc_v;  // {request mismatch, memory 0 ICCM 1 DCCM, at or above 2^t, mie[30]}
    logic cl;
    logic cl_v;  // 0 t from 0 to 5 reads t, 1 written above 26 reads 26
    logic md;
    logic md_v;  // 0 taken once per arming, 1 no trap with mie[30] clear
    logic de;
    logic de_v;  // 0 single-bit read corrected, 1 double-bit read not OKAY
    logic [1:0] tc;
    logic tc_v;  // {mscause not 1, store}
    logic nf_v;
    logic [2:0] dp;
    logic dp_v;  // 0 bit 367, 1 bit 365, 2 bit 364; 4 wide, 5 and 6 kind mismatch
    logic np;
    logic np_v;  // 0 vector unchanged, 1 changed
  } mm_ecc_t;

  covergroup sep_cpu_ecc_irq_cg with function sample (mm_ecc_t s);
    option.per_instance = 1;
    option.name = "sep_cpu_ecc_irq_cg";
    cp_ce_counter: coverpoint s.cc iff (s.cc_v) {
      bins iccm_below_mie0 = {4'b0_0_0_0};
      bins iccm_above_mie0 = {4'b0_0_1_0};
      bins dccm_below_mie0 = {4'b0_1_0_0};
      bins dccm_below_mie1 = {4'b0_1_0_1};
      bins dccm_above_mie0 = {4'b0_1_1_0};
      bins dccm_above_mie1 = {4'b0_1_1_1};
      ignore_bins iccm_mie1 = {4'b0_0_0_1, 4'b0_0_1_1};
      illegal_bins request_mismatch = {[4'b1_000 : 4'b1_111]};
    }
    cp_ce_clamp: coverpoint s.cl iff (s.cl_v) {
      bins t_0_to_5 = {1'b0}; bins above_26_reads_26 = {1'b1};
    }
    cp_mceip_delivery: coverpoint s.md iff (s.md_v) {
      bins taken_once_per_arming = {1'b0}; bins no_trap_mie30_clear = {1'b1};
    }
    cp_dma_ecc_response: coverpoint s.de iff (s.de_v) {
      bins single_corrected = {1'b0}; bins double_not_okay = {1'b1};
    }
    cp_tcm_trap_cause: coverpoint s.tc iff (s.tc_v) {
      bins dccm_load_mcause5 = {2'b00};
      bins dccm_store_mcause7 = {2'b01};
      illegal_bins mscause_not_1 = {2'b10, 2'b11};
    }
    cp_nmi_fast_path: coverpoint s.nf_v iff (s.nf_v) {bins nmi_vec_fetch = {1'b1};}
    cp_ecc_dbg_pulse: coverpoint s.dp iff (s.dp_v) {
      bins iccm_single_367 = {3'd0};
      bins dccm_single_365 = {3'd1};
      bins dccm_double_364 = {3'd2};
      illegal_bins wider_than_one_clk = {3'd4};
      illegal_bins double_event_single_pulse = {3'd5};
      illegal_bins single_event_double_pulse = {3'd6};
    }
    cp_ecc_no_pic: coverpoint s.np iff (s.np_v) {
      bins vector_unchanged = {1'b0}; illegal_bins vector_changed = {1'b1};
    }
  endgroup

  sep_mem_aperture_cg u_sep_mem_aperture_cg = new();
  sep_cpu_ecc_irq_cg  u_sep_cpu_ecc_irq_cg  = new();

  // One-point sample helpers.
  task automatic mm_ap(input logic [3:0] pt, input logic [4:0] v);
    mm_ap_t e;
    e = '0;
    case (pt)
      4'd0: begin
        e.mx   = v[2:0];
        e.mx_v = 1'b1;
      end
      4'd1: begin
        e.as   = v[0];
        e.as_v = 1'b1;
      end
      4'd2: begin
        e.mi   = v[2:0];
        e.mi_v = 1'b1;
      end
      4'd3: begin
        e.rm   = v[2:0];
        e.rm_v = 1'b1;
      end
      4'd4: begin
        e.sb   = v[3:0];
        e.sb_v = 1'b1;
      end
      4'd5: begin
        e.otf  = v[3:0];
        e.otf_v = 1'b1;
      end
      4'd6: begin
        e.te   = v;
        e.te_v = 1'b1;
      end
      4'd7: begin
        e.dt   = v[2:0];
        e.dt_v = 1'b1;
      end
      default: begin
        e.ci   = v[0];
        e.ci_v = 1'b1;
      end
    endcase
    u_sep_mem_aperture_cg.sample(e);
  endtask

  task automatic mm_ecc(input logic [2:0] pt, input logic [3:0] v);
    mm_ecc_t e;
    e = '0;
    case (pt)
      3'd0: begin
        e.cc   = v;
        e.cc_v = 1'b1;
      end
      3'd1: begin
        e.cl   = v[0];
        e.cl_v = 1'b1;
      end
      3'd2: begin
        e.md   = v[0];
        e.md_v = 1'b1;
      end
      3'd3: begin
        e.de   = v[0];
        e.de_v = 1'b1;
      end
      3'd4: begin
        e.tc   = v[1:0];
        e.tc_v = 1'b1;
      end
      3'd5: e.nf_v = 1'b1;
      3'd6: begin
        e.dp   = v[2:0];
        e.dp_v = 1'b1;
      end
      default: begin
        e.np   = v[0];
        e.np_v = 1'b1;
      end
    endcase
    u_sep_cpu_ecc_irq_cg.sample(e);
  endtask

  task automatic mm_dbg(input logic [1:0] pt, input logic [2:0] v);
    mr_dbg_t e;
    e = '0;
    case (pt)
      2'd0: begin
        e.da   = v[1:0];
        e.da_v = 1'b1;
      end
      2'd1: begin
        e.tv   = v[1:0];
        e.tv_v = 1'b1;
      end
      default: begin
        e.ic   = v;
        e.ic_v = 1'b1;
      end
    endcase
    u_sep_debug_trace_cg.sample(e);
  endtask

  task automatic mm_abs(input logic [1:0] pt, input logic [1:0] v);
    mr_abs_t e;
    e = '0;
    case (pt)
      2'd0: begin
        e.rw   = v[0];
        e.rw_v = 1'b1;
      end
      2'd1: e.rr_v = 1'b1;
      default: begin
        e.du   = v;
        e.du_v = 1'b1;
      end
    endcase
    u_sep_documented_absence_cg.sample(e);
  endtask

  function automatic logic mm_rom(input logic [31:0] a);
    return in_win(a, BootRomBase, BootRomEnd);
  endfunction
  function automatic logic mm_sram(input logic [31:0] a);
    return in_win(a, SramBase, SramEnd);
  endfunction
  function automatic logic [1:0] mm_rcls(input logic [1:0] r);
    if (r == AxiOkay) return 2'd0;
    if (r == MmRespSlverr) return 2'd1;
    return 2'd2;
  endfunction
  // A count at or above 2^t: count field [26:0], exponent field [31:27]
  // (doc/interrupts.adoc, Correctable (single-bit) errors).
  function automatic logic mm_at(input logic [31:0] c);
    return {5'd0, c[26:0]} >= (32'd1 << c[31:27]);
  endfunction

  longint unsigned mm_cyc = 0;  // clk_i edges, the index of the next edge
  always @(posedge clk_i) mm_cyc <= mm_cyc + 1;

  // ---------------------------------------------------------------------
  // CPU-LSU burst attributes of the transaction in flight.
  // ---------------------------------------------------------------------
  logic [7:0] mm_aw_len_q = '0;
  logic [7:0] mm_ar_len_q = '0;
  logic [1:0] mm_aw_burst_q = '0;
  logic [1:0] mm_ar_burst_q = '0;
  always @(posedge clk_i) begin
    if (aw_hs) begin
      mm_aw_len_q   <= lsu_req_i.aw.len;
      mm_aw_burst_q <= lsu_req_i.aw.burst;
    end
    if (ar_hs) begin
      mm_ar_len_q   <= lsu_req_i.ar.len;
      mm_ar_burst_q <= lsu_req_i.ar.burst;
    end
  end

  // ---------------------------------------------------------------------
  // ROM loads and stores on the LSU bus: cp_mem_x_class (ROM cells),
  // cp_access_size, cp_rom_write_response.
  // ---------------------------------------------------------------------
  always @(posedge clk_i) begin
    if (!in_reset && mm_own_rom && ar_hs && mm_rom(lsu_ar_addr_i) && (lsu_ar_size_i <= 3'd1)) begin
      mm_ap(4'd1, {4'd0, lsu_ar_size_i[0]});
      if ({lsu_ar_addr_i[31:3], 3'b000} == BootRomBase) mm_ap(4'd0, {3'd0, lsu_ar_size_i[0]});
      if ({lsu_ar_addr_i[31:3], 3'b000} == MmRomLast) mm_ap(4'd0, {3'd1, lsu_ar_size_i[0]});
    end
    if (mm_own_rom && b_any && mm_rom(aw_addr_q) && (wr_lanes inside {4'd1, 4'd2})) begin
      mm_ap(4'd1, {4'd0, (wr_lanes == 4'd2)});
      if (lsu_b_resp_i != 2'b01) mm_abs(2'd1, 2'd0);
    end
  end

  // ---------------------------------------------------------------------
  // cp_macro_if: request and response phases of the memory macro ports.
  // ---------------------------------------------------------------------
  always @(posedge clk_i) begin
    if (mm_own_rom && (rom_req_i.req === 1'b1)) mm_ap(4'd2, 5'd0);
    if (mm_own_rom && (rom_rsp_i.rvalid === 1'b1)) mm_ap(4'd2, 5'd1);
    if (mm_own_sram && (sram_req_i.req === 1'b1)) mm_ap(4'd2, 5'd2);
    if (mm_own_sram && (sram_rsp_i.rvalid === 1'b1)) mm_ap(4'd2, 5'd3);
    if (mm_own_tdma && ((|tcm_i_clken_i === 1'b1) || (|tcm_d_clken_i === 1'b1))) mm_ap(4'd2, 5'd4);
  end

  // ---------------------------------------------------------------------
  // cp_requesting_master and cp_sram_burst. The CPU LSU uses the single
  // outstanding pairing of the LSU model; the inbound master (m_axi, as the
  // DUT receives it) has its own counters with the same rule.
  // ---------------------------------------------------------------------
  wire mm_in_aw_hs = (in_req_i.aw_valid === 1'b1) && (in_resp_i.aw_ready === 1'b1);
  wire mm_in_ar_hs = (in_req_i.ar_valid === 1'b1) && (in_resp_i.ar_ready === 1'b1);
  wire mm_in_b_hs = (in_resp_i.b_valid === 1'b1) && (in_req_i.b_ready === 1'b1);
  wire mm_in_r_hs = (in_resp_i.r_valid === 1'b1) && (in_req_i.r_ready === 1'b1);
  wire mm_in_r_end = mm_in_r_hs && (in_resp_i.r.last === 1'b1);
  logic [3:0] mm_in_aw_out = '0;
  logic [3:0] mm_in_ar_out = '0;
  logic [55:0] mm_in_aw_a, mm_in_ar_a;
  logic [7:0] mm_in_aw_len, mm_in_ar_len;
  logic [1:0] mm_in_aw_burst, mm_in_ar_burst;
  function automatic logic mm_in_sram(input logic [55:0] a);
    logic [55:0] off;
    // The SEP-local address: an address in the SEP global window has the
    // window base removed, as the inbound remap does.
    off = ((a >= sep_base_i) && (a < (sep_base_i + sep_size_i))) ? (a - sep_base_i) : a;
    return (off >= 56'(SramBase)) && (off < 56'(SramEnd));
  endfunction
  function automatic logic mm_fw(input logic [1:0] b);
    return (b == MmBurstFixed) || (b == MmBurstWrap);
  endfunction
  always @(posedge clk_i) begin
    if (in_reset) begin
      mm_in_aw_out <= '0;
      mm_in_ar_out <= '0;
    end else begin
      if (mm_own_sram && mm_in_b_hs && (mm_in_aw_out == 4'd1) && !mm_in_aw_hs && mm_in_sram(
              mm_in_aw_a
          )) begin
        if ((mm_in_aw_len == 8'd0) && mm_fw(mm_in_aw_burst))
          mm_ap(4'd3, {2'd0, (in_resp_i.b.resp != AxiOkay), 1'b1, (mm_in_aw_burst == MmBurstWrap)});
        if (((mm_in_aw_len != 8'd0) && mm_fw(mm_in_aw_burst)) || (mm_in_aw_burst == MmBurstIncr))
          mm_ap(4'd4, {1'b0, mm_in_aw_burst, mm_rcls(in_resp_i.b.resp)});
      end
      if (mm_own_sram && mm_in_r_hs && (mm_in_ar_out == 4'd1) && !mm_in_ar_hs && mm_in_sram(
              mm_in_ar_a
          )) begin
        if ((mm_in_ar_len != 8'd0 && mm_fw(mm_in_ar_burst)) || (mm_in_ar_burst == MmBurstIncr))
          mm_ap(4'd4, {1'b0, mm_in_ar_burst, mm_rcls(in_resp_i.r.resp)});
        if (mm_in_r_end && (mm_in_ar_len == 8'd0) && mm_fw(mm_in_ar_burst))
          mm_ap(4'd3, {2'd0, (in_resp_i.r.resp != AxiOkay), 1'b1, (mm_in_ar_burst == MmBurstWrap)});
      end
      mm_in_aw_out <= mm_in_aw_out + (mm_in_aw_hs ? 4'd1 : 4'd0) -
          ((mm_in_b_hs && ((mm_in_aw_out != 4'd0) || mm_in_aw_hs)) ? 4'd1 : 4'd0);
      mm_in_ar_out <= mm_in_ar_out + (mm_in_ar_hs ? 4'd1 : 4'd0) -
          ((mm_in_r_end && ((mm_in_ar_out != 4'd0) || mm_in_ar_hs)) ? 4'd1 : 4'd0);
      if (mm_in_aw_hs) begin
        mm_in_aw_a     <= in_req_i.aw.addr;
        mm_in_aw_len   <= in_req_i.aw.len;
        mm_in_aw_burst <= in_req_i.aw.burst;
      end
      if (mm_in_ar_hs) begin
        mm_in_ar_a     <= in_req_i.ar.addr;
        mm_in_ar_len   <= in_req_i.ar.len;
        mm_in_ar_burst <= in_req_i.ar.burst;
      end
      // CPU LSU single-beat FIXED and WRAP accesses at the SRAM aperture.
      if (mm_own_sram && b_any && mm_sram(
              aw_addr_q
          ) && (mm_aw_len_q == 8'd0) && mm_fw(
              mm_aw_burst_q
          ))
        mm_ap(4'd3, {2'd0, (lsu_b_resp_i != AxiOkay), 1'b0, (mm_aw_burst_q == MmBurstWrap)});
      if (mm_own_sram && r_any && mm_sram(
              ar_addr_q
          ) && (mm_ar_len_q == 8'd0) && mm_fw(
              mm_ar_burst_q
          ))
        mm_ap(4'd3, {2'd0, (lsu_r_resp_i != AxiOkay), 1'b0, (mm_ar_burst_q == MmBurstWrap)});
    end
  end

  // ---------------------------------------------------------------------
  // cp_otf_reset_x_path. A single-beat CPU-LSU SRAM access in flight when
  // rst_ni falls: the offset is the clk_i edges after the request handshake
  // edge (AR, or the later of AW and W) and before the fall, against W, the
  // edges strictly between the handshake and the response of the last access
  // of that path that completed alone. A ROM read in flight is the handshake
  // on sep_boot_rom_req with no rvalid yet. After the release, the first R
  // or B beat (rvalid for ROM) must follow a request issued after it. The
  // tracking is ungated; the gate applies at the fall.
  // ---------------------------------------------------------------------
  logic mm_or_pend = 1'b0;
  logic mm_ow_aw = 1'b0;
  logic mm_ow_w = 1'b0;
  longint unsigned mm_or_hs = 0;
  longint unsigned mm_ow_awc = 0;
  longint unsigned mm_ow_wc = 0;
  longint unsigned mm_or_wlen = 0;
  longint unsigned mm_ow_wlen = 0;
  logic mm_rom_pend = 1'b0;
  logic mm_st_sram = 1'b0;
  logic mm_st_rom = 1'b0;
  logic mm_st_post = 1'b0;
  logic mm_st_post_r = 1'b0;
  wire [63:0] mm_ow_anchor = (mm_ow_awc > mm_ow_wc) ? mm_ow_awc : mm_ow_wc;
  wire mm_rom_hs = (rom_req_i.req === 1'b1) && (rom_rsp_i.gnt === 1'b1);
  wire mm_rom_rv = (rom_rsp_i.rvalid === 1'b1);
  always @(posedge clk_i) begin
    if (in_reset) begin
      mm_or_pend <= 1'b0;
      mm_ow_aw   <= 1'b0;
      mm_ow_w    <= 1'b0;
    end else begin
      if (r_hs && mm_or_pend) begin
        if (ar_out_q == 4'd1) mm_or_wlen <= mm_cyc - mm_or_hs - 1;
        mm_or_pend <= 1'b0;
      end
      if (ar_hs && mm_sram(lsu_ar_addr_i) && (lsu_req_i.ar.len == 8'd0)) begin
        mm_or_pend <= 1'b1;
        mm_or_hs   <= mm_cyc;
      end
      if (b_hs) begin
        if (mm_ow_aw && mm_ow_w && (aw_out_q == 4'd1)) mm_ow_wlen <= mm_cyc - mm_ow_anchor - 1;
        mm_ow_aw <= 1'b0;
        mm_ow_w  <= 1'b0;
      end
      if (aw_hs && mm_sram(lsu_aw_addr_i) && (lsu_req_i.aw.len == 8'd0)) begin
        mm_ow_aw  <= 1'b1;
        mm_ow_awc <= mm_cyc;
      end
      if (w_hs && !mm_ow_w) begin
        mm_ow_w  <= 1'b1;
        mm_ow_wc <= mm_cyc;
      end
    end
    if (rst_ni !== 1'b1) mm_rom_pend <= 1'b0;
    else if (mm_rom_hs) mm_rom_pend <= 1'b1;
    else if (mm_rom_rv) mm_rom_pend <= 1'b0;
    // Recovery after the release.
    if (in_reset) begin
      mm_st_post   <= 1'b0;
      mm_st_post_r <= 1'b0;
    end else begin
      if (mm_st_sram) begin
        if ((b_hs || r_hs) && !mm_st_post) begin
          if (mm_own_sram) mm_ap(4'd5, 5'b0_11_00);
          mm_st_sram <= 1'b0;
        end else if (b_hs || r_hs) mm_st_sram <= 1'b0;
        if (aw_hs || ar_hs) mm_st_post <= 1'b1;
      end
      if (mm_st_rom) begin
        if (mm_rom_rv && !mm_st_post_r) begin
          if (mm_own_rom) mm_ap(4'd5, 5'b0_11_00);
          mm_st_rom <= 1'b0;
        end else if (mm_rom_rv) mm_st_rom <= 1'b0;
        if (mm_rom_hs) mm_st_post_r <= 1'b1;
      end
      if (!mm_own_sram) mm_st_sram <= 1'b0;
      if (!mm_own_rom) mm_st_rom <= 1'b0;
    end
  end
  function automatic logic [1:0] mm_third(input longint unsigned el, input longint unsigned w,
                                          output logic ok);
    longint unsigned o;
    ok = (el >= 1) && (w != 0) && ((el - 1) < w);
    o  = el - 1;
    if (o * 3 < w) return 2'd0;
    if (o * 3 < w * 2) return 2'd1;
    return 2'd2;
  endfunction
  always @(negedge rst_ni) begin
    logic [1:0] t;
    logic ok;
    if (mm_own_sram) begin
      if (mm_or_pend) begin
        t = mm_third(mm_cyc - mm_or_hs, mm_or_wlen, ok);
        if (ok) mm_ap(4'd5, {3'b0_00, t});
      end
      if (mm_ow_aw && mm_ow_w) begin
        t = mm_third(mm_cyc - mm_ow_anchor, mm_ow_wlen, ok);
        if (ok) mm_ap(4'd5, {3'b0_01, t});
      end
      mm_st_sram <= mm_or_pend || (mm_ow_aw && mm_ow_w);
    end
    if (mm_own_rom && mm_rom_pend) begin
      mm_ap(4'd5, 5'b0_10_00);
      mm_st_rom <= 1'b1;
    end
  end

  // ---------------------------------------------------------------------
  // TCM model: the last word written through the macro port of each
  // {memory, bank, row}. A macro read returns its data the clock after the
  // request; the read data and ECC against the model give the error kind
  // and position of cp_tcm_ecc. Rows with no write through the port (the
  // backdoor image) have no model entry and give no event.
  // ---------------------------------------------------------------------
  logic [38:0] mm_tm[int unsigned];
  logic [3:0] mm_trd_i = '0;
  logic [55:0] mm_trd_ia = '0;
  logic [1:0] mm_trd_d = '0;
  logic [27:0] mm_trd_da = '0;
  function automatic int unsigned mm_key(input logic m, input int unsigned b,
                                         input logic [13:0] row);
    return (int'(m) << 16) | (b << 14) | int'(row);
  endfunction
  // Error event of the last macro read: memory, class (0 single data, 1
  // single ECC, 2 two data, 3 data and ECC, 4 two ECC) and the written data.
  logic mm_ev = 1'b0;
  logic mm_ev_m = 1'b0;
  logic [2:0] mm_ev_c = '0;
  logic [31:0] mm_ev_wd = '0;
  // cpu_tcm_axi_req transactions in flight.
  wire mm_ct_ar_hs = (tcm_axi_req_i.ar_valid === 1'b1) && (tcm_axi_resp_i.ar_ready === 1'b1);
  wire mm_ct_aw_hs = (tcm_axi_req_i.aw_valid === 1'b1) && (tcm_axi_resp_i.aw_ready === 1'b1);
  wire mm_ct_r_hs = (tcm_axi_resp_i.r_valid === 1'b1) && (tcm_axi_req_i.r_ready === 1'b1);
  wire mm_ct_r_end = mm_ct_r_hs && (tcm_axi_resp_i.r.last === 1'b1);
  wire mm_ct_b_hs = (tcm_axi_resp_i.b_valid === 1'b1) && (tcm_axi_req_i.b_ready === 1'b1);
  wire mm_ct_req = (tcm_axi_req_i.ar_valid === 1'b1) || (tcm_axi_req_i.aw_valid === 1'b1);
  logic [3:0] mm_ct_ar_out = '0;
  logic [3:0] mm_ct_aw_out = '0;
  logic [31:0] mm_ct_ar_a = '0;
  wire mm_ct_busy = (mm_ct_ar_out != 4'd0) || (mm_ct_aw_out != 4'd0) || mm_ct_req ||
      (tcm_axi_req_i.w_valid === 1'b1);
  longint unsigned mm_ct_last = 0;  // edge of the last cpu_tcm activity
  // DMA-path event waiting for its R beat; CPU-path event for the pulse kind.
  logic mm_dp_on = 1'b0;
  logic mm_dp_m = 1'b0;
  logic [2:0] mm_dp_c = '0;
  logic [31:0] mm_dp_wd = '0;
  logic mm_ce_v = 1'b0;
  logic mm_ce_m = 1'b0;
  logic mm_ce_dbl = 1'b0;
  longint unsigned mm_ce_t = 0;
  always @(posedge clk_i) begin
    int unsigned nb;
    int unsigned nd;
    int unsigned ne;
    logic ok;
    logic m;
    logic [31:0] wd;
    logic [38:0] rd;
    logic [38:0] df;
    int unsigned k;
    // Reads of the previous edge: data and ECC now on the response.
    nb = 0;
    nd = 0;
    ne = 0;
    ok = 1'b1;
    m  = 1'b0;
    wd = '0;
    for (int b = 0; b < 4; b++) begin
      if (mm_trd_i[b]) begin
        k = mm_key(1'b0, b, mm_trd_ia[14*b+:14]);
        if (mm_tm.exists(k)) begin
          rd = {tcm_i_recc_i[7*b+:7], tcm_i_rdata_i[32*b+:32]};
          if ($isunknown(rd)) ok = 1'b0;
          else begin
            df = rd ^ mm_tm[k];
            if (df != '0) begin
              nb++;
              nd = $countones(df[31:0]);
              ne = $countones(df[38:32]);
              m  = 1'b0;
              wd = mm_tm[k][31:0];
            end
          end
        end
      end
    end
    for (int b = 0; b < 2; b++) begin
      if (mm_trd_d[b]) begin
        k = mm_key(1'b1, b, mm_trd_da[14*b+:14]);
        if (mm_tm.exists(k)) begin
          rd = {tcm_d_recc_i[7*b+:7], tcm_d_rdata_i[32*b+:32]};
          if ($isunknown(rd)) ok = 1'b0;
          else begin
            df = rd ^ mm_tm[k];
            if (df != '0) begin
              nb++;
              nd = $countones(df[31:0]);
              ne = $countones(df[38:32]);
              m  = 1'b1;
              wd = mm_tm[k][31:0];
            end
          end
        end
      end
    end
    mm_ev <= 1'b0;
    if (ok && (nb == 1) && ((nd + ne) inside {1, 2})) begin
      mm_ev    <= 1'b1;
      mm_ev_m  <= m;
      mm_ev_wd <= wd;
      if ((nd == 1) && (ne == 0)) mm_ev_c <= 3'd0;
      else if ((nd == 0) && (ne == 1)) mm_ev_c <= 3'd1;
      else if (nd == 2) mm_ev_c <= 3'd2;
      else if (nd == 1) mm_ev_c <= 3'd3;
      else mm_ev_c <= 3'd4;
    end
    // Writes of this edge update the model; reads of this edge answer next.
    for (int b = 0; b < 4; b++) begin
      if ((tcm_i_clken_i[b] === 1'b1) && (tcm_i_wren_i[b] === 1'b1)) begin
        k = mm_key(1'b0, b, tcm_i_addr_i[14*b+:14]);
        if ($isunknown({tcm_i_wecc_i[7*b+:7], tcm_i_wdata_i[32*b+:32]})) begin
          if (mm_tm.exists(k)) mm_tm.delete(k);
        end else mm_tm[k] = {tcm_i_wecc_i[7*b+:7], tcm_i_wdata_i[32*b+:32]};
      end
      mm_trd_i[b] <= (tcm_i_clken_i[b] === 1'b1) && (tcm_i_wren_i[b] !== 1'b1);
    end
    for (int b = 0; b < 2; b++) begin
      if ((tcm_d_clken_i[b] === 1'b1) && (tcm_d_wren_i[b] === 1'b1)) begin
        k = mm_key(1'b1, b, tcm_d_addr_i[14*b+:14]);
        if ($isunknown({tcm_d_wecc_i[7*b+:7], tcm_d_wdata_i[32*b+:32]})) begin
          if (mm_tm.exists(k)) mm_tm.delete(k);
        end else mm_tm[k] = {tcm_d_wecc_i[7*b+:7], tcm_d_wdata_i[32*b+:32]};
      end
      mm_trd_d[b] <= (tcm_d_clken_i[b] === 1'b1) && (tcm_d_wren_i[b] !== 1'b1);
    end
    mm_trd_ia <= tcm_i_addr_i;
    mm_trd_da <= tcm_d_addr_i;
  end

  // DMA path (the event with a cpu_tcm read in flight) and CPU path (none).
  always @(posedge clk_i) begin
    if (in_reset) begin
      mm_ct_ar_out <= '0;
      mm_ct_aw_out <= '0;
      mm_dp_on     <= 1'b0;
      mm_ce_v      <= 1'b0;
    end else begin
      if (mm_ct_busy) mm_ct_last <= mm_cyc;
      mm_ct_ar_out <= mm_ct_ar_out + (mm_ct_ar_hs ? 4'd1 : 4'd0) -
          ((mm_ct_r_end && ((mm_ct_ar_out != 4'd0) || mm_ct_ar_hs)) ? 4'd1 : 4'd0);
      mm_ct_aw_out <= mm_ct_aw_out + (mm_ct_aw_hs ? 4'd1 : 4'd0) -
          ((mm_ct_b_hs && ((mm_ct_aw_out != 4'd0) || mm_ct_aw_hs)) ? 4'd1 : 4'd0);
      if (mm_ct_ar_hs) mm_ct_ar_a <= tcm_axi_req_i.ar.addr;
      // cp_mem_x_class TCM cells.
      if (mm_own_tdma && (mm_ct_ar_hs || mm_ct_aw_hs)) begin
        logic [31:0] a;
        a = mm_ct_ar_hs ? tcm_axi_req_i.ar.addr : tcm_axi_req_i.aw.addr;
        if (a == MmIccmBase) mm_ap(4'd0, 5'd4);
        if (a == MmIccmEnd - 32'd4) mm_ap(4'd0, 5'd5);
        if (a == MmDccmBase) mm_ap(4'd0, 5'd6);
        if (a == MmDccmEnd - 32'd4) mm_ap(4'd0, 5'd7);
      end
      // A DMA-path event takes the next R beat of the backdoor port.
      begin
        logic on;
        logic dm;
        logic [2:0] dc;
        logic [31:0] dw;
        logic notok;
        logic [31:0] lane;
        on = mm_dp_on;
        dm = mm_dp_m;
        dc = mm_dp_c;
        dw = mm_dp_wd;
        if (mm_ev && (mm_ct_ar_out != 4'd0)) begin
          on = 1'b1;
          dm = mm_ev_m;
          dc = mm_ev_c;
          dw = mm_ev_wd;
        end
        if (on && mm_ct_r_hs) begin
          notok = (tcm_axi_resp_i.r.resp != AxiOkay);
          lane  = mm_ct_ar_a[2] ? tcm_axi_resp_i.r.data[63:32] : tcm_axi_resp_i.r.data[31:0];
          if (mm_own_tdma) begin
            mm_ap(4'd6, {(dc >= 3'd2) && !notok, dm, dc});
            if ((dc <= 3'd1) && (lane === dw)) mm_ecc(3'd3, 4'd0);
            if ((dc >= 3'd2) && notok) mm_ecc(3'd3, 4'd1);
          end
          on = 1'b0;
        end
        mm_dp_on <= on;
        mm_dp_m  <= dm;
        mm_dp_c  <= dc;
        mm_dp_wd <= dw;
      end
      if (mm_ev && !mm_ct_busy && (mm_ct_ar_out == 4'd0)) begin
        mm_ce_v   <= 1'b1;
        mm_ce_m   <= mm_ev_m;
        mm_ce_dbl <= (mm_ev_c >= 3'd2);
        mm_ce_t   <= mm_cyc;
      end
    end
  end

  // ---------------------------------------------------------------------
  // cp_ecc_dbg_pulse and cp_ecc_no_pic: ext_debug_bus_o bits 367 (ICCM
  // single), 365 (DCCM single) and 364 (DCCM double) on a CPU access (no
  // cpu_tcm activity in the last MmCoreQuiet edges).
  // ---------------------------------------------------------------------
  logic [2:0] mm_pq = '0;
  logic [2:0] mm_pon = '0;
  int unsigned mm_pw[3] = '{default: 0};
  logic [42:0] mm_vec_q = '0;
  logic [2:0] mm_vhist = '0;
  logic mm_np_on = 1'b0;
  logic mm_np_chg = 1'b0;
  int unsigned mm_np_cnt = 0;
  always @(posedge clk_i) begin
    logic [2:0] p;
    logic cpu;
    logic vchg;
    p    = {ecc_dbg_i[0] === 1'b1, ecc_dbg_i[1] === 1'b1, ecc_dbg_i[3] === 1'b1};
    cpu  = !mm_ct_busy && ((mm_cyc - mm_ct_last) > MmCoreQuiet);
    vchg = (vec_i !== mm_vec_q);
    for (int i = 0; i < 3; i++) begin
      if (p[i] && !mm_pq[i]) begin
        mm_pon[i] <= mm_own_trap && cpu && !in_reset;
        mm_pw[i]  <= 1;
        if (mm_own_trap && cpu && mm_ce_v && mm_ce_m && ((mm_cyc - mm_ce_t) <= MmKindWin)) begin
          if ((i == 1) && mm_ce_dbl && !p[2]) mm_ecc(3'd6, 4'd5);
          if ((i == 2) && !mm_ce_dbl) mm_ecc(3'd6, 4'd6);
        end
      end else if (p[i]) mm_pw[i] <= mm_pw[i] + 1;
      else if (mm_pq[i]) begin
        if (mm_pon[i] && mm_own_trap) mm_ecc(3'd6, (mm_pw[i] == 1) ? 4'(i) : 4'd4);
        mm_pon[i] <= 1'b0;
      end
    end
    // A correctable pulse: the vector over MmVecWin clocks on each side.
    if (mm_np_on) begin
      if (mm_np_cnt == MmVecWin) begin
        if (mm_own_trap) mm_ecc(3'd7, {3'd0, mm_np_chg});
        mm_np_on <= 1'b0;
      end else begin
        mm_np_chg <= mm_np_chg || vchg;
        mm_np_cnt <= mm_np_cnt + 1;
      end
    end else if (mm_own_trap && cpu && !in_reset && ((p[0] && !mm_pq[0]) || (p[1] && !mm_pq[1]))) begin
      mm_np_on  <= 1'b1;
      mm_np_chg <= (|mm_vhist) || vchg;
      mm_np_cnt <= 0;
    end
    mm_pq    <= p;
    mm_vec_q <= vec_i;
    mm_vhist <= {mm_vhist[1:0], vchg};
  end

  // ---------------------------------------------------------------------
  // cp_ce_counter and cp_ce_clamp: the correctable counters of the trap
  // unit. A sample at each change of a counter or of mie[30]; the request
  // is the per-memory term of ce_int (mdccme_ce_req, miccme_ce_req).
  // ---------------------------------------------------------------------
  logic [31:0] mm_dc_q = '0;
  logic [31:0] mm_ic_q = '0;
  logic mm_mie5_q = 1'b0;
  logic mm_clw_on = 1'b0;
  logic mm_clw_d = 1'b0;
  logic [4:0] mm_clw_t = '0;
  always @(posedge clk_i) begin
    logic mie5;
    logic at;
    logic [4:0] f;
    mie5 = (tlu_mie_i[5] === 1'b1);
    if (!in_reset && mm_own_trap && !$isunknown({tlu_mdccmect_i, tlu_miccmect_i})) begin
      if ((tlu_mdccmect_i != mm_dc_q) || (mie5 != mm_mie5_q)) begin
        at = mm_at(tlu_mdccmect_i);
        mm_ecc(3'd0, {(tlu_dccm_ce_req_i === 1'b1) != at, 1'b1, at, mie5});
      end
      if ((tlu_miccmect_i != mm_ic_q) || (mie5 != mm_mie5_q)) begin
        at = mm_at(tlu_miccmect_i);
        mm_ecc(3'd0, {(tlu_iccm_ce_req_i === 1'b1) != at, 1'b0, at, mie5});
      end
    end
    if (mm_clw_on) begin
      f = mm_clw_d ? tlu_mdccmect_i[31:27] : tlu_miccmect_i[31:27];
      if (mm_own_trap && (mm_clw_t <= 5'd5) && (f == mm_clw_t)) mm_ecc(3'd1, 4'd0);
      if (mm_own_trap && (mm_clw_t > 5'd26) && (f == 5'd26)) mm_ecc(3'd1, 4'd1);
    end
    mm_clw_on <= (tlu_wr_dccmect_i === 1'b1) || (tlu_wr_iccmect_i === 1'b1);
    mm_clw_d  <= (tlu_wr_dccmect_i === 1'b1);
    mm_clw_t  <= tlu_csr_wt_i;
    mm_dc_q   <= tlu_mdccmect_i;
    mm_ic_q   <= tlu_miccmect_i;
    mm_mie5_q <= mie5;
  end

  // ---------------------------------------------------------------------
  // Trace events: cp_traced_event, cp_instr_class, cp_mceip_delivery,
  // cp_tcm_trap_cause, cp_nmi_fast_path.
  // ---------------------------------------------------------------------
  // Class of an encoding (ratified RISC-V M, C and bit-manipulation
  // encodings): 0 M, 1 C, 2 Zba, 3 Zbb, 4 Zbc, 5 Zbs, 7 other.
  function automatic logic [2:0] mm_icls(input logic [31:0] i);
    logic [6:0] op;
    logic [2:0] f3;
    logic [6:0] f7;
    logic [4:0] rs2;
    if (i[1:0] != 2'b11) return 3'd1;
    op  = i[6:0];
    f3  = i[14:12];
    f7  = i[31:25];
    rs2 = i[24:20];
    if (op == 7'b0110011) begin
      if (f7 == 7'b0000001) return 3'd0;
      if ((f7 == 7'b0010000) && (f3 inside {3'b010, 3'b100, 3'b110})) return 3'd2;
      if ((f7 == 7'b0100000) && (f3 inside {3'b100, 3'b110, 3'b111})) return 3'd3;
      if ((f7 == 7'b0000101) && (f3 inside {3'b100, 3'b101, 3'b110, 3'b111})) return 3'd3;
      if ((f7 == 7'b0110000) && (f3 inside {3'b001, 3'b101})) return 3'd3;
      if ((f7 == 7'b0000100) && (f3 == 3'b100) && (rs2 == 5'd0)) return 3'd3;
      if ((f7 == 7'b0000101) && (f3 inside {3'b001, 3'b010, 3'b011})) return 3'd4;
      if ((f7 inside {7'b0010100, 7'b0100100, 7'b0110100}) && (f3 == 3'b001)) return 3'd5;
      if ((f7 == 7'b0100100) && (f3 == 3'b101)) return 3'd5;
    end
    if (op == 7'b0010011) begin
      if ((f7 == 7'b0110000) && (f3 == 3'b001) && (rs2 inside {5'd0, 5'd1, 5'd2, 5'd4, 5'd5}))
        return 3'd3;
      if ((f7 == 7'b0110000) && (f3 == 3'b101)) return 3'd3;
      if ((i[31:20] inside {12'h287, 12'h698}) && (f3 == 3'b101)) return 3'd3;
      if ((f7 inside {7'b0010100, 7'b0100100, 7'b0110100}) && (f3 == 3'b001)) return 3'd5;
      if ((f7 == 7'b0100100) && (f3 == 3'b101)) return 3'd5;
    end
    return 3'd7;
  endfunction

  logic [31:0] mm_mc_q = '0;
  logic mm_md_arm = 1'b0;
  logic mm_md_mst = 1'b0;
  int unsigned mm_sil_cnt = 0;
  logic mm_sil_done = 1'b0;
  logic mm_tw_on = 1'b0;
  logic [4:0] mm_tw_exp = '0;
  int unsigned mm_tw_cnt = 0;
  logic mm_nf_on = 1'b0;
  always @(posedge clk_i) begin
    logic tr;
    logic exc;
    logic intr;
    logic ce_ev;
    logic nmi_new;
    logic [2:0] c;
    tr      = (cpu_trace_valid_i === 1'b1) && !in_reset;
    exc     = (cpu_trace_exc_i === 1'b1);
    intr    = (cpu_trace_interrupt_i === 1'b1);
    ce_ev   = tr && intr && (cpu_trace_ecause_i == MmCauseCe);
    nmi_new = !in_reset && (tlu_mcause_i == MmMcauseNmi) && (mm_mc_q != MmMcauseNmi);
    // cp_traced_event.
    if (mm_own_trap || mm_own_isa) begin
      if (tr && exc && !intr) mm_dbg(2'd1, 3'd0);
      if (ce_ev) mm_dbg(2'd1, 3'd1);
      if (nmi_new) mm_dbg(2'd1, 3'd2);
    end
    // cp_instr_class.
    if (mm_own_isa && tr) begin
      c = mm_icls(cpu_trace_insn_i);
      if (!exc && !intr && (c <= 3'd4)) mm_dbg(2'd2, c);
      if (exc && !intr && (c == 3'd5)) mm_dbg(2'd2, 3'd5);
    end
    // cp_mceip_delivery: one trap per arming of mie[30] with mstatus.MIE set.
    if (!mm_mie5_q && (tlu_mie_i[5] === 1'b1)) begin
      mm_md_arm <= 1'b1;
      mm_md_mst <= (tlu_mstatus_mie_i === 1'b1);
    end else if (mm_md_arm && (tlu_mstatus_mie_i === 1'b1)) mm_md_mst <= 1'b1;
    if (ce_ev) begin
      if (mm_own_trap && mm_md_arm && mm_md_mst) mm_ecc(3'd2, 4'd0);
      mm_md_arm <= 1'b0;
    end
    if ((tlu_ce_int_i === 1'b1) && (tlu_mie_i[5] === 1'b0) && !in_reset) begin
      if (ce_ev) mm_sil_done <= 1'b1;
      else if (!mm_sil_done) begin
        if (mm_sil_cnt + 1 == MmCeSilent) begin
          if (mm_own_trap) mm_ecc(3'd2, 4'd1);
          mm_sil_done <= 1'b1;
        end
        mm_sil_cnt <= mm_sil_cnt + 1;
      end
    end else begin
      mm_sil_cnt  <= 0;
      mm_sil_done <= 1'b0;
    end
    // cp_tcm_trap_cause: a DCCM load or store exception, its mcause and mscause.
    if (mm_tw_on) begin
      if (tlu_mcause_i == 32'(mm_tw_exp)) begin
        if (mm_own_trap) mm_ecc(3'd4, {2'd0, (tlu_mscause_i != 4'd1), (mm_tw_exp == 5'd7)});
        mm_tw_on <= 1'b0;
      end else if (mm_tw_cnt == MmTrapWait) mm_tw_on <= 1'b0;
      mm_tw_cnt <= mm_tw_cnt + 1;
    end
    if (mm_own_trap && tr && exc && !intr && (cpu_trace_ecause_i inside {5'd5, 5'd7}) && in_win(
            cpu_trace_tval_i, MmDccmBase, MmDccmEnd
        )) begin
      mm_tw_on  <= 1'b1;
      mm_tw_exp <= cpu_trace_ecause_i;
      mm_tw_cnt <= 0;
    end
    // cp_nmi_fast_path: the first instruction after the NMI is at SEP_NMI_VEC.
    if (nmi_new) mm_nf_on <= 1'b1;
    else if (mm_nf_on && tr && !exc && !intr) begin
      if (mm_own_trap && (cpu_trace_addr_i == {nmi_vec_i, 1'b0})) mm_ecc(3'd5, 4'd0);
      mm_nf_on <= 1'b0;
    end
    if (in_reset) mm_nf_on <= 1'b0;
    mm_mc_q <= tlu_mcause_i;
  end

  // ---------------------------------------------------------------------
  // cp_dmi_aperture and cp_dmi_uncore: each DMI access of the DTM, and the
  // uncore DMI outputs while dmi_uncore_enable_i is 0.
  // ---------------------------------------------------------------------
  always @(posedge clk_i) begin
    logic up;
    logic uo;
    up = (dmi_addr_i >= 7'h50);
    uo = (dmi_uncore_en_i === 1'b1) || (dmi_uncore_wr_en_i === 1'b1);
    if (mm_own_dmi && !in_reset) begin
      if (dmi_en_i === 1'b1) begin
        mm_dbg(2'd0, {1'b0, (dmi_core_en_i === 1'b1), up});
        if (dmi_uncore_cfg_i !== 1'b1) mm_abs(2'd2, {uo, up});
      end else if ((dmi_uncore_cfg_i !== 1'b1) && uo) mm_abs(2'd2, {1'b1, up});
    end
  end

  // ---------------------------------------------------------------------
  // cp_rom_write_master: a CPU store to the ROM aperture. A ROM macro
  // request (after the interface shim) at the store word is a readback when
  // a read request for that word reached sep_boot_rom_req within
  // MmRomRdAge edges; the cell hits MmStoreQuiet edges after the store
  // response when every such request was a readback.
  // ---------------------------------------------------------------------
  longint unsigned mm_rrd[int unsigned];
  logic mm_sw_on = 1'b0;
  logic mm_sw_bad = 1'b0;
  logic mm_sw_b = 1'b0;
  logic [12:0] mm_sw_word = '0;
  int unsigned mm_sw_cnt = 0;
  always @(posedge clk_i) begin
    int unsigned w;
    logic rb;
    if ((rom_req_i.req === 1'b1) && (rom_req_i.wenable !== 1'b1))
      mm_rrd[int'(rom_req_i.addr[15:3])] = mm_cyc;
    if (mm_sw_on && (rom_macro_req_i === 1'b1) && (rom_macro_addr_i == mm_sw_word)) begin
      w  = int'(mm_sw_word);
      rb = mm_rrd.exists(w) && ((mm_cyc - mm_rrd[w]) <= MmRomRdAge);
      if (!rb) begin
        if (mm_own_rom) mm_abs(2'd0, 2'd1);
        mm_sw_bad <= 1'b1;
      end
    end
    if (in_reset || !mm_own_rom) mm_sw_on <= 1'b0;
    else if (aw_hs && mm_rom(lsu_aw_addr_i)) begin
      mm_sw_on   <= 1'b1;
      mm_sw_bad  <= 1'b0;
      mm_sw_b    <= 1'b0;
      mm_sw_cnt  <= 0;
      mm_sw_word <= 13'((lsu_aw_addr_i - BootRomBase) >> 3);
    end else if (mm_sw_on) begin
      if (b_hs) mm_sw_b <= 1'b1;
      if (mm_sw_b) begin
        if (mm_sw_cnt == MmStoreQuiet) begin
          if (!mm_sw_bad) mm_abs(2'd0, 2'd0);
          mm_sw_on <= 1'b0;
        end
        mm_sw_cnt <= mm_sw_cnt + 1;
      end
    end
  end

  // ---------------------------------------------------------------------
  // cp_demux_target and cp_ext_refused_ifu: the IFU fetch class by ID, the
  // post-demux CPU ports, and the Extension and outbound requests in the
  // window of an unmapped fetch.
  // ---------------------------------------------------------------------
  logic [1:0] mm_ifu_cls[8] = '{default: 2'd0};  // 0 ROM, 1 SRAM, 2 other
  logic mm_eu_on = 1'b0;
  logic mm_eu_leak = 1'b0;
  logic [31:0] mm_eu_a = '0;
  logic [2:0] mm_eu_id = '0;
  function automatic logic [1:0] mm_acls(input logic [31:0] a);
    if (mm_rom(a)) return 2'd0;
    if (mm_sram(a)) return 2'd1;
    return 2'd2;
  endfunction
  wire mm_ifu_ar = (ifu_arvalid_i === 1'b1) && (ifu_arready_i === 1'b1);
  wire mm_ifu_r = (ifu_rvalid_i === 1'b1) && (ifu_rready_i === 1'b1) && (ifu_rlast_i === 1'b1);
  wire mm_lr_ar = (lsu_rom_req_i.ar_valid === 1'b1) && (lsu_rom_resp_i.ar_ready === 1'b1);
  wire mm_lr_aw = (lsu_rom_req_i.aw_valid === 1'b1) && (lsu_rom_resp_i.aw_ready === 1'b1);
  wire mm_lx_ar = (lsu_xbar_req_i.ar_valid === 1'b1) && (lsu_xbar_resp_i.ar_ready === 1'b1);
  wire mm_lx_aw = (lsu_xbar_req_i.aw_valid === 1'b1) && (lsu_xbar_resp_i.aw_ready === 1'b1);
  wire mm_eu_hit = ((ext_req_i.ar_valid === 1'b1) && (ext_req_i.ar.addr == mm_eu_a)) ||
      ((ext_req_i.aw_valid === 1'b1) && (ext_req_i.aw.addr == mm_eu_a)) ||
      ((out_req_i.ar_valid === 1'b1) && (out_req_i.ar.addr[31:0] == mm_eu_a)) ||
      ((out_req_i.aw_valid === 1'b1) && (out_req_i.aw.addr[31:0] == mm_eu_a));
  always @(posedge clk_i) begin
    logic [31:0] la;
    logic [31:0] xa;
    if (in_reset) begin
      mm_eu_on <= 1'b0;
    end else begin
      if (mm_ifu_r) begin
        if (mm_own_demux && (mm_ifu_cls[ifu_rid_i] == 2'd2))
          mm_ap(4'd7, (ifu_rresp_i == MmRespDecerr) ? 5'd0 : 5'd4);
        if (mm_eu_on && (ifu_rid_i == mm_eu_id)) begin
          if (mm_own_demux && !mm_eu_leak && !mm_eu_hit)
            u_sep_fabric_dedicated_port_cg.sample(3'd0, 1'b0, 1'b0, 2'd0, 2'd0, 2'd0, 1'b0, 4'd0,
                                                  1'b0, 1'b1);
          mm_eu_on <= 1'b0;
        end
      end else if (mm_eu_on && mm_eu_hit) mm_eu_leak <= 1'b1;
      if (mm_ifu_ar) begin
        mm_ifu_cls[ifu_arid_i] <= mm_acls(ifu_araddr_i);
        if (!mm_eu_on && (mm_acls(ifu_araddr_i) == 2'd2)) begin
          mm_eu_on   <= 1'b1;
          mm_eu_leak <= 1'b0;
          mm_eu_a    <= ifu_araddr_i;
          mm_eu_id   <= ifu_arid_i;
        end
      end
      if (mm_own_demux) begin
        if ((ifu_rom_req_i.ar_valid === 1'b1) && mm_sram(ifu_rom_req_i.ar.addr)) mm_ap(4'd7, 5'd5);
        if ((ifu_sram_req_i.ar_valid === 1'b1) && mm_rom(ifu_sram_req_i.ar.addr)) mm_ap(4'd7, 5'd5);
        if (mm_lr_ar || mm_lr_aw) begin
          la = mm_lr_ar ? lsu_rom_req_i.ar.addr : lsu_rom_req_i.aw.addr;
          if (mm_rom(la)) mm_ap(4'd7, 5'd1);
          if (mm_sram(la)) mm_ap(4'd7, 5'd7);
        end
        if (mm_lx_ar || mm_lx_aw) begin
          xa = mm_lx_ar ? lsu_xbar_req_i.ar.addr : lsu_xbar_req_i.aw.addr;
          if (mm_sram(xa)) mm_ap(4'd7, 5'd2);
          if (mm_rom(xa)) mm_ap(4'd7, 5'd6);
        end
      end
    end
  end

  // ---------------------------------------------------------------------
  // cp_core_internal_path and cp_tcm_refused_initiator: a core access to
  // the TCM (an ICCM macro read with no cpu_tcm activity in the last
  // MmCoreQuiet edges is an IFU fetch; the LSU M-stage packet gives the LSU
  // loads and stores), then MmCoreQuiet edges with no request on
  // cpu_tcm_axi_req. A request at the accessed word in that window is the
  // illegal cell. Cells: 0 IFU read ICCM, 1 LSU read ICCM, 2 LSU write
  // ICCM, 3 LSU read DCCM, 4 LSU write DCCM.
  // ---------------------------------------------------------------------
  logic [4:0] mm_cq_on = '0;
  logic [4:0] mm_cq_req = '0;
  int unsigned mm_cq_cnt[5] = '{default: 0};
  logic [31:0] mm_cq_a[5] = '{default: '0};
  always @(posedge clk_i) begin
    logic [4:0] ev;
    logic lsu;
    logic [31:0] ra;
    lsu = (lsu_m_valid_i === 1'b1) && (lsu_m_dma_i !== 1'b1);
    ev = '0;
    ev[0] = ((tcm_i_clken_i & ~tcm_i_wren_i) != 4'd0) && !$isunknown(tcm_i_clken_i) &&
        !mm_ct_busy && ((mm_cyc - mm_ct_last) > MmCoreQuiet);
    if (lsu && in_win(lsu_m_addr_i, MmIccmBase, MmIccmEnd)) begin
      ev[1] = (lsu_m_load_i === 1'b1);
      ev[2] = (lsu_m_store_i === 1'b1);
    end
    if (lsu && in_win(lsu_m_addr_i, MmDccmBase, MmDccmEnd)) begin
      ev[3] = (lsu_m_load_i === 1'b1);
      ev[4] = (lsu_m_store_i === 1'b1);
    end
    ra = (tcm_axi_req_i.ar_valid === 1'b1) ? tcm_axi_req_i.ar.addr : tcm_axi_req_i.aw.addr;
    for (int c = 0; c < 5; c++) begin
      if (in_reset || !mm_own_demux) mm_cq_on[c] <= 1'b0;
      else if (mm_cq_on[c]) begin
        if (mm_ct_req) begin
          mm_cq_req[c] <= 1'b1;
          if ((c != 0) && ({ra[31:2], 2'b00} == mm_cq_a[c])) begin
            u_sep_fabric_dedicated_port_cg.sample(3'd0, 1'b0, 1'b0, 2'd0, 2'd0, 2'd0, 1'b0, {
                                                  1'b1, 3'(c)}, 1'b1, 1'b0);
            mm_cq_on[c] <= 1'b0;
          end
        end
        if (mm_cq_cnt[c] == MmCoreQuiet) begin
          mm_cq_on[c] <= 1'b0;
          if (!mm_cq_req[c] && !mm_ct_req) begin
            u_sep_fabric_dedicated_port_cg.sample(3'd0, 1'b0, 1'b0, 2'd0, 2'd0, 2'd0, 1'b0, {
                                                  1'b0, 3'(c)}, 1'b1, 1'b0);
            if (c == 0) mm_ap(4'd8, 5'd0);
            if (c >= 3) mm_ap(4'd8, 5'd1);
          end
        end
        mm_cq_cnt[c] <= mm_cq_cnt[c] + 1;
      end else if (ev[c]) begin
        mm_cq_on[c]  <= 1'b1;
        mm_cq_req[c] <= 1'b0;
        mm_cq_cnt[c] <= 1;
        mm_cq_a[c]   <= {lsu_m_addr_i[31:2], 2'b00};
      end
    end
  end

endmodule : sep_fcov

`endif

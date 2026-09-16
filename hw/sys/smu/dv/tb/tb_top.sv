// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU OSS TB top — Phase-1 SEP=0, shared by the native cocotb / PyUVM flow
// and the SystemVerilog UVM flow. ONE module, two shapes:
//   * default (cocotb, `--dut smu_block`): the pin-level ANSI port list cocotb
//     drives and samples;
//   * `UVM` (SV-UVM, `--dut smu_block --framework uvm`): the port list is replaced
//     by internal TB signals and the harness block at the end of the module
//     adds the clocks, the shared JTAG VIP interface, the SMU-local and
//     embedded-DTP TB interfaces, quiescent tie-offs, uvm_config_db
//     publication, and run_test(). Test classes are compiled via
//     `include "smu_tests.sv".
// Every TB signal is declared once, in tb/smu_tb_signal_list.svh, and
// expanded into the selected shape by the SMU_TB_* macros below.
//
// Instantiates bare `smu` with SEP=0, flattens JTAG + external SMN AXI for
// the VIPs. Macro/I3C/DTP CSR boundaries are idle (no TB placeholder
// terminators); outbound SMN stays a struct port, placed on u_axi_out_if by
// ocah_axi_struct_bridge for the shared AXI slave agent.
//
// Real checkers consume:
//   - rst_cold_stable_ref_clk_no / rst_primary_* after reset release
//   - sep_global_base_o / sep_region_size_o (== 0 when SEP=0)
//   - jtag_* IDCODE/BYPASS via the shared ocah_jtag_vip
//   - s_axi_* CSR frontdoor reads (VERSION_LO etc.)

`timescale 1ps / 1fs

// Shape selection for smu_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
    // cocotb shape: every entry is a pin-level ANSI port, published to cocotb
    // through the Verilator metacomment (smu_public_scope.vlt publishes the
    // whole module as well).
    `define SMU_TB_IN_FIRST(dtype, name) input  wire dtype name /*verilator public_flat_rw*/
    `define SMU_TB_IN(dtype, name)     , input  wire dtype name /*verilator public_flat_rw*/
    `define SMU_TB_OUT(dtype, name)    , output dtype name /*verilator public_flat_rw*/
`else
    // SV-UVM shape: every entry is an internal TB signal for the harness
    // block at the end of this module.
    `define SMU_TB_IN_FIRST(dtype, name) dtype name;
    `define SMU_TB_IN(dtype, name) dtype name;
    `define SMU_TB_OUT(dtype, name) dtype name;
`endif

module smu_uvm_top
  import smu_pkg::*;
  import smu_axi_xbar_pkg::*;
  import smc_pkg::*;
  import prim_jtag_pkg::*;
  import chipyard_4core_mem_pkg::*;
`ifndef UVM
(
  `include "smu_tb_signal_list.svh"
);
`else
();
  `include "smu_tb_signal_list.svh"
`endif

`undef SMU_TB_IN_FIRST
`undef SMU_TB_IN
`undef SMU_TB_OUT

  // ------------------------------------------------------------------
  // JTAG pin pack
  // ------------------------------------------------------------------
  jtag_tap_ctrl_t jtag_ptap_client_tap_ctrl;
  assign jtag_ptap_client_tap_ctrl = '{tms: jtag_tms, trst_n: jtag_trst, tck: jtag_tck};

  // ------------------------------------------------------------------
  // External SMN AXI structs
  // ------------------------------------------------------------------
  axi_56_64_req_t   smu_axi_in_req;
  axi_56_64_resp_t  smu_axi_in_resp;
  axi_out_req_t     smu_axi_out_req;
  axi_out_resp_t    smu_axi_out_resp;

  assign smu_axi_in_req.aw.id     = s_axi_awid;
  assign smu_axi_in_req.aw.addr   = s_axi_awaddr;
  assign smu_axi_in_req.aw.len    = s_axi_awlen;
  assign smu_axi_in_req.aw.size   = s_axi_awsize;
  assign smu_axi_in_req.aw.burst  = s_axi_awburst;
  assign smu_axi_in_req.aw.lock   = s_axi_awlock;
  assign smu_axi_in_req.aw.cache  = s_axi_awcache;
  assign smu_axi_in_req.aw.prot   = s_axi_awprot;
  assign smu_axi_in_req.aw.qos    = s_axi_awqos;
  assign smu_axi_in_req.aw.region = s_axi_awregion;
  assign smu_axi_in_req.aw.user   = s_axi_awuser;
  assign smu_axi_in_req.aw.atop   = '0;
  assign smu_axi_in_req.aw_valid  = s_axi_awvalid;
  assign s_axi_awready            = smu_axi_in_resp.aw_ready;

  assign smu_axi_in_req.w.data    = s_axi_wdata;
  assign smu_axi_in_req.w.strb    = s_axi_wstrb;
  assign smu_axi_in_req.w.last    = s_axi_wlast;
  assign smu_axi_in_req.w.user    = s_axi_wuser;
  assign smu_axi_in_req.w_valid   = s_axi_wvalid;
  assign s_axi_wready             = smu_axi_in_resp.w_ready;

  assign s_axi_bid                = smu_axi_in_resp.b.id;
  assign s_axi_bresp              = smu_axi_in_resp.b.resp;
  assign s_axi_buser              = smu_axi_in_resp.b.user;
  assign s_axi_bvalid             = smu_axi_in_resp.b_valid;
  assign smu_axi_in_req.b_ready   = s_axi_bready;

  assign smu_axi_in_req.ar.id     = s_axi_arid;
  assign smu_axi_in_req.ar.addr   = s_axi_araddr;
  assign smu_axi_in_req.ar.len    = s_axi_arlen;
  assign smu_axi_in_req.ar.size   = s_axi_arsize;
  assign smu_axi_in_req.ar.burst  = s_axi_arburst;
  assign smu_axi_in_req.ar.lock   = s_axi_arlock;
  assign smu_axi_in_req.ar.cache  = s_axi_arcache;
  assign smu_axi_in_req.ar.prot   = s_axi_arprot;
  assign smu_axi_in_req.ar.qos    = s_axi_arqos;
  assign smu_axi_in_req.ar.region = s_axi_arregion;
  assign smu_axi_in_req.ar.user   = s_axi_aruser;
  assign smu_axi_in_req.ar_valid  = s_axi_arvalid;
  assign s_axi_arready            = smu_axi_in_resp.ar_ready;

  assign s_axi_rid                = smu_axi_in_resp.r.id;
  assign s_axi_rdata              = smu_axi_in_resp.r.data;
  assign s_axi_rresp              = smu_axi_in_resp.r.resp;
  assign s_axi_rlast              = smu_axi_in_resp.r.last;
  assign s_axi_ruser              = smu_axi_in_resp.r.user;
  assign s_axi_rvalid             = smu_axi_in_resp.r_valid;
  assign smu_axi_in_req.r_ready   = s_axi_rready;

  // External SMN AXI4 egress: the shared slave agent answers on u_axi_out_if
  // in both realizations (cocotb binds the instance, SV-UVM takes the vif
  // from uvm_config_db); the bridge places the crossbar's struct port on it.
  ocah_axi_if u_axi_out_if (
    .aclk    (clk_smu_i),
    .aresetn (rst_cold_ni)
  );

  ocah_axi_struct_bridge #(
    .axi_req_t  (smu_axi_xbar_pkg::axi_out_req_t),
    .axi_resp_t (smu_axi_xbar_pkg::axi_out_resp_t)
  ) u_axi_out_bridge (
    .axi_req_i  (smu_axi_out_req),
    .axi_resp_o (smu_axi_out_resp),
    .axi_if     (u_axi_out_if)
  );

  always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
    if (!rst_cold_ni) smu_axi_out_awvalid_count <= '0;
    else if (smu_axi_out_req.aw_valid && smu_axi_out_resp.aw_ready)
      smu_axi_out_awvalid_count <= smu_axi_out_awvalid_count + 32'd1;
  end

  always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
    if (!rst_cold_ni) smu_axi_in_awvalid_count <= '0;
    else if (s_axi_awvalid && s_axi_awready)
      smu_axi_in_awvalid_count <= smu_axi_in_awvalid_count + 32'd1;
  end

  // ------------------------------------------------------------------
  // Macro / memory / unused boundary nets
  // ------------------------------------------------------------------
  smc_axil_32_32_req_t  smc_external_req;
  smc_axil_32_32_resp_t smc_external_resp;
  smc_axil_32_32_req_t  smc_efuse_bank_ctrl_req;
  smc_axil_32_32_resp_t smc_efuse_bank_ctrl_resp;
  smc_efuse_pkg::fuse_command_req_t  smc_efuse_shim_command_req;
  smc_efuse_pkg::fuse_command_resp_t smc_efuse_shim_command_resp;
  smc_efuse_pkg::efuse_map_t         smc_shadow_regs;

  rom_req_t              smc_rom_req;
  rom_rsp_t              smc_rom_rsp;
  scratch_ram_req_t      smc_scratch_ram_req [NUM_SRAM_BANKS-1:0];
  scratch_ram_rsp_t      smc_scratch_ram_rsp [NUM_SRAM_BANKS-1:0];
  l1_icache_tag_req_t    smc_l1_icache_tag_req [NUM_ICACHE_TAG_BANKS-1:0];
  l1_icache_tag_rsp_t    smc_l1_icache_tag_rsp [NUM_ICACHE_TAG_BANKS-1:0];
  l1_icache_data_req_t   smc_l1_icache_data_req [NUM_ICACHE_DATA_BANKS-1:0];
  l1_icache_data_rsp_t   smc_l1_icache_data_rsp [NUM_ICACHE_DATA_BANKS-1:0];
  l1_dcache_tag_req_t    smc_l1_dcache_tag_req [NUM_DCACHE_TAG_BANKS-1:0];
  l1_dcache_tag_rsp_t    smc_l1_dcache_tag_rsp [NUM_DCACHE_TAG_BANKS-1:0];
  l1_dcache_data_req_t   smc_l1_dcache_data_req [NUM_DCACHE_DATA_BANKS-1:0];
  l1_dcache_data_rsp_t   smc_l1_dcache_data_rsp [NUM_DCACHE_DATA_BANKS-1:0];

  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad, pad2core_en, core2pad_en, lsio_sel;
  logic [smc_pkg::NUM_MAILBOXES-1:0]  mbx_irqs;
  jtag_tap_pkg::tap_state_e                     ptap_state;
  jtag_inst_reg_pkg::jtag_instruction_decoded_e ptap_inst;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_base_w, sep_size_w;
  smc_pkg::smc_axi_addr_t smc_base_w;
  logic [31:0] smc_size_w;
  jtag_tap_pkg::jtag_ic_reset_default_t jtag_ic_reset_ext;

  // SEP eFuse bank-control shim: SEP=0 holds it idle, but the port is taken
  // to a net so the cov/sv boundary points have something to read.
  sep_efuse_pkg::efuse_axil_req_t sep_efuse_bank_ctrl_req;

  // Boundary outputs observed only by the cov/sv functional-coverage modules.
  logic skip_mem_repair_w, sep_fuse_sense_done_w;
  logic [31:0] ss_config_w;
  smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_w [31:0];
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_req_out_dout_w, ctp_req_in_dout_w;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] ctp_ack_in_dout_w, ctp_ack_out_dout_w;

  // Scan / STAP loopbacks
  jtag_scan_ctrl_t bsr_ctrl, stap_scan_ctrl, dfd_ctrl, dft_sec_ctrl, dft_ctrl;
  logic bsr_out, stap_scan_out, dfd_out, dft_sec_out, dft_out;
  jtag_tap_ctrl_t stap_io_ctrl;
  logic stap_io_tdo, stap_io_tdo_oen;
  jtag_tap_ctrl_t stap_extra_ctrl [0:0];
  logic stap_extra_tdi [0:0];
  logic stap_extra_tdo [0:0];
  logic stap_extra_tdo_oen [0:0];

  assign stap_extra_tdi[0] = stap_extra_tdo[0];
  assign tb_stap_io_tck = stap_io_ctrl.tck;
  assign tb_stap_smc_tck = u_dut.dtp_smc_stap_tap_ctrl.tck;
  assign tb_stap_smc_trst_n = u_dut.dtp_smc_stap_tap_ctrl.trst_n;
  // jtag_tap_ctrl_t has no .tdi; DTP host_tdo_o (dtp_smc_stap_tdo) is the
  // sole driver of SMC CPU TDI — probe the CPU pin, not the return TDO path.
  assign tb_stap_smc_tdi = u_dut.u_smc.smc_cpu_jtag_TDI_i;
  assign tb_stap_smc_tms = u_dut.dtp_smc_stap_tap_ctrl.tms;
  assign tb_stap_smc_tdo_oen = u_dut.u_dtp.jtag_stap_smc_host_tdo_oen_o;
  assign tb_bsr_select = bsr_ctrl.select;
  assign tb_otp_jtag2axi_security_disable =
        u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_otp_jtag2axi_security_disable;
  assign tb_smc_jtag2axi_security_disable =
        u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable;

  // XTRIG: expose CTM req/ack for cocotb
  logic [7:0] xtrig_src_req_w, xtrig_dst_ack_w;
  assign xtrig_ctm_src_req = xtrig_src_req_w;
  assign xtrig_ctm_dst_ack = xtrig_dst_ack_w;

  logic [15:0] ctp_z;
  assign ctp_z = '0;

  // Telemetry: cocotb drives channel-0; remaining receivers stay idle
  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tel_data;
  telemetry_receiver_pkg::atb_id_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tel_id;
  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]
      tel_ready, tel_valid, tel_afvalid, tel_afready;
  assign tel_data[0] = tb_tel_atdata;
  assign tel_id[0] = tb_tel_atid;
  assign tel_valid[0] = tb_tel_atvalid;
  assign tel_afready[0] = tb_tel_afready;
  for (genvar ti = 1; ti < smc_config_pkg::NUM_TELEMETRY_RECEIVERS; ti++) begin : gen_tel_idle
    assign tel_data[ti] = '0;
    assign tel_id[ti] = '0;
    assign tel_valid[ti] = 1'b0;
    assign tel_afready[ti] = 1'b0;
  end
  assign tb_tel_atready = tel_ready[0];
  assign tb_tel_afvalid = tel_afvalid[0];

  // Trace mem idle responses
  trace_mem_pkg::SinkMemPktIn_s  [tn_pkg::TRC_RAM_INSTANCES-1:0] trc_req;
  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trc_resp;
  assign trc_resp = '0;

  // eFuse shim idle response
  assign smc_efuse_shim_command_resp = '0;
  assign smc_efuse_bank_ctrl_resp = '0;

  // I3C mem idle
  i3c_pkg::dat_mem_src_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_src;
  i3c_pkg::dct_mem_src_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_src;
  assign i3c_dat_src = '0;
  assign i3c_dct_src = '0;

  // SEP strap / irq idle (SEP=0 paths still exist as ports)
  logic secure_tm_req;
  assign secure_tm_req = 1'b0;

  // Observables
  assign sep_global_base_o         = sep_base_w;
  assign sep_region_size_o         = sep_size_w;
  assign smc_global_base_o         = smc_base_w;
  assign smc_region_size_o         = smc_size_w;
  assign ext_mailbox_interrupts    = mbx_irqs;
  assign jtag_ptap_state           = 32'(ptap_state);
  assign jtag_ptap_inst_decoded    = 32'(ptap_inst);

  // CPU ROM/scratch/L1$ — same macros as smc_wrapper / smu_wrapper TB.
  // Bare `smu` exposes the CPU memory ports (smc_ip_integration lives in
  // smu_wrapper, not here), so terminate them with the macros directly.
  localparam int unsigned MEM_CFG_WIDTH = 11;
  logic [MEM_CFG_WIDTH-1:0] smc_scratch_ram_cfg [NUM_SRAM_BANKS-1:0];
  logic [MEM_CFG_WIDTH-1:0] smc_icache_tag_cfg  [NUM_ICACHE_TAG_BANKS-1:0];
  logic [MEM_CFG_WIDTH-1:0] smc_icache_data_cfg [NUM_ICACHE_DATA_BANKS-1:0];
  logic [MEM_CFG_WIDTH-1:0] smc_dcache_tag_cfg  [NUM_DCACHE_TAG_BANKS-1:0];
  logic [MEM_CFG_WIDTH-1:0] smc_dcache_data_cfg [NUM_DCACHE_DATA_BANKS-1:0];
  logic [MEM_CFG_WIDTH-1:0] smc_rom_cfg;

  for (genvar i = 0; i < NUM_SRAM_BANKS; i++) begin : gen_smc_scratch_cfg
    assign smc_scratch_ram_cfg[i] = '0;
  end
  for (genvar i = 0; i < NUM_ICACHE_TAG_BANKS; i++) begin : gen_smc_itag_cfg
    assign smc_icache_tag_cfg[i] = '0;
  end
  for (genvar i = 0; i < NUM_ICACHE_DATA_BANKS; i++) begin : gen_smc_idata_cfg
    assign smc_icache_data_cfg[i] = '0;
  end
  for (genvar i = 0; i < NUM_DCACHE_TAG_BANKS; i++) begin : gen_smc_dtag_cfg
    assign smc_dcache_tag_cfg[i] = '0;
  end
  for (genvar i = 0; i < NUM_DCACHE_DATA_BANKS; i++) begin : gen_smc_ddata_cfg
    assign smc_dcache_data_cfg[i] = '0;
  end
  assign smc_rom_cfg = '0;

  OCAH4CORECluster_mems #(
    .MEM_CFG_WIDTH(MEM_CFG_WIDTH)
  ) u_smc_cpu_mem (
    .rom_req            (smc_rom_req),
    .rom_rsp            (smc_rom_rsp),
    .scratch_ram_req    (smc_scratch_ram_req),
    .scratch_ram_rsp    (smc_scratch_ram_rsp),
    .l1_icache_tag_req  (smc_l1_icache_tag_req),
    .l1_icache_tag_rsp  (smc_l1_icache_tag_rsp),
    .l1_icache_data_req (smc_l1_icache_data_req),
    .l1_icache_data_rsp (smc_l1_icache_data_rsp),
    .l1_dcache_tag_req  (smc_l1_dcache_tag_req),
    .l1_dcache_tag_rsp  (smc_l1_dcache_tag_rsp),
    .l1_dcache_data_req (smc_l1_dcache_data_req),
    .l1_dcache_data_rsp (smc_l1_dcache_data_rsp),
    .icache_tag_cfg_i   (smc_icache_tag_cfg),
    .icache_data_cfg_i  (smc_icache_data_cfg),
    .dcache_tag_cfg_i   (smc_dcache_tag_cfg),
    .dcache_data_cfg_i  (smc_dcache_data_cfg),
    .scratch_ram_cfg_i  (smc_scratch_ram_cfg),
    .rom_cfg_i          (smc_rom_cfg)
  );

  // Macro AXI-Lite activity (OR of aw/w/ar valid).
  assign tb_axil_external_active = smc_external_req.aw_valid
                                   | smc_external_req.w_valid
                                   | smc_external_req.ar_valid;
  // Boundary response tied off; nothing answers the macro AXI-Lite window.
  assign smc_external_resp = '0;

  // ------------------------------------------------------------------
  // DUT: smu with SEP=0
  // ------------------------------------------------------------------
  logic jtag_tdo_w, jtag_tdo_oen_w;
  assign jtag_tdo     = jtag_tdo_w;
  assign jtag_tdo_oen = jtag_tdo_oen_w;

  // TB-owned SEP lockstep stimulus/observation. Initialised: an undriven
  // sep_lockstep_ctrl_i would reach the SEP core as X under RV_LOCKSTEP_ENABLE.
  sep_pkg::sep_lockstep_ctrl_t   sep_lockstep_ctrl_i = '0;
  sep_pkg::sep_lockstep_status_t sep_lockstep_status_o;

  function automatic smu_pkg::smu_cfg_t make_tb_cfg();
    smu_pkg::smu_cfg_t cfg = smu_pkg::DefaultCfg;
    // Exercise the most-significant configured DTP mode bit while [1:0] stay SMC-reserved.
    cfg.XTRIG_INT_CT_MODE = 8'h80;
    return cfg;
  endfunction

  localparam smu_pkg::smu_cfg_t TbCfg = make_tb_cfg();

  smu #(
    .Cfg(TbCfg),
    .SEP(0)
  ) u_dut (
    .clk_smu_i,
    .clk_ref_i,
    .clk_periph_i,
    .rst_cold_ni,
    .rst_cold_stable_ref_clk_no,
    .powergood_i,
    .jtag_ptap_client_tap_ctrl_i (jtag_ptap_client_tap_ctrl),
    .jtag_ptap_client_tdi_i      (jtag_tdi),
    .jtag_ptap_client_tdo_o      (jtag_tdo_w),
    .jtag_ptap_client_tdo_oen_o  (jtag_tdo_oen_w),
    .jtag_bsr_host_scan_ctrl_o   (bsr_ctrl),
    .jtag_bsr_host_scan_in_i     (bsr_out),
    .jtag_bsr_host_scan_out_o    (bsr_out),
    .jtag_stap_io_host_tap_ctrl_o(stap_io_ctrl),
    .jtag_stap_io_host_tdi_i     (stap_io_tdo),
    .jtag_stap_io_host_tdo_o     (stap_io_tdo),
    .jtag_stap_io_host_tdo_oen_o (stap_io_tdo_oen),
    .jtag_stap_extra_host_tap_ctrl_o (stap_extra_ctrl),
    .jtag_stap_extra_host_tdi_i      (stap_extra_tdi),
    .jtag_stap_extra_host_tdo_o      (stap_extra_tdo),
    .jtag_stap_extra_host_tdo_oen_o  (stap_extra_tdo_oen),
    .jtag_stap_host_scan_ctrl_o  (stap_scan_ctrl),
    .jtag_stap_host_scan_in_i    (stap_scan_out),
    .jtag_stap_host_scan_out_o   (stap_scan_out),
    .jtag_dfd_host_scan_ctrl_o   (dfd_ctrl),
    .jtag_dfd_host_scan_in_i     (dfd_out),
    .jtag_dfd_host_scan_out_o    (dfd_out),
    .jtag_dft_secure_host_scan_ctrl_o (dft_sec_ctrl),
    .jtag_dft_secure_host_scan_in_i   (dft_sec_out),
    .jtag_dft_secure_host_scan_out_o  (dft_sec_out),
    .jtag_dft_host_scan_ctrl_o   (dft_ctrl),
    .jtag_dft_host_scan_in_i     (dft_out),
    .jtag_dft_host_scan_out_o    (dft_out),
    .dtp_stop_clks_o             (dtp_stop_clks_o),
    .jtag_ptap_state_o           (ptap_state),
    .jtag_ptap_inst_decoded_o    (ptap_inst),
    .jtag_ic_reset_ext_o         (jtag_ic_reset_ext),
    .xtrig_ctm_src_req_o         (xtrig_src_req_w),
    .xtrig_ctm_src_ack_i         (xtrig_ctm_src_ack),
    .xtrig_ctm_dst_req_i         (xtrig_ctm_dst_req),
    .xtrig_ctm_dst_ack_o         (xtrig_dst_ack_w),
    .xtrig_clk_stop_req_i        (xtrig_clk_stop_req),
    .xtrig_ctp_req_out_dout_o    (ctp_req_out_dout_w),
    .xtrig_ctp_req_out_dout_en_o (),
    .xtrig_ctp_req_out_din_i     (ctp_z),
    .xtrig_ctp_req_out_din_en_o  (),
    .xtrig_ctp_req_in_dout_o     (ctp_req_in_dout_w),
    .xtrig_ctp_req_in_dout_en_o  (),
    .xtrig_ctp_req_in_din_i      (ctp_z),
    .xtrig_ctp_req_in_din_en_o   (),
    .xtrig_ctp_ack_in_dout_o     (ctp_ack_in_dout_w),
    .xtrig_ctp_ack_in_dout_en_o  (),
    .xtrig_ctp_ack_in_din_i      (ctp_z),
    .xtrig_ctp_ack_in_din_en_o   (),
    .xtrig_ctp_ack_out_dout_o    (ctp_ack_out_dout_w),
    .xtrig_ctp_ack_out_dout_en_o (),
    .xtrig_ctp_ack_out_din_i     (ctp_z),
    .xtrig_ctp_ack_out_din_en_o  (),
    .rst_primary_ref_clk_no,
    .rst_primary_smc_clk_no,
    // The smu top does not forward rst_primary_periph_clk_no; the TB observes
    // it hierarchically from u_smc below.
    .smu_axi_in_req_i            (smu_axi_in_req),
    .smu_axi_in_resp_o           (smu_axi_in_resp),
    .smu_axi_out_req_o           (smu_axi_out_req),
    .smu_axi_out_resp_i          (smu_axi_out_resp),
    .smc_external_req_o          (smc_external_req),
    .smc_external_resp_i         (smc_external_resp),
    .smc_efuse_bank_ctrl_req_o   (smc_efuse_bank_ctrl_req),
    .smc_efuse_bank_ctrl_resp_i  (smc_efuse_bank_ctrl_resp),
    .smc_efuse_shim_command_req_o(smc_efuse_shim_command_req),
    .smc_efuse_shim_command_resp_i(smc_efuse_shim_command_resp),
    .smc_shadow_regs_o           (smc_shadow_regs),
    .lsio_interface_select_o     (lsio_sel),
    .pad2core_i                  (pad2core),
    .core2pad_o                  (core2pad),
    .pad2core_en_o               (pad2core_en),
    .core2pad_en_o               (core2pad_en),
    .rst_cool_n_from_pin_i       (1'b1),
    .clk_telemetry_i             (clk_smu_i),
    .rst_telemetry_ni            (rst_cold_ni),
    .telemetry_atdata_i          (tel_data),
    .telemetry_atid_i            (tel_id),
    .telemetry_atready_o         (tel_ready),
    .telemetry_atvalid_i         (tel_valid),
    .telemetry_afvalid_o         (tel_afvalid),
    .telemetry_afready_i         (tel_afready),
    .smc_cluster_ded_o           (),
    .smc_wdt_first_timeout_o     (tb_wdt_first_timeout),
    .smc_wdt_second_timeout_o    (),
    .smc_global_base_o           (smc_base_w),
    .smc_region_size_o           (smc_size_w),
    .sep_global_base_o           (sep_base_w),
    .sep_region_size_o           (sep_size_w),
    .smc_ext_interrupts_i        ('0),
    .smc_fuse_sense_done_o,
    .smc_fuse_reset_n_delayed_o,
    .skip_mem_repair_o           (skip_mem_repair_w),
    .ext_boot_seq_done_i         (ext_boot_seq_done_i),
    .lc_state_o                  (lc_state_o),
    .lc_sigint_err_o             (lc_sigint_err_o),
    .smc_ndmreset_request_i      ('0),
    .smc_ndmreset_process_o      (),
    .smc_ext_mailbox_interrupts_o (mbx_irqs),
    .cfg_flr_pf_active_i         (1'b0),
    .isolate_req_o               (),
    .ss_reset_complete_i         ('0),
    .ss_config_o                 (ss_config_w),
    .ss_reset_ctrl_o             (ss_reset_ctrl_w),
    .sync_irq_o                  (),
    .smc_rom_intf_req_o          (smc_rom_req),
    .smc_rom_intf_rsp_i          (smc_rom_rsp),
    .smc_scratch_ram_intf_req_o  (smc_scratch_ram_req),
    .smc_scratch_ram_intf_rsp_i  (smc_scratch_ram_rsp),
    .smc_l1_icache_tag_intf_req_o (smc_l1_icache_tag_req),
    .smc_l1_icache_tag_intf_rsp_i (smc_l1_icache_tag_rsp),
    .smc_l1_icache_data_intf_req_o (smc_l1_icache_data_req),
    .smc_l1_icache_data_intf_rsp_i (smc_l1_icache_data_rsp),
    .smc_l1_dcache_tag_intf_req_o (smc_l1_dcache_tag_req),
    .smc_l1_dcache_tag_intf_rsp_i (smc_l1_dcache_tag_rsp),
    .smc_l1_dcache_data_intf_req_o (smc_l1_dcache_data_req),
    .smc_l1_dcache_data_intf_rsp_i (smc_l1_dcache_data_rsp),
    .smc_disable_sram_auto_init_i (1'b0),
    .smc_init_mem_done_o,
    .chiplet_is_primary_i        (1'b1),
    .timer_count_o               (tb_timer_count),
    .trace_mem_req_o             (trc_req),
    .trace_mem_resp_i            (trc_resp),
    .test_en_i                   (1'b0),
    .scan_rst_ni                 (1'b1),
    .mem_repair_done_i           (1'b1),
    .mem_repair_success_i        (1'b1),
    .mem_repair_abort_i          (1'b0),
    .mbist_done_i                (1'b1),
    .mbist_pass_i                (1'b1),
    .mbist_abort_i               (1'b0),
    // SEP passthrough ports (tied; SEP=0 internals also tie)
    .sep_sram_req_o              (),
    .sep_sram_rsp_i              ('0),
    .sep_boot_rom_req_o          (),
    .sep_boot_rom_rsp_i          ('0),
    .sep_cpu_tcm_req_o           (),
    .sep_cpu_tcm_rsp_i           ('0),
    .sep_efuse_bank_ctrl_req_o   (sep_efuse_bank_ctrl_req),
    .sep_efuse_bank_ctrl_resp_i  ('0),
    .sep_efuse_shim_command_req_o(),
    .sep_efuse_shim_command_resp_i('0),
    .sep_crypto_pka_imem_sram_req_o(),
    .sep_crypto_pka_imem_sram_rsp_i('0),
    .sep_crypto_pka_dmem_sram_req_o(),
    .sep_crypto_pka_dmem_sram_rsp_i('0),
    .sep_km_rom_mem_req_o        (),
    .sep_km_rom_mem_rsp_i        ('0),
    .sep_km_sram_mem_req_o       (),
    .sep_km_sram_mem_rsp_i       ('0),
    .sep_external_req_o     (),
    .sep_external_resp_i    ('0),
    .sep_cpu_trace_o             (),
    .sep_ext_interrupts_i        ('0),
    .lcc_demote_state_1_o        (lcc_demote_state_1_o),
    .lcc_demote_state_2_o        (lcc_demote_state_2_o),
    .sep_fuse_dft_disable_o      (),
    .smc_fuse_dft_disable_o      (),
    .sep_fuse_sense_done_o       (sep_fuse_sense_done_w),
    .clk_sep_wdt_i               (clk_smu_i),
    .secure_tm_req_i             (secure_tm_req),
    .i3c_dat_mem_src_i           (i3c_dat_src),
    .i3c_dat_mem_sink_o          (),
    .i3c_dct_mem_src_i           (i3c_dct_src),
    .i3c_dct_mem_sink_o          (),
    .ext_debug_bus_i             (128'h0),
    .gpio_interrupt_o            (),
    .uart_interrupt_o            (),

    // SEP CPU lockstep control/status
    .sep_lockstep_ctrl_i         (sep_lockstep_ctrl_i),
    .sep_lockstep_status_o       (sep_lockstep_status_o)
  );

  // Peripheral-domain reset: the smu top does not forward SMC's
  // rst_primary_periph_clk_no output, so observe it hierarchically.
  assign rst_primary_periph_clk_no = u_dut.u_smc.rst_primary_periph_clk_no;

  // WDT isolate clamp: observe only.
  assign tb_wdt_reset_raw = u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu
        .wdt_reset_raw[0];
  assign tb_cluster_boundary_isolate = u_dut.u_smc.u_smc_cpu_wrapper.gen_4core_cpu
        .u_smc_cpu.cluster_boundary_isolate;

  // Hierarchical observe of DTP boot-stall / CLA clock-stop.
  assign jtag_boot_stall_ovrd = u_dut.boot_stall_jtag_ovrd;
  assign jtag_boot_stall      = u_dut.boot_stall_jtag_val;
  assign dtp_cla_clock_stop_en = u_dut.dtp_cla_clock_stop_en;
  assign jtag_ic_reset_ext_ovrd   = jtag_ic_reset_ext.ovrd;
  assign jtag_ic_reset_ext_ctrl_n = jtag_ic_reset_ext.val;
  // SMC IC_RESET slice: observe cold-reset override/value from DTP->SMC wire.
  assign jtag_ic_reset_smc_ovrd   = u_dut.jtag_smc_reset_ctrl.ovrd.cold_reset_n_ovrd;
  assign jtag_ic_reset_smc_ctrl_n = u_dut.jtag_smc_reset_ctrl.val.cold_reset_n_val;

  // Loopback unused GPIO; OR TB drive for boot-stall pad bit[57]
  // (smc_padring: boot_stall_o = lsio_pad2core_data[57]).
  // Continuous Force on pad2core is unreliable under Verilator.
  assign pad2core = core2pad |
        ({{(smc_pkg::NUM_GPIO_WRAPS-1){1'b0}}, gpio_boot_stall_drive_i}
         << 57);

  // ------------------------------------------------------------------
  // Functional coverage (cov/sv/): shared by both tb shapes. The modules
  // carry cover-property points, which land in the `user` metric family
  // under --coverage-user, plus commercial-only covergroups internally.
  // Every port below is a smu_tb_signal_list.svh signal; the modules read
  // no DUT hierarchy.
  // ------------------------------------------------------------------
  // This bench is SEP=0, so the SEP-only points are not elaborated.
  smu_boot_fcov #(
      .SepPresent (1'b0)
  ) u_smu_boot_fcov (
    .clk_ref_i                   (clk_ref_i),
    .clk_smu_i                   (clk_smu_i),
    .powergood_i                 (powergood_i),
    .rst_cold_ni                 (rst_cold_ni),
    .ext_boot_seq_done_i         (ext_boot_seq_done_i),
    .rst_cold_stable_ref_clk_ni  (rst_cold_stable_ref_clk_no),
    .rst_primary_ref_clk_ni      (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_no),
    .rst_primary_periph_clk_ni   (rst_primary_periph_clk_no),
    .init_mem_done_i             (smc_init_mem_done_o),
    .fuse_sense_done_i           (smc_fuse_sense_done_o),
    .fuse_reset_n_delayed_i      (smc_fuse_reset_n_delayed_o),
    .jtag_boot_stall_ovrd_i      (jtag_boot_stall_ovrd),
    .jtag_boot_stall_i           (jtag_boot_stall),
    .gpio_boot_stall_drive_i     (gpio_boot_stall_drive_i),
    .lc_state_i                  (lc_state_o),
    .lc_sigint_err_i             (lc_sigint_err_o),
    .lcc_demote_state_1_i        (lcc_demote_state_1_o),
    .lcc_demote_state_2_i        (lcc_demote_state_2_o)
  );

  // This bench is SEP=0, so the SEP-only points are not elaborated.
  smu_xbar_fcov #(
      .SepPresent (1'b0)
  ) u_smu_xbar_fcov (
    .clk_smu_i                (clk_smu_i),
    .rst_cold_ni              (rst_cold_ni),
    .sep_global_base_i        (sep_global_base_o),
    .sep_region_size_i        (sep_region_size_o),
    .smc_global_base_i        (smc_global_base_o),
    .smc_region_size_i        (smc_region_size_o),
    .s_axi_awvalid_i          (s_axi_awvalid),
    .s_axi_awready_i          (s_axi_awready),
    .s_axi_wvalid_i           (s_axi_wvalid),
    .s_axi_wready_i           (s_axi_wready),
    .s_axi_wlast_i            (s_axi_wlast),
    .s_axi_bvalid_i           (s_axi_bvalid),
    .s_axi_bready_i           (s_axi_bready),
    .s_axi_bresp_i            (s_axi_bresp),
    .s_axi_arvalid_i          (s_axi_arvalid),
    .s_axi_arready_i          (s_axi_arready),
    .s_axi_rvalid_i           (s_axi_rvalid),
    .s_axi_rready_i           (s_axi_rready),
    .s_axi_rlast_i            (s_axi_rlast),
    .s_axi_rresp_i            (s_axi_rresp),
    .axi_in_awvalid_count_i   (smu_axi_in_awvalid_count),
    .axi_out_awvalid_count_i  (smu_axi_out_awvalid_count),
    .axil_external_active_i   (tb_axil_external_active)
  );

  // Bare `smu` exposes neither the per-block resets nor the DUT-internal
  // clock mirrors the wrapper bench has, so those ports are tied off here and
  // the points that need them fire only on tb_wrapper_top.
  // This bench is SEP=0, so the SEP-only points are not elaborated.
  smu_rst_fcov #(
      .SepPresent (1'b0)
  ) u_smu_rst_fcov (
    .clk_ref_i                   (clk_ref_i),
    .clk_smu_i                   (clk_smu_i),
    .clk_periph_i                (clk_periph_i),
    .powergood_i                 (powergood_i),
    .rst_cold_ni                 (rst_cold_ni),
    .ext_boot_seq_done_i         (ext_boot_seq_done_i),
    .rst_cold_stable_ref_clk_ni  (rst_cold_stable_ref_clk_no),
    .rst_primary_ref_clk_ni      (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_no),
    .rst_primary_periph_clk_ni   (rst_primary_periph_clk_no),
    .smc_rst_ni                  (rst_primary_smc_clk_no),
    .dtp_rst_ni                  (1'b0),
    .sep_rst_ni                  (1'b0),
    .xbar_rst_ni                 (1'b0),
    .fuse_sense_done_i           (smc_fuse_sense_done_o),
    .sep_fuse_sense_done_i       (sep_fuse_sense_done_w),
    .fuse_reset_n_delayed_i      (smc_fuse_reset_n_delayed_o),
    .skip_mem_repair_i           (skip_mem_repair_w),
    .init_mem_done_i             (smc_init_mem_done_o),
    .disable_sram_auto_init_i    (1'b0),
    .jtag_ptap_state_i           (jtag_ptap_state)
  );

  smu_lc_fcov u_smu_lc_fcov (
    .clk_smu_i                (clk_smu_i),
    .rst_cold_ni              (rst_cold_ni),
    .rst_primary_smc_clk_ni   (rst_primary_smc_clk_no),
    .lc_state_i               (lc_state_o),
    .lcc_demote_state_1_i     (lcc_demote_state_1_o),
    .lcc_demote_state_2_i     (lcc_demote_state_2_o),
    .sep_global_base_i        (sep_global_base_o),
    .sep_region_size_i        (sep_region_size_o),
    .sep_fuse_sense_done_i    (sep_fuse_sense_done_w)
  );

  smu_dtp_fcov u_smu_dtp_fcov (
    .clk_smu_i                  (clk_smu_i),
    .rst_cold_ni                (rst_cold_ni),
    .rst_primary_smc_clk_ni     (rst_primary_smc_clk_no),
    .jtag_ic_reset_ext_ovrd_i   (jtag_ic_reset_ext_ovrd),
    .jtag_ic_reset_ext_ctrl_n_i (jtag_ic_reset_ext_ctrl_n),
    .ctp_req_out_dout_i         (ctp_req_out_dout_w),
    .ctp_req_in_dout_i          (ctp_req_in_dout_w),
    .ctp_ack_in_dout_i          (ctp_ack_in_dout_w),
    .ctp_ack_out_dout_i         (ctp_ack_out_dout_w)
  );

  // This bench is SEP=0, so the SEP-only points are not elaborated.
  smu_ext_fcov #(
      .SepPresent (1'b0)
  ) u_smu_ext_fcov (
    .clk_smu_i                (clk_smu_i),
    .rst_cold_ni              (rst_cold_ni),
    .rst_primary_smc_clk_ni   (rst_primary_smc_clk_no),
    .fuse_sense_done_i        (smc_fuse_sense_done_o),
    .s_axi_awvalid_i          (s_axi_awvalid),
    .s_axi_awready_i          (s_axi_awready),
    .s_axi_awid_i             (s_axi_awid),
    .axi_out_aw_valid_i       (smu_axi_out_req.aw_valid),
    .axi_out_aw_ready_i       (smu_axi_out_resp.aw_ready),
    .axi_out_aw_id_i          (smu_axi_out_req.aw.id),
    .smc_efuse_bank_ctrl_awvalid_i (smc_efuse_bank_ctrl_req.aw_valid),
    .smc_efuse_bank_ctrl_arvalid_i (smc_efuse_bank_ctrl_req.ar_valid),
    .smc_efuse_bank_ctrl_bvalid_i  (smc_efuse_bank_ctrl_resp.b_valid),
    .smc_efuse_bank_ctrl_bready_i  (smc_efuse_bank_ctrl_req.b_ready),
    .smc_efuse_bank_ctrl_rvalid_i  (smc_efuse_bank_ctrl_resp.r_valid),
    .smc_efuse_bank_ctrl_rready_i  (smc_efuse_bank_ctrl_req.r_ready),
    .sep_efuse_bank_ctrl_awvalid_i (sep_efuse_bank_ctrl_req.aw_valid),
    .sep_efuse_bank_ctrl_arvalid_i (sep_efuse_bank_ctrl_req.ar_valid),
    .sep_efuse_bank_ctrl_bvalid_i  (1'b0),
    .sep_efuse_bank_ctrl_bready_i  (sep_efuse_bank_ctrl_req.b_ready),
    .sep_efuse_bank_ctrl_rvalid_i  (1'b0),
    .sep_efuse_bank_ctrl_rready_i  (sep_efuse_bank_ctrl_req.r_ready),
    .ext_mailbox_interrupts_i (ext_mailbox_interrupts),
    .ss_config_i              (ss_config_w),
    .ss_reset_ctrl_i          (ss_reset_ctrl_w),
    .smc_shadow_regs_i        (smc_shadow_regs)
  );

  // ------------------------------------------------------------------
  // P1 families. The three DTP debug bridges and the cross-trigger
  // clock-stop inputs are nets inside `smu`, so they are flattened here and
  // the cov/sv modules take plain wires. The SEP-side alias remap port and
  // the crossbar SEP initiator port exist only in a SEP=1 elaboration, so
  // this SEP=0 bench carries no smu_alias_fcov instance.
  // ------------------------------------------------------------------
  smu_clkstop_fcov u_smu_clkstop_fcov (
    .clk_smu_i               (clk_smu_i),
    .rst_primary_smc_clk_ni  (rst_primary_smc_clk_no),
    .dtp_clk_stop_req_ext_i  (u_dut.dtp_xtrig_clk_stop_req[8:1]),
    .jtag_clock_stop_i       (u_dut.u_dtp.jtag_clock_stop),
    .dtp_stop_clks_i         (dtp_stop_clks_o)
  );

  // This bench is SEP=0, so the SEP-only points are not elaborated.
  smu_dbg_fcov #(
      .SepPresent (1'b0)
  ) u_smu_dbg_fcov (
    .clk_smu_i                   (clk_smu_i),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_no),
    .smc_dbg_awvalid_i           (u_dut.dtp_axi_smc_dbg_req.aw_valid),
    .smc_dbg_arvalid_i           (u_dut.dtp_axi_smc_dbg_req.ar_valid),
    .smc_dbg_bvalid_i            (u_dut.dtp_axi_smc_dbg_resp.b_valid),
    .smc_dbg_bready_i            (u_dut.dtp_axi_smc_dbg_req.b_ready),
    .smc_dbg_bresp_i             (u_dut.dtp_axi_smc_dbg_resp.b.resp),
    .smc_dbg_rvalid_i            (u_dut.dtp_axi_smc_dbg_resp.r_valid),
    .smc_dbg_rready_i            (u_dut.dtp_axi_smc_dbg_req.r_ready),
    .smc_dbg_rlast_i             (u_dut.dtp_axi_smc_dbg_resp.r.last),
    .smc_dbg_rresp_i             (u_dut.dtp_axi_smc_dbg_resp.r.resp),
    .smc_otp_bvalid_i            (u_dut.dtp_axil_smc_otp_jtag_resp.b_valid),
    .smc_otp_bready_i            (u_dut.dtp_axil_smc_otp_jtag_req.b_ready),
    .smc_otp_bresp_i             (u_dut.dtp_axil_smc_otp_jtag_resp.b.resp),
    .smc_otp_rvalid_i            (u_dut.dtp_axil_smc_otp_jtag_resp.r_valid),
    .smc_otp_rready_i            (u_dut.dtp_axil_smc_otp_jtag_req.r_ready),
    .smc_otp_rresp_i             (u_dut.dtp_axil_smc_otp_jtag_resp.r.resp),
    .sep_otp_bvalid_i            (u_dut.dtp_axil_sep_otp_jtag_resp.b_valid),
    .sep_otp_bready_i            (u_dut.dtp_axil_sep_otp_jtag_req.b_ready),
    .sep_otp_bresp_i             (u_dut.dtp_axil_sep_otp_jtag_resp.b.resp),
    .sep_otp_rvalid_i            (u_dut.dtp_axil_sep_otp_jtag_resp.r_valid),
    .sep_otp_rready_i            (u_dut.dtp_axil_sep_otp_jtag_req.r_ready),
    .sep_otp_rresp_i             (u_dut.dtp_axil_sep_otp_jtag_resp.r.resp),
    .dbg_disable_smc_jtag2axi_i  (u_dut.sep_dbg_disable.smc_jtag2axi),
    .dbg_disable_smc_otp_i       (u_dut.sep_dbg_disable.smc_otp_jtag2axi),
    .dbg_disable_sep_otp_i       (u_dut.sep_dbg_disable.sep_otp_jtag2axi)
  );

  smu_nosep_fcov u_smu_nosep_fcov (
    .clk_smu_i          (clk_smu_i),
    .rst_cold_ni        (rst_cold_ni),
    .sep_present_i      (1'b0),
    .ext_in_bvalid_i    (s_axi_bvalid),
    .ext_in_bready_i    (s_axi_bready),
    .ext_in_bresp_i     (s_axi_bresp),
    .ext_in_rvalid_i    (s_axi_rvalid),
    .ext_in_rready_i    (s_axi_rready),
    .ext_in_rlast_i     (s_axi_rlast),
    .ext_in_rresp_i     (s_axi_rresp),
    .axi_out_bvalid_i   (smu_axi_out_resp.b_valid),
    .axi_out_bready_i   (smu_axi_out_req.b_ready),
    .axi_out_bresp_i    (smu_axi_out_resp.b.resp),
    .axi_out_rvalid_i   (smu_axi_out_resp.r_valid),
    .axi_out_rready_i   (smu_axi_out_req.r_ready),
    .axi_out_rlast_i    (smu_axi_out_resp.r.last),
    .axi_out_rresp_i    (smu_axi_out_resp.r.resp)
  );

`ifdef UVM
  // ------------------------------------------------------------------
  // SV-UVM harness (`--dut smu_block --framework uvm`): clocks, the shared JTAG
  // VIP interface on the primary TAP pins, the SMU-local TB interface, the
  // embedded DTP's TB interface (so the DTP bench's reference models and
  // checkers attach unchanged), the JTAG protocol SVA, quiescent tie-offs
  // for every other cocotb-driven stimulus pin, uvm_config_db publication
  // of the four virtual interfaces (u_axi_out_if lives above, in both
  // shapes), and run_test(). Compiled only when the native uvm flow
  // defines UVM; the cocotb flow sees only the ported module above.
  // ------------------------------------------------------------------
  import uvm_pkg::*;

  smu_tb_if u_tb_if ();
  dtp_tb_if u_dtp_tb_if ();
  ocah_jtag_if u_jtag_if ();

  // Three free-running clocks with the periods the env publishes on
  // smu_tb_if from the seeded test cfg (cocotb SmuEnvCfg.randomize_timing
  // parity); TCK is bit-banged by the VIP driver.
  initial begin
    clk_smu_i    = 1'b0;
    clk_ref_i    = 1'b0;
    clk_periph_i = 1'b0;
  end
  always #(u_tb_if.smu_clk_period_ns * 0.5ns) clk_smu_i = ~clk_smu_i;
  always #(u_tb_if.ref_clk_period_ns * 0.5ns) clk_ref_i = ~clk_ref_i;
  always #(u_tb_if.periph_clk_period_ns * 0.5ns) clk_periph_i = ~clk_periph_i;

  // Power-good, cold reset, and the boot-sequence gate are test-sequenced
  // through smu_tb_if; the reset-unit outputs and the fuse-sense
  // observables are mirrored back for the sequences.
  assign powergood_i         = u_tb_if.powergood;
  assign rst_cold_ni         = u_tb_if.rst_cold_n;
  assign ext_boot_seq_done_i = u_tb_if.ext_boot_seq_done;
  assign u_tb_if.rst_cold_stable_ref_clk_n = rst_cold_stable_ref_clk_no;
  assign u_tb_if.rst_primary_ref_clk_n     = rst_primary_ref_clk_no;
  assign u_tb_if.rst_primary_smc_clk_n     = rst_primary_smc_clk_no;
  assign u_tb_if.rst_primary_periph_clk_n  = rst_primary_periph_clk_no;
  assign u_tb_if.fuse_sense_done           = smc_fuse_sense_done_o;
  assign u_tb_if.fuse_reset_n_delayed      = smc_fuse_reset_n_delayed_o;
  assign u_tb_if.lc_state                  = lc_state_o;

  // Cold-reset assertion counter (reference models re-baseline on it).
  logic [31:0] cold_rst_assert_count = '0;
  always @(negedge rst_cold_ni) cold_rst_assert_count <= cold_rst_assert_count + 32'd1;
  assign u_tb_if.cold_rst_assert_count = cold_rst_assert_count;

  // Primary JTAG TAP: TB drives tck/tms/trst_n/tdi, DUT drives tdo/tdo_oen.
  assign jtag_tck  = u_jtag_if.tck;
  assign jtag_tms  = u_jtag_if.tms;
  assign jtag_trst = u_jtag_if.trst_n;
  assign jtag_tdi  = u_jtag_if.tdi;
  assign u_jtag_if.tdo     = jtag_tdo;
  assign u_jtag_if.tdo_oen = jtag_tdo_oen;

  // Embedded DTP through its own TB interface, wired the way the DTP bench
  // wires its top: the one-hot TAP state and decoded instruction the DUT
  // exports, and the assertion counters of the DTP's system and power-on
  // resets, observed on the DTP instance pins (pwr_on_rst_ni is the SMC
  // reset unit's powergood_stable; rst_n_i is the primary smc-clock reset).
  logic [31:0] dtp_sys_rst_assert_count = '0;
  logic [31:0] dtp_por_assert_count     = '0;
  always @(negedge u_dut.u_dtp.rst_n_i)
    dtp_sys_rst_assert_count <= dtp_sys_rst_assert_count + 32'd1;
  always @(negedge u_dut.u_dtp.pwr_on_rst_ni) dtp_por_assert_count <= dtp_por_assert_count + 32'd1;
  assign u_dtp_tb_if.tap_state            = ptap_state;
  assign u_dtp_tb_if.inst_decoded         = ptap_inst;
  assign u_dtp_tb_if.sys_rst_assert_count = dtp_sys_rst_assert_count;
  assign u_dtp_tb_if.por_assert_count     = dtp_por_assert_count;

  // Clean-room JTAG protocol SVA checker (ocah_jtag_vip/sva) on the primary
  // TAP pins + the exported one-hot TAP state, enabled via smu_tb_if.
  ocah_jtag_sva #(
    .EN_STATE_RULES(1'b1)
  ) u_jtag_ptap_sva (
    .tck         (jtag_tck),
    .tms         (jtag_tms),
    .tdi         (jtag_tdi),
    .trst_n      (jtag_trst),
    .tdo         (jtag_tdo),
    .tdo_oen     (jtag_tdo_oen),
    .en_i        (u_tb_if.jtag_sva_en),
    .tap_state_i (ptap_state)
  );

  // ------------------------------------------------------------------
  // Quiescent tie-offs: every other cocotb-driven stimulus pin at the idle
  // value the cocotb smu_base_test bring-up sets. A scenario that needs one
  // of these pins promotes it into smu_tb_if; nothing here is driven from
  // class code.
  // ------------------------------------------------------------------

  // Cross-trigger CTM loopback, clock-stop requests, boot-stall pad.
  assign xtrig_ctm_dst_req       = '0;
  assign xtrig_ctm_src_ack       = '0;
  assign xtrig_clk_stop_req      = '0;
  assign gpio_boot_stall_drive_i = 1'b0;

  // Telemetry ATB channel 0 idle.
  assign tb_tel_atdata  = '0;
  assign tb_tel_atid    = '0;
  assign tb_tel_atvalid = 1'b0;
  assign tb_tel_afready = 1'b0;

  // External SMN AXI4 ingress: no initiator attached, request side idle
  // (the cocotb bring-up idle values: single-beat INCR shape, no valids).
  assign s_axi_awid     = '0;
  assign s_axi_awaddr   = '0;
  assign s_axi_awlen    = '0;
  assign s_axi_awsize   = 3'd3;
  assign s_axi_awburst  = 2'b01;
  assign s_axi_awlock   = 1'b0;
  assign s_axi_awcache  = '0;
  assign s_axi_awprot   = '0;
  assign s_axi_awqos    = '0;
  assign s_axi_awregion = '0;
  assign s_axi_awuser   = '0;
  assign s_axi_awvalid  = 1'b0;
  assign s_axi_wdata    = '0;
  assign s_axi_wstrb    = '0;
  assign s_axi_wlast    = 1'b1;
  assign s_axi_wuser    = '0;
  assign s_axi_wvalid   = 1'b0;
  assign s_axi_bready   = 1'b0;
  assign s_axi_arid     = '0;
  assign s_axi_araddr   = '0;
  assign s_axi_arlen    = '0;
  assign s_axi_arsize   = 3'd3;
  assign s_axi_arburst  = 2'b01;
  assign s_axi_arlock   = 1'b0;
  assign s_axi_arcache  = '0;
  assign s_axi_arprot   = '0;
  assign s_axi_arqos    = '0;
  assign s_axi_arregion = '0;
  assign s_axi_aruser   = '0;
  assign s_axi_arvalid  = 1'b0;
  assign s_axi_rready   = 1'b0;

  // Test classes (one per scenario) and the base test.
  `include "smu_tests.sv"

  initial begin
    uvm_config_db#(virtual smu_tb_if)::set(null, "*", "tb_vif", u_tb_if);
    uvm_config_db#(virtual dtp_tb_if)::set(null, "*", "dtp_tb_vif", u_dtp_tb_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "jtag_vif", u_jtag_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "axi_out_vif", u_axi_out_if);
    run_test();
  end
`endif

endmodule : smu_uvm_top

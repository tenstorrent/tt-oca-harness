// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP control-domain TB interface, shared by the cocotb and SV-UVM flows:
// the system clock and its period, the test-sequenced resets and their
// assertion counters, the lifecycle debug disables, the TAP-state and
// debug-TDR observables the checkers read, the stop_clks change counters,
// the request-activity pulse counters and READY-stall counters tb_top
// derives from the bus pins, and the SVA enables.
// The scan-network observables live in dtp_scan_if and the cross-trigger
// pins in dtp_xtrig_if; the primary TAP pins are on the shared ocah_jtag_if.
//
// cocotb deposits the clock, the resets, and the stimulus members through
// hierarchical handles (env/dtp_tb_if.py); SV-UVM sequences reach the same
// members through the virtual interface, and the harness block in tb_top
// generates the clock from clk_period_ns.

interface dtp_tb_if;

  // System-clock period the harness clock generator reads, set by the env
  // from dtp_env_cfg (the test cfg randomizes it from the runner seed).
  int unsigned clk_period_ns = 10;

  // System clock: cocotb drives it with Clock(); the SV-UVM harness toggles
  // it every half period.
  logic clk = 1'b0;

  // Driven by the TB (reset sequencing owned by the test/sequence).
  logic por_rst_n;
  logic sys_rst_n;

  // System reset armed on a JTAG2AXI read (driven by the reset-abort
  // sequences): while bit t is set (0 smc_axi, 1 smc_otp, 2 sep_otp), tb_top
  // asserts the system reset for sys_rst_on_ar_cycles clocks from the clock
  // edge that completes bridge t's next AR handshake, once per arming.
  logic [2:0] sys_rst_on_ar_arm    = '0;
  logic [3:0] sys_rst_on_ar_cycles = 4'd1;

  // The system reset the DUT and the AXI responders see (driven by tb_top):
  // sys_rst_n with the read-armed pulse.
  logic rst_n;

  // DFT controls of the DUT: test_en_i (test-mode enable for the JTAG2AXI
  // bridges and the CTN CSR crossbar) and scan_rst_ni (unused by the DUT),
  // both idle in functional mode; a DFT-mode scenario drives them here.
  logic test_en    = 1'b0;
  logic scan_rst_n = 1'b1;

  // Reset-assertion counters (driven by tb_top): the scoreboard predictors
  // re-baseline the CSR shadow and the TAP instruction on them.
  logic [31:0] sys_rst_assert_count;
  logic [31:0] por_assert_count;

  // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
  logic [15:0] tap_state;

  // Driven by the DUT top: decoded-IR one-hot observable for CHK-IR-DECODE,
  // 64 bits wide. cocotb reads an enum-typed interface member as a 32-bit
  // integer over VPI, so the member is a packed vector.
  logic [jtag_inst_reg_pkg::DecodedIrWidth-1:0] inst_decoded;

  // Lifecycle debug disables, one named member per dbg_disable_i path
  // (active-high: 1 = path disabled). Init 1 = fail-closed, matching the
  // DUT synchronizers' reset value; JTAG2AXI sequences must clear the
  // target's disable first. cocotb deposits the members by name; SV-UVM
  // writes them through drive_dbg_disable.
  logic dbg_disable_stap_io          = 1'b1;
  logic dbg_disable_stap_smc         = 1'b1;
  logic dbg_disable_stap_sep         = 1'b1;
  logic dbg_disable_stap_extra       = 1'b1;
  logic dbg_disable_stap_host        = 1'b1;
  logic dbg_disable_dft_secure       = 1'b1;
  logic dbg_disable_dft_nonsecure    = 1'b1;
  logic dbg_disable_dfd              = 1'b1;
  logic dbg_disable_smc_jtag2axi     = 1'b1;
  logic dbg_disable_smc_otp_jtag2axi = 1'b1;
  logic dbg_disable_sep_otp_jtag2axi = 1'b1;

  // The dbg_disable_i struct tb_top forwards to the DUT, bound to the
  // members above by field name.
  sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable;

  always_comb begin
    dbg_disable = '{
        stap_io: dbg_disable_stap_io,
        stap_smc: dbg_disable_stap_smc,
        stap_sep: dbg_disable_stap_sep,
        stap_extra: dbg_disable_stap_extra,
        stap_host: dbg_disable_stap_host,
        dft_secure: dbg_disable_dft_secure,
        dft_nonsecure: dbg_disable_dft_nonsecure,
        dfd: dbg_disable_dfd,
        smc_jtag2axi: dbg_disable_smc_jtag2axi,
        smc_otp_jtag2axi: dbg_disable_smc_otp_jtag2axi,
        sep_otp_jtag2axi: dbg_disable_sep_otp_jtag2axi
    };
  end

  function automatic void drive_dbg_disable(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    dbg_disable_stap_io          = d.stap_io;
    dbg_disable_stap_smc         = d.stap_smc;
    dbg_disable_stap_sep         = d.stap_sep;
    dbg_disable_stap_extra       = d.stap_extra;
    dbg_disable_stap_host        = d.stap_host;
    dbg_disable_dft_secure       = d.dft_secure;
    dbg_disable_dft_nonsecure    = d.dft_nonsecure;
    dbg_disable_dfd              = d.dfd;
    dbg_disable_smc_jtag2axi     = d.smc_jtag2axi;
    dbg_disable_smc_otp_jtag2axi = d.smc_otp_jtag2axi;
    dbg_disable_sep_otp_jtag2axi = d.sep_otp_jtag2axi;
  endfunction

  // Runtime enable for the shared AXI protocol SVA checkers.
  logic axi_sva_en = 1'b1;

  // Runtime enable for the shared JTAG protocol SVA checker.
  logic jtag_sva_en = 1'b1;

  // Request-activity pulse-counter mirrors (driven by tb_top): no-activity
  // security evidence sampled from the bus pins.
  logic [31:0] smc_axi_awvalid_count;
  logic [31:0] smc_axi_wvalid_count;
  logic [31:0] smc_axi_arvalid_count;
  logic [31:0] smc_otp_axil_awvalid_count;
  logic [31:0] smc_otp_axil_wvalid_count;
  logic [31:0] smc_otp_axil_arvalid_count;
  logic [31:0] sep_otp_axil_awvalid_count;
  logic [31:0] sep_otp_axil_wvalid_count;
  logic [31:0] sep_otp_axil_arvalid_count;
  logic [31:0] xtrig_axil_awvalid_count;
  logic [31:0] xtrig_axil_wvalid_count;
  logic [31:0] xtrig_axil_arvalid_count;
  // XTRIG CSR port stall counters (driven by tb_top): cycles with AWVALID,
  // ARVALID, and WVALID held while the CSR port keeps the matching READY low.
  logic [31:0] xtrig_axil_aw_stall_count;
  logic [31:0] xtrig_axil_ar_stall_count;
  logic [31:0] xtrig_axil_w_stall_count;
  // XTRIG CSR port occupancy counters (driven by tb_top): AW stall cycles and
  // AW acceptances while an earlier accepted AW awaits its W beat, and AR
  // stall cycles and AR acceptances while an earlier accepted AR awaits its R
  // beat. An acceptance in the cycle whose beat retires the last open request
  // does not count.
  logic [31:0] xtrig_axil_aw_open_stall_count;
  logic [31:0] xtrig_axil_aw_open_accept_count;
  logic [31:0] xtrig_axil_ar_open_stall_count;
  logic [31:0] xtrig_axil_ar_open_accept_count;
  // JTAG2AXI bridge-port stall counters (driven by tb_top): cycles with a
  // request VALID held while the responder keeps the matching READY low and
  // axi_sva_en is set.
  logic [31:0] smc_axi_aw_stall_count;
  logic [31:0] smc_axi_w_stall_count;
  logic [31:0] smc_axi_ar_stall_count;
  logic [31:0] smc_otp_axil_aw_stall_count;
  logic [31:0] smc_otp_axil_w_stall_count;
  logic [31:0] smc_otp_axil_ar_stall_count;
  logic [31:0] sep_otp_axil_aw_stall_count;
  logic [31:0] sep_otp_axil_w_stall_count;
  logic [31:0] sep_otp_axil_ar_stall_count;

  // XTRIG crossbar demux state behind the CSR port (driven by tb_top from
  // the AXI-Lite demux of the cross-trigger network): the AW lock flag,
  // which holds an AW presented to a master port whose AWREADY was low,
  // and the W-pending flag, high while the demux's W-select queue holds the
  // port of an AW whose W beat has not passed the demux.
  logic xtrig_demux_aw_lock;
  logic xtrig_demux_w_pending;

  // XTRIG CSR port spill registers (driven by tb_top): cycles in which a
  // spill register's input READY differs from holding fewer than two beats
  // or its output VALID differs from holding a beat, and cycles in which the
  // W and the R spill register hold two beats.
  logic [31:0] xtrig_axil_spill_err_count;
  logic [31:0] xtrig_axil_w_spill_full_count;
  logic [31:0] xtrig_axil_r_spill_full_count;
  // XTRIG crossbar demux counters (driven by tb_top): the port stall and
  // occupancy counters above, taken at the demux handshakes behind the CSR
  // port spill registers.
  logic [31:0] xtrig_demux_aw_stall_count;
  logic [31:0] xtrig_demux_w_stall_count;
  logic [31:0] xtrig_demux_ar_stall_count;
  logic [31:0] xtrig_demux_aw_open_stall_count;
  logic [31:0] xtrig_demux_aw_open_accept_count;
  logic [31:0] xtrig_demux_ar_open_stall_count;
  logic [31:0] xtrig_demux_ar_open_accept_count;

  // Registered BUSY of every external cross-trigger port (driven by tb_top
  // from the CTP busy outputs); STATUS.BUSY reads the same flop.
  logic [dtp_dv_cfg_pkg::NumCtp-1:0] xtrig_ctp_busy;

  // JTAG2AXI bridge state per target for the stall and reset-abort
  // scenarios, decoded by tb_top from each bridge's TCK-domain AXI state
  // machine by state name: idle; on the write path (address, data, or
  // response wait); on the read path (address or data wait). Beside them the
  // single-op pending flag, and a sticky flag set once the bridge's CDC has
  // run its TCK-side isolate-and-clear; cdc_clear_seen_clear = 1 clears the
  // sticky flags.
  logic smc_axi_fsm_idle;
  logic smc_axi_fsm_write_path;
  logic smc_axi_fsm_read_path;
  logic smc_axi_op_pending;
  logic smc_axi_cdc_clear_seen;
  logic smc_otp_fsm_idle;
  logic smc_otp_fsm_write_path;
  logic smc_otp_fsm_read_path;
  logic smc_otp_op_pending;
  logic smc_otp_cdc_clear_seen;
  logic sep_otp_fsm_idle;
  logic sep_otp_fsm_write_path;
  logic sep_otp_fsm_read_path;
  logic sep_otp_op_pending;
  logic sep_otp_cdc_clear_seen;
  logic cdc_clear_seen_clear = 1'b0;

  // Errored-beat read word per JTAG2AXI bridge port (driven by the JTAG2AXI
  // sequences): tb_top drives it onto the DUT-facing RDATA of every R beat
  // the port's responder answers with SLVERR or DECERR.
  logic [dtp_dv_cfg_pkg::SmcAxiDataWidth-1:0]  smc_axi_err_rdata = '0;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] smc_otp_axil_err_rdata = '0;
  logic [dtp_dv_cfg_pkg::OtpAxilDataWidth-1:0] sep_otp_axil_err_rdata = '0;

  // Debug-TDR observables (driven by tb_top): DEBUG_CONTROL clock-stop /
  // boot-stall outputs and the flattened IC_RESET slice outputs.
  logic stop_clks;
  logic cla_clock_stop_en;
  logic jtag_boot_stall;
  logic jtag_boot_stall_ovrd;
  logic jtag_ic_reset_smc_ovrd;
  logic jtag_ic_reset_smc_ctrl_n;
  logic jtag_ic_reset_sep_ovrd;
  logic jtag_ic_reset_sep_ctrl_n;
  logic jtag_ic_reset_ext_ovrd;
  logic jtag_ic_reset_ext_ctrl_n;

  // stop_clks change counters (driven by tb_top) while rst_n_i is high:
  // every change, and the changes outside a clk_i rising edge.
  logic [31:0] stop_clks_change_count;
  logic [31:0] stop_clks_off_edge_count;

  // CLA clock-stop request vector (driven by debug-TDR sequences; init
  // quiescent so unrelated tests see no requests).
  logic [dtp_dv_cfg_pkg::NumClkStopReq-1:0] xtrig_clk_stop_req = '0;

  // The bench configuration (dtp_dv_cfg_pkg) the cocotb bring-up compares
  // with its own copy of the table.
  logic [7:0]  cfg_num_ctp          = 8'(dtp_dv_cfg_pkg::NumCtp);
  logic [7:0]  cfg_num_int_ct       = 8'(dtp_dv_cfg_pkg::NumIntCt);
  logic [7:0]  cfg_num_clk_stop_req = 8'(dtp_dv_cfg_pkg::NumClkStopReq);
  logic [31:0] cfg_int_ct_mode      = 32'(dtp_dv_cfg_pkg::IntCtMode);
  logic [7:0]  cfg_num_extra_staps  = 8'(dtp_dv_cfg_pkg::NumExtraStaps);
  logic [7:0]  cfg_num_smc_ic_reset = 8'(dtp_dv_cfg_pkg::NumSmcIcReset);
  logic [7:0]  cfg_num_sep_ic_reset = 8'(dtp_dv_cfg_pkg::NumSepIcReset);
  logic [7:0]  cfg_num_ext_ic_reset = 8'(dtp_dv_cfg_pkg::NumExtIcReset);
  logic [7:0]  cfg_och_ver          = dtp_dv_cfg_pkg::OchVer;
  logic [31:0] cfg_idcode           = dtp_dv_cfg_pkg::Idcode;
  logic [7:0]  cfg_wire_or_pull     = 8'(dtp_dv_cfg_pkg::WireOrPull);
  logic [7:0]  cfg_wire_or_assert   = 8'(dtp_dv_cfg_pkg::WireOrAssert);
  logic [7:0]  cfg_ct_dst_latency   = 8'(dtp_dv_cfg_pkg::CtDstLatency);
  logic [7:0]  cfg_smc_axi_addr_width  = 8'(dtp_dv_cfg_pkg::SmcAxiAddrWidth);
  logic [7:0]  cfg_smc_axi_data_width  = 8'(dtp_dv_cfg_pkg::SmcAxiDataWidth);
  logic [7:0]  cfg_otp_axil_addr_width = 8'(dtp_dv_cfg_pkg::OtpAxilAddrWidth);
  logic [7:0]  cfg_otp_axil_data_width = 8'(dtp_dv_cfg_pkg::OtpAxilDataWidth);
  logic [7:0]  cfg_smc_otp_rd_pl_depth = 8'(dtp_dv_cfg_pkg::SmcOtpRdPlDepth);
  logic [7:0]  cfg_smc_otp_wr_pl_depth = 8'(dtp_dv_cfg_pkg::SmcOtpWrPlDepth);
  logic [7:0]  cfg_sep_otp_rd_pl_depth = 8'(dtp_dv_cfg_pkg::SepOtpRdPlDepth);
  logic [7:0]  cfg_sep_otp_wr_pl_depth = 8'(dtp_dv_cfg_pkg::SepOtpWrPlDepth);
  logic [7:0]  cfg_smc_rd_pl_depth     = 8'(dtp_dv_cfg_pkg::SmcRdPlDepth);
  logic [7:0]  cfg_smc_wr_pl_depth     = 8'(dtp_dv_cfg_pkg::SmcWrPlDepth);

endinterface : dtp_tb_if

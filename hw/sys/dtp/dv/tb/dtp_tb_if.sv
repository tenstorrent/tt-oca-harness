// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP control-domain TB interface, shared by the cocotb and SV-UVM flows:
// the system clock and its period, the test-sequenced resets and their
// assertion counters, the lifecycle debug disables, the TAP-state and
// debug-TDR observables the checkers read, the request-activity pulse
// counters tb_top derives from the bus pins, and the SVA enables.
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

  // DFT controls of the DUT: test_en_i (scan-enable for the clock gaters)
  // and scan_rst_ni (reset-synchronizer bypass, active-low), both idle in
  // functional mode; a DFT-mode scenario drives them here.
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
  logic [jtag_inst_reg_pkg::DECODED_IR_WIDTH-1:0] inst_decoded;

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
  // XTRIG CSR port stall counters (driven by tb_top): cycles with AWVALID
  // and ARVALID held while the crossbar keeps the matching READY low.
  logic [31:0] xtrig_axil_aw_stall_count;
  logic [31:0] xtrig_axil_ar_stall_count;

  // XTRIG crossbar demux state behind the CSR port (driven by tb_top from
  // the AXI-Lite demux of the cross-trigger network): the AW lock flag,
  // which holds an AW presented to a master port whose AWREADY was low,
  // and the W-pending flag, high from an accepted AW until its W beat
  // passes the demux.
  logic xtrig_demux_aw_lock;
  logic xtrig_demux_w_pending;

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

endinterface : dtp_tb_if

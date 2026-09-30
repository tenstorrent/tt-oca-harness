// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP scan-domain TB interface, shared by the cocotb and SV-UVM flows: the
// boundary-scan, iJTAG SIB, and extended STAP host scan-chain controls, the
// forwarded STAP TAP pins with their TMS mismatch flags and TRST assertion
// counters, and the downstream-TAP and host-segment attach enables. The scan window monitors
// sample the controls once per TCK cycle; the scan scenarios judge them
// against the SIB and 3DCR models.

interface dtp_scan_if;

  // Boundary-scan chain controls (driven by tb_top from the DUT's
  // jtag_bsr_host_scan_ctrl_o). select is qualified by the boundary-scan
  // instructions; the capture/shift/update strobes are the TAP's DR strobes
  // under every instruction; run_test_idle and test_logic_reset decode the
  // TAP state; runbist follows the RUNBIST instruction decode; chrst_n is the
  // active-low TMP conditional reset, low in Test-Logic-Reset unless
  // persistence is on.
  logic jtag_bsr_select;
  logic jtag_bsr_shift_en;
  logic jtag_bsr_capture_en;
  logic jtag_bsr_update_en;
  logic jtag_bsr_run_test_idle;
  logic jtag_bsr_test_logic_reset;
  logic jtag_bsr_runbist;
  logic jtag_bsr_chrst_n;

  // iJTAG SIB scan controls (driven by tb_top): the secure DFT, non-secure
  // DFT, and DFD host scan chains. The non-secure DFT host also exposes the
  // state and RUNBIST fields its SIB forwards ungated.
  logic jtag_dft_secure_select;
  logic jtag_dft_secure_shift_en;
  logic jtag_dft_secure_capture_en;
  logic jtag_dft_secure_update_en;
  logic jtag_dft_select;
  logic jtag_dft_shift_en;
  logic jtag_dft_capture_en;
  logic jtag_dft_update_en;
  logic jtag_dft_run_test_idle;
  logic jtag_dft_test_logic_reset;
  logic jtag_dft_runbist;
  logic jtag_dfd_select;
  logic jtag_dfd_shift_en;
  logic jtag_dfd_capture_en;
  logic jtag_dfd_update_en;

  // Extended STAP host scan controls (driven by tb_top).
  logic jtag_stap_host_select;
  logic jtag_stap_host_shift_en;
  logic jtag_stap_host_capture_en;
  logic jtag_stap_host_update_en;

  // Forwarded STAP TAP pins per host port (driven by tb_top from the DUT's
  // per-port tap_ctrl struct and TDO enable).
  logic jtag_stap_io_tms;
  logic jtag_stap_io_tck;
  logic jtag_stap_io_trst_n;
  logic jtag_stap_io_tdo_oen;
  logic jtag_stap_smc_tms;
  logic jtag_stap_smc_tck;
  logic jtag_stap_smc_trst_n;
  logic jtag_stap_smc_tdo_oen;
  logic jtag_stap_sep_tms;
  logic jtag_stap_sep_tck;
  logic jtag_stap_sep_trst_n;
  logic jtag_stap_sep_tdo_oen;
  logic jtag_stap_extra0_tms;
  logic jtag_stap_extra0_tck;
  logic jtag_stap_extra0_trst_n;
  logic jtag_stap_extra0_tdo_oen;

  // Per-port TMS mismatch flags (driven by tb_top): high when the port's
  // forwarded TMS differed from the primary TMS at the last rising TCK
  // edge.
  logic jtag_stap_io_tms_mismatch;
  logic jtag_stap_smc_tms_mismatch;
  logic jtag_stap_sep_tms_mismatch;
  logic jtag_stap_extra0_tms_mismatch;

  // Per-port host TRST assertion counters (driven by tb_top): one count per
  // falling edge of the port's forwarded TRST.
  logic [31:0] jtag_stap_io_trst_assert_count;
  logic [31:0] jtag_stap_smc_trst_assert_count;
  logic [31:0] jtag_stap_sep_trst_assert_count;
  logic [31:0] jtag_stap_extra0_trst_assert_count;

  // Downstream STAP TAP attach enables (driven by the test before
  // bring-up; default 0 keeps each STAP host port's wire loopback). With
  // a port's enable set, tb_top routes the downstream ocah_jtag_if TDO
  // into that STAP's host TDI.
  logic stap_io_ds_en     = 1'b0;
  logic stap_smc_ds_en    = 1'b0;
  logic stap_sep_ds_en    = 1'b0;
  logic stap_extra0_ds_en = 1'b0;
  // Extended STAP host segment attach enable (driven by the test before
  // bring-up; default 0 keeps the host scan loopback). With it set, tb_top
  // returns the host scan-out to the host scan-in through the host segment.
  logic stap_host_seg_en  = 1'b0;

endinterface : dtp_scan_if

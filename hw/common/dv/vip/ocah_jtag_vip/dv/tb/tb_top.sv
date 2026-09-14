// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive JTAG wire harness for the shared JTAG VIP selftests. No DUT RTL:
// cocotb attaches the VIP master and the VIP reactive TAP device to the same
// nets from both sides.
//
//   jtag_* — the one TAP connection: the master (OcahJtagMasterDriver behind
//            OcahJtagMasterSequence) drives TCK, TMS, TDI, and TRST and
//            samples TDO; the device (OcahJtagSlaveAgent behind
//            OcahJtagSlaveSequence) samples TCK, TMS, TDI, and TRST and
//            drives TDO and its output enable.
//
// ocah_jtag_sva watches the connection. In the cocotb shape the harness
// mirrors the device's TAP controller state onto jtag_tap_state as the
// one-hot a DUT exports, so the state rules run as well; in the SV-UVM shape
// the device state stays inside the slave driver, so EN_STATE_RULES is 0 and
// the pin-level rules run alone.
//
// clk is a free-running reference clock the cocotb harness drives so the
// simulator always holds a timed event while the master bit-bangs TCK.
//
// In the cocotb shape the nets are driven from cocotb (--public-flat-rw) and
// the lint waivers cover the undriven cocotb-owned nets. In the SV-UVM shape
// (+define+UVM from the native profile's [frameworks.uvm] overlay) the same
// module holds one ocah_jtag_if that the VIP master and the VIP device drive
// from opposite sides, publishes it as `jtag_vif` together with the
// covergroup sampler ocah_jtag_cov_if (cov/ocah_jtag_cov.sv) as
// `jtag_cov_vif`, and calls run_test().

`timescale 1ns / 1ps

module ocah_jtag_vip_tb_top;

`ifndef UVM
  /* verilator lint_off UNDRIVEN */
  /* verilator lint_off UNUSEDSIGNAL */
  logic clk;
  logic jtag_tck;
  logic jtag_tms;
  logic jtag_tdi;
  logic jtag_tdo;
  logic jtag_trst;
  logic jtag_tdo_oen;
  logic [15:0] jtag_tap_state;
  /* verilator lint_on UNUSEDSIGNAL */
  /* verilator lint_on UNDRIVEN */

  ocah_jtag_sva #(
    .EN_STATE_RULES(1'b1)
  ) u_jtag_sva (
    .tck        (jtag_tck),
    .tms        (jtag_tms),
    .tdi        (jtag_tdi),
    .trst_n     (jtag_trst),
    .tdo        (jtag_tdo),
    .tdo_oen    (jtag_tdo_oen),
    .en_i       (1'b1),
    .tap_state_i(jtag_tap_state)
  );
`endif

`ifdef UVM
  import uvm_pkg::*;

  ocah_jtag_if u_jtag_if ();

  ocah_jtag_sva #(
    .EN_STATE_RULES(1'b0)
  ) u_jtag_sva (
    .tck        (u_jtag_if.tck),
    .tms        (u_jtag_if.tms),
    .tdi        (u_jtag_if.tdi),
    .trst_n     (u_jtag_if.trst_n),
    .tdo        (u_jtag_if.tdo),
    .tdo_oen    (u_jtag_if.tdo_oen),
    .en_i       (1'b1),
    .tap_state_i('0)
  );

  ocah_jtag_cov_if u_jtag_cov_if (
    .tck_i  (u_jtag_if.tck),
    .trst_ni(u_jtag_if.trst_n)
  );

  `include "ocah_jtag_vip_tests.sv"

  initial begin
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "jtag_vif", u_jtag_if);
    uvm_config_db#(virtual ocah_jtag_cov_if)::set(null, "*", "jtag_cov_vif", u_jtag_cov_if);
    run_test();
  end
`endif

endmodule

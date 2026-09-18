// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive UART wire harness for the shared UART VIP selftests. No DUT RTL:
// cocotb attaches the VIP console host and a device-side line driver and
// sampler to the two nets from both ends, with the passive tap listening.
//
//   uart_h2d - host to device: the console (OcahUartConsole) drives it, the
//              device-side sampler (OcahUartLineMonitor) reconstructs it.
//   uart_d2h - device to host: the device-side driver (OcahUartMasterDriver)
//              drives it, the console's receive path reconstructs it.
//
// clk is a free-running reference clock the cocotb harness drives so the
// simulator always holds a timed event while the engines bit-bang the lines.
//
// The nets are driven from cocotb (--public-flat-rw); the lint waivers cover
// the undriven cocotb-owned nets.

`timescale 1ns / 1ps

module ocah_uart_vip_tb_top;

  /* verilator lint_off UNDRIVEN */
  /* verilator lint_off UNUSEDSIGNAL */
  logic clk;
  logic uart_h2d;
  logic uart_d2h;
  /* verilator lint_on UNUSEDSIGNAL */
  /* verilator lint_on UNDRIVEN */

endmodule

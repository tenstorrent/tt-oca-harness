// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive SPI wire harness for the shared SPI VIP selftests. No DUT RTL:
// cocotb attaches the VIP controller engine and the VIP flash device to the
// same nets from both sides, with the passive monitor listening on them.
//
//   spi_* — the one single-SPI Mode-0 connection: the controller
//           (OcahSpiMasterBfm behind OcahSpiMasterSequence) drives cs_n,
//           sclk, and mosi and samples miso; the device (OcahSpiFlash)
//           samples cs_n, sclk, and mosi and drives miso.
//   spi4_* — a four-lane connection: the controller engine drives cs_n,
//           sclk, the four data lanes and every output enable; the device
//           (OcahSpiFlash in quad_io) drives the four lanes back.
//
// clk is a free-running reference clock the cocotb harness drives so the
// simulator always holds a timed event while the controller bit-bangs sclk.
//
// The nets are driven from cocotb (--public-flat-rw); the lint waivers cover
// the undriven cocotb-owned nets.

`timescale 1ns / 1ps

module ocah_spi_vip_tb_top;

  /* verilator lint_off UNDRIVEN */
  /* verilator lint_off UNUSEDSIGNAL */
  logic clk;
  logic spi_cs_n;
  logic spi_sclk;
  logic spi_mosi;
  logic spi_miso;
  // Four-lane link: the controller engine drives lanes, their output enables
  // and the chip-select/clock enables; the flash device drives spi4_sd_in.
  logic       spi4_cs_n;
  logic       spi4_sclk;
  logic [3:0] spi4_sd_out;
  logic [3:0] spi4_sd_oe;
  logic [3:0] spi4_sd_in;
  logic       spi4_cs_oe;
  logic       spi4_sck_oe;
  /* verilator lint_on UNUSEDSIGNAL */
  /* verilator lint_on UNDRIVEN */

endmodule

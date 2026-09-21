// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passthrough-only subset of the OpenTitan `spi_device_pkg`.
//
// The upstream `spi_host` module types its passthrough ports with
// `spi_device_pkg::passthrough_req_t` / `passthrough_rsp_t`. OCAH does not
// instantiate `spi_device`, and the full upstream package imports
// `spi_device_reg_pkg` (SRAM layout, command-info tables, TPM constants), so
// vendoring it would pull the whole `spi_device` register block along. This
// overlay carries only the two structs and their defaults, taken from upstream
// `hw/ip/spi_device/rtl/spi_device_pkg.sv` and reformatted to this
// repository's SystemVerilog style, so that `spi_host` compiles unmodified
// with its passthrough interface tied off.
//
// If `spi_device` is ever vendored, delete this file and list the upstream
// package instead; the definitions here are a strict subset of it.

package spi_device_pkg;

  // Passthrough Inter-module signals
  typedef struct packed {
    // passthrough_en: switch the mux for downstream SPI pad to host system not
    // the internal SPI_HOST IP
    logic       passthrough_en;

    // Passthrough includes SCK also. The sck_en is pad out enable not CG
    // enable. The CG is placed in SPI_DEVICE IP.
    logic       sck;
    logic       sck_en;

    // CSb should be pull-up pad. In passthrough mode, CSb is directly connected
    // to the host systems CSb except when SPI_DEVICE decides to drop the
    // command.
    logic       csb;
    logic       csb_en;

    // SPI data from host system to downstream flash device.
    logic [3:0] s;
    logic [3:0] s_en;
  } passthrough_req_t;

  typedef struct packed {
    // SPI data from downstream flash device to host system.
    logic [3:0] s;
  } passthrough_rsp_t;

  parameter passthrough_req_t PASSTHROUGH_REQ_DEFAULT = '{
      passthrough_en: 1'b0,
      sck: 1'b0,
      sck_en: 1'b0,
      csb: 1'b1,
      csb_en: 1'b0,
      s: 4'h0,
      s_en: 4'h0
  };

  parameter passthrough_rsp_t PASSTHROUGH_RSP_DEFAULT = '{s: 4'h0};

endpackage : spi_device_pkg

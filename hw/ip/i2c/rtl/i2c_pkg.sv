// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Hold I2C shared parameters, FIFO widths, and AXI-Lite typedefs.
//
// Defines controller and target FIFO data widths, the ACQ FIFO entry identifiers, timeout
// mode, read/write and ACK/NACK encodings, and the axil_req_t / axil_resp_t used by i2c.

package i2c_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH = i2c_reg_pkg::I2C_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  /////////////////////
  // I2C Definitions //
  /////////////////////

  parameter int unsigned I2C_ACQ_BYTE_ID_WIDTH = 3;

  // Possible future optimization (OpenTitan #22028): encode this more
  // efficiently in the ACQ FIFO. Each entry in the
  // ACQ FIFO does not need to contain both an 8 bit data field and a 3 bit
  // identifier. We should have the ACQ FIFO be 9 bits wide where the MSB
  // indicates whether it is a data byte or a control byte. This way we can
  // add more values to this enum without having to widen the ACQ FIFO width.
  typedef enum logic [I2C_ACQ_BYTE_ID_WIDTH-1:0] {
    ACQ_DATA       = 3'b000,
    ACQ_START      = 3'b001,
    ACQ_STOP       = 3'b010,
    ACQ_RESTART    = 3'b011,
    // ACQ_NACK means one of two things:
    // 1. We received a read request to our address, but had to NACK the
    // address because our ACQ FIFO is full.
    // 2. We received too many bytes in a write request and had to NACK a data
    // byte. The NACK'ed data byte is still in the data field for inspection.
    ACQ_NACK       = 3'b100,
    // ACQ_NACK_START means that we were addressed on this item, but we timed
    // out after stretching.
    ACQ_NACK_START = 3'b101,
    // ACQ_NACK_STOP means that we were addressed during the transaction, but we
    // timed out after stretching and received the Stop to end the
    // transaction.
    ACQ_NACK_STOP  = 3'b110
  } i2c_acq_byte_id_e;

  typedef enum logic {
    STRETCH_TIMEOUT_MODE = 1'b0,
    BUS_TIMEOUT_MODE     = 1'b1
  } i2c_timeout_mode_e;

  // Width of each entry in the FMT FIFO with enough space for an 8-bit data
  // byte and 5 flags.
  parameter int unsigned CONTROLLER_TX_FIFO_WIDTH = 8 + 5;

  // Width of each entry in the RX and TX FIFO: just an 8-bit data byte.
  parameter int unsigned CONTROLLER_RX_FIFO_WIDTH = 8;
  parameter int unsigned TARGET_TX_FIFO_WIDTH = 8;

  // Width of each entry in the ACQ FIFO with enough space for an 8-bit data
  // byte and an identifier defined by i2c_acq_byte_id_e.
  parameter int unsigned TARGET_RX_FIFO_WIDTH = I2C_ACQ_BYTE_ID_WIDTH + 8;

  typedef enum bit {
    WRITE = 1'b0,
    READ = 1'b1
  } rw_e;

  typedef enum bit {
    ACK = 1'b0,
    NACK = 1'b1
  } acknack_e;

endpackage

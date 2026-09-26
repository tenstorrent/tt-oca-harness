// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold ATB telemetry widths and AXI-Lite typedefs for the receiver.
//
// Defines packet and block sizes and the axil_req_t / axil_resp_t used by
// telemetry_receiver.

package telemetry_receiver_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH =
        telemetry_receiver_reg_pkg::TELEMETRY_RECEIVER_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  /////////////////////////////////////
  // Telemetry Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned TELEMETRY_DATA_WIDTH = 8;

  typedef logic [TELEMETRY_DATA_WIDTH-1:0] telemetry_data_t;
  typedef logic [6:0] atb_id_t;  // Fixed by ATB Standard.


  ////////////////////////////////////
  // Telemetry Receiver Definitions //
  ////////////////////////////////////

  localparam int unsigned TELEMETRY_PACKET_WIDTH = 64;
  localparam int unsigned TELEMETRY_HEADER_WIDTH = 9;
  localparam int unsigned TELEMETRY_COUNTER_WIDTH = 32;
  localparam int unsigned TELEMETRY_BLOCK_WIDTH = TELEMETRY_DATA_WIDTH + 1;

  localparam int unsigned TELEMETRY_PROBE_ID_WIDTH = 5;
  typedef logic [TELEMETRY_PROBE_ID_WIDTH-1:0] telemetry_probe_id_t;

  // General
  localparam int unsigned NUM_BEATS_PER_PACKET = TELEMETRY_PACKET_WIDTH / TELEMETRY_DATA_WIDTH;
  localparam int unsigned NUM_BLOCKS_PER_PACKET = TELEMETRY_PACKET_WIDTH / TELEMETRY_BLOCK_WIDTH;

  // Telemetry message decoding
  typedef struct packed {
    logic            vld;
    telemetry_data_t counter_val_partial;
  } telemetry_block_t;

  typedef struct packed {
    logic                                         last_packet;
    telemetry_block_t [NUM_BLOCKS_PER_PACKET-1:0] blocks;
  } telemetry_packet_t;

  typedef logic [TELEMETRY_COUNTER_WIDTH-1:0] telemetry_counter_val_t;

  typedef struct packed {
    logic                   vld;
    telemetry_counter_val_t value;
  } telemetry_counter_t;

  // Register block
  localparam int unsigned NUM_COUNTER_REGS = 32;

endpackage

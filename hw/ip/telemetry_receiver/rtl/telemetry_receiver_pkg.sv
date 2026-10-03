// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold ATB telemetry widths and AXI-Lite typedefs for the receiver.
//
// Defines packet and block sizes and the axil_req_t / axil_resp_t used by
// telemetry_receiver.
// A 64-bit packet holds a last_packet bit above seven 9-bit blocks, each a valid bit and a
// data byte. The AXI-Lite address width is the register block's minimum, data is 32 bits,
// and NumCounterRegs is 32.

package telemetry_receiver_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned RegAddrWidth =
        telemetry_receiver_reg_pkg::TELEMETRY_RECEIVER_REG_MIN_ADDR_WIDTH;
  localparam int unsigned RegDataWidth = 32;
  localparam int unsigned RegStrbWidth = RegDataWidth / 8;

  typedef logic [RegAddrWidth-1:0] reg_addr_t;
  typedef logic [RegDataWidth-1:0] reg_data_t;
  typedef logic [RegStrbWidth-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  /////////////////////////////////////
  // Telemetry Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned TelemetryDataWidth = 8;

  typedef logic [TelemetryDataWidth-1:0] telemetry_data_t;
  typedef logic [6:0] atb_id_t;  // Fixed by ATB Standard.


  ////////////////////////////////////
  // Telemetry Receiver Definitions //
  ////////////////////////////////////

  localparam int unsigned TelemetryPacketWidth = 64;
  localparam int unsigned TelemetryHeaderWidth = 9;
  localparam int unsigned TelemetryCounterWidth = 32;
  localparam int unsigned TelemetryBlockWidth = TelemetryDataWidth + 1;

  localparam int unsigned TelemetryProbeIdWidth = 5;
  typedef logic [TelemetryProbeIdWidth-1:0] telemetry_probe_id_t;

  // General
  localparam int unsigned NumBeatsPerPacket = TelemetryPacketWidth / TelemetryDataWidth;
  localparam int unsigned NumBlocksPerPacket = TelemetryPacketWidth / TelemetryBlockWidth;

  // Telemetry message decoding
  typedef struct packed {
    logic            vld;
    telemetry_data_t counter_val_partial;
  } telemetry_block_t;

  typedef struct packed {
    logic                                         last_packet;
    telemetry_block_t [NumBlocksPerPacket-1:0]    blocks;
  } telemetry_packet_t;

  typedef logic [TelemetryCounterWidth-1:0] telemetry_counter_val_t;

  typedef struct packed {
    logic                   vld;
    telemetry_counter_val_t value;
  } telemetry_counter_t;

  // Register block
  localparam int unsigned NumCounterRegs = 32;

endpackage

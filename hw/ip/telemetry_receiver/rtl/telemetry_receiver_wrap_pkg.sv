// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold address-map and AXI-Lite typedefs for the telemetry receiver wrapper.
//
// Defines the 32-bit REG_ADDR_WIDTH and REG_DATA_WIDTH and the axil types used by
// telemetry_receiver_wrap, MAX_NUM_TELEMETRY_RECEIVERS (16) and at_req_t, the {atid, atdata}
// word carried across the ATB clock crossing.

package telemetry_receiver_wrap_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH = 32;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  ////////////////////////////////////
  // Telemetry Receiver Definitions //
  ////////////////////////////////////

  localparam int unsigned MAX_NUM_TELEMETRY_RECEIVERS = 16;

  // CDC
  typedef struct packed {
    telemetry_receiver_pkg::atb_id_t         atid;
    telemetry_receiver_pkg::telemetry_data_t atdata;
  } at_req_t;

endpackage

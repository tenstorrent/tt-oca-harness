// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold the ATB beat types and AXI-Lite typedefs for the receiver.
//
// Defines the axil_req_t / axil_resp_t used by telemetry_receiver and telemetry_entry_t, the
// {atid, atdata} beat its FIFO stores. The AXI-Lite address width is the register block's
// minimum and data is 32 bits.

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

  typedef struct packed {
    atb_id_t         atid;
    telemetry_data_t atdata;
  } telemetry_entry_t;

endpackage

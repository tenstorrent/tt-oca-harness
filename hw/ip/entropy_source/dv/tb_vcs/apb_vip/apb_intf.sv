// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// APB4 interface for entropy_source connectivity
//------------------------------------------------------------------------------
interface apb_intf #(
  parameter int ADDR_WIDTH = 12,
  parameter int DATA_WIDTH = 32
);
  logic                  pclk;
  logic                  presetn;
  logic [ADDR_WIDTH-1:0] paddr;
  logic                  psel;
  logic                  penable;
  logic                  pwrite;
  logic [DATA_WIDTH-1:0] pwdata;
  logic [DATA_WIDTH-1:0] prdata;
  // APB4 signals
  logic                  pready;
  logic                  pslverr;

  // Optional modports for readability
  modport master(
      input pclk, presetn,
      output paddr, psel, penable, pwrite, pwdata,
      input prdata, pready, pslverr
  );

  modport slave(
      input pclk, presetn, paddr, psel, penable, pwrite, pwdata,
      output prdata, pready, pslverr
  );
endinterface

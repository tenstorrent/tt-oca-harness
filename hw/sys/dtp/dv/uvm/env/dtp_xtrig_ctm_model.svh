// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CTM routing model (the cocotb DtpCtmRefModel twin): the
// OR-of-selected-destinations behaviour of the RTL. CT_SRC[i].CT_DST_SELECT
// selects which destination-input bits feed output/source port i; route()
// returns the outputs a destination pulse reaches. Programmed by the XTRIG
// scenario alongside the CSR writes and cross-checked on every route
// (CHK-XTRIG-ROUTE-MODEL). Plain model class held by the scenario, built
// with new(); no reporting.

class dtp_xtrig_ctm_model;

  localparam int unsigned NumPorts = dtp_pkg::DEFAULT_NUM_CTP + dtp_pkg::DEFAULT_NUM_INT_CT;
  localparam bit [31:0] SelectMask = (32'd1 << NumPorts) - 1;

  bit [31:0] select[NumPorts];

  function new();
    foreach (select[i]) select[i] = '0;
  endfunction

  function void program_src(int unsigned src_idx, bit [31:0] dst_mask);
    select[src_idx] = dst_mask & SelectMask;
  endfunction

  function bit [31:0] route(bit [31:0] dst_value);
    bit [31:0] routed = '0;
    dst_value &= SelectMask;
    foreach (select[src_idx]) begin
      if ((dst_value & select[src_idx]) != 0) routed |= 32'd1 << src_idx;
    end
    return routed & SelectMask;
  endfunction

endclass : dtp_xtrig_ctm_model

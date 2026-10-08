// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CTM routing model (the cocotb DtpXtrigCtmModel twin) from the register
// contract: CT_SRC[k].CONFIG_0.CT_DST_SELECT (cross_trigger_matrix.rdl) holds
// one bit per CT_Dst input port, and the pulses of the selected inputs are
// OR'd onto CT_Src output k. route() returns the output vector a set of input
// pulses reaches. Programmed by the XTRIG scenario alongside the CSR writes
// and compared against the DUT output vector on every route
// (CHK-XTRIG-ROUTE-MODEL). Plain model class held by the scenario, built
// with new(); no reporting.

class dtp_xtrig_ctm_model;

  localparam int unsigned NumPorts = DtpXtrigNumCtmPorts;
  localparam bit [31:0] SelectMask = (32'd1 << NumPorts) - 1;

  bit [31:0] select[NumPorts];

  function new();
    foreach (select[i]) select[i] = '0;
  endfunction

  function void program_src(int unsigned output_port, bit [31:0] input_mask);
    select[output_port] = input_mask & SelectMask;
  endfunction

  function bit [31:0] route(bit [31:0] input_pulses);
    bit [31:0] routed = '0;
    input_pulses &= SelectMask;
    foreach (select[output_port]) begin
      if ((input_pulses & select[output_port]) != 0) routed |= 32'd1 << output_port;
    end
    return routed & SelectMask;
  endfunction

endclass : dtp_xtrig_ctm_model

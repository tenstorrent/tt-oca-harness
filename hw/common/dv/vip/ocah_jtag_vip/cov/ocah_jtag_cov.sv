// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Functional-coverage collector for the shared JTAG VIP: TAP state/transition
// occupancy, IR/DR scan shapes, and reset causes. Commercial-simulator only
// (covergroups are outside Verilator's supported subset) — never add to
// Verilator filelists. Sampling is function-based so both procedural code and
// UVM subscriber write() functions can drive it; the UVM-side sampler is
// uvm/ocah_jtag_cov.svh.
//
// State numbering follows the VIP convention: IEEE 1149.1 states 0..15
// (Test-Logic-Reset = 0), i.e. the bit index of one-hot RTL encodings.

interface ocah_jtag_cov_if (
  input logic tck_i,
  input logic trst_ni
);

  // One TAP controller step: previous state, sampled TMS, next state.
  covergroup cg_step with function sample (
      int unsigned prev_state, bit tms, int unsigned next_state
  );
    option.per_instance = 1;
    cp_prev: coverpoint prev_state {bins state[] = {[0 : 15]};}
    cp_next: coverpoint next_state {bins state[] = {[0 : 15]};}
    cp_tms: coverpoint tms;
    // 32 legal transition edges (16 states x tms in {0,1}).
    x_edge  : cross cp_prev, cp_tms;
  endgroup

  // One reconstructed IR/DR scan.
  covergroup cg_scan with function sample (
      bit is_ir, int unsigned bit_count, bit instr_known, bit [5:0] instruction
  );
    option.per_instance = 1;
    cp_kind: coverpoint is_ir {bins dr = {0}; bins ir = {1};}
    cp_len: coverpoint bit_count {
      bins single = {1};
      bins short_len = {[2 : 8]};
      bins word_len = {[9 : 32]};
      bins wide_len = {[33 : 64]};
      bins huge_len = {[65 : $]};
    }
    cp_instr: coverpoint instruction iff (instr_known) {bins opcode[] = {[0 : 63]};}
    x_kind_len : cross cp_kind, cp_len;
  endgroup

  // One entry into Test-Logic-Reset, by cause.
  covergroup cg_reset with function sample (bit via_trst);
    option.per_instance = 1;
    cp_cause: coverpoint via_trst {bins tms_walk = {0}; bins trst = {1};}
  endgroup

  cg_step  step_cg  = new();
  cg_scan  scan_cg  = new();
  cg_reset reset_cg = new();

  function automatic void sample_step(input int unsigned prev_state, input bit tms,
                                      input int unsigned next_state);
    if (!trst_ni) begin
      return;
    end
    step_cg.sample(prev_state, tms, next_state);
  endfunction

  function automatic void sample_scan(input bit is_ir, input int unsigned bit_count,
                                      input bit instr_known, input bit [5:0] instruction);
    if (!trst_ni) begin
      return;
    end
    scan_cg.sample(is_ir, bit_count, instr_known, instruction);
  endfunction

  // Reset-cause coverage is sampled on the reset event itself, so it is not
  // gated on trst_ni.
  function automatic void sample_reset(input bit via_trst);
    reset_cg.sample(via_trst);
  endfunction

endinterface : ocah_jtag_cov_if

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge observables for the bench. tb_top binds one instance into
// every jtag2axi bridge and forms the inputs in the bridge's own scope from
// its AXI state machine's state names and its internal signals, so the bench
// carries no copy of the state encoding: idle; on the write path (address,
// data, or response wait); on the read path (address or data wait); the
// transaction the state machine completes on this TCK edge with its
// response, its {from the single-op buffer, with-error-status, increment}
// flags, op, AxSIZE, requested size and byte offset in the beat, and the
// series status before it; the CDC's TCK-side clear with what it discards
// ({single or with-error-status operation, series operation}); the SINGLE_OP
// Update-DR with the scanned op field; the synchronized disable.

module dtp_j2a_state_flags (
  input  logic       idle_i,
  input  logic       write_path_i,
  input  logic       read_path_i,
  input  logic       beat_done_i,
  input  logic [1:0] beat_resp_i,
  input  logic [2:0] beat_mode_i,
  input  logic [1:0] beat_op_i,
  input  logic [2:0] beat_size_i,
  input  logic [2:0] beat_req_size_i,
  input  logic [2:0] beat_offset_i,
  input  logic [1:0] sticky_i,
  input  logic       clear_pending_i,
  input  logic [1:0] abort_i,
  input  logic       single_upd_i,
  input  logic [1:0] scan_op_i,
  input  logic       sec_dis_i,
  output logic       idle_o,
  output logic       write_path_o,
  output logic       read_path_o,
  output logic       beat_done_o,
  output logic [1:0] beat_resp_o,
  output logic [2:0] beat_mode_o,
  output logic [1:0] beat_op_o,
  output logic [2:0] beat_size_o,
  output logic [2:0] beat_req_size_o,
  output logic [2:0] beat_offset_o,
  output logic [1:0] sticky_o,
  output logic       clear_pending_o,
  output logic [1:0] abort_o,
  output logic       single_upd_o,
  output logic [1:0] scan_op_o,
  output logic       sec_dis_o
);

  assign idle_o          = idle_i;
  assign write_path_o    = write_path_i;
  assign read_path_o     = read_path_i;
  assign beat_done_o     = beat_done_i;
  assign beat_resp_o     = beat_resp_i;
  assign beat_mode_o     = beat_mode_i;
  assign beat_op_o       = beat_op_i;
  assign beat_size_o     = beat_size_i;
  assign beat_req_size_o = beat_req_size_i;
  assign beat_offset_o   = beat_offset_i;
  assign sticky_o        = sticky_i;
  assign clear_pending_o = clear_pending_i;
  assign abort_o         = abort_i;
  assign single_upd_o    = single_upd_i;
  assign scan_op_o       = scan_op_i;
  assign sec_dis_o       = sec_dis_i;

endmodule : dtp_j2a_state_flags

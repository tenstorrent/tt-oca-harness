// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge state flags for the bench. tb_top binds one instance into
// every jtag2axi bridge and forms the inputs in the bridge's own scope from
// its AXI state machine's state names, so the bench carries no copy of the
// state encoding: idle; on the write path (address, data, or response wait);
// on the read path (address or data wait).

module dtp_j2a_state_flags (
  input  logic idle_i,
  input  logic write_path_i,
  input  logic read_path_i,
  output logic idle_o,
  output logic write_path_o,
  output logic read_path_o
);

  assign idle_o       = idle_i;
  assign write_path_o = write_path_i;
  assign read_path_o  = read_path_i;

endmodule : dtp_j2a_state_flags

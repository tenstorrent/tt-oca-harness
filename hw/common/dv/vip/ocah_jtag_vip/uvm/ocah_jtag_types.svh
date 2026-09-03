// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Encoding-agnostic IEEE 1149.1 TAP controller model. State values follow the
// conventional IEEE state numbering 0..15 (matching the bit index of common
// one-hot RTL encodings, so DUT-side checkers can map `$clog2(onehot)` to
// this enum directly). Literals are OCAH_JTAG_-prefixed so this package can
// be wildcard-imported alongside DUT RTL packages that use the bare names.

typedef enum int unsigned {
  OCAH_JTAG_TEST_LOGIC_RESET = 0,
  OCAH_JTAG_RUN_TEST_IDLE    = 1,
  OCAH_JTAG_SELECT_DR_SCAN   = 2,
  OCAH_JTAG_CAPTURE_DR       = 3,
  OCAH_JTAG_SHIFT_DR         = 4,
  OCAH_JTAG_EXIT1_DR         = 5,
  OCAH_JTAG_PAUSE_DR         = 6,
  OCAH_JTAG_EXIT2_DR         = 7,
  OCAH_JTAG_UPDATE_DR        = 8,
  OCAH_JTAG_SELECT_IR_SCAN   = 9,
  OCAH_JTAG_CAPTURE_IR       = 10,
  OCAH_JTAG_SHIFT_IR         = 11,
  OCAH_JTAG_EXIT1_IR         = 12,
  OCAH_JTAG_PAUSE_IR         = 13,
  OCAH_JTAG_EXIT2_IR         = 14,
  OCAH_JTAG_UPDATE_IR        = 15
} ocah_jtag_tap_state_e;

// IEEE 1149.1 next-state reference table.
function automatic ocah_jtag_tap_state_e ocah_jtag_next_state(ocah_jtag_tap_state_e cur, bit tms);
  case (cur)
    OCAH_JTAG_TEST_LOGIC_RESET: return tms ? OCAH_JTAG_TEST_LOGIC_RESET : OCAH_JTAG_RUN_TEST_IDLE;
    OCAH_JTAG_RUN_TEST_IDLE:    return tms ? OCAH_JTAG_SELECT_DR_SCAN   : OCAH_JTAG_RUN_TEST_IDLE;
    OCAH_JTAG_SELECT_DR_SCAN:   return tms ? OCAH_JTAG_SELECT_IR_SCAN   : OCAH_JTAG_CAPTURE_DR;
    OCAH_JTAG_CAPTURE_DR:       return tms ? OCAH_JTAG_EXIT1_DR         : OCAH_JTAG_SHIFT_DR;
    OCAH_JTAG_SHIFT_DR:         return tms ? OCAH_JTAG_EXIT1_DR         : OCAH_JTAG_SHIFT_DR;
    OCAH_JTAG_EXIT1_DR:         return tms ? OCAH_JTAG_UPDATE_DR        : OCAH_JTAG_PAUSE_DR;
    OCAH_JTAG_PAUSE_DR:         return tms ? OCAH_JTAG_EXIT2_DR         : OCAH_JTAG_PAUSE_DR;
    OCAH_JTAG_EXIT2_DR:         return tms ? OCAH_JTAG_UPDATE_DR        : OCAH_JTAG_SHIFT_DR;
    OCAH_JTAG_UPDATE_DR:        return tms ? OCAH_JTAG_SELECT_DR_SCAN   : OCAH_JTAG_RUN_TEST_IDLE;
    OCAH_JTAG_SELECT_IR_SCAN:   return tms ? OCAH_JTAG_TEST_LOGIC_RESET : OCAH_JTAG_CAPTURE_IR;
    OCAH_JTAG_CAPTURE_IR:       return tms ? OCAH_JTAG_EXIT1_IR         : OCAH_JTAG_SHIFT_IR;
    OCAH_JTAG_SHIFT_IR:         return tms ? OCAH_JTAG_EXIT1_IR         : OCAH_JTAG_SHIFT_IR;
    OCAH_JTAG_EXIT1_IR:         return tms ? OCAH_JTAG_UPDATE_IR        : OCAH_JTAG_PAUSE_IR;
    OCAH_JTAG_PAUSE_IR:         return tms ? OCAH_JTAG_EXIT2_IR         : OCAH_JTAG_PAUSE_IR;
    OCAH_JTAG_EXIT2_IR:         return tms ? OCAH_JTAG_UPDATE_IR        : OCAH_JTAG_SHIFT_IR;
    OCAH_JTAG_UPDATE_IR:        return tms ? OCAH_JTAG_SELECT_DR_SCAN   : OCAH_JTAG_RUN_TEST_IDLE;
    default:                    return OCAH_JTAG_TEST_LOGIC_RESET;
  endcase
endfunction

// Shortest TMS-bit path between two TAP states: breadth-first search over
// the 16-state IEEE 1149.1 graph (tms=0 explored before tms=1, matching the
// cocotb jtag_tms_path helper so both flows drive identical paths). Empty
// when start == target; the graph is strongly connected, so a path always
// exists.
function automatic void ocah_jtag_tms_path(input ocah_jtag_tap_state_e from_state,
                                           input ocah_jtag_tap_state_e to_state,
                                           output bit path[$]);
  bit          visited[16];
  int unsigned prev_state[16];
  bit          prev_tms[16];
  int unsigned bfs_queue[$];
  path.delete();
  if (from_state == to_state) return;
  visited[int'(from_state)] = 1'b1;
  bfs_queue.push_back(int'(from_state));
  while (bfs_queue.size() > 0) begin
    int unsigned cur = bfs_queue.pop_front();
    for (int unsigned t = 0; t <= 1; t++) begin
      int unsigned nxt = int'(ocah_jtag_next_state(ocah_jtag_tap_state_e'(cur), bit'(t)));
      if (visited[nxt]) continue;
      visited[nxt]    = 1'b1;
      prev_state[nxt] = cur;
      prev_tms[nxt]   = bit'(t);
      if (nxt == int'(to_state)) begin
        while (nxt != int'(from_state)) begin
          path.push_front(prev_tms[nxt]);
          nxt = prev_state[nxt];
        end
        return;
      end
      bfs_queue.push_back(nxt);
    end
  end
endfunction

// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG TAP Package
//
//-----------------------------------------------------------------------------

package jtag_tap_pkg;

  //--------------------------------------------------------------------------
  // Constants
  //--------------------------------------------------------------------------



  //--------------------------------------------------------------------------
  // IEEE 1149.1 TAP Controller States (One-Hot Encoded)
  //--------------------------------------------------------------------------
  typedef enum logic [15:0] {
    TEST_LOGIC_RESET = 16'h0001,   // State 0
    RUN_TEST_IDLE    = 16'h0002,   // State 1
    SELECT_DR_SCAN   = 16'h0004,   // State 2
    CAPTURE_DR       = 16'h0008,   // State 3
    SHIFT_DR         = 16'h0010,   // State 4
    EXIT1_DR         = 16'h0020,   // State 5
    PAUSE_DR         = 16'h0040,   // State 6
    EXIT2_DR         = 16'h0080,   // State 7
    UPDATE_DR        = 16'h0100,   // State 8
    SELECT_IR_SCAN   = 16'h0200,   // State 9
    CAPTURE_IR       = 16'h0400,   // State 10
    SHIFT_IR         = 16'h0800,   // State 11
    EXIT1_IR         = 16'h1000,   // State 12
    PAUSE_IR         = 16'h2000,   // State 13
    EXIT2_IR         = 16'h4000,   // State 14
    UPDATE_IR        = 16'h8000    // State 15
  } tap_state_e;

  //--------------------------------------------------------------------------
  // Function to check one-hot encoding
  //--------------------------------------------------------------------------
  function automatic logic is_onehot(logic [15:0] value);
    return ($countones(value) == 1);
  endfunction

  //--------------------------------------------------------------------------
  // Function to check if state is valid TAP state
  //--------------------------------------------------------------------------
  function automatic logic is_valid_tap_state(logic [15:0] state);
    case (state)
      TEST_LOGIC_RESET,
            RUN_TEST_IDLE,
            SELECT_DR_SCAN,
            CAPTURE_DR,
            SHIFT_DR,
            EXIT1_DR,
            PAUSE_DR,
            EXIT2_DR,
            UPDATE_DR,
            SELECT_IR_SCAN,
            CAPTURE_IR,
            SHIFT_IR,
            EXIT1_IR,
            PAUSE_IR,
            EXIT2_IR,
            UPDATE_IR: return 1'b1;
      default:   return 1'b0;
    endcase
  endfunction

  //--------------------------------------------------------------------------
  // Function to detect state corruption
  //--------------------------------------------------------------------------
  function automatic logic detect_state_error(logic [15:0] state);
    return (!is_onehot(state) || !is_valid_tap_state(state));
  endfunction

  //--------------------------------------------------------------------------
  // Function to check if state is a DR-side state
  //--------------------------------------------------------------------------
  function automatic logic is_dr_state(logic [15:0] state);
    case (state)
      SELECT_DR_SCAN, CAPTURE_DR, SHIFT_DR,
            EXIT1_DR, PAUSE_DR, EXIT2_DR, UPDATE_DR: return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  //--------------------------------------------------------------------------
  // Function to check if state is an IR-side state
  //--------------------------------------------------------------------------
  function automatic logic is_ir_state(logic [15:0] state);
    case (state)
      SELECT_IR_SCAN, CAPTURE_IR, SHIFT_IR,
            EXIT1_IR, PAUSE_IR, EXIT2_IR, UPDATE_IR: return 1'b1;
      default: return 1'b0;
    endcase
  endfunction

  //--------------------------------------------------------------------------
  // Default Stub Types for jtag_ptap Parameter Defaults
  // IC_RESET TDR slice stub - `.ovrd`/`.val` sub-struct signature.
  //--------------------------------------------------------------------------

  typedef struct packed {
    logic ovrd;
    logic val;
  } jtag_ic_reset_default_t;

endpackage : jtag_tap_pkg

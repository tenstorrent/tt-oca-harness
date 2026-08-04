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
function automatic ocah_jtag_tap_state_e ocah_jtag_next_state(
    ocah_jtag_tap_state_e cur, bit tms
);
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

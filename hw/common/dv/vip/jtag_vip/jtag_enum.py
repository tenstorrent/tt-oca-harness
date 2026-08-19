# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from enum import IntEnum


class JTAG_TAP_State_e(IntEnum):
    TEST_LOGIC_RESET = 0x0001
    RUN_TEST_IDLE = 0x0002
    SELECT_DR_SCAN = 0x0004
    CAPTURE_DR = 0x0008
    SHIFT_DR = 0x0010
    EXIT1_DR = 0x0020
    PAUSE_DR = 0x0040
    EXIT2_DR = 0x0080
    UPDATE_DR = 0x0100
    SELECT_IR_SCAN = 0x0200
    CAPTURE_IR = 0x0400
    SHIFT_IR = 0x0800
    EXIT1_IR = 0x1000
    PAUSE_IR = 0x2000
    EXIT2_IR = 0x4000
    UPDATE_IR = 0x8000

    @staticmethod
    def compare_states(rtl_state: int, exp_state: int) -> bool:
        """Compare expected state with RTL state"""
        return rtl_state == exp_state


class JTAG_TAP_FSM:
    _state_table = {
        JTAG_TAP_State_e.TEST_LOGIC_RESET: [
            JTAG_TAP_State_e.RUN_TEST_IDLE,
            JTAG_TAP_State_e.TEST_LOGIC_RESET,
        ],
        JTAG_TAP_State_e.RUN_TEST_IDLE: [
            JTAG_TAP_State_e.RUN_TEST_IDLE,
            JTAG_TAP_State_e.SELECT_DR_SCAN,
        ],
        JTAG_TAP_State_e.SELECT_DR_SCAN: [
            JTAG_TAP_State_e.CAPTURE_DR,
            JTAG_TAP_State_e.SELECT_IR_SCAN,
        ],
        JTAG_TAP_State_e.CAPTURE_DR: [
            JTAG_TAP_State_e.SHIFT_DR,
            JTAG_TAP_State_e.EXIT1_DR,
        ],
        JTAG_TAP_State_e.SHIFT_DR: [
            JTAG_TAP_State_e.SHIFT_DR,
            JTAG_TAP_State_e.EXIT1_DR,
        ],
        JTAG_TAP_State_e.EXIT1_DR: [
            JTAG_TAP_State_e.PAUSE_DR,
            JTAG_TAP_State_e.UPDATE_DR,
        ],
        JTAG_TAP_State_e.PAUSE_DR: [
            JTAG_TAP_State_e.PAUSE_DR,
            JTAG_TAP_State_e.EXIT2_DR,
        ],
        JTAG_TAP_State_e.EXIT2_DR: [
            JTAG_TAP_State_e.SHIFT_DR,
            JTAG_TAP_State_e.UPDATE_DR,
        ],
        JTAG_TAP_State_e.UPDATE_DR: [
            JTAG_TAP_State_e.RUN_TEST_IDLE,
            JTAG_TAP_State_e.SELECT_DR_SCAN,
        ],
        JTAG_TAP_State_e.SELECT_IR_SCAN: [
            JTAG_TAP_State_e.CAPTURE_IR,
            JTAG_TAP_State_e.TEST_LOGIC_RESET,
        ],
        JTAG_TAP_State_e.CAPTURE_IR: [
            JTAG_TAP_State_e.SHIFT_IR,
            JTAG_TAP_State_e.EXIT1_IR,
        ],
        JTAG_TAP_State_e.SHIFT_IR: [
            JTAG_TAP_State_e.SHIFT_IR,
            JTAG_TAP_State_e.EXIT1_IR,
        ],
        JTAG_TAP_State_e.EXIT1_IR: [
            JTAG_TAP_State_e.PAUSE_IR,
            JTAG_TAP_State_e.UPDATE_IR,
        ],
        JTAG_TAP_State_e.PAUSE_IR: [
            JTAG_TAP_State_e.PAUSE_IR,
            JTAG_TAP_State_e.EXIT2_IR,
        ],
        JTAG_TAP_State_e.EXIT2_IR: [
            JTAG_TAP_State_e.SHIFT_IR,
            JTAG_TAP_State_e.UPDATE_IR,
        ],
        JTAG_TAP_State_e.UPDATE_IR: [
            JTAG_TAP_State_e.RUN_TEST_IDLE,
            JTAG_TAP_State_e.SELECT_DR_SCAN,
        ],
    }

    _state_to_state_tms_list_table = {
        JTAG_TAP_State_e.TEST_LOGIC_RESET: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [0, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [0, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [0, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [0, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [0, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [0, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [0, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [0, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [0, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [0, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [0, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [0, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [0, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [0, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.RUN_TEST_IDLE: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.SELECT_DR_SCAN: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0, 1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [],
            JTAG_TAP_State_e.CAPTURE_DR: [0],
            JTAG_TAP_State_e.SHIFT_DR: [0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 0, 1, 1],
        },
        JTAG_TAP_State_e.CAPTURE_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [],
            JTAG_TAP_State_e.SHIFT_DR: [0],
            JTAG_TAP_State_e.EXIT1_DR: [1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.SHIFT_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [0],
            JTAG_TAP_State_e.EXIT1_DR: [1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.EXIT1_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT1_DR: [],
            JTAG_TAP_State_e.PAUSE_DR: [0],
            JTAG_TAP_State_e.EXIT2_DR: [0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.PAUSE_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [0],
            JTAG_TAP_State_e.EXIT2_DR: [1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.EXIT2_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [0],
            JTAG_TAP_State_e.EXIT1_DR: [0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [],
            JTAG_TAP_State_e.UPDATE_DR: [1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.UPDATE_DR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1, 0, 1, 1],
        },
        JTAG_TAP_State_e.SELECT_IR_SCAN: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0, 1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [0, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [0, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [0, 1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [0, 1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [0, 1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [0, 1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [0, 1, 1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [],
            JTAG_TAP_State_e.CAPTURE_IR: [0],
            JTAG_TAP_State_e.SHIFT_IR: [0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [0, 1, 1],
        },
        JTAG_TAP_State_e.CAPTURE_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [],
            JTAG_TAP_State_e.SHIFT_IR: [0],
            JTAG_TAP_State_e.EXIT1_IR: [1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1],
        },
        JTAG_TAP_State_e.SHIFT_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [0],
            JTAG_TAP_State_e.EXIT1_IR: [1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1],
        },
        JTAG_TAP_State_e.EXIT1_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT1_IR: [],
            JTAG_TAP_State_e.PAUSE_IR: [0],
            JTAG_TAP_State_e.EXIT2_IR: [0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [1],
        },
        JTAG_TAP_State_e.PAUSE_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [0],
            JTAG_TAP_State_e.EXIT2_IR: [1],
            JTAG_TAP_State_e.UPDATE_IR: [1, 1],
        },
        JTAG_TAP_State_e.EXIT2_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [1, 0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [0],
            JTAG_TAP_State_e.EXIT1_IR: [0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [],
            JTAG_TAP_State_e.UPDATE_IR: [1],
        },
        JTAG_TAP_State_e.UPDATE_IR: {
            JTAG_TAP_State_e.TEST_LOGIC_RESET: [1, 1, 1],
            JTAG_TAP_State_e.RUN_TEST_IDLE: [0],
            JTAG_TAP_State_e.SELECT_DR_SCAN: [1],
            JTAG_TAP_State_e.CAPTURE_DR: [1, 0],
            JTAG_TAP_State_e.SHIFT_DR: [1, 0, 0],
            JTAG_TAP_State_e.EXIT1_DR: [1, 0, 1],
            JTAG_TAP_State_e.PAUSE_DR: [1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_DR: [1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_DR: [1, 0, 1, 1],
            JTAG_TAP_State_e.SELECT_IR_SCAN: [1, 1],
            JTAG_TAP_State_e.CAPTURE_IR: [1, 1, 0],
            JTAG_TAP_State_e.SHIFT_IR: [1, 1, 0, 0],
            JTAG_TAP_State_e.EXIT1_IR: [1, 1, 0, 1],
            JTAG_TAP_State_e.PAUSE_IR: [1, 1, 0, 1, 0],
            JTAG_TAP_State_e.EXIT2_IR: [1, 1, 0, 1, 0, 1],
            JTAG_TAP_State_e.UPDATE_IR: [],
        },
    }

    @staticmethod
    def get_next_state(current_state: JTAG_TAP_State_e, tms: int) -> JTAG_TAP_State_e:
        """
        Get the next state based on the current state and TMS value.
        """
        return JTAG_TAP_FSM._state_table[current_state][tms % 2]

    @staticmethod
    def get_final_state(
        start_state: JTAG_TAP_State_e, tms_list: list[int]
    ) -> JTAG_TAP_State_e:
        """
        Get the final state based on the start state and TMS value list.
        """
        current_state = start_state
        for tms in tms_list:
            current_state = JTAG_TAP_FSM.get_next_state(current_state, tms)
        return current_state

    @staticmethod
    def get_tms_list(
        current_state: JTAG_TAP_State_e, target_state: JTAG_TAP_State_e
    ) -> list[int]:
        """
        Get the TMS value list based on the current state and target state.
        """
        return JTAG_TAP_FSM._state_to_state_tms_list_table[current_state][target_state]

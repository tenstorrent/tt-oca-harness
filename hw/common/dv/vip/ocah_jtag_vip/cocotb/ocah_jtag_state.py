# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCAH-owned IEEE 1149.1 TAP state helpers."""

from __future__ import annotations

from collections import deque
from enum import IntEnum
from random import Random
from typing import Any


class OcahJtagState(IntEnum):
    """IEEE 1149.1 TAP controller states using OCAH/DTP one-hot values."""

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


_NAME_ALIASES = {
    "SELECT_DR": "SELECT_DR_SCAN",
    "SELECT_IR": "SELECT_IR_SCAN",
    "RTI": "RUN_TEST_IDLE",
    "TLR": "TEST_LOGIC_RESET",
}

_TRANSITIONS: dict[OcahJtagState, tuple[OcahJtagState, OcahJtagState]] = {
    OcahJtagState.TEST_LOGIC_RESET: (
        OcahJtagState.RUN_TEST_IDLE,
        OcahJtagState.TEST_LOGIC_RESET,
    ),
    OcahJtagState.RUN_TEST_IDLE: (
        OcahJtagState.RUN_TEST_IDLE,
        OcahJtagState.SELECT_DR_SCAN,
    ),
    OcahJtagState.SELECT_DR_SCAN: (
        OcahJtagState.CAPTURE_DR,
        OcahJtagState.SELECT_IR_SCAN,
    ),
    OcahJtagState.CAPTURE_DR: (
        OcahJtagState.SHIFT_DR,
        OcahJtagState.EXIT1_DR,
    ),
    OcahJtagState.SHIFT_DR: (
        OcahJtagState.SHIFT_DR,
        OcahJtagState.EXIT1_DR,
    ),
    OcahJtagState.EXIT1_DR: (
        OcahJtagState.PAUSE_DR,
        OcahJtagState.UPDATE_DR,
    ),
    OcahJtagState.PAUSE_DR: (
        OcahJtagState.PAUSE_DR,
        OcahJtagState.EXIT2_DR,
    ),
    OcahJtagState.EXIT2_DR: (
        OcahJtagState.SHIFT_DR,
        OcahJtagState.UPDATE_DR,
    ),
    OcahJtagState.UPDATE_DR: (
        OcahJtagState.RUN_TEST_IDLE,
        OcahJtagState.SELECT_DR_SCAN,
    ),
    OcahJtagState.SELECT_IR_SCAN: (
        OcahJtagState.CAPTURE_IR,
        OcahJtagState.TEST_LOGIC_RESET,
    ),
    OcahJtagState.CAPTURE_IR: (
        OcahJtagState.SHIFT_IR,
        OcahJtagState.EXIT1_IR,
    ),
    OcahJtagState.SHIFT_IR: (
        OcahJtagState.SHIFT_IR,
        OcahJtagState.EXIT1_IR,
    ),
    OcahJtagState.EXIT1_IR: (
        OcahJtagState.PAUSE_IR,
        OcahJtagState.UPDATE_IR,
    ),
    OcahJtagState.PAUSE_IR: (
        OcahJtagState.PAUSE_IR,
        OcahJtagState.EXIT2_IR,
    ),
    OcahJtagState.EXIT2_IR: (
        OcahJtagState.SHIFT_IR,
        OcahJtagState.UPDATE_IR,
    ),
    OcahJtagState.UPDATE_IR: (
        OcahJtagState.RUN_TEST_IDLE,
        OcahJtagState.SELECT_DR_SCAN,
    ),
}


def coerce_jtag_state(state: Any) -> OcahJtagState:
    """Return an `OcahJtagState` from an enum, int, or state-name string."""
    if isinstance(state, OcahJtagState):
        return state
    if isinstance(state, IntEnum):
        return OcahJtagState(int(state))
    if isinstance(state, int):
        return OcahJtagState(state)

    name = getattr(state, "name", state)
    if not isinstance(name, str):
        raise ValueError(f"unsupported JTAG TAP state {state!r}")
    normalized = name.upper().replace("-", "_")
    normalized = _NAME_ALIASES.get(normalized, normalized)
    return OcahJtagState[normalized]


def next_jtag_state(state: OcahJtagState, tms: int) -> OcahJtagState:
    """Return the next TAP state for a sampled TMS bit."""
    return _TRANSITIONS[coerce_jtag_state(state)][1 if int(tms) else 0]


def jtag_tms_path(start: Any, target: Any) -> list[int]:
    """Return a shortest TMS-bit path between two TAP states."""
    start_state = coerce_jtag_state(start)
    target_state = coerce_jtag_state(target)
    if start_state == target_state:
        return []

    queue: deque[tuple[OcahJtagState, list[int]]] = deque([(start_state, [])])
    seen = {start_state}
    while queue:
        state, path = queue.popleft()
        for tms in (0, 1):
            nxt = next_jtag_state(state, tms)
            if nxt in seen:
                continue
            nxt_path = [*path, tms]
            if nxt == target_state:
                return nxt_path
            seen.add(nxt)
            queue.append((nxt, nxt_path))
    raise ValueError(f"no TAP path from {start_state.name} to {target_state.name}")


def random_jtag_state(rng: Random, *, exclude: set[OcahJtagState] | None = None) -> OcahJtagState:
    """Choose a deterministic random TAP state from the supplied RNG."""
    excluded = set(exclude or set())
    choices = [state for state in OcahJtagState if state not in excluded]
    if not choices:
        raise ValueError("no TAP state choices remain after exclusions")
    return rng.choice(choices)

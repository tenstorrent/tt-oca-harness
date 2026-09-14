# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""IEEE 1149.1 TAP controller reference model for OCAH JTAG checking.

Rule provenance: all TAP contracts are implemented from the public IEEE Std
1149.1 clause descriptions. No third-party protocol-checker source was
consulted or copied.
"""

from __future__ import annotations

from collections.abc import Iterable

from .ocah_jtag_item import OcahJtagStateItem
from .ocah_jtag_state import OcahJtagState, coerce_jtag_state, next_jtag_state

__all__ = ["OcahJtagTapRefModel", "TLR_TMS_ONES"]

# IEEE 1149.1 guarantees Test-Logic-Reset after five rising TCK edges with
# TMS held at 1, regardless of the starting controller state.
TLR_TMS_ONES = 5

_MAX_HISTORY_DEFAULT = 2000


class OcahJtagTapRefModel:
    """Pure-Python IEEE 1149.1 TAP controller reference model.

    Tracks the predicted controller state across TMS steps and predicts the
    data behavior of the mandatory BYPASS and device-identification registers.
    The model holds no simulator handles, so it can be unit-tested standalone
    and shared between active sequences and passive scoreboards.
    """

    def __init__(
        self,
        *,
        name: str = "OcahJtagTapRefModel",
        max_history: int = _MAX_HISTORY_DEFAULT,
    ) -> None:
        self.name = name
        self._max_history = int(max_history)
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self.state_history: list[OcahJtagStateItem] = []
        self.visited_states: set[OcahJtagState] = {self._state}

    @property
    def state(self) -> OcahJtagState:
        """Current predicted TAP controller state."""
        return self._state

    def clear(self) -> None:
        """Return to Test-Logic-Reset and drop retained history."""
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self.state_history.clear()
        self.visited_states = {self._state}

    def reset(self) -> OcahJtagState:
        """Model a TAP reset (TRST assertion or a TMS-high walk) to TLR."""
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self.visited_states.add(self._state)
        return self._state

    def sync(self, state) -> OcahJtagState:
        """Re-align the model to a known state after BFM-internal navigation.

        Scan helpers that end back in Run-Test/Idle move the TAP without
        per-step visibility; call this at those landing points so subsequent
        `step()` predictions start from the true controller state.
        """
        self._state = coerce_jtag_state(state)
        self.visited_states.add(self._state)
        return self._state

    def step(
        self,
        tms: int,
        *,
        tdi: int = 0,
        tdo: int = 0,
        time_ns: float | None = None,
    ) -> OcahJtagState:
        """Advance one rising TCK edge with the sampled TMS bit."""
        previous = self._state
        self._state = next_jtag_state(previous, tms)
        self.visited_states.add(self._state)
        if len(self.state_history) < self._max_history:
            self.state_history.append(
                OcahJtagStateItem(
                    previous_state=previous,
                    tms=int(tms) & 0x1,
                    next_state=self._state,
                    tdi=tdi,
                    tdo=tdo,
                    time_ns=time_ns,
                    source=self.name,
                )
            )
        return self._state

    def steps(self, tms_bits: Iterable[int]) -> OcahJtagState:
        """Advance through a TMS bit sequence and return the final state."""
        for tms in tms_bits:
            self.step(tms)
        return self._state

    @staticmethod
    def predict_bypass_tdo(pattern: int, width: int, *, capture_bit: int = 0) -> int:
        """Expected LSB-first TDO for a scan through the one-bit BYPASS register.

        The bypass register captures a fixed bit and then delays TDI to TDO by
        exactly one TCK, so bit 0 of the observed value is the captured bit and
        bits [width-1:1] are the first width-1 shifted-in pattern bits.
        """
        if width <= 0:
            return 0
        mask = (1 << max(width - 1, 0)) - 1
        return (capture_bit & 0x1) | ((pattern & mask) << 1)

    @staticmethod
    def predict_idcode_marker() -> int:
        """The device-identification register always presents 1 in bit 0."""
        return 1

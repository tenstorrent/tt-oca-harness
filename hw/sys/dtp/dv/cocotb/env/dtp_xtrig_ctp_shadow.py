# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Programmed mode and polarity of every external CTP.

The SV-UVM twin is ``uvm/env/dtp_xtrig_ctp_shadow.svh``.
"""

from __future__ import annotations

from .dtp_xtrig_types import (
    XTRIG_CTP_MODE_P2P,
    XTRIG_CTP_MODE_WIRE_OR,
    XTRIG_NUM_CTP,
    XTRIG_WIRE_OR_PULL,
    check_ctp_idx,
)

__all__ = ["DtpXtrigCtpShadow"]


class DtpXtrigCtpShadow:
    """Programmed CONFIG.MODE and CONFIG.INVERT of every external CTP.

    Held by the env cfg, so it outlives a scenario pass: the DUT keeps its CTP
    configuration from one pass to the next. A system reset or a CONFIG clear
    returns every CTP to wire-OR, not inverted (the register reset value).
    """

    def __init__(self) -> None:
        self.modes = [XTRIG_CTP_MODE_WIRE_OR] * XTRIG_NUM_CTP
        self.inverts = [0] * XTRIG_NUM_CTP

    def clear(self) -> None:
        self.modes = [XTRIG_CTP_MODE_WIRE_OR] * XTRIG_NUM_CTP
        self.inverts = [0] * XTRIG_NUM_CTP

    def note(self, ctp_idx: int, *, mode: int, invert: int) -> None:
        check_ctp_idx(ctp_idx)
        self.modes[ctp_idx] = mode
        self.inverts[ctp_idx] = invert

    @property
    def p2p_mask(self) -> int:
        return sum(1 << i for i, mode in enumerate(self.modes) if mode == XTRIG_CTP_MODE_P2P)

    @property
    def invert_mask(self) -> int:
        return sum(1 << i for i, inv in enumerate(self.inverts) if inv)

    @property
    def wire_pull_mask(self) -> int:
        """Rest level of every CTP's private wire: the pull of the board built for its INVERT."""
        return sum(XTRIG_WIRE_OR_PULL[inv] << i for i, inv in enumerate(self.inverts))

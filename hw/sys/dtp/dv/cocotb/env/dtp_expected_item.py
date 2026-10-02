# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One scalar expectation from a DTP reference model, and the callback export it travels on.

``DtpExpectedItem`` is paired by the scoreboard with the observed item it
was predicted from: the expected value under a mask, the evidence context,
and whether the pair carries a contract at all (``compare=False`` pairs and
drops without a record, so a reference model can publish one item per
observed item and keep the two streams in lockstep). The SV-UVM twin is
``dtp_expected_item``.

``DtpAnalysisImp`` is an analysis export that hands each item to a bound
method, so one component can take several streams, as the SV-UVM
``uvm_analysis_imp_decl`` exports do.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyuvm import uvm_analysis_export

__all__ = ["DtpAnalysisImp", "DtpExpectedItem"]

_MASK64 = (1 << 64) - 1


@dataclass(frozen=True)
class DtpExpectedItem:
    """Expected value under a mask, or no contract for the paired observation."""

    compare: bool = True
    expected: int = 0
    mask: int = _MASK64
    context: str = ""
    time_ns: float | None = None


class DtpAnalysisImp(uvm_analysis_export):
    """Analysis export that routes each written item to ``write_fn``."""

    def __init__(self, name: str, parent: object, write_fn: Callable[[Any], None]) -> None:
        super().__init__(name, parent)
        self._write_fn = write_fn

    def write(self, item: Any) -> None:
        self._write_fn(item)

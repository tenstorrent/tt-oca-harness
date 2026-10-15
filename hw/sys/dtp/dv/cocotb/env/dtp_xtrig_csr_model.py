# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-trigger CSR shadow: the readback value of every CSR with a readback contract.

The CTM selects, CTP CONFIG and STRETCH_MULT are rebuilt from the writes
observed on the XTRIG AXI-Lite port under their byte strobes and the
register's implemented-bit mask, and cleared on every system or power-on
reset. Each register is keyed by the CSR word that holds it
(``xtrig_csr_word``). Plain class held by ``DtpXtrigCsrRefModel``; no
reporting. The SV-UVM twin is ``dtp_xtrig_csr_model``.
"""

from __future__ import annotations

from .dtp_xtrig_types import apply_wstrb, xtrig_csr_word

__all__ = ["DtpXtrigCsrModel"]


class DtpXtrigCsrModel:
    """Readback shadow of the cross-trigger CSR words."""

    def __init__(self) -> None:
        self._shadow: dict[int, int] = {}

    def clear(self) -> None:
        self._shadow.clear()

    def write(self, addr: int, data: int, *, wstrb: int, mask: int, reset_value: int) -> None:
        """An OKAY write: merge the strobed bytes into the shadow under the mask."""
        current = self.read(addr, mask=mask, reset_value=reset_value)
        self._shadow[xtrig_csr_word(addr)] = apply_wstrb(current, data, wstrb) & mask

    def read(self, addr: int, *, mask: int, reset_value: int) -> int:
        """Expected readback: the shadow, or the register's reset value."""
        return self._shadow.get(xtrig_csr_word(addr), reset_value) & mask

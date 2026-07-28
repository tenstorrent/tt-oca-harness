# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Protocol sanity checker for OCAH JTAG item streams."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ocah_jtag_item import OcahJtagScanItem


@dataclass(frozen=True)
class OcahJtagCheckerError:
    """Single JTAG checker finding."""

    message: str
    item: OcahJtagScanItem


class OcahJtagChecker:
    """Deterministic item-level checker for IEEE 1149.1 scan records."""

    def __init__(
        self,
        *,
        name: str = "OcahJtagChecker",
        ir_width: int | None = None,
        raise_on_error: bool = True,
    ) -> None:
        self.name = name
        self.ir_width = ir_width
        self.raise_on_error = raise_on_error
        self.log = logging.getLogger(name)
        self.errors: list[OcahJtagCheckerError] = []

    def attach_monitor(self, monitor) -> None:
        """Attach checker to an `OcahJtagMonitor` item callback."""
        monitor.add_item_callback(self.check_item)

    def clear(self) -> None:
        self.errors.clear()

    def check_item(self, item: OcahJtagScanItem) -> bool:
        """Check one scan item. Returns True when no new finding is recorded."""
        before = len(self.errors)
        self._check_width(item)
        self._check_idcode_marker(item)
        self._check_bypass_shape(item)
        return len(self.errors) == before

    def assert_clean(self) -> None:
        """Raise if any retained checker findings exist."""
        if not self.errors:
            return
        joined = "\n".join(error.message for error in self.errors)
        raise AssertionError(f"{self.name}: {len(self.errors)} JTAG checker error(s):\n{joined}")

    def _record(self, message: str, item: OcahJtagScanItem) -> None:
        error = OcahJtagCheckerError(message=message, item=item)
        self.errors.append(error)
        self.log.error("%s: %s", self.name, message)
        if self.raise_on_error:
            raise AssertionError(f"{self.name}: {message}")

    def _check_width(self, item: OcahJtagScanItem) -> None:
        if item.bit_count < 0:
            self._record(f"{item.kind} scan has negative bit_count={item.bit_count}", item)
        if item.is_ir and self.ir_width is not None and item.bit_count != self.ir_width:
            self._record(
                f"IR scan width {item.bit_count} does not match expected {self.ir_width}",
                item,
            )

    def _check_idcode_marker(self, item: OcahJtagScanItem) -> None:
        if not item.is_dr or item.instruction != 0x01 or item.bit_count < 32:
            return
        if (item.tdo_value & 0x1) != 1:
            self._record("IDCODE DR scan marker bit[0] is not 1", item)

    def _check_bypass_shape(self, item: OcahJtagScanItem) -> None:
        if not item.is_dr or item.instruction is None or item.bit_count <= 1:
            return
        # BYPASS-like scans are often wider than the one-bit register because
        # tests intentionally push long patterns through the one-cycle delay.
        if item.bit_count > 0 and item.tdo_value < 0:
            self._record("DR scan returned a negative TDO value", item)

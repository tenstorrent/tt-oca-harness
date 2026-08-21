# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Protocol sanity checker for OCAH APB transaction items."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ocah_apb_item import OcahApbItem


@dataclass(frozen=True)
class OcahApbCheckerError:
    """Single APB checker finding."""

    message: str
    item: OcahApbItem


class OcahApbChecker:
    """Deterministic item-level APB checker."""

    def __init__(
        self,
        *,
        name: str = "OcahApbChecker",
        data_width: int = 32,
        raise_on_error: bool = True,
    ) -> None:
        self.name = name
        self.data_width = data_width
        self.raise_on_error = raise_on_error
        self.log = logging.getLogger(name)
        self.errors: list[OcahApbCheckerError] = []

    def attach_monitor(self, monitor) -> None:
        """Attach this checker to an OCAH APB monitor item callback."""
        monitor.add_item_callback(self.check_item)

    def clear(self) -> None:
        self.errors.clear()

    def check_item(self, item: OcahApbItem) -> bool:
        """Check one completed APB item. Returns True when no new error is found."""
        before = len(self.errors)
        self._check_response(item)
        self._check_strobe(item)
        self._check_wait_cycles(item)
        return len(self.errors) == before

    def assert_clean(self) -> None:
        """Raise if any checker findings were retained."""
        if not self.errors:
            return
        joined = "\n".join(error.message for error in self.errors)
        raise AssertionError(f"{self.name}: {len(self.errors)} protocol error(s):\n{joined}")

    def _record(self, message: str, item: OcahApbItem) -> None:
        error = OcahApbCheckerError(message=message, item=item)
        self.errors.append(error)
        self.log.error("%s: %s", self.name, message)
        if self.raise_on_error:
            raise AssertionError(f"{self.name}: {message}")

    def _check_response(self, item: OcahApbItem) -> None:
        if item.timed_out and item.ok:
            self._record("APB timed-out item cannot be OK", item)
        if item.pslverr and item.ok:
            self._record("APB item has PSLVERR but ok=True", item)
        if not item.pslverr and not item.timed_out and not item.ok:
            self._record("APB item has ok=False without PSLVERR or timeout", item)

    def _check_strobe(self, item: OcahApbItem) -> None:
        if not item.is_write or item.strobe is None or item.strobe < 0:
            return
        byte_lanes = max(self.data_width // 8, 1)
        if item.strobe >= (1 << byte_lanes):
            self._record(
                f"APB write strobe 0x{item.strobe:x} exceeds {byte_lanes} byte lanes",
                item,
            )

    def _check_wait_cycles(self, item: OcahApbItem) -> None:
        if item.wait_cycles < 0:
            self._record(f"APB item has negative wait_cycles={item.wait_cycles}", item)

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Protocol sanity checker for OCAH AXI transaction items."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .ocah_axi_item import OcahAxiItem
from .results import RESP_DECERR, RESP_EXOKAY, RESP_OKAY, RESP_SLVERR, RESP_TIMEOUT

LEGAL_RESPONSES = {RESP_OKAY, RESP_EXOKAY, RESP_SLVERR, RESP_DECERR, RESP_TIMEOUT}


@dataclass(frozen=True)
class OcahAxiCheckerError:
    """Single checker finding."""

    message: str
    item: OcahAxiItem


class OcahAxiChecker:
    """Deterministic item-level AXI/AXI-Lite checker."""

    def __init__(
        self,
        *,
        name: str = "OcahAxiChecker",
        raise_on_error: bool = True,
        check_4kb_boundary: bool = True,
        check_alignment: bool = False,
    ) -> None:
        self.name = name
        self.raise_on_error = raise_on_error
        self.check_4kb_boundary = check_4kb_boundary
        self.check_alignment = check_alignment
        self.log = logging.getLogger(name)
        self.errors: list[OcahAxiCheckerError] = []

    def attach_monitor(self, monitor) -> None:
        """Attach this checker to an OCAH monitor item callback."""
        monitor.add_item_callback(self.check_item)

    def clear(self) -> None:
        """Clear retained checker findings."""
        self.errors.clear()

    def check_item(self, item: OcahAxiItem) -> bool:
        """Check one completed item. Returns True when no new error is found."""
        before = len(self.errors)
        self._check_response_codes(item)
        self._check_axi_lite_single_beat(item)
        self._check_expected_beat_count(item)
        self._check_alignment(item)
        self._check_4kb(item)
        return len(self.errors) == before

    def assert_clean(self) -> None:
        """Raise if any checker findings were retained."""
        if not self.errors:
            return
        joined = "\n".join(error.message for error in self.errors)
        raise AssertionError(f"{self.name}: {len(self.errors)} protocol error(s):\n{joined}")

    def _record(self, message: str, item: OcahAxiItem) -> None:
        error = OcahAxiCheckerError(message=message, item=item)
        self.errors.append(error)
        self.log.error("%s: %s", self.name, message)
        if self.raise_on_error:
            raise AssertionError(f"{self.name}: {message}")

    def _check_response_codes(self, item: OcahAxiItem) -> None:
        for resp in item.resp_list:
            if int(resp) not in LEGAL_RESPONSES:
                self._record(f"illegal AXI response code {resp}", item)

    def _check_axi_lite_single_beat(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4-lite":
            return
        if item.beat_count > 1:
            self._record(f"AXI-Lite item has {item.beat_count} beats; expected 1", item)
        if item.burst not in (None, 0):
            self._record(f"AXI-Lite item carries unexpected burst={item.burst}", item)
        if item.transaction_id not in (None, 0):
            self._record(f"AXI-Lite item carries unexpected id={item.transaction_id}", item)

    def _check_expected_beat_count(self, item: OcahAxiItem) -> None:
        expected = item.metadata.get("expected_beats")
        if expected is None:
            return
        if item.beat_count != int(expected):
            self._record(
                f"{item.protocol} {item.direction} beat_count={item.beat_count}, expected={expected}",
                item,
            )

    def _check_alignment(self, item: OcahAxiItem) -> None:
        if not self.check_alignment or item.size is None:
            return
        beat_bytes = 2 ** int(item.size)
        if item.address % beat_bytes:
            self._record(
                f"{item.protocol} {item.direction} address 0x{item.address:x} is not "
                f"aligned to {beat_bytes} bytes",
                item,
            )

    def _check_4kb(self, item: OcahAxiItem) -> None:
        if not self.check_4kb_boundary or item.protocol != "axi4" or item.size is None:
            return
        beat_bytes = 2 ** int(item.size)
        transfer_bytes = beat_bytes * max(item.beat_count, 1)
        if (item.address & 0xFFF) + transfer_bytes > 0x1000:
            self._record(
                f"AXI4 {item.direction} crosses 4KB boundary: "
                f"addr=0x{item.address:x}, bytes={transfer_bytes}",
                item,
            )

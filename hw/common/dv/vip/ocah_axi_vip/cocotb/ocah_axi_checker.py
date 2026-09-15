# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Protocol sanity checker for OCAH AXI transaction items.

Item-level protocol legality rules are retained in ``errors``; named exact-value
evidence (``CHK-* PASS/FAIL`` lines and ``CHECKER_SUMMARY``) is delegated to the
common ``ocah_checker.OcahChecker`` core, following the composition contract in
``hw/common/dv/docs/vip-checker-model.adoc``.

Rule provenance: all protocol rules are implemented from the public AMBA AXI4
specification (ARM IHI 0022) rule descriptions. No third-party protocol-checker
source was consulted or copied.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ocah_checker import OcahChecker

from .ocah_axi_item import OcahAxiItem
from .ocah_axi_types import RESP_DECERR, RESP_EXOKAY, RESP_OKAY, RESP_SLVERR, RESP_TIMEOUT

LEGAL_RESPONSES = {RESP_OKAY, RESP_EXOKAY, RESP_SLVERR, RESP_DECERR, RESP_TIMEOUT}

BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2
_LEGAL_BURSTS = {BURST_FIXED, BURST_INCR, BURST_WRAP}
_WRAP_LEGAL_BEATS = {2, 4, 8, 16}
_FIXED_MAX_BEATS = 16


@dataclass(frozen=True)
class OcahAxiCheckerError:
    """Single checker finding."""

    message: str
    item: OcahAxiItem
    rule: str = ""


class OcahAxiChecker:
    """Deterministic item-level AXI/AXI-Lite checker with named evidence."""

    def __init__(
        self,
        *,
        name: str = "OcahAxiChecker",
        raise_on_error: bool = True,
        check_4kb_boundary: bool = True,
        check_alignment: bool = False,
        check_strobes: bool = True,
        bus_bytes: int | None = None,
        required_ids: Iterable[str] = (),
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.raise_on_error = raise_on_error
        self.check_4kb_boundary = check_4kb_boundary
        self.check_alignment = check_alignment
        self.check_strobes = check_strobes
        self.bus_bytes = bus_bytes
        self.log = logger or logging.getLogger(name)
        self.errors: list[OcahAxiCheckerError] = []
        self.evidence = OcahChecker(
            name=name,
            required_ids=required_ids,
            fail_fast=raise_on_error,
            logger=self.log,
        )

    def attach_monitor(self, monitor) -> None:
        """Attach this checker to an OCAH monitor item callback."""
        monitor.add_item_callback(self.check_item)

    def clear(self) -> None:
        """Clear retained checker findings and named evidence."""
        self.errors.clear()
        self.evidence.clear()

    def check_item(self, item: OcahAxiItem) -> bool:
        """Check one completed item. Returns True when no new error is found."""
        before = len(self.errors)
        self._check_response_codes(item)
        self._check_axi_lite_single_beat(item)
        self._check_axi_lite_resp(item)
        self._check_expected_beat_count(item)
        self._check_burst_legal(item)
        self._check_size_legal(item)
        self._check_wrap(item)
        self._check_fixed_len(item)
        self._check_alignment(item)
        self._check_4kb(item)
        self._check_strobe_legal(item)
        return len(self.errors) == before

    def assert_clean(self) -> None:
        """Raise if any checker findings were retained."""
        if not self.errors:
            return
        joined = "\n".join(error.message for error in self.errors)
        raise AssertionError(f"{self.name}: {len(self.errors)} protocol error(s):\n{joined}")

    def expect_equal(
        self,
        check_id: str,
        observed: Any,
        expected: Any,
        *,
        context: str = "",
    ) -> bool:
        """Emit one exact-value evidence check through the common core."""
        return self.evidence.expect_equal(check_id, observed, expected, context=context)

    def expect_true(
        self,
        check_id: str,
        condition: Any,
        *,
        context: str = "",
    ) -> bool:
        """Emit one boolean evidence check through the common core."""
        return self.evidence.expect_true(check_id, condition, context=context)

    def expect_not_timed_out(
        self,
        check_id: str,
        *,
        timed_out: bool,
        timeout_ns: float,
        context: str = "",
    ) -> bool:
        """Require an AXI transaction to complete within its declared bound."""
        return self.evidence.expect_not_timed_out(
            check_id, timed_out=timed_out, timeout_ns=timeout_ns, context=context
        )

    def expect_timeout(
        self,
        check_id: str,
        *,
        timed_out: bool,
        timeout_ns: float,
        context: str = "",
    ) -> bool:
        """Require an explicitly expected, bounded AXI timeout."""
        return self.evidence.expect_timeout(
            check_id, timed_out=timed_out, timeout_ns=timeout_ns, context=context
        )

    def finalize(self) -> None:
        """Fail on retained protocol findings or incomplete named evidence."""
        self.assert_clean()
        self.evidence.finalize()

    def _record(self, rule: str, message: str, item: OcahAxiItem) -> None:
        full_message = f"{rule}: {message}"
        error = OcahAxiCheckerError(message=full_message, item=item, rule=rule)
        self.errors.append(error)
        self.log.error("%s: %s", self.name, full_message)
        if self.raise_on_error:
            raise AssertionError(f"{self.name}: {full_message}")

    def _check_response_codes(self, item: OcahAxiItem) -> None:
        if not item.resp_list and not item.timed_out:
            # A completed transaction with no response beats verified nothing;
            # only a genuine timeout may carry an empty response list.
            self._record(
                "AXI-RESP-LEGAL",
                "completed item carries no response beats",
                item,
            )
        for resp in item.resp_list:
            if int(resp) not in LEGAL_RESPONSES:
                self._record("AXI-RESP-LEGAL", f"illegal AXI response code {resp}", item)
            elif int(resp) == RESP_TIMEOUT and not item.timed_out:
                # The timeout sentinel is TB bookkeeping, not a bus encoding;
                # it is only legal on an item that actually timed out.
                self._record(
                    "AXI-RESP-LEGAL",
                    "timeout response sentinel on an item without timed_out",
                    item,
                )

    def _check_axi_lite_single_beat(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4-lite":
            return
        if item.beat_count > 1:
            self._record(
                "AXI-LITE-SINGLE",
                f"AXI-Lite item has {item.beat_count} beats; expected 1",
                item,
            )
        if item.burst not in (None, 0):
            self._record(
                "AXI-LITE-SINGLE", f"AXI-Lite item carries unexpected burst={item.burst}", item
            )
        if item.transaction_id not in (None, 0):
            self._record(
                "AXI-LITE-SINGLE",
                f"AXI-Lite item carries unexpected id={item.transaction_id}",
                item,
            )

    def _check_axi_lite_resp(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4-lite":
            return
        for resp in item.resp_list:
            if int(resp) == RESP_EXOKAY:
                self._record("AXI-LITE-RESP", "EXOKAY response is illegal on AXI-Lite", item)

    def _check_expected_beat_count(self, item: OcahAxiItem) -> None:
        expected = item.metadata.get("expected_beats")
        if expected is None:
            return
        if item.beat_count != int(expected):
            self._record(
                "AXI-BEATS",
                f"{item.protocol} {item.direction} beat_count={item.beat_count}, "
                f"expected={expected}",
                item,
            )

    def _check_burst_legal(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4" or item.burst is None:
            return
        if int(item.burst) not in _LEGAL_BURSTS:
            self._record("AXI-BURST-LEGAL", f"reserved burst encoding {item.burst:#b}", item)

    def _check_size_legal(self, item: OcahAxiItem) -> None:
        if self.bus_bytes is None or item.size is None:
            return
        if 2 ** int(item.size) > self.bus_bytes:
            self._record(
                "AXI-SIZE-LEGAL",
                f"AxSIZE={item.size} ({2 ** int(item.size)} bytes) exceeds the "
                f"{self.bus_bytes}-byte data bus",
                item,
            )

    def _check_wrap(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4" or item.burst != BURST_WRAP:
            return
        if item.size is not None and item.address % (2 ** int(item.size)):
            self._record(
                "AXI-WRAP-ALIGN",
                f"WRAP burst address 0x{item.address:x} is not aligned to "
                f"{2 ** int(item.size)} bytes",
                item,
            )
        if item.beat_count not in _WRAP_LEGAL_BEATS:
            self._record(
                "AXI-WRAP-ALIGN",
                f"WRAP burst length {item.beat_count} is not in {{2, 4, 8, 16}}",
                item,
            )

    def _check_fixed_len(self, item: OcahAxiItem) -> None:
        if item.protocol != "axi4" or item.burst != BURST_FIXED:
            return
        if item.beat_count > _FIXED_MAX_BEATS:
            self._record(
                "AXI-FIXED-LEN",
                f"FIXED burst length {item.beat_count} exceeds {_FIXED_MAX_BEATS}",
                item,
            )

    def _check_alignment(self, item: OcahAxiItem) -> None:
        if not self.check_alignment or item.size is None:
            return
        beat_bytes = 2 ** int(item.size)
        if item.address % beat_bytes:
            self._record(
                "AXI-ALIGN",
                f"{item.protocol} {item.direction} address 0x{item.address:x} is not "
                f"aligned to {beat_bytes} bytes",
                item,
            )

    def _check_4kb(self, item: OcahAxiItem) -> None:
        if not self.check_4kb_boundary or item.protocol != "axi4" or item.size is None:
            return
        # The 4KB rule constrains incrementing bursts only. FIXED re-addresses
        # the same beat and WRAP cannot cross its own wrap boundary.
        if item.burst not in (None, BURST_INCR):
            return
        beat_bytes = 2 ** int(item.size)
        transfer_bytes = beat_bytes * max(item.beat_count, 1)
        # Beats after the first are size-aligned, so the burst footprint spans
        # from the ALIGNED start.
        aligned = item.address & ~(beat_bytes - 1)
        if (aligned & 0xFFF) + transfer_bytes > 0x1000:
            self._record(
                "AXI-4KB",
                f"AXI4 {item.direction} crosses 4KB boundary: "
                f"addr=0x{item.address:x} (aligned 0x{aligned:x}), "
                f"bytes={transfer_bytes}",
                item,
            )

    def _check_strobe_legal(self, item: OcahAxiItem) -> None:
        if not self.check_strobes or not item.is_write or not item.strobes:
            return
        for beat_index, strobe in enumerate(item.strobes):
            if int(strobe) < 0:
                self._record(
                    "AXI-STRB-LEGAL",
                    f"beat {beat_index} carries negative strobe {strobe}",
                    item,
                )
                return
        if self.bus_bytes is None:
            return
        bus_mask = (1 << self.bus_bytes) - 1
        for beat_index, strobe in enumerate(item.strobes):
            if int(strobe) & ~bus_mask:
                self._record(
                    "AXI-STRB-LEGAL",
                    f"beat {beat_index} strobe 0x{int(strobe):x} exceeds {self.bus_bytes}-byte bus",
                    item,
                )
        if item.size is None or item.burst == BURST_WRAP:
            # Lane-window checking for WRAP requires wrap-boundary modeling;
            # the bus-width check above still applies.
            return
        beat_bytes = 2 ** int(item.size)
        aligned = item.address & ~(beat_bytes - 1)
        for beat_index, strobe in enumerate(item.strobes):
            if item.burst == BURST_FIXED or item.protocol == "axi4-lite":
                # FIXED bursts re-address the SAME (possibly unaligned)
                # location every beat, so the unaligned lane restriction
                # applies to all beats, not just the first.
                beat_addr = item.address
            else:
                beat_addr = item.address if beat_index == 0 else aligned + beat_index * beat_bytes
            lane_base = (beat_addr & ~(beat_bytes - 1)) % self.bus_bytes
            first_lane = beat_addr % self.bus_bytes
            allowed = 0
            for lane in range(lane_base, lane_base + beat_bytes):
                if lane >= first_lane:
                    allowed |= 1 << lane
            if int(strobe) & ~allowed:
                self._record(
                    "AXI-STRB-LEGAL",
                    f"beat {beat_index} strobe 0x{int(strobe):x} outside active "
                    f"lanes 0x{allowed:x} (addr=0x{beat_addr:x} size={item.size})",
                    item,
                )

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Protocol sanity checker for OCAH JTAG item streams.

Item-level protocol legality rules are retained in ``errors``; named
exact-value evidence (``CHK-* PASS/FAIL`` lines and ``CHECKER_SUMMARY``) is
delegated to the common ``ocah_checker.OcahChecker`` core, following the
composition contract in ``hw/common/dv/docs/vip-checker-model.adoc``. TAP
behavior predictions come from the bundled ``OcahJtagTapRefModel``.

Rule provenance: all TAP contracts are implemented from the public IEEE Std
1149.1 clause descriptions. No third-party protocol-checker source was
consulted or copied.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ocah_checker import OcahChecker

from .ocah_jtag_item import OcahJtagScanItem
from .ocah_jtag_ref_model import TLR_TMS_ONES, OcahJtagTapRefModel
from .ocah_jtag_state import coerce_jtag_state


def _state_label(value: Any) -> tuple[int, str]:
    """Return (int value, state name) tolerating illegal observed encodings."""
    try:
        state = coerce_jtag_state(value)
        return int(state), state.name
    except (KeyError, ValueError):
        return int(value), "INVALID"


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
        required_ids: Iterable[str] = (),
        ref_model: OcahJtagTapRefModel | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.ir_width = ir_width
        self.raise_on_error = raise_on_error
        self.log = logger or logging.getLogger(name)
        self.errors: list[OcahJtagCheckerError] = []
        self.ref_model = ref_model or OcahJtagTapRefModel(name=f"{name}.ref_model")
        self.evidence = OcahChecker(
            name=name,
            required_ids=required_ids,
            fail_fast=raise_on_error,
            logger=self.log,
        )

    def attach_monitor(self, monitor) -> None:
        """Attach checker to an `OcahJtagMasterMonitor` item callback."""
        monitor.add_item_callback(self.check_item)

    def clear(self) -> None:
        self.errors.clear()
        self.evidence.clear()
        self.ref_model.clear()

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

    def sync_state(self, state) -> None:
        """Re-align the TAP reference model after BFM-internal navigation."""
        self.ref_model.sync(state)

    def check_reset_to_tlr(
        self,
        observed_state,
        *,
        check_id: str = "CHK-TAP-RESET-TLR",
        context: str = "",
    ) -> bool:
        """Named check: a TAP reset must leave the controller in TLR."""
        predicted = self.ref_model.reset()
        observed_int, observed_name = _state_label(observed_state)
        return self.expect_equal(
            check_id,
            observed_int,
            int(predicted),
            context=f"observed={observed_name} {context}".strip(),
        )

    def check_state_step(
        self,
        tms,
        observed_state,
        *,
        check_id: str = "CHK-TAP-STATE",
        context: str = "",
    ) -> bool:
        """Named check: one TMS step must land in the reference-model state."""
        previous = self.ref_model.state
        predicted = self.ref_model.step(tms)
        observed_int, observed_name = _state_label(observed_state)
        passed = self.expect_equal(
            check_id,
            observed_int,
            int(predicted),
            context=(
                f"prev={previous.name} tms={int(tms) & 0x1} "
                f"predicted={predicted.name} observed={observed_name} {context}"
            ).strip(),
        )
        if not passed and observed_name != "INVALID":
            # In aggregate mode keep later predictions meaningful by
            # re-aligning to what the DUT actually did.
            self.ref_model.sync(observed_int)
        return passed

    def check_tms_ones_to_tlr(
        self,
        ones_count: int,
        observed_state,
        *,
        check_id: str = "CHK-TAP-TLR-TMS5",
        context: str = "",
    ) -> bool:
        """Named check: >= five TMS-high TCK cycles must force TLR."""
        if int(ones_count) < TLR_TMS_ONES:
            raise ValueError(
                f"IEEE 1149.1 guarantees TLR only after {TLR_TMS_ONES}+ "
                f"TMS-high cycles, got {ones_count}"
            )
        predicted = self.ref_model.reset()
        observed_int, observed_name = _state_label(observed_state)
        return self.expect_equal(
            check_id,
            observed_int,
            int(predicted),
            context=f"tms_ones={int(ones_count)} observed={observed_name} {context}".strip(),
        )

    def check_bypass_latency(
        self,
        observed_tdo: int,
        *,
        pattern: int,
        width: int,
        capture_bit: int = 0,
        instruction: int | None = None,
        check_id: str = "CHK-BYPASS-LATENCY",
        context: str = "",
    ) -> bool:
        """Named check: BYPASS TDO equals TDI delayed by exactly one TCK."""
        predicted = self.ref_model.predict_bypass_tdo(pattern, width, capture_bit=capture_bit)
        mask = (1 << width) - 1 if width > 0 else 0
        instr_ctx = f"ir=0x{instruction:02x} " if instruction is not None else ""
        return self.expect_equal(
            check_id,
            int(observed_tdo) & mask,
            predicted,
            context=f"{instr_ctx}width={width} pattern=0x{pattern:x} {context}".strip(),
        )

    def check_scan_length(
        self,
        item: OcahJtagScanItem,
        *,
        expected_width: int,
        check_id: str | None = None,
        context: str = "",
    ) -> bool:
        """Named check: monitor-observed scan bit count equals the driven width."""
        resolved = check_id or ("CHK-SCAN-IR-LEN" if item.is_ir else "CHK-SCAN-DR-LEN")
        instr_ctx = f"ir=0x{item.instruction:02x} " if item.instruction is not None else ""
        return self.expect_equal(
            resolved,
            item.bit_count,
            int(expected_width),
            context=f"kind={item.kind} {instr_ctx}{context}".strip(),
        )

    def expect_equal(
        self,
        check_id: str,
        observed: Any,
        expected: Any,
        *,
        context: str = "",
    ) -> bool:
        """Emit one exact-value evidence check through the common core."""
        return self.evidence.expect_equal(
            check_id,
            observed,
            expected,
            context=context,
        )

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
        """Require a JTAG operation to complete within its declared bound."""
        return self.evidence.expect_not_timed_out(
            check_id,
            timed_out=timed_out,
            timeout_ns=timeout_ns,
            context=context,
        )

    def expect_timeout(
        self,
        check_id: str,
        *,
        timed_out: bool,
        timeout_ns: float,
        context: str = "",
    ) -> bool:
        """Require an explicitly expected, bounded JTAG timeout."""
        return self.evidence.expect_timeout(
            check_id,
            timed_out=timed_out,
            timeout_ns=timeout_ns,
            context=context,
        )

    def finalize(self) -> None:
        """Fail on retained protocol findings or incomplete named evidence."""
        self.assert_clean()
        self.evidence.finalize()

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
        # tests push long patterns through the one-cycle delay.
        if item.bit_count > 0 and item.tdo_value < 0:
            self._record("DR scan returned a negative TDO value", item)

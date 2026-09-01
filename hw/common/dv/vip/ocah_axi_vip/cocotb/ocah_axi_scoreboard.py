# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI/AXI-Lite scoreboard pairing observed items with reference-model predictions.

Composes the protocol-neutral ``ocah_checker.OcahChecker`` evidence core per the
contract in ``hw/common/dv/docs/vip-checker-model.adoc``. Pure Python (no cocotb
imports) so the mechanics are validated simulator-free.

Expected-vs-unexpected non-OKAY classification generalizes the SEP pattern:
tests arm response credits (``arm_expected_resp``); a completed transaction whose
worst response consumes a matching credit is *expected* (``CHK-AXI-RESP-EXPECTED``),
any other non-OKAY fails the plain ``CHK-AXI-RESP`` comparison against the
reference-model policy. Unconsumed credits fail at finalization
(``CHK-AXI-CREDITS``) so an armed error that never happened is also a failure.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from ocah_checker import OcahChecker

from .ocah_axi_item import OcahAxiItem
from .ocah_axi_ref_model import OcahAxiRefModel
from .ocah_axi_types import RESP_EXOKAY, RESP_OKAY

CHK_RESP = "CHK-AXI-RESP"
CHK_RESP_EXPECTED = "CHK-AXI-RESP-EXPECTED"
CHK_RDATA = "CHK-AXI-RDATA"
CHK_WMEM = "CHK-AXI-WMEM"
CHK_STRB = "CHK-AXI-STRB"
CHK_NOACT = "CHK-AXI-NOACT"
CHK_BLOCKED = "CHK-AXI-BLOCKED"
CHK_DRAIN = "CHK-AXI-DRAIN"
CHK_COMPLETION = "CHK-AXI-COMPLETION"
CHK_TIMEOUT = "CHK-AXI-TIMEOUT"
CHK_STREAM_MIN = "CHK-AXI-STREAM-MIN"
CHK_CREDITS = "CHK-AXI-CREDITS"
CHK_NONVAC = "CHK-AXI-NONVAC"

DEFAULT_STREAM = "default"


@dataclass
class _RespCredit:
    resp: int
    remaining: int
    address: int | None
    direction: str | None
    stream: str | None
    context: str
    armed_seq: int = 0


@dataclass
class _StrobeCredit:
    strobes: tuple[int, ...]
    remaining: int
    address: int | None
    stream: str | None
    context: str
    armed_seq: int = 0


@dataclass
class _TimeoutCredit:
    remaining: int
    timeout_ns: float
    address: int | None
    direction: str | None
    stream: str | None
    context: str
    armed_seq: int = 0


@dataclass
class _StreamState:
    model: OcahAxiRefModel | None = None
    items: int = 0
    compared: int = 0
    checks: int = 0
    blocked_window_start: int | None = None
    blocked_window_hits: int = 0
    monitors: list = field(default_factory=list)
    # Commit-order replay: items carrying metadata["commit_order"] are
    # processed strictly in that order (shadow-memory commits follow the
    # responder's data-acceptance order even when B responses legally
    # reorder across IDs).
    reorder: dict = field(default_factory=dict)
    next_order: int = 0


class OcahAxiScoreboard:
    """Protocol-only comparator for AXI/AXI-Lite transaction streams."""

    def __init__(
        self,
        *,
        name: str = "OcahAxiScoreboard",
        model: OcahAxiRefModel | None = None,
        raise_on_error: bool = False,
        required_ids: Iterable[str] = (),
        check_read_data: bool = True,
        min_transactions_per_stream: dict[str, int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.raise_on_error = raise_on_error
        self.check_read_data = check_read_data
        self.min_transactions_per_stream = dict(min_transactions_per_stream or {})
        self.log = logger or logging.getLogger(name)
        self.evidence = OcahChecker(
            name=name,
            required_ids=required_ids,
            fail_fast=raise_on_error,
            logger=self.log,
        )
        self.errors: list[str] = []
        self._credits: list[_RespCredit] = []
        self._strobe_credits: list[_StrobeCredit] = []
        self._timeout_credits: list[_TimeoutCredit] = []
        self._credits_armed = 0
        # Monotonic event sequence stamping both credit arming and item
        # arrival, so a credit armed AFTER a transaction was observed can
        # never classify it (temporal fail-closed even under commit-order
        # buffering).
        self._event_seq = 0
        self._streams: dict[str, _StreamState] = {}
        self._finalized = False

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def attach_monitor(
        self,
        monitor,
        *,
        stream: str = DEFAULT_STREAM,
        model: OcahAxiRefModel | None = None,
    ) -> None:
        """Route a monitor's completed items into this scoreboard."""
        state = self._stream(stream)
        if model is not None:
            state.model = model
        state.monitors.append(monitor)
        monitor.add_item_callback(lambda item: self.add_observed(item, stream=stream))

    def set_stream_model(self, stream: str, model: OcahAxiRefModel) -> None:
        """Assign the reference model that predicts a stream's expectations."""
        self._stream(stream).model = model

    def add_observed(self, item: OcahAxiItem, *, stream: str = DEFAULT_STREAM) -> None:
        """Check one completed transaction against credits and the model.

        Items carrying ``metadata["commit_order"]`` are replayed strictly in
        that order so model commits track the responder's data order.
        """
        if self._finalized:
            # Nothing may arrive after the summary was emitted; the owning
            # environment must halt monitors before finalizing.
            self._error(
                f"transaction observed after finalize(): {self._item_context(item, stream)}"
            )
            raise AssertionError(f"{self.name}: transaction observed after finalize()")
        state = self._stream(stream)
        state.items += 1
        arrival_seq = self._event_seq
        self._event_seq += 1

        # Temporal policy is evaluated at ARRIVAL, never at (possibly later)
        # replay time: a transaction observed while its stream must be silent
        # is a violation even if it is processed after the window closes.
        violated = False
        if state.blocked_window_start is not None:
            state.blocked_window_hits += 1
            self._error(
                f"transaction observed inside blocked window: {self._item_context(item, stream)}"
            )
            violated = True

        order = item.metadata.get("commit_order")
        if order is None:
            if not violated:
                self._process_observed(item, stream, state, arrival_seq)
            return
        order = int(order)
        if order < state.next_order or order in state.reorder:
            # A duplicate or stale slot may never displace a buffered
            # transaction (that would let a later benign completion replace
            # a buffered failure).
            self._error(
                f"duplicate or stale commit_order={order} "
                f"(next expected {state.next_order}): "
                f"{self._item_context(item, stream)}"
            )
            return
        state.reorder[order] = (item, violated, arrival_seq)
        while state.next_order in state.reorder:
            queued_item, queued_violated, queued_seq = state.reorder.pop(state.next_order)
            state.next_order += 1
            if not queued_violated:
                self._process_observed(queued_item, stream, state, queued_seq)

    def _process_observed(
        self, item: OcahAxiItem, stream: str, state: _StreamState, arrival_seq: int
    ) -> None:
        context = self._item_context(item, stream)

        if item.timed_out:
            # A timeout is legal only when the TEST armed it via
            # arm_expected_timeout(); nothing carried on the observed item can
            # authorize its own pass.
            timeout_credit = self._match_timeout_credit(item, stream, arrival_seq)
            if timeout_credit is not None:
                self.evidence.expect_timeout(
                    CHK_TIMEOUT,
                    timed_out=True,
                    timeout_ns=timeout_credit.timeout_ns,
                    context=f"{context} {timeout_credit.context}".strip(),
                )
            else:
                self.evidence.expect_not_timed_out(
                    CHK_COMPLETION,
                    timed_out=True,
                    timeout_ns=float(item.metadata.get("timeout_ns", 0)),
                    context=context,
                )
            state.compared += 1
            state.checks += 1
            return

        model = state.model or self.model
        prediction = self._predict(model, item)

        # Declarative blocked-region policy: a transaction observed inside a
        # blocked region is a violation regardless of its response — the whole
        # point is that it must never reach the subordinate. Always fails.
        if prediction is not None and prediction.blocked:
            self.evidence.expect_equal(
                CHK_BLOCKED,
                1,
                0,
                context=f"{context} policy=blocked-region",
            )
            state.checks += 1
            return

        observed_resp = item.resp
        observed_resps = tuple(int(resp) for resp in item.resp_list) or (observed_resp,)
        credit = self._match_credit(item, stream, observed_resp, arrival_seq)
        state.compared += 1
        if credit is not None:
            self.evidence.expect_equal(
                CHK_RESP_EXPECTED,
                observed_resp,
                credit.resp,
                context=f"{context} {credit.context}".strip(),
            )
            state.checks += 1
            # A credit never overrides the model: when a model is attached,
            # the per-beat comparison is emitted unconditionally, so a credit
            # conflicting with the model's expectation fails here.
            if prediction is not None:
                self.evidence.expect_equal(
                    CHK_RESP, observed_resps, tuple(prediction.resp_list), context=context
                )
                state.checks += 1
        else:
            expected_resps = (
                tuple(prediction.resp_list)
                if prediction is not None
                else tuple([RESP_OKAY] * len(observed_resps))
            )
            self.evidence.expect_equal(CHK_RESP, observed_resps, expected_resps, context=context)
            state.checks += 1

        if (
            item.is_read
            and self.check_read_data
            and prediction is not None
            and prediction.resp in (RESP_OKAY, RESP_EXOKAY)
            and all(resp in (RESP_OKAY, RESP_EXOKAY) for resp in observed_resps)
        ):
            # Data is checked for every SUCCESS completion (OKAY or EXOKAY):
            # an EXOKAY beat still fails the response comparison above when
            # the model did not predict it, but its data corruption must not
            # go unexamined either.
            self.evidence.expect_equal(
                CHK_RDATA,
                tuple(item.data_words),
                tuple(prediction.data_words),
                context=context,
            )
            state.checks += 1

        if item.is_write:
            strobe_credit = self._match_strobe_credit(item, stream, arrival_seq)
            if strobe_credit is not None:
                self.evidence.expect_equal(
                    CHK_STRB,
                    tuple(int(strobe) for strobe in item.strobes),
                    strobe_credit.strobes,
                    context=f"{context} {strobe_credit.context}".strip(),
                )
                state.checks += 1

    # ------------------------------------------------------------------
    # Expected-vs-unexpected non-OKAY (generalizes SEP arm_expected_decerr)
    # ------------------------------------------------------------------

    def arm_expected_resp(
        self,
        resp: int,
        *,
        count: int = 1,
        address: int | None = None,
        direction: str | None = None,
        stream: str | None = None,
        context: str = "",
    ) -> None:
        """Declare the next ``count`` matching non-OKAY responses as expected."""
        self._credits.append(
            _RespCredit(
                resp=int(resp),
                remaining=int(count),
                address=None if address is None else int(address),
                direction=direction,
                stream=stream,
                context=context,
                armed_seq=self._event_seq,
            )
        )
        self._event_seq += 1
        self._credits_armed += int(count)
        self.log.info(
            "%s: armed expected resp=%d count=%d addr=%s direction=%s stream=%s",
            self.name,
            int(resp),
            count,
            "-" if address is None else hex(address),
            direction or "-",
            stream or "-",
        )

    def unconsumed_credits(self) -> int:
        return (
            sum(credit.remaining for credit in self._credits)
            + sum(credit.remaining for credit in self._strobe_credits)
            + sum(credit.remaining for credit in self._timeout_credits)
        )

    def arm_expected_timeout(
        self,
        *,
        timeout_ns: float,
        count: int = 1,
        address: int | None = None,
        direction: str | None = None,
        stream: str | None = None,
        context: str = "",
    ) -> None:
        """Declare the next ``count`` matching timeouts as expected (bounded).

        This is the only way a timed-out transaction can pass; an unarmed
        timeout fails CHK-AXI-COMPLETION and an armed timeout that never
        happens fails CHK-AXI-CREDITS at finalization.
        """
        self._timeout_credits.append(
            _TimeoutCredit(
                remaining=int(count),
                timeout_ns=float(timeout_ns),
                address=None if address is None else int(address),
                direction=direction,
                stream=stream,
                context=context,
                armed_seq=self._event_seq,
            )
        )
        self._event_seq += 1
        self._credits_armed += int(count)
        self.log.info(
            "%s: armed expected timeout count=%d bound=%sns addr=%s direction=%s stream=%s",
            self.name,
            count,
            timeout_ns,
            "-" if address is None else hex(address),
            direction or "-",
            stream or "-",
        )

    def arm_expected_strobes(
        self,
        strobes,
        *,
        count: int = 1,
        address: int | None = None,
        stream: str | None = None,
        context: str = "",
    ) -> None:
        """Declare the intent write strobes for the next matching write(s).

        The expectation comes from the STIMULUS (e.g. the wstrb field the test
        programmed), never from the observed bus, so CHK-AXI-STRB catches a
        DUT/bridge that corrupts strobes end to end. Unconsumed strobe credits
        fail CHK-AXI-CREDITS at finalization.
        """
        self._strobe_credits.append(
            _StrobeCredit(
                strobes=tuple(int(strobe) for strobe in strobes),
                remaining=int(count),
                address=None if address is None else int(address),
                stream=stream,
                context=context,
                armed_seq=self._event_seq,
            )
        )
        self._event_seq += 1
        self._credits_armed += int(count)
        self.log.info(
            "%s: armed expected strobes=%s count=%d addr=%s stream=%s",
            self.name,
            [hex(strobe) for strobe in self._strobe_credits[-1].strobes],
            count,
            "-" if address is None else hex(address),
            stream or "-",
        )

    # ------------------------------------------------------------------
    # Blocked / no-activity evidence
    # ------------------------------------------------------------------

    @staticmethod
    def snapshot_activity(counts: dict[str, int]) -> dict[str, int]:
        """Freeze a request-activity counter snapshot for later comparison."""
        return {key: int(value) for key, value in counts.items()}

    def expect_no_activity(
        self,
        *,
        before: dict[str, int],
        after: dict[str, int],
        check_id: str = CHK_NOACT,
        context: str = "",
    ) -> bool:
        """Require request-activity counters unchanged across a blocked window."""
        return self.evidence.expect_equal(
            check_id,
            self.snapshot_activity(after),
            self.snapshot_activity(before),
            context=context,
        )

    def begin_blocked_window(self, *, stream: str = DEFAULT_STREAM) -> None:
        """Open a window during which any observed item on the stream fails."""
        state = self._stream(stream)
        if state.blocked_window_start is not None:
            self._error(f"blocked window already open on stream {stream!r}")
            return
        state.blocked_window_start = state.items
        state.blocked_window_hits = 0

    def end_blocked_window(
        self,
        *,
        stream: str = DEFAULT_STREAM,
        check_id: str = CHK_NOACT,
        context: str = "",
    ) -> bool:
        """Close a blocked window and emit zero-observed-transaction evidence."""
        state = self._stream(stream)
        if state.blocked_window_start is None:
            self._error(f"blocked window closed without being opened on stream {stream!r}")
            return False
        hits = state.blocked_window_hits
        state.blocked_window_start = None
        state.blocked_window_hits = 0
        return self.evidence.expect_equal(
            check_id, hits, 0, context=f"{context} stream={stream}".strip()
        )

    # ------------------------------------------------------------------
    # Direct memory audit
    # ------------------------------------------------------------------

    def check_memory(
        self,
        check_id: str = CHK_WMEM,
        *,
        dut_bytes: bytes,
        address: int,
        length: int,
        stream: str = DEFAULT_STREAM,
        context: str = "",
        expected: bytes | None = None,
    ) -> bool:
        """Compare DUT memory bytes against an independent expectation.

        Pass ``expected`` with the STIMULUS-derived bytes whenever the test
        knows the intent (the strongest, non-circular form). Without it the
        model's shadow is used, which only proves RAM-vs-observed-bus
        consistency (the shadow is itself built from observed bus traffic).
        """
        if expected is not None:
            return self.evidence.expect_equal(
                check_id,
                bytes(dut_bytes),
                bytes(expected),
                context=(
                    f"{context} addr=0x{int(address):x} len={int(length)} source=intent"
                ).strip(),
            )
        model = self._stream(stream).model or self.model
        if model is None:
            self._error(f"check_memory on stream {stream!r} without a reference model")
            return False
        return self.evidence.expect_equal(
            check_id,
            bytes(dut_bytes),
            model.read_bytes(address, length),
            context=(f"{context} addr=0x{int(address):x} len={int(length)} source=model").strip(),
        )

    # ------------------------------------------------------------------
    # Evidence forwards
    # ------------------------------------------------------------------

    def expect_equal(self, check_id: str, observed, expected, *, context: str = "") -> bool:
        return self.evidence.expect_equal(check_id, observed, expected, context=context)

    def expect_true(self, check_id: str, condition, *, context: str = "") -> bool:
        return self.evidence.expect_true(check_id, condition, context=context)

    def expect_not_timed_out(
        self, check_id: str, *, timed_out: bool, timeout_ns: float, context: str = ""
    ) -> bool:
        return self.evidence.expect_not_timed_out(
            check_id, timed_out=timed_out, timeout_ns=timeout_ns, context=context
        )

    def expect_timeout(
        self, check_id: str, *, timed_out: bool, timeout_ns: float, context: str = ""
    ) -> bool:
        return self.evidence.expect_timeout(
            check_id, timed_out=timed_out, timeout_ns=timeout_ns, context=context
        )

    def expect_nonvacuous(self, condition, *, context: str = "") -> bool:
        """Emit the domain non-vacuity proof (CHK-AXI-NONVAC)."""
        return self.evidence.expect_true(CHK_NONVAC, condition, context=context)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset evidence, credits, findings, and stream counters."""
        self.evidence.clear()
        self.errors.clear()
        self._credits.clear()
        self._strobe_credits.clear()
        self._timeout_credits.clear()
        self._credits_armed = 0
        self._event_seq = 0
        self._streams.clear()
        self._finalized = False

    def finalize(self) -> None:
        """Emit summary evidence exactly once and fail closed on any defect."""
        if self._finalized:
            self._error("finalize() called more than once")
        self._finalized = True

        for stream, state in self._streams.items():
            if state.blocked_window_start is not None:
                self._error(f"blocked window left open on stream {stream!r}")

        if self._credits_armed:
            self.evidence.expect_equal(
                CHK_CREDITS,
                self.unconsumed_credits(),
                0,
                context=f"armed={self._credits_armed}",
            )

        for stream, minimum in self.min_transactions_per_stream.items():
            compared = self._streams.get(stream, _StreamState()).compared
            self.evidence.expect_true(
                CHK_STREAM_MIN,
                compared >= int(minimum),
                context=f"stream={stream} transactions={compared} min={minimum}",
            )

        # Commit-order replay must be empty: a held item means an earlier
        # completion never arrived (the drain check below names the culprit).
        for stream, state in self._streams.items():
            if state.reorder:
                self._error(
                    f"{len(state.reorder)} transaction(s) on stream {stream!r} "
                    f"held for a missing earlier completion "
                    f"(next expected order {state.next_order})"
                )

        # Drain: every accepted request must have completed (no in-flight
        # AW/AR left in a monitor) and no completion may have arrived without
        # a request phase (orphans). Either condition fails the run.
        for stream, state in self._streams.items():
            for monitor in state.monitors:
                pending = getattr(monitor, "pending_transactions", None)
                if pending is None:
                    continue
                counts = pending()
                self.evidence.expect_equal(
                    CHK_DRAIN,
                    {
                        "pending": sum(counts.values()),
                        "orphans": getattr(monitor, "orphan_responses", 0),
                        "callback_errors": getattr(monitor, "callback_errors", 0),
                    },
                    {"pending": 0, "orphans": 0, "callback_errors": 0},
                    context=(
                        f"stream={stream} monitor={getattr(monitor, 'name', '?')} "
                        f"in_flight={counts}"
                    ),
                )

        if self.errors:
            joined = "\n".join(self.errors)
            raise AssertionError(f"{self.name}: {len(self.errors)} scoreboard error(s):\n{joined}")
        self.evidence.finalize()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _stream(self, stream: str) -> _StreamState:
        return self._streams.setdefault(stream, _StreamState())

    def _predict(self, model: OcahAxiRefModel | None, item: OcahAxiItem):
        if model is None:
            return None
        if item.is_write:
            return model.predict_write(
                address=item.address,
                data_words=item.data_words,
                strobes=item.strobes,
                size=item.size,
                burst=item.burst,
            )
        return model.predict_read(
            address=item.address,
            beat_count=item.beat_count,
            size=item.size,
            burst=item.burst,
        )

    def _match_credit(
        self, item: OcahAxiItem, stream: str, observed_resp: int, arrival_seq: int
    ) -> _RespCredit | None:
        if observed_resp == RESP_OKAY:
            return None
        model = self._stream(stream).model or self.model
        beat_bytes = model.beat_bytes if model is not None else 1
        item_aligned = (item.address // beat_bytes) * beat_bytes
        for credit in self._credits:
            if credit.remaining <= 0:
                continue
            if credit.armed_seq >= arrival_seq:
                # Armed AFTER this transaction was observed: cannot classify it.
                continue
            if credit.resp != observed_resp:
                continue
            if credit.stream is not None and credit.stream != stream:
                continue
            if credit.direction is not None and credit.direction != item.direction:
                continue
            if credit.address is not None:
                credit_aligned = (credit.address // beat_bytes) * beat_bytes
                if credit_aligned != item_aligned:
                    continue
            credit.remaining -= 1
            return credit
        return None

    def _match_timeout_credit(
        self, item: OcahAxiItem, stream: str, arrival_seq: int
    ) -> _TimeoutCredit | None:
        model = self._stream(stream).model or self.model
        beat_bytes = model.beat_bytes if model is not None else 1
        item_aligned = (item.address // beat_bytes) * beat_bytes
        for credit in self._timeout_credits:
            if credit.remaining <= 0:
                continue
            if credit.armed_seq >= arrival_seq:
                continue
            if credit.stream is not None and credit.stream != stream:
                continue
            if credit.direction is not None and credit.direction != item.direction:
                continue
            if credit.address is not None:
                credit_aligned = (credit.address // beat_bytes) * beat_bytes
                if credit_aligned != item_aligned:
                    continue
            credit.remaining -= 1
            return credit
        return None

    def _match_strobe_credit(
        self, item: OcahAxiItem, stream: str, arrival_seq: int
    ) -> _StrobeCredit | None:
        model = self._stream(stream).model or self.model
        beat_bytes = model.beat_bytes if model is not None else 1
        item_aligned = (item.address // beat_bytes) * beat_bytes
        for credit in self._strobe_credits:
            if credit.remaining <= 0:
                continue
            if credit.armed_seq >= arrival_seq:
                continue
            if credit.stream is not None and credit.stream != stream:
                continue
            if credit.address is not None:
                credit_aligned = (credit.address // beat_bytes) * beat_bytes
                if credit_aligned != item_aligned:
                    continue
            credit.remaining -= 1
            return credit
        return None

    def _item_context(self, item: OcahAxiItem, stream: str) -> str:
        return (
            f"stream={stream} {item.protocol} {item.direction} "
            f"addr=0x{item.address:x} beats={item.beat_count}"
        )

    def _error(self, message: str) -> None:
        self.errors.append(message)
        self.log.error("%s: %s", self.name, message)
        if self.raise_on_error:
            raise AssertionError(f"{self.name}: {message}")
